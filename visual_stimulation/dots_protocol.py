from __future__ import annotations

import copy
import datetime as dt
import math
import re
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


FPS = 60
STIMULUS_MEDIA_CSV = "csv"
STIMULUS_MEDIA_VIDEO = "video"
SUPPORTED_STIMULUS_SUFFIXES = {".csv", ".mp4"}
MICROSCOPE_BASE_FRAME_RATE_HZ = 30
PIXELS_MONITOR = [1280, 800]
MONITOR_NAME = "DLC_Projector"
MONITOR_WIDTH_CM = 15.2
MONITOR_DISTANCE_CM = 1
ARDUINO_PORT = "COM3"
ACQ_TRIGGER_PIN = 11
AUX_TRIGGER_PIN = 13
TRIGGER_PULSE_SEC = 0.05
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
    data_frame: pd.DataFrame | None = None
    media_type: str = STIMULUS_MEDIA_CSV


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
    media_type: str = STIMULUS_MEDIA_CSV


@dataclass(frozen=True)
class PlannedBlock:
    block_num: int
    trial_indices: list[int]
    start_sec: float
    end_sec: float
    duration_sec: float
    acquisition_frame_count: int
    block_kind: str = "stimulus_block"


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
    planned_blocks: list[PlannedBlock]
    timeline: list[TimelineSegment]
    total_duration_sec: float

    @property
    def total_trials(self) -> int:
        return len(self.trials)

    @property
    def planned_block_count(self) -> int:
        return len(self.planned_blocks)

    @property
    def planned_block_frame_counts(self) -> list[int]:
        return [block.acquisition_frame_count for block in self.planned_blocks]

    @property
    def planned_total_acquisition_frames(self) -> int:
        return sum(self.planned_block_frame_counts)


def derive_functional_framerate(functional_params: dict[str, Any]) -> float:
    n_frames = float(functional_params.get("n_frames", 0))
    n_slices = float(functional_params.get("n_slices", 0))
    if n_frames <= 0 or n_slices <= 0:
        raise ValueError("n_frames and n_slices must be greater than 0 to derive framerate")
    return MICROSCOPE_BASE_FRAME_RATE_HZ / n_frames / n_slices


def normalize_session(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("session must be an integer greater than or equal to 1")
    if isinstance(value, int):
        session = value
    elif isinstance(value, str) and value.strip().isdigit():
        session = int(value)
    else:
        raise ValueError("session must be an integer greater than or equal to 1")
    if session < 1:
        raise ValueError("session must be an integer greater than or equal to 1")
    return session


def get_mode_defaults(mode: str) -> dict[str, Any]:
    if mode == MODE_LOOP_STIMULI:
        metadata = {
            "experiment_name": "social_buffering",
            "experimenter": "Lukas",
            "experiment_date": None,
            "fish_ID": "L587_f03",
            "session": 1,
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
            "trigger_pulse_sec": TRIGGER_PULSE_SEC,
            "mock_mode": False,
            "mock_output_root": str(MOCK_OUTPUT_ROOT),
        }
    elif mode == MODE_LOOP_BLOCKS:
        metadata = {
            "experiment_name": "groupsize_thalamus_exp02",
            "experimenter": "Matilde",
            "experiment_date": None,
            "fish_ID": "L395_f01",
            "session": 1,
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
            "trigger_pulse_sec": TRIGGER_PULSE_SEC,
            "mock_mode": False,
            "mock_output_root": str(MOCK_OUTPUT_ROOT),
        }
    elif mode == MODE_CONTINUOUS_SESSION:
        metadata = {
            "experiment_name": "groupsize_thalamus_exp02",
            "experimenter": "Matilde",
            "experiment_date": None,
            "fish_ID": "L395_f01",
            "session": 1,
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
            "trigger_pulse_sec": TRIGGER_PULSE_SEC,
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
    file_paths = sorted(
        (path for path in stimuli_path.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_STIMULUS_SUFFIXES),
        key=lambda path: path.name,
    )
    if mode == MODE_LOOP_STIMULI:
        file_paths.sort(key=_numeric_sort_key)
    if not file_paths:
        raise ValueError(f"No stimulus CSV/MP4 files found in {stimuli_path}")

    catalog: list[StimulusSpec] = []
    runtime_keys: set[str] = set()
    for file_path in file_paths:
        if mode == MODE_LOOP_STIMULI:
            runtime_key = str(file_path)
            display_name = file_path.stem
        else:
            runtime_key = file_path.stem
            display_name = file_path.stem
        if runtime_key in runtime_keys:
            raise ValueError(f"Duplicate stimulus key '{runtime_key}' from files in {stimuli_path}")
        runtime_keys.add(runtime_key)

        if file_path.suffix.lower() == ".csv":
            data_frame = pd.read_csv(file_path)
            if data_frame.empty:
                raise ValueError(f"Stimulus file is empty: {file_path}")
            frame_count = len(data_frame)
            n_dots = _infer_n_dots(data_frame)
            duration_sec = frame_count / FPS
            media_type = STIMULUS_MEDIA_CSV
        else:
            data_frame = None
            duration_sec = _read_video_duration_sec(file_path)
            frame_count = max(1, round(duration_sec * FPS))
            n_dots = 0
            media_type = STIMULUS_MEDIA_VIDEO
        catalog.append(
            StimulusSpec(
                runtime_key=runtime_key,
                display_name=display_name,
                path=file_path,
                frame_count=frame_count,
                n_dots=n_dots,
                duration_sec=duration_sec,
                data_frame=data_frame,
                media_type=media_type,
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
    prepared_metadata["session"] = normalize_session(prepared_metadata.get("session", 1))
    prepared_metadata["fish_orientation"] = prepared_metadata.get("fish_orientation") or "bottom-left"
    prepared_metadata["path_to_stimuli"] = str(Path(stimuli_dir))
    prepared_metadata["fish_age_dpf"] = compute_fish_age_days(prepared_metadata.get("fish_birth"))

    prepared_runtime["stimuli_dir"] = str(Path(stimuli_dir))
    prepared_runtime["mode"] = mode
    prepared_runtime["mock_mode"] = bool(prepared_runtime.get("mock_mode", False))
    prepared_runtime["mock_output_root"] = str(Path(prepared_runtime.get("mock_output_root", MOCK_OUTPUT_ROOT)))
    prepared_functional["framerate"] = derive_functional_framerate(prepared_functional)
    return prepared_metadata, prepared_functional, prepared_stimuli, prepared_runtime


def build_run_plan(
    mode: str,
    metadata: dict[str, Any],
    functional_params: dict[str, Any],
    stimuli_params: dict[str, Any],
    runtime: dict[str, Any],
    stimuli_catalog: list[StimulusSpec],
) -> DotsRunPlan:
    functional_params = copy.deepcopy(functional_params)
    functional_params["framerate"] = derive_functional_framerate(functional_params)
    stimuli_params = copy.deepcopy(stimuli_params)
    stimulus_by_key = {stimulus.runtime_key: stimulus for stimulus in stimuli_catalog}
    order = _build_trial_order(mode, runtime, stimuli_params, stimuli_catalog)
    block_size = int(stimuli_params.get("n_trials_per_block", 1))
    if mode != MODE_LOOP_STIMULI and block_size <= 0:
        raise ValueError("n_trials_per_block must be greater than 0")

    timeline: list[TimelineSegment] = []
    trials: list[PlannedTrial] = []
    planned_blocks: list[PlannedBlock] = []
    current_time = 0.0
    order_index = 0

    block_groups = _build_block_trial_groups(mode, order, block_size)
    pre_stim_rest = float(stimuli_params.get("pre_stim_resting_sec", 0))
    pre_stim_pause = float(stimuli_params.get("pre_stim_pause_sec", 0))
    post_stim_pause = float(stimuli_params.get("post_stim_pause_sec", 0))
    inter_block_pause = float(stimuli_params.get("inter_block_pause_sec", 0))
    framerate = float(functional_params["framerate"])
    trial_index = 0

    post_pause_duration = post_stim_pause if mode != MODE_LOOP_BLOCKS else pre_stim_pause

    def block_group_duration(block_trial_keys: list[str]) -> float:
        return sum(
            pre_stim_pause + stimulus_by_key[stimulus_key].duration_sec + post_pause_duration
            for stimulus_key in block_trial_keys
        )

    def append_trial_segments(block_num: int, block_trial_keys: list[str]) -> list[int]:
        nonlocal current_time, order_index, trial_index
        block_trial_indices: list[int] = []
        for stimulus_key in block_trial_keys:
            stimulus = stimulus_by_key[stimulus_key]
            block_trial_indices.append(trial_index)
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
                    media_type=stimulus.media_type,
                )
            )
            current_time, order_index = _append_timed_segment(
                timeline,
                order_index,
                current_time,
                "prestim_pause",
                pre_stim_pause,
                f"Trial {trial_index + 1} pre-pause",
                trial_index=trial_index,
                block_num=block_num,
                stimulus_key=stimulus.runtime_key,
                stimulus_name=stimulus.display_name,
                stimulus_path=str(stimulus.path),
            )
            current_time, order_index = _append_marker(
                timeline,
                order_index,
                current_time,
                "trigger",
                f"B{block_num}_acq_start_stim{trial_index}",
                trial_index=trial_index,
                block_num=block_num,
                stimulus_key=stimulus.runtime_key,
                stimulus_name=stimulus.display_name,
                stimulus_path=str(stimulus.path),
            )
            current_time, order_index = _append_marker(
                timeline,
                order_index,
                current_time,
                "trigger",
                f"B{block_num}_aux_pulse_stim{trial_index}",
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
            current_time, order_index = _append_marker(
                timeline,
                order_index,
                current_time,
                "trigger",
                f"B{block_num}_aux_pulse_end_stim{trial_index}",
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
                post_pause_duration,
                f"Trial {trial_index + 1} post-pause",
                trial_index=trial_index,
                block_num=block_num,
                stimulus_key=stimulus.runtime_key,
                stimulus_name=stimulus.display_name,
                stimulus_path=str(stimulus.path),
            )
            trial_index += 1
        return block_trial_indices

    if mode != MODE_LOOP_STIMULI and block_groups:
        pre_stim_rest = block_group_duration(block_groups[0])
        stimuli_params["pre_stim_resting_sec"] = pre_stim_rest
        current_time, order_index = _append_marker(
            timeline, order_index, current_time, "trigger", "B0_start", block_num=0
        )
        acquisition_start = current_time
        current_time, order_index = _append_timed_segment(
            timeline,
            order_index,
            current_time,
            "rest",
            pre_stim_rest,
            "Baseline rest",
            block_num=0,
        )
        current_time, order_index = _append_marker(
            timeline, order_index, current_time, "trigger", "B0_end", block_num=0
        )
        planned_blocks.append(
            PlannedBlock(
                block_num=0,
                trial_indices=[],
                start_sec=acquisition_start,
                end_sec=current_time,
                duration_sec=current_time - acquisition_start,
                acquisition_frame_count=math.ceil((current_time - acquisition_start) * framerate),
                block_kind="baseline_rest",
            )
        )
        current_time, order_index = _append_timed_segment(
            timeline,
            order_index,
            current_time,
            "interblock_pause",
            inter_block_pause,
            "Block 0 pause",
            block_num=0,
        )

    for block_index, block_trial_keys in enumerate(block_groups):
        block_num = block_index if mode == MODE_LOOP_STIMULI else block_index + 1
        current_time, order_index = _append_marker(
            timeline, order_index, current_time, "trigger", f"B{block_num}_start", block_num=block_num
        )
        if mode == MODE_LOOP_STIMULI and block_num == 0:
            current_time, order_index = _append_timed_segment(
                timeline,
                order_index,
                current_time,
                "rest",
                pre_stim_rest,
                "Pre-stimulus rest",
                block_num=block_num,
            )
        acquisition_start = current_time

        block_trial_indices = append_trial_segments(block_num, block_trial_keys)

        current_time, order_index = _append_marker(
            timeline, order_index, current_time, "trigger", f"B{block_num}_end", block_num=block_num
        )
        planned_blocks.append(
            PlannedBlock(
                block_num=block_num,
                trial_indices=block_trial_indices,
                start_sec=acquisition_start,
                end_sec=current_time,
                duration_sec=current_time - acquisition_start,
                acquisition_frame_count=math.ceil((current_time - acquisition_start) * framerate),
            )
        )

        if block_index < len(block_groups) - 1:
            current_time, order_index = _append_timed_segment(
                timeline,
                order_index,
                current_time,
                "interblock_pause",
                inter_block_pause,
                f"Block {block_num} pause",
                block_num=block_num,
            )

    functional_params["n_volumes"] = sum(block.acquisition_frame_count for block in planned_blocks)

    return DotsRunPlan(
        mode=mode,
        metadata=copy.deepcopy(metadata),
        functional_params=functional_params,
        stimuli_params=copy.deepcopy(stimuli_params),
        runtime=copy.deepcopy(runtime),
        stimuli_catalog=list(stimuli_catalog),
        trials=trials,
        planned_blocks=planned_blocks,
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


def plan_to_planned_block_rows(plan: DotsRunPlan) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for block in plan.planned_blocks:
        rows.append(
            {
                "mode": plan.mode,
                "block_num": block.block_num,
                "block_kind": block.block_kind,
                "trial_indices": ", ".join(str(trial_index) for trial_index in block.trial_indices),
                "start_sec": round(block.start_sec, 6),
                "end_sec": round(block.end_sec, 6),
                "duration_sec": round(block.duration_sec, 6),
                "acquisition_frame_count": block.acquisition_frame_count,
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
        summary["planned_block_count"] = plan.planned_block_count
        summary["planned_block_durations_sec"] = [round(block.duration_sec, 6) for block in plan.planned_blocks]
        summary["planned_block_frame_counts"] = plan.planned_block_frame_counts
        summary["planned_total_acquisition_frames"] = plan.planned_total_acquisition_frames
    return summary


def format_duration(total_seconds: float) -> str:
    total_seconds = int(round(total_seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:d}:{seconds:02d}"


def compute_fish_age_days(fish_birth: str | None) -> int | None:
    if not fish_birth:
        return None
    parsed = dt.datetime.strptime(fish_birth, "%Y-%m-%d")
    return (dt.datetime.today() - parsed).days


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

    rng = random.Random(runtime.get("stimulus_shuffle_seed"))
    for _ in range(n_reps):
        chunk = list(base_order)
        rng.shuffle(chunk)
        order.extend(chunk)
    return order


def _build_block_trial_groups(mode: str, order: list[str], block_size: int) -> list[list[str]]:
    if mode == MODE_LOOP_STIMULI:
        return [list(order)]
    return [order[index : index + block_size] for index in range(0, len(order), block_size)]


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


def _read_video_duration_sec(file_path: Path) -> float:
    duration_sec = _read_video_duration_with_cv2(file_path)
    if duration_sec is None:
        duration_sec = _read_video_duration_with_moviepy(file_path)
    if duration_sec is None or duration_sec <= 0:
        raise ValueError(f"Could not read MP4 stimulus duration: {file_path}")
    return duration_sec


def _read_video_duration_with_cv2(file_path: Path) -> float | None:
    try:
        import cv2
    except ImportError:
        return None

    capture = cv2.VideoCapture(str(file_path))
    try:
        if not capture.isOpened():
            return None
        frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if frame_count <= 0 or fps <= 0:
            return None
        return frame_count / fps
    finally:
        capture.release()


def _read_video_duration_with_moviepy(file_path: Path) -> float | None:
    try:
        from moviepy.editor import VideoFileClip
    except ImportError:
        try:
            from moviepy import VideoFileClip
        except ImportError:
            return None

    try:
        clip = VideoFileClip(str(file_path))
    except Exception:
        return None
    try:
        duration = float(clip.duration)
    finally:
        clip.close()
    return duration if duration > 0 else None


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
