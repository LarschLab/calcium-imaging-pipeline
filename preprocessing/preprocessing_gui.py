from __future__ import annotations

import json
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from preprocessing_workflow import (
    PREPROCESSING_MODE_FULL_MEMORY,
    PREPROCESSING_MODE_STREAMING,
    preprocessing_config_from_dict,
    raise_for_invalid_suite2p_inputs,
    suite2p_config_from_dict,
    write_json_config,
)


GUI_SETTINGS_PATH = Path.home() / ".calcium_imaging_pipeline" / "preprocessing_gui_settings.json"
CLI_PATH = Path(__file__).resolve().with_name("preprocessing_cli.py")


def load_gui_settings(settings_path: Path = GUI_SETTINGS_PATH) -> dict[str, Any]:
    try:
        return json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_gui_settings(settings: dict[str, Any], settings_path: Path = GUI_SETTINGS_PATH) -> None:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def build_preprocessing_subprocess_command(config_path: Path) -> list[str]:
    return [sys.executable, str(CLI_PATH), "preprocess", "--config", str(config_path)]


def build_suite2p_subprocess_command(config_path: Path) -> list[str]:
    return [sys.executable, str(CLI_PATH), "suite2p", "--config", str(config_path)]


def default_settings() -> dict[str, Any]:
    return {
        "data_root": "",
        "fish_ids": "",
        "protocol": "resonant",
        "mode": PREPROCESSING_MODE_STREAMING,
        "blocks": "",
        "n_planes": "5",
        "n_frames_per_plane": "3",
        "volume_flyback_frames": "0",
        "workers": "auto",
        "remove_first_frame": True,
        "ops_path": "",
        "fps": "2",
        "selected_planes": "all",
        "fast_disk": "",
        "storage_root": "",
    }


class PreprocessingGuiApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Calcium Imaging Preprocessing")
        self.root.geometry("980x720")

        settings = default_settings()
        settings.update(load_gui_settings())
        if not settings.get("data_root"):
            settings["data_root"] = settings.get("output_base") or settings.get("input_base") or ""
        self.vars = {key: tk.StringVar(value=str(value)) for key, value in settings.items() if key != "remove_first_frame"}
        self.remove_first_frame_var = tk.BooleanVar(value=bool(settings.get("remove_first_frame", True)))
        self.status_var = tk.StringVar(value="Ready.")
        self.process: subprocess.Popen[str] | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.config_paths: list[Path] = []

        self._build_ui()
        self._update_stage_state()
        self.root.after(100, self._drain_log_queue)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        form = ttk.Frame(self.root, padding=12)
        form.grid(row=0, column=0, sticky="ew")
        for col in range(4):
            form.columnconfigure(col, weight=1)

        self._path_row(form, 0, "Data root", "data_root")
        self._entry_row(form, 1, "Fish IDs", "fish_ids", "Comma-separated fish folder names")

        ttk.Label(form, text="Protocol").grid(row=2, column=0, sticky="w", pady=4)
        protocol = ttk.Combobox(form, textvariable=self.vars["protocol"], values=("resonant", "linear"), state="readonly", width=16)
        protocol.grid(row=2, column=1, sticky="ew", pady=4)
        protocol.bind("<<ComboboxSelected>>", lambda _event: self._update_stage_state())

        ttk.Label(form, text="Preprocessing mode").grid(row=2, column=2, sticky="w", pady=4)
        mode = ttk.Combobox(
            form,
            textvariable=self.vars["mode"],
            values=(PREPROCESSING_MODE_STREAMING, PREPROCESSING_MODE_FULL_MEMORY),
            state="readonly",
            width=20,
        )
        mode.grid(row=2, column=3, sticky="ew", pady=4)

        self.streaming_note = ttk.Label(
            form,
            text="Low-memory streaming is the default. It has unit fixture coverage; validate on real large TIFFs before relying on it unattended.",
            foreground="#8a5a00",
        )
        self.streaming_note.grid(row=3, column=0, columnspan=4, sticky="w", pady=(0, 8))

        self._entry_row(form, 4, "Blocks", "blocks", "Optional comma-separated block numbers")
        self._entry_row(form, 5, "Planes", "n_planes", "Required for resonant preprocessing")
        self._entry_row(form, 6, "Frames/plane", "n_frames_per_plane", "Required for resonant preprocessing")
        self._entry_row(form, 7, "Flyback frames", "volume_flyback_frames", "Usually 0 or 1")
        self._entry_row(form, 8, "Preprocessing workers", "workers", "Use 'auto' for session-level parallelism")

        ttk.Checkbutton(form, text="Remove first frame per plane group", variable=self.remove_first_frame_var).grid(
            row=9, column=0, columnspan=2, sticky="w", pady=4
        )

        ttk.Separator(form).grid(row=10, column=0, columnspan=4, sticky="ew", pady=10)
        self._path_row(form, 11, "Suite2P ops .npy", "ops_path", file_mode=True)
        self._entry_row(form, 12, "FPS", "fps", "Suite2P fs")
        self._entry_row(form, 13, "Suite2P planes", "selected_planes", "Use 'all' or comma-separated plane indices")
        self._path_row(form, 14, "Fast disk", "fast_disk")
        self._path_row(form, 15, "Mirror root", "storage_root")

        actions = ttk.Frame(self.root, padding=(12, 0, 12, 8))
        actions.grid(row=2, column=0, sticky="ew")
        actions.columnconfigure(4, weight=1)
        self.preprocess_button = ttk.Button(actions, text="Start Preprocessing", command=self.start_preprocessing)
        self.preprocess_button.grid(row=0, column=0, padx=(0, 8))
        self.suite2p_button = ttk.Button(actions, text="Start Suite2P", command=self.start_suite2p)
        self.suite2p_button.grid(row=0, column=1, padx=(0, 8))
        self.cancel_button = ttk.Button(actions, text="Cancel Running Stage", command=self.cancel_stage, state="disabled")
        self.cancel_button.grid(row=0, column=2, padx=(0, 8))
        ttk.Label(actions, textvariable=self.status_var).grid(row=0, column=4, sticky="e")

        log_frame = ttk.LabelFrame(self.root, text="Stage Log", padding=8)
        log_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(log_frame, height=16, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

    def _entry_row(self, parent: ttk.Frame, row: int, label: str, key: str, hint: str = "") -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=self.vars[key]).grid(row=row, column=1, sticky="ew", pady=4)
        if hint:
            ttk.Label(parent, text=hint, foreground="#666666").grid(row=row, column=2, columnspan=2, sticky="w", pady=4)

    def _path_row(self, parent: ttk.Frame, row: int, label: str, key: str, file_mode: bool = False) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=self.vars[key]).grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)
        command = lambda: self._browse_path(key, file_mode=file_mode)
        ttk.Button(parent, text="Browse", command=command).grid(row=row, column=3, sticky="ew", padx=(8, 0), pady=4)

    def _browse_path(self, key: str, file_mode: bool = False) -> None:
        if file_mode:
            path = filedialog.askopenfilename(title=f"Select {key}", filetypes=[("NumPy files", "*.npy"), ("All files", "*.*")])
        else:
            path = filedialog.askdirectory(title=f"Select {key}")
        if path:
            self.vars[key].set(path)

    def collect_preprocessing_config(self) -> dict[str, Any]:
        return {
            "data_root": self.vars["data_root"].get(),
            "fish_ids": self.vars["fish_ids"].get(),
            "protocol": self.vars["protocol"].get(),
            "mode": self.vars["mode"].get(),
            "blocks": self.vars["blocks"].get(),
            "n_planes": self.vars["n_planes"].get(),
            "n_frames_per_plane": self.vars["n_frames_per_plane"].get(),
            "volume_flyback_frames": self.vars["volume_flyback_frames"].get(),
            "workers": self.vars["workers"].get(),
            "remove_first_frame": self.remove_first_frame_var.get(),
            "progress": True,
        }

    def collect_suite2p_config(self) -> dict[str, Any]:
        return {
            "data_root": self.vars["data_root"].get(),
            "fish_ids": self.vars["fish_ids"].get(),
            "ops_path": self.vars["ops_path"].get(),
            "fps": self.vars["fps"].get(),
            "selected_planes": self.vars["selected_planes"].get(),
            "fast_disk": self.vars["fast_disk"].get(),
            "storage_root": self.vars["storage_root"].get(),
        }

    def start_preprocessing(self) -> None:
        config = self.collect_preprocessing_config()
        try:
            preprocessing_config_from_dict(config)
        except Exception as exc:
            messagebox.showerror("Preprocessing config error", str(exc))
            return
        self._save_settings()
        self._start_stage("preprocessing", config, build_preprocessing_subprocess_command)

    def start_suite2p(self) -> None:
        config = self.collect_suite2p_config()
        try:
            parsed = suite2p_config_from_dict(config)
            raise_for_invalid_suite2p_inputs(parsed)
        except Exception as exc:
            messagebox.showerror("Suite2P blocked", str(exc))
            return
        self._save_settings()
        self._start_stage("Suite2P", config, build_suite2p_subprocess_command)

    def cancel_stage(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.status_var.set("Cancelling running stage...")
            self.process.terminate()

    def _start_stage(self, label: str, config: dict[str, Any], command_builder) -> None:
        if self.process is not None and self.process.poll() is None:
            messagebox.showwarning("Stage already running", "Cancel or wait for the current stage before starting another.")
            return

        config_path = self._write_temp_config(config)
        command = command_builder(config_path)
        self._append_log(f"\n[{label}] command: {' '.join(command)}\n")
        self.status_var.set(f"{label} running...")
        self._set_running(True)

        self.process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._read_process_output, args=(self.process, label), daemon=True).start()

    def _write_temp_config(self, config: dict[str, Any]) -> Path:
        temp_dir = Path(tempfile.gettempdir()) / "calcium_preprocessing_gui"
        temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix="config_", suffix=".json", dir=temp_dir, delete=False) as tmp:
            config_path = Path(tmp.name)
        write_json_config(config_path, config)
        self.config_paths.append(config_path)
        return config_path

    def _read_process_output(self, process: subprocess.Popen[str], label: str) -> None:
        if process.stdout is not None:
            for line in process.stdout:
                self.log_queue.put(line)
        return_code = process.wait()
        self.log_queue.put(f"[{label}] exited with code {return_code}\n")
        self.log_queue.put(("__STAGE_DONE__", label, return_code))

    def _drain_log_queue(self) -> None:
        while True:
            try:
                item = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, tuple) and item[0] == "__STAGE_DONE__":
                _tag, label, return_code = item
                self.status_var.set(f"{label} finished." if return_code == 0 else f"{label} failed.")
                self._set_running(False)
            else:
                self._append_log(str(item))
        self.root.after(100, self._drain_log_queue)

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.preprocess_button.configure(state=state)
        self.suite2p_button.configure(state=state)
        self.cancel_button.configure(state="normal" if running else "disabled")

    def _save_settings(self) -> None:
        settings = {key: var.get() for key, var in self.vars.items()}
        settings["remove_first_frame"] = self.remove_first_frame_var.get()
        try:
            save_gui_settings(settings)
        except OSError as exc:
            self.status_var.set(f"Settings were not saved: {exc}")

    def _update_stage_state(self) -> None:
        is_resonant = self.vars["protocol"].get() == "resonant"
        if not is_resonant:
            self.status_var.set("Linear preprocessing writes a stack; Suite2P GUI expects resonant plane TIFFs.")


def launch_preprocessing_gui() -> None:
    root = tk.Tk()
    PreprocessingGuiApp(root)
    root.mainloop()


if __name__ == "__main__":
    launch_preprocessing_gui()
