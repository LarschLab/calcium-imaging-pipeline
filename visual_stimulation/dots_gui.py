from __future__ import annotations

import colorsys
import json
import random
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from dots_protocol import (
    FPS,
    MODE_CHOICES,
    MODE_CONTINUOUS_SESSION,
    MODE_LABELS,
    MODE_LOOP_BLOCKS,
    MODE_LOOP_STIMULI,
    DotsRunPlan,
    MOCK_OUTPUT_ROOT,
    PlannedBlock,
    SAMPLE_STIMULI_DIR,
    STIMULUS_MEDIA_VIDEO,
    StimulusSpec,
    TimelineSegment,
    build_run_plan,
    format_duration,
    get_mode_defaults,
    load_stimuli_catalog,
    prepare_run_config,
    summarize_plan,
)
from dots_runner import run_planned_experiment
from line_fish_alignment import show_fish_alignment


FIELD_GROUPS = (
    ("metadata", "Metadata"),
    ("functional_params", "Functional"),
    ("stimuli_params", "Stimulus"),
)

AUTO_PREVIEW_DEBOUNCE_MS = 400
LABEL_TOOLTIP_DELAY_MS = 500
TIMELINE_PREVIEW_HEIGHT_PX = 180
TIMELINE_MIN_VISIBLE_SEC = 1.0
TIMELINE_ZOOM_IN_FACTOR = 0.8
TIMELINE_ZOOM_OUT_FACTOR = 1.25
TIMELINE_BLOCK_GUIDE_LABEL = "Blocks"
INPUT_GROUP_ROWS = ("metadata", "functional_params", "stimuli_params")
FORM_GROUP_COLUMNS = 3
DEFAULT_WINDOW_GEOMETRY = "1800x1250"
MIN_WINDOW_WIDTH = 1280
WINDOW_SAFETY_MARGIN_PX = 80
PREVIEW_PENDING_RUN_BLOCK_REASON = "Wait for auto-preview to refresh current settings before running."
DEFAULT_INITIAL_MODE = MODE_LOOP_BLOCKS
GUI_SETTINGS_PATH = Path.home() / ".calcium_imaging_pipeline" / "dots_gui_settings.json"
GUI_SETTINGS_STIMULI_PARAMS_BY_MODE_KEY = "stimuli_params_by_mode"
GUI_SETTINGS_FUNCTIONAL_PARAMS_BY_MODE_KEY = "functional_params_by_mode"
LEGEND_ENTRIES_PER_ROW = 4
AUTO_BLOCK_FIELD_NAME = "n_trials_per_block"
AUTO_REST_FIELD_NAME = "pre_stim_resting_sec"
REMEMBERED_STIMULI_PARAM_EXCLUDED_FIELDS = {AUTO_BLOCK_FIELD_NAME, AUTO_REST_FIELD_NAME}
DERIVED_FUNCTIONAL_FIELDS = {"n_volumes", "framerate"}
REMEMBERED_FUNCTIONAL_PARAM_EXCLUDED_FIELDS = DERIVED_FUNCTIONAL_FIELDS
REMEMBERED_METADATA_FIELDS = (
    "experiment_name",
    "experimenter",
    "fish_ID",
    "fish_birth",
    "genotype",
)

FIELD_HELP_TEXT: dict[str, dict[str, str]] = {
    "metadata": {
        "experiment_name": "Experiment label used in metadata and output naming.",
        "experimenter": "Name or initials of the person running the session.",
        "experiment_date": "Run timestamp; leave empty to auto-fill at preview/run time.",
        "fish_ID": "Animal identifier written to run metadata.",
        "fish_birth": "Birth date used to compute fish age (YYYY-MM-DD).",
        "fish_age_dpf": "Age in days post fertilization; auto-computed from fish_birth.",
        "genotype": "Genotype string stored with run metadata.",
        "size": "Free-text size descriptor for the fish.",
        "time_embedding": "Optional embedding timestamp or code.",
        "fish_orientation": "Orientation of the fish in the field of view.",
        "respond_to_omr": "Behavior note indicating OMR response.",
        "respond_to_vibrations": "Behavior note indicating vibration response.",
        "respond_to_bouts": "Behavior note indicating spontaneous bout response.",
        "embedding_comments": "Optional notes about embedding quality or issues.",
        "projector_LED_current": "Projector LED current setting used during acquisition.",
        "projector_power": "Projector power setting used during acquisition.",
        "general_comments": "Additional free-text notes for this run.",
    },
    "functional_params": {
        "mode": "Microscope acquisition mode for this run.",
        "n_frames": "Frames per volume acquisition cycle.",
        "n_slices": "Slices per volume acquisition cycle.",
        "n_volumes": "Derived total acquisition volumes for the planned run.",
        "step_size": "Z-step size between slices.",
        "framerate": "Derived acquisition volume rate in Hz.",
        "AOM_mW": "Laser power (mW) used for AOM.",
        "ETL_start": "Initial ETL offset or focal setting.",
        "pump_speed": "Perfusion pump speed setting.",
        "volume_flyback": "Flyback setting applied between volumes.",
        "frame_flyback": "Flyback setting applied between frames.",
        "motion_correction": "Whether online motion correction is enabled.",
    },
    "stimuli_params": {
        "pre_stim_resting_sec": "Initial resting period before the first stimulus.",
        "pre_stim_pause_sec": "Pause before each stimulus trial.",
        "post_stim_pause_sec": "Pause after each stimulus trial.",
        "inter_block_pause_sec": "Pause inserted between blocks.",
        "n_trials_per_block": "Number of trials included in each block.",
        "n_rep_stim": "How many repetitions per stimulus entry.",
        "max_n_dots": "Maximum number of dots allowed in selected stimuli.",
        "dot_radius_cm": "Dot radius in centimeters when fixed radius mode is used.",
    },
}

FIELD_DISPLAY_LABELS: dict[str, dict[str, str]] = {
    "metadata": {
        "experiment_name": "Experiment name",
        "experimenter": "Experimenter",
        "experiment_date": "Experiment date",
        "fish_ID": "Fish ID",
        "fish_birth": "Fish birth date",
        "fish_age_dpf": "Fish age (dpf)",
        "genotype": "Genotype",
        "size": "Fish size",
        "time_embedding": "Embedding time",
        "fish_orientation": "Fish orientation",
        "respond_to_omr": "Responds to OMR",
        "respond_to_vibrations": "Responds to vibrations",
        "respond_to_bouts": "Responds to bouts",
        "embedding_comments": "Embedding comments",
        "projector_LED_current": "Projector LED current",
        "projector_power": "Projector power",
        "general_comments": "General comments",
    },
    "functional_params": {
        "mode": "Acquisition mode",
        "n_frames": "Frames / plane",
        "n_slices": "Number of planes",
        "n_volumes": "Volume count",
        "step_size": "Step size (um)",
        "framerate": "Volume rate (Hz)",
        "AOM_mW": "AOM power (mW)",
        "ETL_start": "ETL start",
        "pump_speed": "Pump speed",
        "volume_flyback": "Volume flyback",
        "frame_flyback": "Frame flyback",
        "motion_correction": "Motion correction",
    },
    "stimuli_params": {
        "pre_stim_resting_sec": "Pre-stim rest (s)",
        "pre_stim_pause_sec": "Pre-stim pause (s)",
        "post_stim_pause_sec": "Post-stim pause (s)",
        "inter_block_pause_sec": "Inter-block pause (s)",
        "n_trials_per_block": "Stimuli / block",
        "n_rep_stim": "Stimuli repetitions",
        "max_n_dots": "Max number of dots",
        "dot_radius_cm": "Dot radius (cm)",
    },
}

DARK_CONSOLE_THEME = {
    "root_bg": "#0b1120",
    "panel_bg": "#111827",
    "panel_alt_bg": "#0f172a",
    "field_bg": "#182235",
    "field_fg": "#e5edf7",
    "muted_fg": "#94a3b8",
    "text_fg": "#e5edf7",
    "border": "#263244",
    "grid": "#263244",
    "primary": "#22d3ee",
    "primary_hover": "#67e8f9",
    "accent": "#f59e0b",
    "danger": "#f97316",
    "canvas_bg": "#0f172a",
    "hover_outline": "#f8fafc",
    "trigger": "#e5edf7",
    "baseline_block": "#38bdf8",
    "stimulus_block": "#f8fafc",
}
TOOLTIP_BG_COLOR = "#020617"
TOOLTIP_FG_COLOR = DARK_CONSOLE_THEME["text_fg"]
DARK_TTK_STYLE_NAMES = (
    "TFrame",
    "Panel.TFrame",
    "TLabelframe",
    "TLabelframe.Label",
    "TLabel",
    "Muted.TLabel",
    "TEntry",
    "TCombobox",
    "TCheckbutton",
    "TButton",
    "Accent.TButton",
    "Vertical.TScrollbar",
)

BASE_TIMELINE_COLORS = {
    "rest": "#1d4ed8",
    "prestim_pause": "#d97706",
    "poststim_pause": "#92400e",
    "interblock_pause": "#7c3aed",
}


def compute_group_grid_positions(group_keys: tuple[str, ...], columns: int) -> dict[str, tuple[int, int]]:
    if columns <= 0:
        raise ValueError("columns must be a positive integer")
    return {group_key: (index // columns, index % columns) for index, group_key in enumerate(group_keys)}


def compute_legend_grid_positions(entry_count: int, entries_per_row: int) -> list[tuple[int, int]]:
    if entries_per_row <= 0:
        raise ValueError("entries_per_row must be a positive integer")
    return [
        (entry_index // entries_per_row, (entry_index % entries_per_row) * 2)
        for entry_index in range(entry_count)
    ]


def collect_timeline_stimulus_identities(timeline: list[TimelineSegment]) -> list[str]:
    return sorted(
        {
            segment.stimulus_name
            for segment in timeline
            if segment.kind == "stimulus" and segment.stimulus_name
        }
    )


def clamp_timeline_view(start_sec: float, end_sec: float, total_duration_sec: float) -> tuple[float, float]:
    total_duration_sec = max(float(total_duration_sec), TIMELINE_MIN_VISIBLE_SEC)
    visible_duration = max(float(end_sec) - float(start_sec), TIMELINE_MIN_VISIBLE_SEC)
    visible_duration = min(visible_duration, total_duration_sec)
    start_sec = max(0.0, min(float(start_sec), total_duration_sec - visible_duration))
    return start_sec, start_sec + visible_duration


def zoom_timeline_view(
    start_sec: float,
    end_sec: float,
    total_duration_sec: float,
    anchor_sec: float,
    zoom_factor: float,
) -> tuple[float, float]:
    if zoom_factor <= 0:
        raise ValueError("zoom_factor must be positive")
    current_duration = max(float(end_sec) - float(start_sec), TIMELINE_MIN_VISIBLE_SEC)
    total_duration_sec = max(float(total_duration_sec), TIMELINE_MIN_VISIBLE_SEC)
    next_duration = max(TIMELINE_MIN_VISIBLE_SEC, min(total_duration_sec, current_duration * zoom_factor))
    anchor_sec = max(0.0, min(float(anchor_sec), total_duration_sec))
    anchor_fraction = 0.0 if current_duration <= 0 else (anchor_sec - float(start_sec)) / current_duration
    anchor_fraction = max(0.0, min(anchor_fraction, 1.0))
    next_start = anchor_sec - anchor_fraction * next_duration
    return clamp_timeline_view(next_start, next_start + next_duration, total_duration_sec)


def pan_timeline_view(
    start_sec: float,
    end_sec: float,
    total_duration_sec: float,
    delta_sec: float,
) -> tuple[float, float]:
    return clamp_timeline_view(float(start_sec) + float(delta_sec), float(end_sec) + float(delta_sec), total_duration_sec)


def visible_timeline_block_spans(
    planned_blocks: list[PlannedBlock],
    visible_start_sec: float,
    visible_end_sec: float,
) -> list[tuple[PlannedBlock, float, float]]:
    visible_spans: list[tuple[PlannedBlock, float, float]] = []
    for block in planned_blocks:
        if block.end_sec < visible_start_sec or block.start_sec > visible_end_sec:
            continue
        clipped_start = max(block.start_sec, visible_start_sec)
        clipped_end = min(block.end_sec, visible_end_sec)
        if clipped_end <= clipped_start:
            continue
        visible_spans.append((block, clipped_start, clipped_end))
    return visible_spans


def count_unique_presented_stimuli(stimuli_catalog: list[StimulusSpec]) -> int:
    return len({stimulus.runtime_key for stimulus in stimuli_catalog})


def derive_standard_trials_per_block(stimuli_catalog: list[StimulusSpec]) -> int:
    return count_unique_presented_stimuli(stimuli_catalog) * 2


def format_field_label(group_key: str, field_name: str) -> str:
    return FIELD_DISPLAY_LABELS.get(group_key, {}).get(field_name, field_name.replace("_", " "))


def format_block_volume_count(plan: DotsRunPlan) -> str:
    if not plan.planned_blocks:
        return "none"
    return f"{plan.planned_blocks[0].acquisition_frame_count} volumes"


def build_pre_run_checklist_items(plan: DotsRunPlan) -> list[str]:
    block_volume_count = format_block_volume_count(plan)
    return [
        f"Orient fish using the {plan.metadata.get('fish_orientation', 'bottom-left')} alignment marker.",
        f"Set microscope total volumes per block to {block_volume_count}.",
        "Confirm light-path levers are set.",
        "Confirm microscope acquisition is ready/armed.",
        "Confirm fish, stimulus folder, and previewed schedule are correct.",
    ]


def _visual_frame_count_for_segment(plan: DotsRunPlan, segment: TimelineSegment) -> int:
    if segment.kind == "stimulus" and segment.trial_index is not None:
        for trial in plan.trials:
            if trial.trial_index == segment.trial_index:
                return trial.frame_count
    return round(segment.duration_sec * FPS)


def build_timeline_segment_description(plan: DotsRunPlan, segment: TimelineSegment) -> str:
    title = segment.stimulus_name or segment.label or segment.kind.replace("_", " ")
    lines = [
        title,
        f"Type: {segment.kind.replace('_', ' ')}",
        f"Start: {format_duration(segment.start_sec)} ({segment.start_sec:.2f} sec)",
        f"End: {format_duration(segment.end_sec)} ({segment.end_sec:.2f} sec)",
        f"Duration: {_visual_frame_count_for_segment(plan, segment)} frames / {segment.duration_sec:.2f} sec",
    ]
    if segment.block_num is not None:
        lines.append(f"Block: B{segment.block_num}")
    if segment.trial_index is not None:
        lines.append(f"Trial: {segment.trial_index + 1}")
    if segment.stimulus_key:
        lines.append(f"Stimulus key: {segment.stimulus_key}")
    if segment.kind == "stimulus":
        for trial in plan.trials:
            if trial.trial_index == segment.trial_index:
                if trial.media_type == STIMULUS_MEDIA_VIDEO:
                    lines.append("Media: MP4 video")
                else:
                    lines.append(f"Dots: {trial.n_dots}")
                lines.append(f"Path: {trial.stimulus_path}")
                break
    elif segment.stimulus_name:
        lines.append(f"Stimulus: {segment.stimulus_name}")
    return "\n".join(lines)


def load_gui_settings(settings_path: Path = GUI_SETTINGS_PATH) -> dict[str, Any]:
    try:
        with settings_path.open("r", encoding="utf-8") as settings_file:
            settings = json.load(settings_file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return settings if isinstance(settings, dict) else {}


def save_gui_settings(settings: dict[str, Any], settings_path: Path = GUI_SETTINGS_PATH) -> None:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with settings_path.open("w", encoding="utf-8") as settings_file:
        json.dump(settings, settings_file, indent=2, sort_keys=True)


def build_remembered_gui_settings(
    metadata: dict[str, Any],
    stimuli_dir: str,
    mode: str | None = None,
    stimuli_params: dict[str, Any] | None = None,
    existing_settings: dict[str, Any] | None = None,
    functional_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = dict(existing_settings) if isinstance(existing_settings, dict) else {}
    remembered_metadata = {
        field_name: metadata[field_name]
        for field_name in REMEMBERED_METADATA_FIELDS
        if field_name in metadata
    }
    settings["metadata"] = remembered_metadata
    settings["stimuli_dir"] = stimuli_dir
    if mode is not None and stimuli_params is not None:
        remembered_by_mode = settings.get(GUI_SETTINGS_STIMULI_PARAMS_BY_MODE_KEY, {})
        if not isinstance(remembered_by_mode, dict):
            remembered_by_mode = {}
        else:
            remembered_by_mode = dict(remembered_by_mode)
        remembered_by_mode[mode] = {
            field_name: field_value
            for field_name, field_value in stimuli_params.items()
            if field_name not in REMEMBERED_STIMULI_PARAM_EXCLUDED_FIELDS
        }
        settings[GUI_SETTINGS_STIMULI_PARAMS_BY_MODE_KEY] = remembered_by_mode
    if mode is not None and functional_params is not None:
        remembered_functional_by_mode = settings.get(GUI_SETTINGS_FUNCTIONAL_PARAMS_BY_MODE_KEY, {})
        if not isinstance(remembered_functional_by_mode, dict):
            remembered_functional_by_mode = {}
        else:
            remembered_functional_by_mode = dict(remembered_functional_by_mode)
        remembered_functional_by_mode[mode] = {
            field_name: field_value
            for field_name, field_value in functional_params.items()
            if field_name not in REMEMBERED_FUNCTIONAL_PARAM_EXCLUDED_FIELDS
        }
        settings[GUI_SETTINGS_FUNCTIONAL_PARAMS_BY_MODE_KEY] = remembered_functional_by_mode
    return settings


def build_base_preview_summary(plan: DotsRunPlan) -> str:
    first_trials = ", ".join(trial.stimulus_name for trial in plan.trials[:6]) or "none"
    framerate = float(plan.functional_params.get("framerate", 0))
    n_volumes = plan.functional_params.get("n_volumes", plan.planned_total_acquisition_frames)
    return (
        f"Mode: {MODE_LABELS[plan.mode]}\n"
        f"Stimuli: {len(plan.stimuli_catalog)} files\n"
        f"Trials: {plan.total_trials}\n"
        f"Total duration: {format_duration(plan.total_duration_sec)} ({plan.total_duration_sec:.2f} sec)\n"
        f"Derived framerate: {framerate:.6g} Hz\n"
        f"Derived n_volumes: {n_volumes}\n"
        f"Mock run: {'yes' if plan.runtime.get('mock_mode') else 'no'}\n"
        f"First trials: {first_trials}"
    )


def build_compact_preview_summary(plan: DotsRunPlan) -> str:
    n_volumes = plan.functional_params.get("n_volumes", plan.planned_total_acquisition_frames)
    block_count = plan.planned_block_count
    parts = [
        MODE_LABELS[plan.mode],
        f"{len(plan.stimuli_catalog)} stimuli",
        f"{plan.total_trials} trials",
        f"{format_duration(plan.total_duration_sec)} total",
        f"{n_volumes} volumes",
    ]
    if block_count:
        parts.append(f"{block_count} blocks")
    parts.append(f"Mock: {'yes' if plan.runtime.get('mock_mode') else 'no'}")
    return " | ".join(parts)


def enrich_preview_summary_with_block_planning(plan: DotsRunPlan, base_summary: str) -> tuple[str, str | None]:
    if plan.mode not in {MODE_LOOP_BLOCKS, MODE_CONTINUOUS_SESSION}:
        return base_summary, None
    summary = summarize_plan(plan)
    block_frame_counts = plan.planned_block_frame_counts
    run_block_reason = None
    if len(set(block_frame_counts)) > 1:
        run_block_reason = (
            "Planned acquisition blocks have unequal volume counts; adjust stimuli/block or stimuli so "
            "baseline and stimulus blocks match."
        )
    inter_block_pause_sec = float(plan.stimuli_params.get("inter_block_pause_sec", 0))
    inter_block_pause_count = sum(1 for segment in plan.timeline if segment.kind == "interblock_pause")
    inter_block_pause_total_sec = inter_block_pause_count * inter_block_pause_sec
    if inter_block_pause_count > 0:
        inter_block_pause_line = (
            f"Inter-block pause contribution: "
            f"{inter_block_pause_count} x {inter_block_pause_sec:.2f} sec "
            f"({inter_block_pause_total_sec:.2f} sec total)"
        )
    elif inter_block_pause_sec > 0:
        inter_block_pause_line = (
            "Inter-block pause: not applied (single block; reduce n_trials_per_block to create multiple blocks)"
        )
    else:
        inter_block_pause_line = "Inter-block pause: none configured"
    block_lines = ", ".join(
        f"B{block.block_num} {block.block_kind.replace('_', ' ')}: "
        f"{format_duration(block.duration_sec)} ({block.duration_sec:.2f} sec, {block.acquisition_frame_count} frames)"
        for block in plan.planned_blocks
    )
    summary_text = (
        f"{base_summary}\n"
        f"Planned blocks: {summary['planned_block_count']}\n"
        f"Block acquisition durations and frames: {block_lines}\n"
        f"{inter_block_pause_line}\n"
        f"Total planned acquisition frames: {summary['planned_total_acquisition_frames']}"
    )
    return summary_text, run_block_reason


class DotsGuiApp:
    def __init__(self, root: tk.Tk, initial_mode: str):
        self.root = root
        self.root.title("Dots Experiment Launcher")
        self._configure_window_geometry()

        self.mode_var = tk.StringVar(value=initial_mode)
        self.stimuli_dir_var = tk.StringVar()
        self.mock_mode_var = tk.BooleanVar(value=False)
        self.mock_output_root_var = tk.StringVar(value=str(MOCK_OUTPUT_ROOT))
        self.summary_var = tk.StringVar(value="Load a stimulus folder and review parameters. Preview refreshes automatically.")
        self.status_var = tk.StringVar(value="Waiting for input.")

        self.field_vars: dict[str, dict[str, Any]] = {}
        self.runtime_defaults: dict[str, Any] = {}
        self.current_plan: DotsRunPlan | None = None
        self._preview_after_id: str | None = None
        self.preview_is_current = False
        self.run_block_reason = PREVIEW_PENDING_RUN_BLOCK_REASON
        self.dirty = True
        self.remembered_settings = load_gui_settings()
        self.stimulus_shuffle_seed = self._new_stimulus_shuffle_seed()
        self.auto_n_trials_per_block = True
        self._updating_dynamic_n_trials_per_block = False
        self.timeline_view_start_sec = 0.0
        self.timeline_view_end_sec = 1.0
        self.timeline_segment_items: dict[int, TimelineSegment] = {}
        self.hovered_timeline_segment_order: int | None = None
        self.timeline_hover_popup: tk.Toplevel | None = None
        self.timeline_hover_label: tk.Label | None = None
        self._timeline_pan_last_x: int | None = None

        self._configure_dark_console_theme()
        self._build_layout()
        self._load_mode(initial_mode)

    def _configure_dark_console_theme(self) -> None:
        self.root.configure(background=DARK_CONSOLE_THEME["root_bg"])
        self.root.option_add("*Background", DARK_CONSOLE_THEME["panel_bg"])
        self.root.option_add("*Foreground", DARK_CONSOLE_THEME["text_fg"])
        self.root.option_add("*selectBackground", DARK_CONSOLE_THEME["primary"])
        self.root.option_add("*selectForeground", "#04111f")
        self.root.option_add("*Entry.Background", DARK_CONSOLE_THEME["field_bg"])
        self.root.option_add("*Entry.Foreground", DARK_CONSOLE_THEME["field_fg"])
        self.root.option_add("*Listbox.Background", DARK_CONSOLE_THEME["field_bg"])
        self.root.option_add("*Listbox.Foreground", DARK_CONSOLE_THEME["field_fg"])
        self.root.option_add("*Listbox.selectBackground", DARK_CONSOLE_THEME["primary"])
        self.root.option_add("*Listbox.selectForeground", "#04111f")
        self.root.option_add("*TCombobox*Listbox.background", DARK_CONSOLE_THEME["field_bg"])
        self.root.option_add("*TCombobox*Listbox.foreground", DARK_CONSOLE_THEME["field_fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", DARK_CONSOLE_THEME["primary"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#04111f")
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(".", font=("TkDefaultFont", 10))
        style.configure("TFrame", background=DARK_CONSOLE_THEME["panel_bg"])
        style.configure(
            "Panel.TFrame",
            background=DARK_CONSOLE_THEME["panel_bg"],
            bordercolor=DARK_CONSOLE_THEME["border"],
            relief="flat",
        )
        style.configure(
            "TLabelframe",
            background=DARK_CONSOLE_THEME["panel_bg"],
            foreground=DARK_CONSOLE_THEME["primary"],
            bordercolor=DARK_CONSOLE_THEME["border"],
            relief="solid",
        )
        style.configure(
            "TLabelframe.Label",
            background=DARK_CONSOLE_THEME["panel_bg"],
            foreground=DARK_CONSOLE_THEME["primary"],
            font=("TkDefaultFont", 10, "bold"),
        )
        style.configure("TLabel", background=DARK_CONSOLE_THEME["panel_bg"], foreground=DARK_CONSOLE_THEME["text_fg"])
        style.configure(
            "Muted.TLabel",
            background=DARK_CONSOLE_THEME["panel_bg"],
            foreground=DARK_CONSOLE_THEME["muted_fg"],
        )
        style.configure(
            "TEntry",
            fieldbackground=DARK_CONSOLE_THEME["field_bg"],
            foreground=DARK_CONSOLE_THEME["field_fg"],
            insertcolor=DARK_CONSOLE_THEME["field_fg"],
            bordercolor=DARK_CONSOLE_THEME["border"],
            lightcolor=DARK_CONSOLE_THEME["border"],
            darkcolor=DARK_CONSOLE_THEME["border"],
            selectbackground=DARK_CONSOLE_THEME["primary"],
            selectforeground="#04111f",
            padding=4,
        )
        style.configure(
            "TCombobox",
            fieldbackground=DARK_CONSOLE_THEME["field_bg"],
            foreground=DARK_CONSOLE_THEME["field_fg"],
            background=DARK_CONSOLE_THEME["field_bg"],
            arrowcolor=DARK_CONSOLE_THEME["primary"],
            bordercolor=DARK_CONSOLE_THEME["border"],
            lightcolor=DARK_CONSOLE_THEME["border"],
            darkcolor=DARK_CONSOLE_THEME["border"],
            selectbackground=DARK_CONSOLE_THEME["primary"],
            selectforeground="#04111f",
            padding=4,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", DARK_CONSOLE_THEME["field_bg"])],
            foreground=[("readonly", DARK_CONSOLE_THEME["field_fg"])],
        )
        style.configure(
            "TCheckbutton",
            background=DARK_CONSOLE_THEME["panel_bg"],
            foreground=DARK_CONSOLE_THEME["text_fg"],
            indicatorcolor=DARK_CONSOLE_THEME["field_bg"],
        )
        style.map(
            "TCheckbutton",
            foreground=[("active", DARK_CONSOLE_THEME["primary_hover"])],
            background=[("active", DARK_CONSOLE_THEME["panel_bg"])],
        )
        style.configure(
            "TButton",
            background=DARK_CONSOLE_THEME["field_bg"],
            foreground=DARK_CONSOLE_THEME["text_fg"],
            bordercolor=DARK_CONSOLE_THEME["border"],
            lightcolor=DARK_CONSOLE_THEME["border"],
            darkcolor=DARK_CONSOLE_THEME["border"],
            focusthickness=1,
            focuscolor=DARK_CONSOLE_THEME["primary"],
            padding=(10, 5),
        )
        style.map(
            "TButton",
            background=[("active", DARK_CONSOLE_THEME["border"]), ("disabled", DARK_CONSOLE_THEME["panel_alt_bg"])],
            foreground=[("active", DARK_CONSOLE_THEME["primary_hover"]), ("disabled", DARK_CONSOLE_THEME["muted_fg"])],
        )
        style.configure(
            "Accent.TButton",
            background=DARK_CONSOLE_THEME["primary"],
            foreground="#04111f",
            bordercolor=DARK_CONSOLE_THEME["primary"],
            lightcolor=DARK_CONSOLE_THEME["primary"],
            darkcolor=DARK_CONSOLE_THEME["primary"],
            font=("TkDefaultFont", 10, "bold"),
        )
        style.map(
            "Accent.TButton",
            background=[("active", DARK_CONSOLE_THEME["primary_hover"]), ("disabled", DARK_CONSOLE_THEME["panel_alt_bg"])],
            foreground=[("active", "#04111f"), ("disabled", DARK_CONSOLE_THEME["muted_fg"])],
        )
        style.configure(
            "Vertical.TScrollbar",
            background=DARK_CONSOLE_THEME["field_bg"],
            troughcolor=DARK_CONSOLE_THEME["panel_alt_bg"],
            bordercolor=DARK_CONSOLE_THEME["border"],
            arrowcolor=DARK_CONSOLE_THEME["primary"],
            lightcolor=DARK_CONSOLE_THEME["border"],
            darkcolor=DARK_CONSOLE_THEME["border"],
        )

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=0)
        self.root.rowconfigure(1, weight=0)
        self.root.rowconfigure(2, weight=1)
        self.root.rowconfigure(3, weight=0)

        preview = ttk.Frame(self.root, padding=(12, 8, 12, 4), style="TFrame")
        preview.grid(row=0, column=0, sticky="ew")
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(1, weight=0)

        summary_frame = ttk.LabelFrame(preview, text="Summary", padding=(8, 4, 8, 4))
        summary_frame.grid(row=0, column=0, sticky="ew")
        summary_frame.columnconfigure(0, weight=1)
        ttk.Label(summary_frame, textvariable=self.summary_var, wraplength=1260, justify="left").grid(
            row=0, column=0, sticky="ew"
        )

        timeline_frame = ttk.LabelFrame(preview, text="Timeline Preview", padding=(8, 6, 8, 6))
        timeline_frame.grid(row=1, column=0, sticky="ew")
        timeline_frame.columnconfigure(0, weight=1)
        timeline_frame.rowconfigure(0, weight=0)
        self.timeline_canvas = tk.Canvas(
            timeline_frame,
            height=TIMELINE_PREVIEW_HEIGHT_PX,
            background=DARK_CONSOLE_THEME["canvas_bg"],
            highlightthickness=0,
        )
        self.timeline_canvas.grid(row=0, column=0, sticky="ew")

        legend = ttk.Frame(preview)
        legend.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.legend_frame = legend
        self._render_legend()

        controls = ttk.LabelFrame(self.root, text="Run Setup", padding=10)
        controls.grid(row=1, column=0, sticky="ew", padx=12, pady=(6, 0))
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
        setup_buttons = ttk.Frame(controls)
        setup_buttons.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(10, 0))
        setup_buttons.columnconfigure(0, weight=1)
        ttk.Button(setup_buttons, text="Orient fish", command=self._show_fish_alignment_from_current_inputs).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(setup_buttons, text="Visual test bouts", command=self._launch_visual_test_bouts).grid(
            row=1, column=0, sticky="ew", pady=(8, 0)
        )

        self.mock_output_row = ttk.Frame(controls)
        self.mock_output_row.columnconfigure(0, weight=1)
        ttk.Entry(self.mock_output_row, textvariable=self.mock_output_root_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(self.mock_output_row, text="Browse", command=self._browse_mock_output_root).grid(
            row=0, column=1, padx=(8, 0)
        )
        self.mock_output_label = ttk.Label(controls, text="Mock Output Root")
        self.mock_output_label.grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.mock_output_row.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(10, 0))

        forms_frame = ttk.Frame(self.root, padding=(12, 10, 12, 0))
        forms_frame.grid(row=2, column=0, sticky="nsew")
        forms_frame.columnconfigure(0, weight=1)
        forms_frame.rowconfigure(0, weight=1)

        self.forms_canvas = tk.Canvas(
            forms_frame,
            highlightthickness=0,
            borderwidth=0,
            background=DARK_CONSOLE_THEME["root_bg"],
        )
        self.forms_canvas.grid(row=0, column=0, sticky="nsew")
        forms_scrollbar = ttk.Scrollbar(forms_frame, orient="vertical", command=self.forms_canvas.yview)
        forms_scrollbar.grid(row=0, column=1, sticky="ns")
        self.forms_canvas.configure(yscrollcommand=forms_scrollbar.set)

        self.forms_container = ttk.Frame(self.forms_canvas)
        for column_index in range(FORM_GROUP_COLUMNS):
            self.forms_container.columnconfigure(column_index, weight=1, uniform="form-group")
        self.forms_canvas_window = self.forms_canvas.create_window((0, 0), window=self.forms_container, anchor="nw")
        self.forms_container.bind("<Configure>", lambda _: self._sync_forms_scrollregion())
        self.forms_canvas.bind(
            "<Configure>",
            lambda event: self.forms_canvas.itemconfigure(self.forms_canvas_window, width=event.width),
        )
        self.forms_canvas.bind("<Enter>", lambda _: self._bind_forms_mousewheel())
        self.forms_canvas.bind("<Leave>", lambda _: self._unbind_forms_mousewheel())

        footer = ttk.Frame(self.root, padding=(12, 12, 12, 12))
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)

        buttons = ttk.Frame(footer)
        buttons.grid(row=0, column=0, sticky="ew")
        buttons.columnconfigure((0, 1), weight=1)
        self.run_button = ttk.Button(buttons, text="Run", command=self.run_plan, state="disabled", style="Accent.TButton")
        self.run_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(buttons, text="Quit", command=self.root.destroy).grid(row=0, column=1, sticky="ew")

        ttk.Label(footer, textvariable=self.status_var, wraplength=1260, style="Muted.TLabel").grid(
            row=1, column=0, sticky="ew", pady=(12, 0)
        )

        self.timeline_canvas.bind("<Configure>", lambda _: self._draw_timeline())
        self.timeline_canvas.bind("<MouseWheel>", self._on_timeline_mousewheel)
        self.timeline_canvas.bind("<Button-4>", self._on_timeline_mousewheel)
        self.timeline_canvas.bind("<Button-5>", self._on_timeline_mousewheel)
        self.timeline_canvas.bind("<ButtonPress-2>", self._on_timeline_pan_start)
        self.timeline_canvas.bind("<Control-ButtonPress-1>", self._on_timeline_pan_start)
        self.timeline_canvas.bind("<B2-Motion>", self._on_timeline_pan_drag)
        self.timeline_canvas.bind("<Control-B1-Motion>", self._on_timeline_pan_drag)
        self.timeline_canvas.bind("<ButtonRelease-2>", self._on_timeline_pan_end)
        self.timeline_canvas.bind("<Control-ButtonRelease-1>", self._on_timeline_pan_end)
        self.timeline_canvas.bind("<Motion>", self._on_timeline_motion)
        self.timeline_canvas.bind("<Leave>", self._on_timeline_leave)
        self.stimuli_dir_var.trace_add("write", lambda *_: self._mark_dirty(randomize_stimulus_order=True))
        self.mock_output_root_var.trace_add("write", lambda *_: self._mark_dirty())
        self._update_mock_output_visibility()

    def _configure_window_geometry(self) -> None:
        default_width, default_height = (int(value) for value in DEFAULT_WINDOW_GEOMETRY.split("x", 1))
        available_width = max(self.root.winfo_screenwidth() - WINDOW_SAFETY_MARGIN_PX, 640)
        available_height = max(self.root.winfo_screenheight() - WINDOW_SAFETY_MARGIN_PX, 480)
        startup_width = min(default_width, available_width)
        startup_height = min(default_height, available_height)
        min_width = min(MIN_WINDOW_WIDTH, available_width)
        min_height = 1
        self.root.geometry(f"{startup_width}x{startup_height}")
        self.root.minsize(min_width, min_height)

    def _load_mode(self, mode: str) -> None:
        self.mode_var.set(mode)
        self._refresh_stimulus_shuffle_seed()
        self.auto_n_trials_per_block = True
        defaults = get_mode_defaults(mode)
        self.runtime_defaults = defaults["runtime"]
        for child in self.forms_container.winfo_children():
            child.destroy()
        self.field_vars = {}
        group_positions = compute_group_grid_positions(INPUT_GROUP_ROWS, FORM_GROUP_COLUMNS)

        group_labels = dict(FIELD_GROUPS)
        for group_key in INPUT_GROUP_ROWS:
            row_index, column_index = group_positions[group_key]
            group_label = group_labels[group_key]
            frame = ttk.LabelFrame(self.forms_container, text=group_label, padding=10)
            right_pad = 12 if column_index < FORM_GROUP_COLUMNS - 1 else 0
            frame.grid(row=row_index, column=column_index, sticky="ew", pady=(0, 12), padx=(0, right_pad))
            frame.columnconfigure(1, weight=1)
            self.field_vars[group_key] = {}
            values = defaults[group_key]
            for field_index, (field_name, field_value) in enumerate(values.items()):
                if group_key == "functional_params" and field_name in DERIVED_FUNCTIONAL_FIELDS:
                    continue
                label = ttk.Label(frame, text=format_field_label(group_key, field_name))
                label.grid(row=field_index, column=0, sticky="w")
                self._install_label_tooltip(label, group_key, field_name, group_label)
                variable, widget = self._create_input(frame, group_key, field_name, field_value)
                widget.grid(row=field_index, column=1, sticky="ew", padx=(8, 0), pady=2)
                self.field_vars[group_key][field_name] = variable

        self._sync_forms_scrollregion()
        self.forms_canvas.yview_moveto(0)
        self._apply_remembered_settings()
        self.current_plan = None
        self._mark_dirty("Protocol changed. Preview will refresh automatically.")

    def _create_input(
        self,
        parent: ttk.LabelFrame,
        group_key: str,
        field_name: str,
        field_value: Any,
    ) -> tuple[Any, ttk.Widget]:
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
            variable.trace_add(
                "write",
                lambda *_, group=group_key, field=field_name: self._on_field_change(group, field),
            )
        else:
            variable.trace_add(
                "write",
                lambda *_, group=group_key, field=field_name: self._on_field_change(group, field),
            )
        return variable, widget

    def _on_field_change(self, group_key: str, field_name: str) -> None:
        if self._updating_dynamic_n_trials_per_block:
            return
        randomize_stimulus_order = group_key == "stimuli_params"
        if group_key == "stimuli_params" and field_name == AUTO_BLOCK_FIELD_NAME:
            self.auto_n_trials_per_block = False
        self._mark_dirty(randomize_stimulus_order=randomize_stimulus_order)

    def _install_label_tooltip(self, label: ttk.Label, group_key: str, field_name: str, group_label: str) -> None:
        help_text = FIELD_HELP_TEXT.get(group_key, {}).get(
            field_name,
            f"{group_label} setting: {field_name.replace('_', ' ')}.",
        )
        DelayedTooltip(label, help_text, delay_ms=LABEL_TOOLTIP_DELAY_MS)

    def _sync_forms_scrollregion(self) -> None:
        self.forms_canvas.configure(scrollregion=self.forms_canvas.bbox("all"))

    def _bind_forms_mousewheel(self) -> None:
        self.forms_canvas.bind_all("<MouseWheel>", self._on_forms_mousewheel)
        self.forms_canvas.bind_all("<Button-4>", self._on_forms_mousewheel)
        self.forms_canvas.bind_all("<Button-5>", self._on_forms_mousewheel)

    def _unbind_forms_mousewheel(self) -> None:
        self.forms_canvas.unbind_all("<MouseWheel>")
        self.forms_canvas.unbind_all("<Button-4>")
        self.forms_canvas.unbind_all("<Button-5>")

    def _on_forms_mousewheel(self, event: Any) -> None:
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            event_delta = int(getattr(event, "delta", 0))
            if event_delta == 0:
                return
            if abs(event_delta) >= 120:
                delta = int(-event_delta / 120)
            else:
                delta = -1 if event_delta > 0 else 1
        self.forms_canvas.yview_scroll(delta, "units")

    def _browse_stimuli_dir(self) -> None:
        selected = filedialog.askdirectory(title="Select the folder containing the stimulus CSV/MP4 files")
        if selected:
            self.stimuli_dir_var.set(selected)
            self._mark_dirty("Stimulus folder changed. Refreshing preview.")

    def _use_sample_stimuli(self) -> None:
        self.stimuli_dir_var.set(str(SAMPLE_STIMULI_DIR))
        self._mark_dirty("Sample stimulus folder selected. Refreshing preview.")

    def _browse_mock_output_root(self) -> None:
        selected = filedialog.askdirectory(title="Select the root folder for mock-run outputs")
        if selected:
            self.mock_output_root_var.set(selected)
            self._mark_dirty("Mock output root changed. Refreshing preview.")

    def _on_mock_mode_toggle(self) -> None:
        self._update_mock_output_visibility()
        mode_label = "enabled" if self.mock_mode_var.get() else "disabled"
        self._mark_dirty(f"Mock run {mode_label}. Refreshing preview.")

    def _selected_fish_orientation(self) -> str:
        orientation_var = self.field_vars.get("metadata", {}).get("fish_orientation")
        if orientation_var is None:
            return "bottom-left"
        return str(orientation_var.get() or "bottom-left")

    def _show_fish_alignment_from_current_inputs(self) -> None:
        runtime = self.current_plan.runtime if self.current_plan else self.runtime_defaults
        try:
            show_fish_alignment(self._selected_fish_orientation(), runtime)
        except Exception as exc:
            messagebox.showerror("Fish orientation failed", str(exc))
            self.status_var.set(f"Fish orientation failed: {exc}")
            return
        self.status_var.set("Fish orientation display closed.")

    def _launch_visual_test_bouts(self) -> None:
        script_path = Path(__file__).with_name("visual_test_bouts.py")
        try:
            subprocess.Popen([sys.executable, str(script_path)], cwd=str(script_path.parent))
        except Exception as exc:
            messagebox.showerror("Visual test bouts failed", str(exc))
            self.status_var.set(f"Visual test bouts failed: {exc}")
            return
        self.status_var.set("Visual test bouts launched.")

    def _apply_remembered_settings(self) -> None:
        metadata_settings = self.remembered_settings.get("metadata", {})
        if isinstance(metadata_settings, dict):
            metadata_vars = self.field_vars.get("metadata", {})
            for field_name in REMEMBERED_METADATA_FIELDS:
                if field_name in metadata_settings and field_name in metadata_vars:
                    remembered_value = metadata_settings[field_name]
                    metadata_vars[field_name].set("" if remembered_value is None else str(remembered_value))
        stimuli_dir = self.remembered_settings.get("stimuli_dir")
        if isinstance(stimuli_dir, str) and stimuli_dir:
            self.stimuli_dir_var.set(stimuli_dir)
        stimuli_params_by_mode = self.remembered_settings.get(GUI_SETTINGS_STIMULI_PARAMS_BY_MODE_KEY, {})
        if not isinstance(stimuli_params_by_mode, dict):
            return
        stimuli_params_settings = stimuli_params_by_mode.get(self.mode_var.get(), {})
        if isinstance(stimuli_params_settings, dict):
            stimuli_vars = self.field_vars.get("stimuli_params", {})
            for field_name, remembered_value in stimuli_params_settings.items():
                if field_name in stimuli_vars and field_name not in REMEMBERED_STIMULI_PARAM_EXCLUDED_FIELDS:
                    stimuli_vars[field_name].set("" if remembered_value is None else str(remembered_value))
        functional_params_by_mode = self.remembered_settings.get(GUI_SETTINGS_FUNCTIONAL_PARAMS_BY_MODE_KEY, {})
        if not isinstance(functional_params_by_mode, dict):
            return
        functional_params_settings = functional_params_by_mode.get(self.mode_var.get(), {})
        if isinstance(functional_params_settings, dict):
            functional_vars = self.field_vars.get("functional_params", {})
            for field_name, remembered_value in functional_params_settings.items():
                if field_name in functional_vars and field_name not in REMEMBERED_FUNCTIONAL_PARAM_EXCLUDED_FIELDS:
                    functional_vars[field_name].set("" if remembered_value is None else str(remembered_value))

    def _update_mock_output_visibility(self) -> None:
        if self.mock_mode_var.get():
            self.mock_output_label.grid()
            self.mock_output_row.grid()
        else:
            self.mock_output_label.grid_remove()
            self.mock_output_row.grid_remove()

    @staticmethod
    def _new_stimulus_shuffle_seed() -> int:
        return random.randrange(2**32)

    def _refresh_stimulus_shuffle_seed(self) -> None:
        self.stimulus_shuffle_seed = self._new_stimulus_shuffle_seed()

    def _mark_dirty(self, status: str | None = None, randomize_stimulus_order: bool = False) -> None:
        if randomize_stimulus_order:
            self._refresh_stimulus_shuffle_seed()
        self.dirty = True
        self.preview_is_current = False
        self._set_run_block_reason(PREVIEW_PENDING_RUN_BLOCK_REASON)
        self._render_legend()
        if status:
            self.status_var.set(status)
        self._schedule_auto_preview()

    def _set_run_block_reason(self, reason: str | None) -> None:
        self.run_block_reason = reason
        can_run = self.preview_is_current and self.current_plan is not None and reason is None
        self.run_button.configure(state="normal" if can_run else "disabled")

    def _schedule_auto_preview(self) -> None:
        if self._preview_after_id is not None:
            self.root.after_cancel(self._preview_after_id)
        self._preview_after_id = self.root.after(AUTO_PREVIEW_DEBOUNCE_MS, self._auto_preview)

    def _auto_preview(self) -> None:
        self._preview_after_id = None
        if not self.stimuli_dir_var.get().strip():
            return
        self.preview_plan(show_dialog=False)

    def _collect_group_values(self, group_name: str) -> dict[str, Any]:
        defaults = get_mode_defaults(self.mode_var.get())[group_name]
        result: dict[str, Any] = {}
        for field_name, variable in self.field_vars[group_name].items():
            raw_value = variable.get()
            default_value = defaults[field_name]
            result[field_name] = self._coerce_value(raw_value, default_value)
        return result

    def _apply_dynamic_n_trials_per_block(self, stimuli_catalog: list[StimulusSpec]) -> None:
        if self.mode_var.get() == MODE_LOOP_STIMULI or not self.auto_n_trials_per_block:
            return
        standard_trial_count = derive_standard_trials_per_block(stimuli_catalog)
        if standard_trial_count <= 0:
            return
        n_trials_var = self.field_vars.get("stimuli_params", {}).get(AUTO_BLOCK_FIELD_NAME)
        if n_trials_var is None:
            return
        self._updating_dynamic_n_trials_per_block = True
        try:
            n_trials_var.set(str(standard_trial_count))
        finally:
            self._updating_dynamic_n_trials_per_block = False

    def _apply_derived_rest_to_field(self) -> None:
        if not self.current_plan or self.current_plan.mode == MODE_LOOP_STIMULI:
            return
        rest_var = self.field_vars.get("stimuli_params", {}).get(AUTO_REST_FIELD_NAME)
        if rest_var is None:
            return
        derived_rest = self.current_plan.stimuli_params.get(AUTO_REST_FIELD_NAME)
        if derived_rest is None:
            return
        self._updating_dynamic_n_trials_per_block = True
        try:
            rest_var.set(f"{float(derived_rest):.6g}")
        finally:
            self._updating_dynamic_n_trials_per_block = False

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

    def preview_plan(self, show_dialog: bool = True) -> None:
        try:
            if not self.stimuli_dir_var.get():
                raise ValueError("Select a stimulus folder before previewing.")
            metadata = self._collect_group_values("metadata")
            functional_params = self._collect_group_values("functional_params")
            stimuli_catalog = load_stimuli_catalog(self.stimuli_dir_var.get(), self.mode_var.get())
            self._apply_dynamic_n_trials_per_block(stimuli_catalog)
            stimuli_params = self._collect_group_values("stimuli_params")
            runtime_defaults = dict(self.runtime_defaults)
            runtime_defaults["mock_mode"] = bool(self.mock_mode_var.get())
            runtime_defaults["mock_output_root"] = self.mock_output_root_var.get() or str(MOCK_OUTPUT_ROOT)
            runtime_defaults["stimulus_shuffle_seed"] = self.stimulus_shuffle_seed
            metadata, functional_params, stimuli_params, runtime = prepare_run_config(
                self.mode_var.get(),
                metadata,
                functional_params,
                stimuli_params,
                runtime_defaults,
                self.stimuli_dir_var.get(),
            )
            self.current_plan = build_run_plan(
                self.mode_var.get(),
                metadata,
                functional_params,
                stimuli_params,
                runtime,
                stimuli_catalog,
            )
            self._apply_derived_rest_to_field()
        except Exception as exc:
            if show_dialog:
                messagebox.showerror("Preview failed", str(exc))
            self.status_var.set(f"Preview failed: {exc}")
            self.preview_is_current = False
            self.dirty = True
            self._set_run_block_reason(f"Preview must succeed before running: {exc}")
            return

        summary_text = build_base_preview_summary(self.current_plan)
        summary_text, run_block_reason = enrich_preview_summary_with_block_planning(self.current_plan, summary_text)
        self.summary_var.set(build_compact_preview_summary(self.current_plan))
        if run_block_reason:
            self.status_var.set(f"Preview is current, but run is blocked: {run_block_reason}")
        else:
            self.status_var.set("Preview is current. Run will use this exact schedule.")
        self.preview_is_current = True
        self.dirty = False
        self._set_run_block_reason(run_block_reason)
        self._remember_current_settings()
        self._reset_timeline_view()
        self._render_legend()
        self._draw_timeline()

    def _remember_current_settings(self) -> None:
        if not self.current_plan:
            return
        settings = build_remembered_gui_settings(
            self.current_plan.metadata,
            self.current_plan.runtime.get("stimuli_dir", self.stimuli_dir_var.get()),
            self.current_plan.mode,
            self.current_plan.stimuli_params,
            self.remembered_settings,
            self.current_plan.functional_params,
        )
        try:
            save_gui_settings(settings)
            self.remembered_settings = settings
        except OSError as exc:
            self.status_var.set(f"Preview is current, but GUI settings were not saved: {exc}")

    def _stimulus_identity_color_map(self) -> dict[str, str]:
        if not self.current_plan:
            return {}
        stimulus_identities = collect_timeline_stimulus_identities(self.current_plan.timeline)
        if not stimulus_identities:
            return {}
        colors = self._generate_distinct_colors(len(stimulus_identities))
        return dict(zip(stimulus_identities, colors))

    @staticmethod
    def _generate_distinct_colors(count: int) -> list[str]:
        if count <= 0:
            return []
        colors: list[str] = []
        for idx in range(count):
            hue = idx / count
            rgb = colorsys.hsv_to_rgb(hue, 0.65, 0.95)
            colors.append("#{0:02x}{1:02x}{2:02x}".format(*(int(channel * 255) for channel in rgb)))
        return colors

    def _render_legend(self) -> None:
        for child in self.legend_frame.winfo_children():
            child.destroy()
        legend_bg = DARK_CONSOLE_THEME["panel_bg"]
        entries: list[tuple[str, str]] = [
            (kind.replace("_", " "), color) for kind, color in BASE_TIMELINE_COLORS.items()
        ]
        entries.extend(
            (f"stimulus: {stimulus_name}", color) for stimulus_name, color in self._stimulus_identity_color_map().items()
        )
        positions = compute_legend_grid_positions(len(entries), LEGEND_ENTRIES_PER_ROW)
        for idx, (label, color) in enumerate(entries):
            row_index, column_index = positions[idx]
            swatch = tk.Canvas(self.legend_frame, width=18, height=18, highlightthickness=0, background=legend_bg)
            swatch.grid(row=row_index, column=column_index, padx=(0, 4), pady=(0, 4))
            swatch.create_rectangle(1, 1, 17, 17, fill=color, outline="")
            ttk.Label(self.legend_frame, text=label).grid(
                row=row_index,
                column=column_index + 1,
                padx=(0, 16),
                pady=(0, 4),
                sticky="w",
            )

    def _reset_timeline_view(self) -> None:
        total_duration = max(self.current_plan.total_duration_sec if self.current_plan else 1.0, TIMELINE_MIN_VISIBLE_SEC)
        self.timeline_view_start_sec = 0.0
        self.timeline_view_end_sec = total_duration
        self.hovered_timeline_segment_order = None
        self._hide_timeline_hover_popup()

    def _timeline_geometry(self) -> tuple[int, int, int, int]:
        width = max(self.timeline_canvas.winfo_width(), 640)
        label_width = 160
        right_margin = 30
        timeline_width = max(width - label_width - right_margin, 200)
        return width, label_width, right_margin, timeline_width

    def _timeline_x_to_sec(self, x: float) -> float:
        _, label_width, _, timeline_width = self._timeline_geometry()
        visible_duration = max(self.timeline_view_end_sec - self.timeline_view_start_sec, TIMELINE_MIN_VISIBLE_SEC)
        x_fraction = (float(x) - label_width) / timeline_width
        x_fraction = max(0.0, min(x_fraction, 1.0))
        return self.timeline_view_start_sec + x_fraction * visible_duration

    def _on_timeline_mousewheel(self, event: Any) -> str:
        if not self.current_plan:
            return "break"
        if getattr(event, "num", None) == 4:
            zoom_factor = TIMELINE_ZOOM_IN_FACTOR
        elif getattr(event, "num", None) == 5:
            zoom_factor = TIMELINE_ZOOM_OUT_FACTOR
        else:
            event_delta = int(getattr(event, "delta", 0))
            if event_delta == 0:
                return "break"
            zoom_factor = TIMELINE_ZOOM_IN_FACTOR if event_delta > 0 else TIMELINE_ZOOM_OUT_FACTOR
        anchor_sec = self._timeline_x_to_sec(getattr(event, "x", 0))
        self.timeline_view_start_sec, self.timeline_view_end_sec = zoom_timeline_view(
            self.timeline_view_start_sec,
            self.timeline_view_end_sec,
            self.current_plan.total_duration_sec,
            anchor_sec,
            zoom_factor,
        )
        self._draw_timeline()
        self._refresh_timeline_hover(getattr(event, "x", 0), getattr(event, "y", 0))
        return "break"

    def _on_timeline_pan_start(self, event: Any) -> str:
        if self.current_plan:
            self._timeline_pan_last_x = int(getattr(event, "x", 0))
        return "break"

    def _on_timeline_pan_drag(self, event: Any) -> str:
        if not self.current_plan or self._timeline_pan_last_x is None:
            return "break"
        x = int(getattr(event, "x", 0))
        _, _, _, timeline_width = self._timeline_geometry()
        visible_duration = max(self.timeline_view_end_sec - self.timeline_view_start_sec, TIMELINE_MIN_VISIBLE_SEC)
        delta_sec = ((self._timeline_pan_last_x - x) / timeline_width) * visible_duration
        self.timeline_view_start_sec, self.timeline_view_end_sec = pan_timeline_view(
            self.timeline_view_start_sec,
            self.timeline_view_end_sec,
            self.current_plan.total_duration_sec,
            delta_sec,
        )
        self._timeline_pan_last_x = x
        self._draw_timeline()
        self._refresh_timeline_hover(x, int(getattr(event, "y", 0)))
        return "break"

    def _on_timeline_pan_end(self, _: Any) -> str:
        self._timeline_pan_last_x = None
        return "break"

    def _on_timeline_motion(self, event: Any) -> None:
        self._refresh_timeline_hover(int(getattr(event, "x", 0)), int(getattr(event, "y", 0)))

    def _on_timeline_leave(self, _: Any) -> None:
        self.hovered_timeline_segment_order = None
        self._timeline_pan_last_x = None
        self._hide_timeline_hover_popup()
        self._draw_timeline()

    def _refresh_timeline_hover(self, x: int, y: int) -> None:
        if not self.current_plan:
            self._hide_timeline_hover_popup()
            return
        segment = self._timeline_segment_at_pointer()
        next_order = segment.order if segment else None
        if next_order != self.hovered_timeline_segment_order:
            self.hovered_timeline_segment_order = next_order
            self._draw_timeline()
        if segment:
            self._show_timeline_hover_popup(build_timeline_segment_description(self.current_plan, segment), x, y)
        else:
            self._hide_timeline_hover_popup()

    def _timeline_segment_at_pointer(self) -> TimelineSegment | None:
        for item_id in self.timeline_canvas.find_withtag("current"):
            segment = self.timeline_segment_items.get(item_id)
            if segment is not None:
                return segment
        return None

    def _show_timeline_hover_popup(self, text: str, x: int, y: int) -> None:
        if self.timeline_hover_popup is None or not self.timeline_hover_popup.winfo_exists():
            self.timeline_hover_popup = tk.Toplevel(self.timeline_canvas)
            self.timeline_hover_popup.wm_overrideredirect(True)
            self.timeline_hover_label = tk.Label(
                self.timeline_hover_popup,
                text=text,
                justify="left",
                background=TOOLTIP_BG_COLOR,
                foreground=TOOLTIP_FG_COLOR,
                relief="solid",
                borderwidth=1,
                padx=8,
                pady=6,
                wraplength=420,
            )
            self.timeline_hover_label.pack()
        elif self.timeline_hover_label is not None:
            self.timeline_hover_label.configure(text=text)
        root_x = self.timeline_canvas.winfo_rootx() + x + 16
        root_y = self.timeline_canvas.winfo_rooty() + y + 18
        self.timeline_hover_popup.wm_geometry(f"+{root_x}+{root_y}")

    def _hide_timeline_hover_popup(self) -> None:
        if self.timeline_hover_popup is not None:
            try:
                self.timeline_hover_popup.destroy()
            except tk.TclError:
                pass
        self.timeline_hover_popup = None
        self.timeline_hover_label = None

    def _draw_timeline(self) -> None:
        canvas = self.timeline_canvas
        canvas.delete("all")
        self.timeline_segment_items = {}
        if not self.current_plan:
            canvas.create_text(24, 24, anchor="nw", text="No preview yet.", fill=DARK_CONSOLE_THEME["muted_fg"])
            return

        width, label_width, right_margin, timeline_width = self._timeline_geometry()
        height = max(canvas.winfo_height(), 320)
        top = 40
        row_height = 36
        total_duration = max(self.current_plan.total_duration_sec, 1e-6)
        self.timeline_view_start_sec, self.timeline_view_end_sec = clamp_timeline_view(
            self.timeline_view_start_sec,
            self.timeline_view_end_sec,
            total_duration,
        )
        visible_start = self.timeline_view_start_sec
        visible_end = self.timeline_view_end_sec
        visible_duration = max(visible_end - visible_start, TIMELINE_MIN_VISIBLE_SEC)

        canvas.create_text(16, 16, anchor="nw", text=format_duration(visible_start), fill=DARK_CONSOLE_THEME["muted_fg"])
        canvas.create_text(
            width / 2,
            16,
            text=f"Visible: {format_duration(visible_duration)}",
            fill=DARK_CONSOLE_THEME["muted_fg"],
        )
        canvas.create_text(width - 16, 16, anchor="ne", text=format_duration(visible_end), fill=DARK_CONSOLE_THEME["muted_fg"])

        tracks = [
            ("rest", "Rest"),
            ("interblock_pause", "Inter-block"),
            ("prestim_pause", "Pre"),
            ("stimulus", "Stimulus"),
            ("poststim_pause", "Post"),
        ]
        stimulus_identity_colors = self._stimulus_identity_color_map()
        track_y = {kind: top + idx * row_height for idx, (kind, _) in enumerate(tracks)}
        block_guide_y = top + len(tracks) * row_height + 24

        for kind, label in tracks:
            y = track_y[kind]
            canvas.create_text(12, y + 12, anchor="w", text=label, fill=DARK_CONSOLE_THEME["text_fg"])
            canvas.create_line(label_width, y + 24, width - right_margin, y + 24, fill=DARK_CONSOLE_THEME["grid"])

        for segment in self.current_plan.timeline:
            if segment.duration_sec <= 0 or segment.kind not in track_y:
                continue
            if segment.end_sec < visible_start or segment.start_sec > visible_end:
                continue
            clipped_start = max(segment.start_sec, visible_start)
            clipped_end = min(segment.end_sec, visible_end)
            x0 = label_width + ((clipped_start - visible_start) / visible_duration) * timeline_width
            x1 = label_width + ((clipped_end - visible_start) / visible_duration) * timeline_width
            if x1 - x0 < 2:
                x1 = x0 + 2
            y = track_y[segment.kind]
            color = BASE_TIMELINE_COLORS.get(segment.kind, "#e5e7eb")
            if segment.kind == "stimulus":
                color = stimulus_identity_colors.get(segment.stimulus_name, "#fca5a5")
            outline = DARK_CONSOLE_THEME["hover_outline"] if segment.order == self.hovered_timeline_segment_order else ""
            width_px = 2 if segment.order == self.hovered_timeline_segment_order else 1
            item_id = canvas.create_rectangle(
                x0,
                y + 6,
                x1,
                y + 22,
                fill=color,
                outline=outline,
                width=width_px,
            )
            self.timeline_segment_items[item_id] = segment
            if segment.kind == "stimulus" and (x1 - x0) > 40:
                canvas.create_text((x0 + x1) / 2, y + 14, text=segment.stimulus_name or segment.label, font=("TkDefaultFont", 8))

        for segment in self.current_plan.timeline:
            if segment.kind != "trigger":
                continue
            if segment.start_sec < visible_start or segment.start_sec > visible_end:
                continue
            x = label_width + ((segment.start_sec - visible_start) / visible_duration) * timeline_width
            canvas.create_line(
                x,
                top - 6,
                x,
                top + len(tracks) * row_height,
                fill=DARK_CONSOLE_THEME["trigger"],
                dash=(3, 3),
            )

        canvas.create_text(12, block_guide_y, anchor="w", text=TIMELINE_BLOCK_GUIDE_LABEL, fill=DARK_CONSOLE_THEME["text_fg"])
        canvas.create_line(label_width, block_guide_y, width - right_margin, block_guide_y, fill=DARK_CONSOLE_THEME["grid"])
        for block, clipped_start, clipped_end in visible_timeline_block_spans(
            self.current_plan.planned_blocks,
            visible_start,
            visible_end,
        ):
            x0 = label_width + ((clipped_start - visible_start) / visible_duration) * timeline_width
            x1 = label_width + ((clipped_end - visible_start) / visible_duration) * timeline_width
            if x1 - x0 < 2:
                x1 = x0 + 2
            color = (
                DARK_CONSOLE_THEME["baseline_block"]
                if block.block_kind == "baseline_rest"
                else DARK_CONSOLE_THEME["stimulus_block"]
            )
            canvas.create_line(x0, block_guide_y, x1, block_guide_y, fill=color, width=4)
            label_x = min(max((x0 + x1) / 2, label_width + 12), width - right_margin - 12)
            canvas.create_text(
                label_x,
                block_guide_y + 12,
                text=f"B{block.block_num}",
                fill=color,
                font=("TkDefaultFont", 8),
            )

    def run_plan(self) -> None:
        print("[dots_gui] Run button handler entered", flush=True)
        if self.run_block_reason:
            title = "Run blocked" if self.preview_is_current else "Preview pending"
            messagebox.showwarning(title, self.run_block_reason)
            return
        if not self.current_plan:
            messagebox.showwarning("Preview pending", PREVIEW_PENDING_RUN_BLOCK_REASON)
            return
        checklist = PreRunChecklistDialog(self.root, build_pre_run_checklist_items(self.current_plan))
        if not checklist.accepted:
            print("[dots_gui] Pre-run checklist cancelled", flush=True)
            return
        print("[dots_gui] Pre-run checklist accepted", flush=True)

        self.root.withdraw()
        print("[dots_gui] GUI withdrawn", flush=True)
        try:
            print("[dots_gui] Calling run_planned_experiment()", flush=True)
            meta_dir = run_planned_experiment(self.current_plan)
            print(f"[dots_gui] run_planned_experiment() returned: {meta_dir}", flush=True)
        except Exception as exc:
            print(f"[dots_gui] run_planned_experiment() raised: {exc}", flush=True)
            self.root.deiconify()
            messagebox.showerror("Run failed", str(exc))
            self.status_var.set(f"Run failed: {exc}")
            return

        messagebox.showinfo("Run complete", f"Logs saved to:\n{meta_dir}")
        self.root.destroy()


class PreRunChecklistDialog:
    def __init__(self, parent: tk.Tk, checklist_items: list[str]):
        self.accepted = False
        self.window = tk.Toplevel(parent)
        self.window.title("Pre-run checklist")
        self.window.configure(background=DARK_CONSOLE_THEME["panel_bg"])
        self.window.transient(parent)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)

        frame = ttk.Frame(self.window, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)

        ttk.Label(
            frame,
            text="Confirm each item before starting the experiment.",
            justify="left",
            wraplength=520,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 12))

        self.item_vars: list[tk.BooleanVar] = []
        for item_index, item_text in enumerate(checklist_items, start=1):
            var = tk.BooleanVar(value=False)
            self.item_vars.append(var)
            ttk.Checkbutton(
                frame,
                text=item_text,
                variable=var,
                command=self._update_start_state,
            ).grid(row=item_index, column=0, sticky="w", pady=3)

        button_row = ttk.Frame(frame)
        button_row.grid(row=len(checklist_items) + 1, column=0, sticky="ew", pady=(16, 0))
        button_row.columnconfigure((0, 1), weight=1)
        ttk.Button(button_row, text="Cancel", command=self._cancel).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.start_button = ttk.Button(button_row, text="Start", command=self._start, state="disabled")
        self.start_button.grid(row=0, column=1, sticky="ew")

        parent.wait_window(self.window)

    def _update_start_state(self) -> None:
        all_checked = all(item_var.get() for item_var in self.item_vars)
        self.start_button.configure(state="normal" if all_checked else "disabled")

    def _start(self) -> None:
        self.accepted = True
        self.window.destroy()

    def _cancel(self) -> None:
        self.accepted = False
        self.window.destroy()


class DelayedTooltip:
    def __init__(self, widget: ttk.Label, text: str, delay_ms: int = LABEL_TOOLTIP_DELAY_MS):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id: str | None = None
        self._tooltip_window: tk.Toplevel | None = None

        self.widget.bind("<Enter>", self._schedule_show, add="+")
        self.widget.bind("<Leave>", self._hide, add="+")
        self.widget.bind("<ButtonPress>", self._hide, add="+")
        self.widget.bind("<Destroy>", self._hide, add="+")

    def _schedule_show(self, _: Any) -> None:
        self._cancel_pending()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _show(self) -> None:
        self._after_id = None
        if self._tooltip_window is not None or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        tooltip = tk.Toplevel(self.widget)
        tooltip.wm_overrideredirect(True)
        tooltip.wm_geometry(f"+{x}+{y}")
        tooltip.configure(background=TOOLTIP_BG_COLOR)
        label = tk.Label(
            tooltip,
            text=self.text,
            justify="left",
            relief="solid",
            borderwidth=1,
            wraplength=420,
            padx=8,
            pady=6,
            bg=TOOLTIP_BG_COLOR,
            fg=TOOLTIP_FG_COLOR,
            highlightthickness=0,
        )
        label.grid(row=0, column=0, sticky="nsew")
        self._tooltip_window = tooltip

    def _cancel_pending(self) -> None:
        if self._after_id is not None:
            self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _hide(self, _: Any) -> None:
        self._cancel_pending()
        if self._tooltip_window is not None:
            self._tooltip_window.destroy()
            self._tooltip_window = None


def launch_dots_gui(initial_mode: str) -> None:
    root = tk.Tk()
    app = DotsGuiApp(root, initial_mode=initial_mode)
    del app
    root.mainloop()


if __name__ == "__main__":
    launch_dots_gui(initial_mode=DEFAULT_INITIAL_MODE)
