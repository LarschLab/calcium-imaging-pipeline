from __future__ import annotations

import copy
import datetime as dt
import re
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


FPS = 60
PIXELS_MONITOR = [1280, 800]
MONITOR_NAME = "DLC_Projector"
MONITOR_WIDTH_CM = 15.2
MONITOR_DISTANCE_CM = 1
ARDUINO_PORT = "COM3"
ACQ_TRIGGER_PIN = 11
AUX_TRIGGER_PIN = 13
DATA_PATH = Path(r"Z:\FAC\FBM\CIG\jlarsch\default\D2c\07_Data")
VISUAL_STIMULATION_DIR = Path(__file__).resolve().parent
SAMPLE_STIMULI_DIR = VISUAL_STIMULATION_DIR / "sample_stimuli" / "dots_mock"
MOCK_OUTPUT_ROOT = VISUAL_STIMULATION_DIR.parent / "tmp" / "mock_runs"

MODE_LOOP_STIMULI = "loop_stimuli"
MODE_LOOP_BLOCKS = "loop_blocks"
MODE_CONTINUOUS_SESSION = "continuous_session"

MODE_LABELS = {
    MODE_LOOP_STIMULI: "Loop Stimuli",
    MODE_LOOP_BLOCKS: "Loop Blocks",
    MODE_CONTINUOUS_SESSION: "Continuous Session",
}

MODE_CHOICES = (
    MODE_LOOP_STIMULI,
    MODE_LOOP_BLOCKS,
    MODE_CONTINUOUS_SESSION,
)


@dataclass(frozen=True)
class StimulusSpec:
    runtime_key: str
    display_name: str
    path: Path
    frame_count: int
    n_dots: int
    duration_sec: float
    data_frame: pd.DataFrame


@dataclass(frozen=True)
class PlannedTrial:
    trial_index: int
    block_num: int
    stimulus_key: str
    stimulus_name: str
    stimulus_path: Path
    frame_count: int
    n_dots: int
    duration_sec: float


@dataclass(frozen=True)
class TimelineSegment:
    order: int
    kind: str
    start_sec: float
    duration_sec: float
    label: str
    trial_index: int | None = None
    block_num: int | None = None
    stimulus_key: str | None = None
    stimulus_name: str | None = None
    stimulus_path: str | None = None

    @property
    def end_sec(self) -> float:
        return self.start_sec + self.duration_sec


@dataclass(frozen=True)
class DotsRunPlan:
    mode: str
    metadata: dict[str, Any]
    functional_params: dict[str, Any]
    stimuli_params: dict[str, Any]
    runtime: dict[str, Any]
    stimuli_catalog: list[StimulusSpec]
    trials: list[PlannedTrial]
    timeline: list[TimelineSegment]
    total_duration_sec: float

    @property
    def total_trials(self) -> int:
        return len(self.trials)


def get_mode_defaults(mode: str) -> dict[str, Any]:
    if mode == MODE_LOOP_STIMULI:
        metadata = {
            "experiment_name": "social_buffering",
            "experimenter": "Lukas",
            "experiment_date": None,
            "fish_ID": "L587_f03",
            "fish_birth": "2026-01-20",
            "fish_age_dpf": 14,
            "genotype": "huc:H2B-GCamp6s",
            "size": "medium",
            "time_embedding": None,
            "fish_orientation": "bottom-left",
            "respond_to_omr": True,
            "respond_to_vibrations": True,
            "respond_to_bouts": False,
            "embedding_comments": None,
            "projector_LED_current": 30,
            "general_comments": None,
        }
        stimuli_params = {
            "pre_stim_resting_sec": 0,
            "pre_stim_pause_sec": 0,
            "post_stim_pause_sec": 0,
            "inter_block_pause_sec": 1,
            "n_trials_per_block": 18,
            "n_rep_stim": 1,
            "max_n_dots": 5,
        }
        functional_params = {
            "mode": "resonant",
            "n_frames": 3,
            "n_slices": 5,
            "n_volumes": 580,
            "step_size": 10,
            "framerate": 2,
            "AOM_mW": 24,
            "ETL_start": -20,
            "pump_speed": 0,
            "volume_flyback": 0,
            "frame_flyback": 0,
            "motion_correction": False,
        }
        runtime = {
            "data_path": str(DATA_PATH),
            "data_root_suffix": "",
            "stimulus_order": "sequential",
            "block_behavior": "per_stimulus_acquisition",
            "dot_radius_mode": "fixed",
            "dot_radius_cm": 0.2,
            "use_loom_markers": True,
            "window_color": "red",
            "monitor_name": MONITOR_NAME,
            "monitor_width_cm": MONITOR_WIDTH_CM,
            "monitor_distance_cm": MONITOR_DISTANCE_CM,
            "pixels_monitor": list(PIXELS_MONITOR),
            "screen": 1,
            "fullscr": True,
            "arduino_port": ARDUINO_PORT,
            "acq_trigger_pin": ACQ_TRIGGER_PIN,
            "aux_trigger_pin": AUX_TRIGGER_PIN,
            "mock_mode": False,
            "mock_output_root": str(MOCK_OUTPUT_ROOT),
        }
    elif mode == MODE_LOOP_BLOCKS:
        metadata = {
            "experiment_name": "groupsize_thalamus_exp02",
            "experimenter": "Matilde",
            "experiment_date": None,
            "fish_ID": 3,
            "fish_birth": "2025-06-23",
            "fish_age_dpf": None,
            "genotype": "huc:H2B-GCamp6s",
            "size": "medium",
            "time_embedding": None,
            "fish_orientation": "bottom-left",
            "respond_to_omr": False,
            "respond_to_vibrations": False,
            "respond_to_bouts": False,
            "embedding_comments": None,
            "projector_LED_current": 40,
            "general_comments": None,
        }
        stimuli_params = {
            "pre_stim_resting_sec": 813.666667,
            "pre_stim_pause_sec": 12.5,
            "post_stim_pause_sec": 12.5,
            "inter_block_pause_sec": 20,
            "n_trials_per_block": 16,
            "n_rep_stim": 4,
            "max_n_dots": 6,
            "manual_block_frames": "",
        }
        functional_params = {
            "mode": "resonant",
            "n_frames": 3,
            "n_slices": 5,
            "n_volumes": 1610,
            "step_size": 10,
            "framerate": 2,
            "AOM_mW": 32,
            "ETL_start": -20,
            "pump_speed": 0,
            "volume_flyback": 0,
            "frame_flyback": 0,
            "motion_correction": False,
        }
        runtime = {
            "data_path": str(DATA_PATH),
            "data_root_suffix": "Microscopy",
            "stimulus_order": "random",
            "block_behavior": "block_rollover",
            "dot_radius_mode": "per_frame",
            "use_loom_markers": False,
            "window_color": "red",
            "monitor_name": MONITOR_NAME,
            "monitor_width_cm": MONITOR_WIDTH_CM,
            "monitor_distance_cm": MONITOR_DISTANCE_CM,
            "pixels_monitor": list(PIXELS_MONITOR),
            "screen": 1,
            "fullscr": True,
            "arduino_port": ARDUINO_PORT,
            "acq_trigger_pin": ACQ_TRIGGER_PIN,
            "aux_trigger_pin": AUX_TRIGGER_PIN,
            "mock_mode": False,
            "mock_output_root": str(MOCK_OUTPUT_ROOT),
        }
    elif mode == MODE_CONTINUOUS_SESSION:
        metadata = {
            "experiment_name": "groupsize_thalamus_exp02",
            "experimenter": "Matilde",
            "experiment_date": None,
            "fish_ID": 3,
            "fish_birth": "2025-06-23",
            "fish_age_dpf": None,
            "genotype": "huc:H2B-GCamp6s",
            "size": "medium",
            "time_embedding": None,
            "fish_orientation": "bottom-left",
            "respond_to_omr": False,
            "respond_to_vibrations": False,
            "respond_to_bouts": False,
            "embedding_comments": None,
            "projector_power": 40,
            "general_comments": None,
        }
        stimuli_params = {
            "pre_stim_resting_sec": 813.666667,
            "pre_stim_pause_sec": 12.5,
            "post_stim_pause_sec": 12.5,
            "inter_block_pause_sec": 20,
            "n_trials_per_block": 16,
            "n_rep_stim": 4,
            "dot_radius_cm": 0.2,
            "max_n_dots": 6,
            "manual_block_frames": "",
        }
        functional_params = {
            "mode": "linear",
            "n_frames": 3,
            "n_slices": 5,
            "n_volumes": 1610,
            "step_size": 10,
            "framerate": 2,
            "AOM_mW": 32,
            "ETL_start": -20,
            "pump_speed": 0,
            "volume_flyback": 0,
            "frame_flyback": 0,
            "motion_correction": False,
        }
        runtime = {
            "data_path": str(DATA_PATH),
            "data_root_suffix": "Microscopy",
            "stimulus_order": "random",
            "block_behavior": "block_rollover",
            "dot_radius_mode": "config",
            "use_loom_markers": False,
            "window_color": "red",
            "monitor_name": MONITOR_NAME,
            "monitor_width_cm": MONITOR_WIDTH_CM,
            "monitor_distance_cm": MONITOR_DISTANCE_CM,
            "pixels_monitor": list(PIXELS_MONITOR),
            "screen": 1,
            "fullscr": True,
            "arduino_port": ARDUINO_PORT,
            "acq_trigger_pin": ACQ_TRIGGER_PIN,
            "aux_trigger_pin": AUX_TRIGGER_PIN,
            "mock_mode": False,
            "mock_output_root": str(MOCK_OUTPUT_ROOT),
        }
    else:
        raise ValueError(f"Unsupported dots mode: {mode}")

    metadata = copy.deepcopy(metadata)
    metadata["experiment_date"] = dt.datetime.now().strftime("%Y-%m-%d-%H%M")
    return {
        "metadata": metadata,
        "stimuli_params": copy.deepcopy(stimuli_params),
        "functional_params": copy.deepcopy(functional_params),
        "runtime": copy.deepcopy(runtime),
    }


def load_stimuli_catalog(stimuli_dir: str | Path, mode: str) -> list[StimulusSpec]:
    stimuli_path = Path(stimuli_dir)
    file_paths = list(stimuli_path.glob("*.csv"))
    if mode == MODE_LOOP_STIMULI:
        file_paths.sort(key=_numeric_sort_key)
    if not file_paths:
        raise ValueError(f"No stimulus CSV files found in {stimuli_path}")

    catalog: list[StimulusSpec] = []
    for file_path in file_paths:
        data_frame = pd.read_csv(file_path)
        if data_frame.empty:
            raise ValueError(f"Stimulus file is empty: {file_path}")
        if mode == MODE_LOOP_STIMULI:
            runtime_key = str(file_path)
            display_name = file_path.stem
        else:
            runtime_key = file_path.stem.split("_")[0]
            display_name = runtime_key
        frame_count = len(data_frame)
        n_dots = _infer_n_dots(data_frame)
        catalog.append(
            StimulusSpec(
                runtime_key=runtime_key,
                display_name=display_name,
                path=file_path,
                frame_count=frame_count,
                n_dots=n_dots,
                duration_sec=frame_count / FPS,
                data_frame=data_frame,
            )
        )
    return catalog


def prepare_run_config(
    mode: str,
    metadata: dict[str, Any],
    functional_params: dict[str, Any],
    stimuli_params: dict[str, Any],
    runtime: dict[str, Any],
    stimuli_dir: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    prepared_metadata = copy.deepcopy(metadata)
    prepared_functional = copy.deepcopy(functional_params)
    prepared_stimuli = copy.deepcopy(stimuli_params)
    prepared_runtime = copy.deepcopy(runtime)

    prepared_metadata["experiment_date"] = prepared_metadata.get("experiment_date") or dt.datetime.now().strftime("%Y-%m-%d-%H%M")
    prepared_metadata["fish_orientation"] = prepared_metadata.get("fish_orientation") or "bottom-left"
    prepared_metadata["path_to_stimuli"] = str(Path(stimuli_dir))
    prepared_metadata["fish_age_dpf"] = compute_fish_age_days(prepared_metadata.get("fish_birth"))

    prepared_runtime["stimuli_dir"] = str(Path(stimuli_dir))
    prepared_runtime["mode"] = mode
    prepared_runtime["mock_mode"] = bool(prepared_runtime.get("mock_mode", False))
    prepared_runtime["mock_output_root"] = str(Path(prepared_runtime.get("mock_output_root", MOCK_OUTPUT_ROOT)))
    return prepared_metadata, prepared_functional, prepared_stimuli, prepared_runtime


def build_run_plan(
    mode: str,
    metadata: dict[str, Any],
    functional_params: dict[str, Any],
    stimuli_params: dict[str, Any],
    runtime: dict[str, Any],
    stimuli_catalog: list[StimulusSpec],
) -> DotsRunPlan:
    stimulus_by_key = {stimulus.runtime_key: stimulus for stimulus in stimuli_catalog}
    order = _build_trial_order(mode, runtime, stimuli_params, stimuli_catalog)

    timeline: list[TimelineSegment] = []
    trials: list[PlannedTrial] = []
    current_time = 0.0
    order_index = 0
    block_num = 0

    current_time, order_index = _append_timed_segment(
        timeline,
        order_index,
        current_time,
        "rest",
        float(stimuli_params.get("pre_stim_resting_sec", 0)),
        "Pre-stimulus rest",
        block_num=block_num,
    )

    if mode == MODE_LOOP_STIMULI:
        current_time, order_index = _append_marker(
            timeline, order_index, current_time, "trigger", "B0_start", block_num=0
        )
        for trial_index, stimulus_key in enumerate(order):
            stimulus = stimulus_by_key[stimulus_key]
            trials.append(
                PlannedTrial(
                    trial_index=trial_index,
                    block_num=0,
                    stimulus_key=stimulus.runtime_key,
                    stimulus_name=stimulus.display_name,
                    stimulus_path=stimulus.path,
                    frame_count=stimulus.frame_count,
                    n_dots=stimulus.n_dots,
                    duration_sec=stimulus.duration_sec,
                )
            )
            current_time, order_index = _append_timed_segment(
                timeline,
                order_index,
                current_time,
                "prestim_pause",
                float(stimuli_params.get("pre_stim_pause_sec", 0)),
                f"Trial {trial_index + 1} pre-pause",
                trial_index=trial_index,
                block_num=0,
                stimulus_key=stimulus.runtime_key,
                stimulus_name=stimulus.display_name,
                stimulus_path=str(stimulus.path),
            )
            current_time, order_index = _append_marker(
                timeline,
                order_index,
                current_time,
                "trigger",
                f"B0_acq_start_stim{trial_index}",
                trial_index=trial_index,
                block_num=0,
                stimulus_key=stimulus.runtime_key,
                stimulus_name=stimulus.display_name,
                stimulus_path=str(stimulus.path),
            )
            current_time, order_index = _append_marker(
                timeline,
                order_index,
                current_time,
                "trigger",
                f"B0_aux_pulse_stim{trial_index}",
                trial_index=trial_index,
                block_num=0,
                stimulus_key=stimulus.runtime_key,
                stimulus_name=stimulus.display_name,
                stimulus_path=str(stimulus.path),
            )
            current_time, order_index = _append_timed_segment(
                timeline,
                order_index,
                current_time,
                "stimulus",
                stimulus.duration_sec,
                stimulus.display_name,
                trial_index=trial_index,
                block_num=0,
                stimulus_key=stimulus.runtime_key,
                stimulus_name=stimulus.display_name,
                stimulus_path=str(stimulus.path),
            )
            current_time, order_index = _append_marker(
                timeline,
                order_index,
                current_time,
                "trigger",
                f"B0_aux_pulse_end_stim{trial_index}",
                trial_index=trial_index,
                block_num=0,
                stimulus_key=stimulus.runtime_key,
                stimulus_name=stimulus.display_name,
                stimulus_path=str(stimulus.path),
            )
            current_time, order_index = _append_timed_segment(
                timeline,
                order_index,
                current_time,
                "poststim_pause",
                float(stimuli_params.get("post_stim_pause_sec", 0)),
                f"Trial {trial_index + 1} post-pause",
                trial_index=trial_index,
                block_num=0,
                stimulus_key=stimulus.runtime_key,
                stimulus_name=stimulus.display_name,
                stimulus_path=str(stimulus.path),
            )
        current_time, order_index = _append_marker(
            timeline, order_index, current_time, "trigger", "B0_end", block_num=0
        )
    else:
        current_time, order_index = _append_marker(
            timeline, order_index, current_time, "trigger", "B0_start", block_num=0
        )
        block_size = int(stimuli_params.get("n_trials_per_block", 1))
        inter_block_pause = float(stimuli_params.get("inter_block_pause_sec", 0))
        post_pause = float(
            stimuli_params.get(
                "pre_stim_pause_sec" if mode == MODE_LOOP_BLOCKS else "post_stim_pause_sec",
                0,
            )
        )
        for trial_index, stimulus_key in enumerate(order):
            if block_size <= 0:
                raise ValueError("n_trials_per_block must be greater than 0")
            if trial_index % block_size == 0:
                current_time, order_index = _append_marker(
                    timeline, order_index, current_time, "trigger", f"B{block_num}_end", block_num=block_num
                )
                current_time, order_index = _append_timed_segment(
                    timeline,
                    order_index,
                    current_time,
                    "interblock_pause",
                    inter_block_pause,
                    f"Block {block_num} pause",
                    block_num=block_num,
                )
                block_num += 1
                current_time, order_index = _append_marker(
                    timeline, order_index, current_time, "trigger", f"B{block_num}_start", block_num=block_num
                )

            stimulus = stimulus_by_key[stimulus_key]
            trials.append(
                PlannedTrial(
                    trial_index=trial_index,
                    block_num=block_num,
                    stimulus_key=stimulus.runtime_key,
                    stimulus_name=stimulus.display_name,
                    stimulus_path=stimulus.path,
                    frame_count=stimulus.frame_count,
                    n_dots=stimulus.n_dots,
                    duration_sec=stimulus.duration_sec,
                )
            )
            current_time, order_index = _append_timed_segment(
                timeline,
                order_index,
                current_time,
                "prestim_pause",
                float(stimuli_params.get("pre_stim_pause_sec", 0)),
                f"Trial {trial_index + 1} pre-pause",
                trial_index=trial_index,
                block_num=block_num,
                stimulus_key=stimulus.runtime_key,
                stimulus_name=stimulus.display_name,
                stimulus_path=str(stimulus.path),
            )
            current_time, order_index = _append_timed_segment(
                timeline,
                order_index,
                current_time,
                "stimulus",
                stimulus.duration_sec,
                stimulus.display_name,
                trial_index=trial_index,
                block_num=block_num,
                stimulus_key=stimulus.runtime_key,
                stimulus_name=stimulus.display_name,
                stimulus_path=str(stimulus.path),
            )
            current_time, order_index = _append_timed_segment(
                timeline,
                order_index,
                current_time,
                "poststim_pause",
                post_pause,
                f"Trial {trial_index + 1} post-pause",
                trial_index=trial_index,
                block_num=block_num,
                stimulus_key=stimulus.runtime_key,
                stimulus_name=stimulus.display_name,
                stimulus_path=str(stimulus.path),
            )
        current_time, order_index = _append_marker(
            timeline, order_index, current_time, "trigger", f"B{block_num}_end", block_num=block_num
        )

    return DotsRunPlan(
        mode=mode,
        metadata=copy.deepcopy(metadata),
        functional_params=copy.deepcopy(functional_params),
        stimuli_params=copy.deepcopy(stimuli_params),
        runtime=copy.deepcopy(runtime),
        stimuli_catalog=list(stimuli_catalog),
        trials=trials,
        timeline=timeline,
        total_duration_sec=current_time,
    )


def plan_to_schedule_rows(plan: DotsRunPlan) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for segment in plan.timeline:
        rows.append(
            {
                "mode": plan.mode,
                "order": segment.order,
                "kind": segment.kind,
                "label": segment.label,
                "start_sec": round(segment.start_sec, 6),
                "duration_sec": round(segment.duration_sec, 6),
                "end_sec": round(segment.end_sec, 6),
                "trial_index": segment.trial_index,
                "block_num": segment.block_num,
                "stimulus_key": segment.stimulus_key,
                "stimulus_name": segment.stimulus_name,
                "stimulus_path": segment.stimulus_path,
            }
        )
    return rows


def summarize_plan(plan: DotsRunPlan) -> dict[str, Any]:
    summary = {
        "mode": plan.mode,
        "mode_label": MODE_LABELS[plan.mode],
        "total_duration_sec": round(plan.total_duration_sec, 3),
        "total_duration_pretty": format_duration(plan.total_duration_sec),
        "total_trials": plan.total_trials,
        "n_stimuli": len(plan.stimuli_catalog),
    }
    if plan.mode in {MODE_LOOP_BLOCKS, MODE_CONTINUOUS_SESSION}:
        manual_block_frames, derived_planes_per_block, derived_total_planes = _compute_manual_block_plane_summary(plan)
        summary["manual_block_frames"] = ", ".join(str(frame_count) for frame_count in manual_block_frames)
        summary["derived_planes_per_block"] = derived_planes_per_block
        summary["derived_total_planes"] = derived_total_planes
    return summary


def format_duration(total_seconds: float) -> str:
    total_seconds = int(round(total_seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:d}:{seconds:02d}"


def infer_stimulus_type(stimulus_name: str | None) -> str:
    if not stimulus_name:
        return "unknown"
    normalized = stimulus_name.strip()
    if not normalized:
        return "unknown"
    tokens = re.split(r"[_\-\s]+", normalized)
    if tokens and tokens[0]:
        return tokens[0]
    return normalized


def compute_fish_age_days(fish_birth: str | None) -> int | None:
    if not fish_birth:
        return None
    parsed = dt.datetime.strptime(fish_birth, "%Y-%m-%d")
    return (dt.datetime.today() - parsed).days


def _compute_manual_block_plane_summary(plan: DotsRunPlan) -> tuple[list[int], list[float], float]:
    manual_field = plan.stimuli_params.get("manual_block_frames", "")
    manual_block_frames = _parse_manual_block_frames(manual_field)
    planned_block_count = _planned_block_count_from_trials(plan.trials)
    if len(manual_block_frames) != planned_block_count:
        raise ValueError(
            "manual_block_frames count does not match planned block count "
            f"({len(manual_block_frames)} entered vs {planned_block_count} planned)"
        )

    framerate = float(plan.functional_params.get("framerate", 0))
    derived_planes_per_block = [frame_count / FPS * framerate for frame_count in manual_block_frames]
    derived_total_planes = sum(derived_planes_per_block)
    return manual_block_frames, derived_planes_per_block, derived_total_planes


def _parse_manual_block_frames(raw_value: Any) -> list[int]:
    raw_text = "" if raw_value is None else str(raw_value)
    parts = [part.strip() for part in raw_text.split(",")]
    if not raw_text.strip() or any(part == "" for part in parts):
        raise ValueError(
            "manual_block_frames is required for block-based modes and must be a comma-separated list "
            "of positive integers."
        )

    frame_counts: list[int] = []
    for part in parts:
        try:
            frame_count = int(part)
        except ValueError as exc:
            raise ValueError(f"manual_block_frames contains a non-numeric value: '{part}'") from exc
        if frame_count <= 0:
            raise ValueError(f"manual_block_frames entries must be positive integers; got {frame_count}")
        frame_counts.append(frame_count)
    return frame_counts


def _planned_block_count_from_trials(trials: list[PlannedTrial]) -> int:
    ordered_blocks: list[int] = []
    for trial in trials:
        if trial.block_num not in ordered_blocks:
            ordered_blocks.append(trial.block_num)
    return len(ordered_blocks)


def _build_trial_order(
    mode: str,
    runtime: dict[str, Any],
    stimuli_params: dict[str, Any],
    stimuli_catalog: list[StimulusSpec],
) -> list[str]:
    n_reps = int(stimuli_params.get("n_rep_stim", 1))
    if n_reps <= 0:
        raise ValueError("n_rep_stim must be greater than 0")
    base_order = [stimulus.runtime_key for stimulus in stimuli_catalog]
    order: list[str] = []

    if runtime.get("stimulus_order") == "sequential":
        for _ in range(n_reps):
            order.extend(base_order)
        return order

    rng = random.Random()
    for _ in range(n_reps):
        chunk = list(base_order)
        rng.shuffle(chunk)
        order.extend(chunk)
    return order


def _numeric_sort_key(path: Path) -> tuple[int, str]:
    match = re.search(r"\d+", path.stem)
    if match:
        return int(match.group()), path.name
    return 10**9, path.name


def _infer_n_dots(data_frame: pd.DataFrame) -> int:
    x_columns = [column for column in data_frame.columns if re.match(r"dot\d+_x$", column)]
    if x_columns:
        return len(x_columns)
    return len(data_frame.columns) // 3


def _append_timed_segment(
    timeline: list[TimelineSegment],
    order_index: int,
    start_sec: float,
    kind: str,
    duration_sec: float,
    label: str,
    **kwargs: Any,
) -> tuple[float, int]:
    duration_sec = float(duration_sec)
    if duration_sec <= 0:
        return start_sec, order_index
    timeline.append(
        TimelineSegment(
            order=order_index,
            kind=kind,
            start_sec=start_sec,
            duration_sec=duration_sec,
            label=label,
            **kwargs,
        )
    )
    return start_sec + duration_sec, order_index + 1


def _append_marker(
    timeline: list[TimelineSegment],
    order_index: int,
    start_sec: float,
    kind: str,
    label: str,
    **kwargs: Any,
) -> tuple[float, int]:
    timeline.append(
        TimelineSegment(
            order=order_index,
            kind=kind,
            start_sec=start_sec,
            duration_sec=0.0,
            label=label,
            **kwargs,
        )
    )
    return start_sec, order_index + 1
