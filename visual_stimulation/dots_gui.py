from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from dots_protocol import (
    MODE_CHOICES,
    MODE_LABELS,
    DotsRunPlan,
    MOCK_OUTPUT_ROOT,
    SAMPLE_STIMULI_DIR,
    build_run_plan,
    format_duration,
    get_mode_defaults,
    load_stimuli_catalog,
    prepare_run_config,
    summarize_plan,
)
from dots_runner import run_planned_experiment


FIELD_GROUPS = (
    ("metadata", "Metadata"),
    ("functional_params", "Functional"),
    ("stimuli_params", "Stimulus"),
)

TIMELINE_COLORS = {
    "rest": "#dbeafe",
    "prestim_pause": "#fef3c7",
    "stimulus": "#fca5a5",
    "poststim_pause": "#fde68a",
    "interblock_pause": "#c4b5fd",
}


class DotsGuiApp:
    def __init__(self, root: tk.Tk, initial_mode: str):
        self.root = root
        self.root.title("Dots Experiment Launcher")
        self.root.geometry("1380x900")

        self.mode_var = tk.StringVar(value=initial_mode)
        self.stimuli_dir_var = tk.StringVar()
        self.mock_mode_var = tk.BooleanVar(value=False)
        self.mock_output_root_var = tk.StringVar(value=str(MOCK_OUTPUT_ROOT))
        self.summary_var = tk.StringVar(value="Load a stimulus folder, review parameters, then preview.")
        self.status_var = tk.StringVar(value="Waiting for input.")

        self.field_vars: dict[str, dict[str, Any]] = {}
        self.runtime_defaults: dict[str, Any] = {}
        self.current_plan: DotsRunPlan | None = None
        self.dirty = True

        self._build_layout()
        self._load_mode(initial_mode)

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        left = ttk.Frame(self.root, padding=12)
        left.grid(row=0, column=0, sticky="nsw")
        right = ttk.Frame(self.root, padding=12)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        controls = ttk.LabelFrame(left, text="Run Setup", padding=10)
        controls.grid(row=0, column=0, sticky="new")
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="Protocol").grid(row=0, column=0, sticky="w")
        mode_menu = ttk.Combobox(
            controls,
            state="readonly",
            values=[MODE_LABELS[mode] for mode in MODE_CHOICES],
        )
        mode_menu.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        mode_menu.current(MODE_CHOICES.index(self.mode_var.get()))

        def on_mode_change(_: Any) -> None:
            self._load_mode(MODE_CHOICES[mode_menu.current()])

        mode_menu.bind("<<ComboboxSelected>>", on_mode_change)
        self.mode_menu = mode_menu

        ttk.Label(controls, text="Stimulus Folder").grid(row=1, column=0, sticky="w", pady=(10, 0))
        folder_row = ttk.Frame(controls)
        folder_row.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(10, 0))
        folder_row.columnconfigure(0, weight=1)
        ttk.Entry(folder_row, textvariable=self.stimuli_dir_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(folder_row, text="Browse", command=self._browse_stimuli_dir).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(folder_row, text="Use Sample", command=self._use_sample_stimuli).grid(row=0, column=2, padx=(8, 0))

        self.mock_mode_button = ttk.Checkbutton(
            controls,
            text="Mock run",
            variable=self.mock_mode_var,
            command=self._on_mock_mode_toggle,
        )
        self.mock_mode_button.grid(row=2, column=0, sticky="w", pady=(10, 0))

        self.mock_output_row = ttk.Frame(controls)
        self.mock_output_row.columnconfigure(0, weight=1)
        ttk.Entry(self.mock_output_row, textvariable=self.mock_output_root_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(self.mock_output_row, text="Browse", command=self._browse_mock_output_root).grid(
            row=0, column=1, padx=(8, 0)
        )
        self.mock_output_label = ttk.Label(controls, text="Mock Output Root")
        self.mock_output_label.grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.mock_output_row.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(10, 0))

        self.forms_container = ttk.Frame(left)
        self.forms_container.grid(row=1, column=0, sticky="nsew", pady=(12, 0))

        buttons = ttk.Frame(left)
        buttons.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        buttons.columnconfigure((0, 1, 2), weight=1)
        ttk.Button(buttons, text="Preview", command=self.preview_plan).grid(row=0, column=0, sticky="ew")
        self.run_button = ttk.Button(buttons, text="Run", command=self.run_plan, state="disabled")
        self.run_button.grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(buttons, text="Quit", command=self.root.destroy).grid(row=0, column=2, sticky="ew")

        ttk.Label(left, textvariable=self.status_var, wraplength=420, foreground="#374151").grid(
            row=3, column=0, sticky="ew", pady=(12, 0)
        )

        ttk.LabelFrame(right, text="Summary", padding=10).grid(row=0, column=0, sticky="ew")
        ttk.Label(right, textvariable=self.summary_var, wraplength=860, justify="left").grid(
            row=0, column=0, sticky="ew", pady=(10, 12)
        )

        timeline_frame = ttk.LabelFrame(right, text="Timeline Preview", padding=10)
        timeline_frame.grid(row=1, column=0, sticky="nsew")
        timeline_frame.columnconfigure(0, weight=1)
        timeline_frame.rowconfigure(0, weight=1)
        self.timeline_canvas = tk.Canvas(timeline_frame, height=420, background="white", highlightthickness=0)
        self.timeline_canvas.grid(row=0, column=0, sticky="nsew")

        legend = ttk.Frame(right)
        legend.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        for idx, (kind, color) in enumerate(TIMELINE_COLORS.items()):
            swatch = tk.Canvas(legend, width=18, height=18, highlightthickness=0, background=legend.cget("background"))
            swatch.grid(row=0, column=idx * 2, padx=(0, 4))
            swatch.create_rectangle(1, 1, 17, 17, fill=color, outline="")
            ttk.Label(legend, text=kind.replace("_", " ")).grid(row=0, column=idx * 2 + 1, padx=(0, 16))

        self.timeline_canvas.bind("<Configure>", lambda _: self._draw_timeline())
        self.mock_output_root_var.trace_add("write", lambda *_: self._mark_dirty())
        self._update_mock_output_visibility()

    def _load_mode(self, mode: str) -> None:
        self.mode_var.set(mode)
        defaults = get_mode_defaults(mode)
        self.runtime_defaults = defaults["runtime"]
        for child in self.forms_container.winfo_children():
            child.destroy()
        self.field_vars = {}

        for row_index, (group_key, group_label) in enumerate(FIELD_GROUPS):
            frame = ttk.LabelFrame(self.forms_container, text=group_label, padding=10)
            frame.grid(row=row_index, column=0, sticky="new", pady=(0, 12))
            frame.columnconfigure(1, weight=1)
            self.field_vars[group_key] = {}
            values = defaults[group_key]
            for field_index, (field_name, field_value) in enumerate(values.items()):
                ttk.Label(frame, text=field_name).grid(row=field_index, column=0, sticky="w")
                variable, widget = self._create_input(frame, field_name, field_value)
                widget.grid(row=field_index, column=1, sticky="ew", padx=(8, 0), pady=2)
                self.field_vars[group_key][field_name] = variable

        self.current_plan = None
        self._mark_dirty("Protocol changed. Review parameters and preview again.")

    def _create_input(self, parent: ttk.LabelFrame, field_name: str, field_value: Any) -> tuple[Any, ttk.Widget]:
        if field_name == "fish_orientation":
            variable = tk.StringVar(value=str(field_value))
            widget = ttk.Combobox(parent, textvariable=variable, state="readonly", values=["bottom-left", "top-right"])
        elif isinstance(field_value, bool):
            variable = tk.BooleanVar(value=field_value)
            widget = ttk.Checkbutton(parent, variable=variable)
        else:
            text = "" if field_value is None else str(field_value)
            variable = tk.StringVar(value=text)
            widget = ttk.Entry(parent, textvariable=variable)

        if isinstance(variable, tk.BooleanVar):
            variable.trace_add("write", lambda *_: self._mark_dirty())
        else:
            variable.trace_add("write", lambda *_: self._mark_dirty())
        return variable, widget

    def _browse_stimuli_dir(self) -> None:
        selected = filedialog.askdirectory(title="Select the folder containing the stimulus CSV files")
        if selected:
            self.stimuli_dir_var.set(selected)
            self._mark_dirty("Stimulus folder changed. Preview again to refresh the plan.")

    def _use_sample_stimuli(self) -> None:
        self.stimuli_dir_var.set(str(SAMPLE_STIMULI_DIR))
        self._mark_dirty("Sample stimulus folder selected. Preview again to refresh the plan.")

    def _browse_mock_output_root(self) -> None:
        selected = filedialog.askdirectory(title="Select the root folder for mock-run outputs")
        if selected:
            self.mock_output_root_var.set(selected)
            self._mark_dirty("Mock output root changed. Preview again to refresh the plan.")

    def _on_mock_mode_toggle(self) -> None:
        self._update_mock_output_visibility()
        mode_label = "enabled" if self.mock_mode_var.get() else "disabled"
        self._mark_dirty(f"Mock run {mode_label}. Preview again to refresh the plan.")

    def _update_mock_output_visibility(self) -> None:
        if self.mock_mode_var.get():
            self.mock_output_label.grid()
            self.mock_output_row.grid()
        else:
            self.mock_output_label.grid_remove()
            self.mock_output_row.grid_remove()

    def _mark_dirty(self, status: str | None = None) -> None:
        self.dirty = True
        self.current_plan = None
        self.run_button.configure(state="disabled")
        if status:
            self.status_var.set(status)

    def _collect_group_values(self, group_name: str) -> dict[str, Any]:
        defaults = get_mode_defaults(self.mode_var.get())[group_name]
        result: dict[str, Any] = {}
        for field_name, variable in self.field_vars[group_name].items():
            raw_value = variable.get()
            default_value = defaults[field_name]
            result[field_name] = self._coerce_value(raw_value, default_value)
        return result

    def _coerce_value(self, raw_value: Any, default_value: Any) -> Any:
        if isinstance(default_value, bool):
            return bool(raw_value)
        if raw_value == "" and default_value is None:
            return None
        if isinstance(default_value, int) and not isinstance(default_value, bool):
            return int(raw_value)
        if isinstance(default_value, float):
            return float(raw_value)
        return raw_value

    def preview_plan(self) -> None:
        try:
            if not self.stimuli_dir_var.get():
                raise ValueError("Select a stimulus folder before previewing.")
            metadata = self._collect_group_values("metadata")
            functional_params = self._collect_group_values("functional_params")
            stimuli_params = self._collect_group_values("stimuli_params")
            runtime_defaults = dict(self.runtime_defaults)
            runtime_defaults["mock_mode"] = bool(self.mock_mode_var.get())
            runtime_defaults["mock_output_root"] = self.mock_output_root_var.get() or str(MOCK_OUTPUT_ROOT)
            metadata, functional_params, stimuli_params, runtime = prepare_run_config(
                self.mode_var.get(),
                metadata,
                functional_params,
                stimuli_params,
                runtime_defaults,
                self.stimuli_dir_var.get(),
            )
            stimuli_catalog = load_stimuli_catalog(self.stimuli_dir_var.get(), self.mode_var.get())
            self.current_plan = build_run_plan(
                self.mode_var.get(),
                metadata,
                functional_params,
                stimuli_params,
                runtime,
                stimuli_catalog,
            )
        except Exception as exc:
            messagebox.showerror("Preview failed", str(exc))
            self.status_var.set(f"Preview failed: {exc}")
            return

        summary = summarize_plan(self.current_plan)
        first_trials = ", ".join(trial.stimulus_name for trial in self.current_plan.trials[:6]) or "none"
        self.summary_var.set(
            f"Mode: {summary['mode_label']}\n"
            f"Stimuli: {summary['n_stimuli']} files\n"
            f"Trials: {summary['total_trials']}\n"
            f"Total duration: {summary['total_duration_pretty']} ({summary['total_duration_sec']:.2f} sec)\n"
            f"Mock run: {'yes' if self.current_plan.runtime.get('mock_mode') else 'no'}\n"
            f"First trials: {first_trials}"
        )
        self.status_var.set("Preview is current. Run will use this exact schedule.")
        self.dirty = False
        self.run_button.configure(state="normal")
        self._draw_timeline()

    def _draw_timeline(self) -> None:
        canvas = self.timeline_canvas
        canvas.delete("all")
        if not self.current_plan:
            canvas.create_text(24, 24, anchor="nw", text="No preview yet.", fill="#6b7280")
            return

        width = max(canvas.winfo_width(), 640)
        height = max(canvas.winfo_height(), 320)
        top = 40
        row_height = 36
        label_width = 160
        right_margin = 30
        timeline_width = max(width - label_width - right_margin, 200)
        total_duration = max(self.current_plan.total_duration_sec, 1e-6)

        canvas.create_text(16, 16, anchor="nw", text=f"0 sec", fill="#374151")
        canvas.create_text(width - 16, 16, anchor="ne", text=format_duration(total_duration), fill="#374151")

        tracks = [
            ("rest", "Rest"),
            ("interblock_pause", "Inter-block"),
            ("prestim_pause", "Pre"),
            ("stimulus", "Stimulus"),
            ("poststim_pause", "Post"),
        ]
        track_y = {kind: top + idx * row_height for idx, (kind, _) in enumerate(tracks)}

        for kind, label in tracks:
            y = track_y[kind]
            canvas.create_text(12, y + 12, anchor="w", text=label, fill="#111827")
            canvas.create_line(label_width, y + 24, width - right_margin, y + 24, fill="#e5e7eb")

        for segment in self.current_plan.timeline:
            if segment.duration_sec <= 0 or segment.kind not in track_y:
                continue
            x0 = label_width + (segment.start_sec / total_duration) * timeline_width
            x1 = label_width + (segment.end_sec / total_duration) * timeline_width
            if x1 - x0 < 2:
                x1 = x0 + 2
            y = track_y[segment.kind]
            canvas.create_rectangle(
                x0,
                y + 6,
                x1,
                y + 22,
                fill=TIMELINE_COLORS[segment.kind],
                outline="",
            )
            if segment.kind == "stimulus" and (x1 - x0) > 40:
                canvas.create_text((x0 + x1) / 2, y + 14, text=segment.stimulus_name or segment.label, font=("TkDefaultFont", 8))

        for segment in self.current_plan.timeline:
            if segment.kind != "trigger":
                continue
            x = label_width + (segment.start_sec / total_duration) * timeline_width
            canvas.create_line(x, top - 6, x, top + len(tracks) * row_height, fill="#111827", dash=(3, 3))

    def run_plan(self) -> None:
        if self.dirty or not self.current_plan:
            messagebox.showwarning("Preview required", "Preview the current settings before running.")
            return
        run_label = "mock run" if self.current_plan.runtime.get("mock_mode") else "experiment"
        if not messagebox.askyesno("Start experiment", f"Launch the {run_label} with the previewed schedule?"):
            return

        self.root.withdraw()
        try:
            meta_dir = run_planned_experiment(self.current_plan)
        except Exception as exc:
            self.root.deiconify()
            messagebox.showerror("Run failed", str(exc))
            self.status_var.set(f"Run failed: {exc}")
            return

        messagebox.showinfo("Run complete", f"Logs saved to:\n{meta_dir}")
        self.root.destroy()


def launch_dots_gui(initial_mode: str) -> None:
    root = tk.Tk()
    app = DotsGuiApp(root, initial_mode=initial_mode)
    del app
    root.mainloop()


if __name__ == "__main__":
    launch_dots_gui(initial_mode="loop_stimuli")
