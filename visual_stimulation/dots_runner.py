from __future__ import annotations

import datetime
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from dots_protocol import (
    DotsRunPlan,
    FPS,
    MODE_LOOP_BLOCKS,
    MODE_LOOP_STIMULI,
    STIMULUS_MEDIA_CSV,
    STIMULUS_MEDIA_VIDEO,
    plan_to_planned_block_rows,
    plan_to_schedule_rows,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_repo_root_str = str(_REPO_ROOT)
try:
    sys.path.remove(_repo_root_str)
except ValueError:
    pass
sys.path.insert(0, _repo_root_str)

from utils import init_experiment_tree


def _diagnostic(message: str) -> None:
    print(f"[dots_runner] {message}", flush=True)


@dataclass
class _MockRuntimeState:
    exp_time: float = 0.0
    block_time: float = 0.0

    def log_event(
        self,
        exp_event_log: list[dict[str, Any]],
        block_event_log: list[dict[str, Any]],
        event_name: str,
    ) -> None:
        exp_event_log.append({"event": event_name, "timestamp": self.exp_time})
        block_event_log.append({"event": event_name, "timestamp": self.block_time})

    def advance(self, duration_sec: float) -> None:
        self.exp_time += float(duration_sec)
        self.block_time += float(duration_sec)

    def reset_block(self) -> None:
        self.block_time = 0.0


def run_planned_experiment(plan: DotsRunPlan) -> Path:
    branch = "mock" if plan.runtime.get("mock_mode") else "hardware"
    _diagnostic(f"run_planned_experiment entered: mode={plan.mode} branch={branch}")
    if plan.runtime.get("mock_mode"):
        return _run_mock_experiment(plan)
    return _run_hardware_experiment(plan)


def _run_hardware_experiment(plan: DotsRunPlan) -> Path:
    from psychopy import core, monitors, tools, visual

    _diagnostic("hardware runner entered")
    metadata = dict(plan.metadata)
    functional_params = dict(plan.functional_params)
    stimuli_params = dict(plan.stimuli_params)
    runtime = dict(plan.runtime)

    meta_dir = _resolve_metadata_dir(metadata, runtime)
    _diagnostic(f"metadata directory resolved: {meta_dir}")

    win = None
    board, pin_acq, pin_aux = _setup_trigger_pins(runtime)
    _diagnostic("Arduino trigger pins initialized")

    try:
        monitor = monitors.Monitor(runtime["monitor_name"], width=float(runtime["monitor_width_cm"]))
        monitor.setSizePix(runtime["pixels_monitor"])
        monitor.setDistance(float(runtime["monitor_distance_cm"]))
        tools.monitorunittools.cm2pix(1, monitor)

        win = visual.Window(
            size=runtime["pixels_monitor"],
            color=runtime["window_color"],
            units="pix",
            monitor=monitor,
            screen=int(runtime["screen"]),
            fullscr=bool(runtime["fullscr"]),
        )
        _diagnostic("PsychoPy window created")

        dot_radius = float(runtime.get("dot_radius_cm") or stimuli_params.get("dot_radius_cm", 0.2))
        dots = [
            visual.Circle(win=win, radius=dot_radius, fillColor="black", pos=[0, 0], units="cm")
            for _ in range(int(stimuli_params["max_n_dots"]))
        ]
    except Exception:
        if win is not None:
            win.close()
        try:
            board.exit()
        except Exception:
            pass
        raise

    flip_coordinates = str(metadata.get("fish_orientation", "")).lower() == "bottom-left"
    stimuli_by_key = {stimulus.runtime_key: stimulus for stimulus in plan.stimuli_catalog}
    trigger_pulse_sec = float(runtime.get("trigger_pulse_sec", 0.05))

    exp_event_log: list[dict[str, Any]] = []
    block_event_log: list[dict[str, Any]] = []
    trial_sequence: list[Any] = []
    exp_clock = core.Clock()
    block_clock = core.Clock()
    block_num = 0

    def log_event(event_name: str) -> None:
        exp_event_log.append({"event": event_name, "timestamp": exp_clock.getTime()})
        block_event_log.append({"event": event_name, "timestamp": block_clock.getTime()})

    try:
        if plan.mode == MODE_LOOP_STIMULI:
            _diagnostic("B0 acquisition trigger pulse starting")
            _pulse_pin(pin_acq, trigger_pulse_sec, core.wait)
            _diagnostic("B0 acquisition trigger pulse finished")
            log_event("B0_start")
            _flip_for_duration(win, float(stimuli_params.get("pre_stim_resting_sec", 0)))
            for trial in plan.trials:
                block_num = 0
                trial_sequence.append(Path(trial.stimulus_path))
                log_event(f"B{block_num}_prestim{trial.trial_index}_pause")
                _flip_for_duration(win, float(stimuli_params["pre_stim_pause_sec"]))

                _pulse_pin(pin_acq, trigger_pulse_sec, core.wait)
                log_event(f"B{block_num}_acq_start_stim{trial.trial_index}")

                _pulse_pin(pin_aux, trigger_pulse_sec, core.wait)
                print(trial.stimulus_key, "started")
                log_event(f"B{block_num}_stim{trial.trial_index}_{trial.stimulus_key}")

                stimulus = stimuli_by_key[trial.stimulus_key]
                _present_stimulus(
                    win,
                    visual,
                    dots,
                    stimulus,
                    flip_coordinates,
                    dot_radius_mode=runtime.get("dot_radius_mode", "fixed"),
                    fixed_radius=dot_radius,
                    pin_aux=pin_aux,
                    exp_event_log=exp_event_log,
                    block_event_log=block_event_log,
                    exp_clock=exp_clock,
                    block_clock=block_clock,
                    trigger_pulse_sec=trigger_pulse_sec,
                    wait=core.wait,
                    block_num=block_num,
                    trial_index=trial.trial_index,
                    stimulus_key=trial.stimulus_key,
                    use_loom_markers=bool(runtime.get("use_loom_markers")),
                )
                _pulse_pin(pin_aux, trigger_pulse_sec, core.wait)

                log_event(f"B{block_num}_poststim{trial.trial_index}_pause")
                _flip_for_duration(win, float(stimuli_params["post_stim_pause_sec"]))

            log_event("B0_end")
        else:
            post_pause_key = "pre_stim_pause_sec" if plan.mode == MODE_LOOP_BLOCKS else "post_stim_pause_sec"
            for block_index, planned_block in enumerate(plan.planned_blocks):
                block_num = planned_block.block_num
                _diagnostic(f"B{block_num} acquisition trigger pulse starting")
                _pulse_pin(pin_acq, trigger_pulse_sec, core.wait)
                _diagnostic(f"B{block_num} acquisition trigger pulse finished")
                block_clock = core.Clock()
                log_event(f"B{block_num}_start")
                if planned_block.block_kind == "baseline_rest":
                    _flip_for_duration(win, planned_block.duration_sec)

                for trial_index in planned_block.trial_indices:
                    trial = plan.trials[trial_index]
                    trial_sequence.append(trial.stimulus_name)
                    stimulus = stimuli_by_key[trial.stimulus_key]

                    log_event(f"B{block_num}_prestim{trial.trial_index}_pause")
                    _flip_for_duration(win, float(stimuli_params["pre_stim_pause_sec"]))

                    pin_aux.write(1)
                    print(trial.stimulus_name, "started")
                    log_event(f"B{block_num}_stim{trial.trial_index}_{trial.stimulus_name}")
                    _present_stimulus(
                        win,
                        visual,
                        dots,
                        stimulus,
                        flip_coordinates,
                        dot_radius_mode=runtime.get("dot_radius_mode", "per_frame"),
                        fixed_radius=float(stimuli_params.get("dot_radius_cm", dot_radius)),
                        pin_aux=pin_aux,
                        exp_event_log=exp_event_log,
                        block_event_log=block_event_log,
                        exp_clock=exp_clock,
                        block_clock=block_clock,
                        trigger_pulse_sec=trigger_pulse_sec,
                        wait=core.wait,
                        block_num=block_num,
                        trial_index=trial.trial_index,
                        stimulus_key=trial.stimulus_name,
                        use_loom_markers=False,
                    )
                    pin_aux.write(0)

                    log_event(f"B{block_num}_poststim{trial.trial_index}_pause")
                    _flip_for_duration(win, float(stimuli_params[post_pause_key]))

                log_event(f"B{block_num}_end")
                next_block = plan.planned_blocks[block_index + 1] if block_index < len(plan.planned_blocks) - 1 else None
                if (
                    next_block is not None
                    and planned_block.block_kind in {"baseline_rest", "stimulus_block"}
                    and next_block.block_kind == "stimulus_block"
                ):
                    log_event(f"B{block_num}_interblock_pause")
                    _flip_for_duration(win, float(stimuli_params["inter_block_pause_sec"]))
    except KeyboardInterrupt:
        print("\nManual interruption detected. Finalizing and saving logs...")
    finally:
        print("Experiment ended")
        if win is not None:
            win.close()
        try:
            board.exit()
        except Exception:
            pass

    current_date = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    _diagnostic("final output save starting")
    _save_outputs(
        meta_dir,
        current_date,
        metadata,
        functional_params,
        stimuli_params,
        runtime,
        plan,
        exp_event_log,
        block_event_log,
        trial_sequence,
    )
    _diagnostic("final output save finished")
    _append_post_run_metadata(meta_dir, current_date, metadata, stimuli_params, functional_params, runtime, plan)
    return meta_dir


def _setup_trigger_pins(runtime: dict[str, Any]) -> tuple[Any, Any, Any]:
    from pyfirmata import Arduino

    port = str(runtime["arduino_port"])
    board = None
    try:
        board = Arduino(port)
        pin_acq = board.get_pin(f'd:{int(runtime["acq_trigger_pin"])}:o')
        pin_aux = board.get_pin(f'd:{int(runtime["aux_trigger_pin"])}:o')
        pin_acq.write(0)
        pin_aux.write(0)
    except Exception as exc:
        if board is not None:
            try:
                board.exit()
            except Exception:
                pass
        raise RuntimeError(
            f"Could not open Arduino trigger port {port}. The experiment was not started; "
            "check that the device is connected, not already open in another program, "
            "and that this user has permission to access the port."
        ) from exc
    return board, pin_acq, pin_aux


def _pulse_pin(pin: Any, duration_sec: float, wait: Any) -> None:
    pin.write(1)
    wait(float(duration_sec))
    pin.write(0)


def _run_mock_experiment(plan: DotsRunPlan) -> Path:
    _diagnostic("mock runner entered")
    metadata = dict(plan.metadata)
    functional_params = dict(plan.functional_params)
    stimuli_params = dict(plan.stimuli_params)
    runtime = dict(plan.runtime)

    meta_dir = _resolve_metadata_dir(metadata, runtime)
    _diagnostic(f"metadata directory resolved: {meta_dir}")
    exp_event_log: list[dict[str, Any]] = []
    block_event_log: list[dict[str, Any]] = []
    trial_sequence: list[Any] = []
    state = _MockRuntimeState()

    if plan.mode == MODE_LOOP_STIMULI:
        state.log_event(exp_event_log, block_event_log, "B0_start")
        state.advance(float(stimuli_params.get("pre_stim_resting_sec", 0)))
        for trial in plan.trials:
            trial_sequence.append(Path(trial.stimulus_path))
            state.log_event(exp_event_log, block_event_log, f"B0_prestim{trial.trial_index}_pause")
            state.advance(float(stimuli_params["pre_stim_pause_sec"]))
            state.log_event(exp_event_log, block_event_log, f"B0_acq_start_stim{trial.trial_index}")
            state.log_event(exp_event_log, block_event_log, f"B0_stim{trial.trial_index}_{trial.stimulus_key}")
            _simulate_stimulus(
                state,
                exp_event_log,
                block_event_log,
                trial,
                plan,
                block_num=0,
                stimulus_key=trial.stimulus_key,
                use_loom_markers=bool(runtime.get("use_loom_markers")),
            )
            state.log_event(exp_event_log, block_event_log, f"B0_poststim{trial.trial_index}_pause")
            state.advance(float(stimuli_params["post_stim_pause_sec"]))
        state.log_event(exp_event_log, block_event_log, "B0_end")
    else:
        post_pause_key = "pre_stim_pause_sec" if plan.mode == MODE_LOOP_BLOCKS else "post_stim_pause_sec"
        for block_index, planned_block in enumerate(plan.planned_blocks):
            block_num = planned_block.block_num
            state.reset_block()
            state.log_event(exp_event_log, block_event_log, f"B{block_num}_start")
            if planned_block.block_kind == "baseline_rest":
                state.advance(planned_block.duration_sec)

            for trial_index in planned_block.trial_indices:
                trial = plan.trials[trial_index]
                trial_sequence.append(trial.stimulus_name)
                state.log_event(exp_event_log, block_event_log, f"B{block_num}_prestim{trial.trial_index}_pause")
                state.advance(float(stimuli_params["pre_stim_pause_sec"]))
                state.log_event(exp_event_log, block_event_log, f"B{block_num}_stim{trial.trial_index}_{trial.stimulus_name}")
                _simulate_stimulus(
                    state,
                    exp_event_log,
                    block_event_log,
                    trial,
                    plan,
                    block_num=block_num,
                    stimulus_key=trial.stimulus_name,
                    use_loom_markers=False,
                )
                state.log_event(exp_event_log, block_event_log, f"B{block_num}_poststim{trial.trial_index}_pause")
                state.advance(float(stimuli_params[post_pause_key]))

            state.log_event(exp_event_log, block_event_log, f"B{block_num}_end")
            next_block = plan.planned_blocks[block_index + 1] if block_index < len(plan.planned_blocks) - 1 else None
            if (
                next_block is not None
                and planned_block.block_kind in {"baseline_rest", "stimulus_block"}
                and next_block.block_kind == "stimulus_block"
            ):
                state.log_event(exp_event_log, block_event_log, f"B{block_num}_interblock_pause")
                state.advance(float(stimuli_params["inter_block_pause_sec"]))
                state.reset_block()

    current_date = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    _diagnostic("final output save starting")
    _save_outputs(
        meta_dir,
        current_date,
        metadata,
        functional_params,
        stimuli_params,
        runtime,
        plan,
        exp_event_log,
        block_event_log,
        trial_sequence,
    )
    _diagnostic("final output save finished")
    _append_mock_metadata(meta_dir, current_date, metadata, stimuli_params, functional_params, runtime, plan)
    return meta_dir


def _simulate_stimulus(
    state: _MockRuntimeState,
    exp_event_log: list[dict[str, Any]],
    block_event_log: list[dict[str, Any]],
    trial: Any,
    plan: DotsRunPlan,
    block_num: int,
    stimulus_key: str,
    use_loom_markers: bool,
) -> None:
    stimulus = next(stim for stim in plan.stimuli_catalog if stim.runtime_key == trial.stimulus_key)
    if stimulus.media_type == STIMULUS_MEDIA_CSV and stimulus.data_frame is not None and use_loom_markers:
        radius_columns = [f"dot{dot_idx}_radius" for dot_idx in range(trial.n_dots)]
        for frame_index in range(len(stimulus.data_frame)):
            radius_values = [
                stimulus.data_frame[column][frame_index]
                for column in radius_columns
                if column in stimulus.data_frame.columns
            ]
            if any(radius == 0.1 for radius in radius_values):
                loom_offset = frame_index / FPS
                exp_event_log.append(
                    {
                        "event": f"B{block_num}_stim{trial.trial_index}_{stimulus_key}_loom_start",
                        "timestamp": state.exp_time + loom_offset,
                    }
                )
                block_event_log.append(
                    {
                        "event": f"B{block_num}_stim{trial.trial_index}_{stimulus_key}_loom_start",
                        "timestamp": state.block_time + loom_offset,
                    }
                )
                break
    state.advance(trial.duration_sec)


def _present_stimulus(
    win: Any,
    visual: Any,
    dots: list[Any],
    stimulus: Any,
    flip_coordinates: bool,
    dot_radius_mode: str,
    fixed_radius: float,
    pin_aux: Any,
    exp_event_log: list[dict[str, Any]],
    block_event_log: list[dict[str, Any]],
    exp_clock: Any,
    block_clock: Any,
    trigger_pulse_sec: float,
    wait: Any,
    block_num: int,
    trial_index: int,
    stimulus_key: str,
    use_loom_markers: bool,
) -> None:
    if stimulus.media_type == STIMULUS_MEDIA_VIDEO:
        _draw_video_stimulus(win, visual, stimulus.path)
        return
    if stimulus.media_type != STIMULUS_MEDIA_CSV or stimulus.data_frame is None:
        raise ValueError(f"Unsupported stimulus media type for {stimulus.path}: {stimulus.media_type}")
    _draw_stimulus(
        win,
        dots,
        stimulus.data_frame,
        stimulus.n_dots,
        flip_coordinates,
        dot_radius_mode,
        fixed_radius,
        pin_aux,
        exp_event_log,
        block_event_log,
        exp_clock,
        block_clock,
        trigger_pulse_sec,
        wait,
        block_num,
        trial_index,
        stimulus_key,
        use_loom_markers,
    )


def _draw_video_stimulus(win: Any, visual: Any, stimulus_path: Path) -> None:
    movie = visual.MovieStim(win, filename=str(stimulus_path), units="pix", loop=False)
    while not movie.isFinished:
        movie.draw()
        win.flip()


def _draw_stimulus(
    win: Any,
    dots: list[Any],
    data_frame: pd.DataFrame,
    n_dots: int,
    flip_coordinates: bool,
    dot_radius_mode: str,
    fixed_radius: float,
    pin_aux: Any,
    exp_event_log: list[dict[str, Any]],
    block_event_log: list[dict[str, Any]],
    exp_clock: Any,
    block_clock: Any,
    trigger_pulse_sec: float,
    wait: Any,
    block_num: int,
    trial_index: int,
    stimulus_key: str,
    use_loom_markers: bool,
) -> None:
    for frame in range(len(data_frame)):
        for dot_idx in range(n_dots):
            x = data_frame[f"dot{dot_idx}_x"][frame]
            y = data_frame[f"dot{dot_idx}_y"][frame]
            radius_column = f"dot{dot_idx}_radius"
            radius = data_frame[radius_column][frame] if radius_column in data_frame.columns else fixed_radius
            if use_loom_markers and radius == 0.1:
                exp_event_log.append(
                    {
                        "event": f"B{block_num}_stim{trial_index}_{stimulus_key}_loom_start",
                        "timestamp": exp_clock.getTime(),
                    }
                )
                block_event_log.append(
                    {
                        "event": f"B{block_num}_stim{trial_index}_{stimulus_key}_loom_start",
                        "timestamp": block_clock.getTime(),
                    }
                )
                _pulse_pin(pin_aux, trigger_pulse_sec, wait)
                print(f"loom presentation, frame: {frame}")
            if flip_coordinates:
                x, y = -x, -y
            dots[dot_idx].radius = radius if dot_radius_mode == "per_frame" else fixed_radius
            dots[dot_idx].pos = (x, y)
            dots[dot_idx].draw()
        win.flip()


def _flip_for_duration(win: Any, duration_sec: float, fps: int = FPS) -> None:
    for _ in range(int(round(fps * float(duration_sec), 1))):
        win.flip()


def _resolve_metadata_dir(metadata: dict[str, Any], runtime: dict[str, Any]) -> Path:
    if runtime.get("mock_mode"):
        root_base = Path(runtime["mock_output_root"])
    else:
        root_base = Path(runtime["data_path"]) / str(metadata["experimenter"])
    data_root_suffix = runtime.get("data_root_suffix")
    if data_root_suffix:
        root_base = root_base / data_root_suffix
    exp_name = str(metadata["fish_ID"])
    paths = init_experiment_tree(root_base, exp_name)
    return paths["raw_2p_metadata"]


def _session_output_stem(current_date: str, metadata: dict[str, Any]) -> str:
    stem = f"{current_date}_f{metadata['fish_ID']}"
    session = int(metadata.get("session", 1))
    if session > 1:
        stem = f"{stem}_r{session}"
    return stem


def _save_outputs(
    meta_dir: Path,
    current_date: str,
    metadata: dict[str, Any],
    functional_params: dict[str, Any],
    stimuli_params: dict[str, Any],
    runtime: dict[str, Any],
    plan: DotsRunPlan,
    exp_event_log: list[dict[str, Any]],
    block_event_log: list[dict[str, Any]],
    trial_sequence: list[Any],
) -> None:
    output_stem = _session_output_stem(current_date, metadata)

    pd.DataFrame(exp_event_log).to_csv(meta_dir / f"{output_stem}_experiment_log.csv", index=False)
    pd.DataFrame(block_event_log).to_csv(meta_dir / f"{output_stem}_block_log.csv", index=False)
    pd.DataFrame(trial_sequence, columns=["stimulus"]).to_csv(
        meta_dir / f"{output_stem}_trial_sequence.csv", index=False
    )
    pd.DataFrame(plan_to_planned_block_rows(plan)).to_csv(
        meta_dir / f"{output_stem}_planned_blocks.csv", index=False
    )
    pd.DataFrame(plan_to_schedule_rows(plan)).to_csv(
        meta_dir / f"{output_stem}_planned_schedule.csv", index=False
    )

    metadata_rows = _build_metadata_rows(metadata, stimuli_params, functional_params, runtime, plan)
    pd.DataFrame(metadata_rows, columns=["parameter", "value"]).to_csv(
        meta_dir / f"{output_stem}_metadata.csv", index=False
    )


def _append_post_run_metadata(
    meta_dir: Path,
    current_date: str,
    metadata: dict[str, Any],
    stimuli_params: dict[str, Any],
    functional_params: dict[str, Any],
    runtime: dict[str, Any],
    plan: DotsRunPlan,
) -> None:
    from psychopy import core, gui

    metadata["fish_died"] = False
    anatomy_params = _default_anatomy_params()

    dlg = gui.DlgFromDict(metadata, title="Metadata", sortKeys=False)
    if not dlg.OK:
        core.quit()
    dlg = gui.DlgFromDict(anatomy_params, title="Anatomy", sortKeys=False)
    if not dlg.OK:
        core.quit()

    all_data = _build_metadata_rows(metadata, stimuli_params, functional_params, runtime, plan, anatomy_params)
    pd.DataFrame(all_data, columns=["parameter", "value"]).to_csv(
        meta_dir / f"{_session_output_stem(current_date, metadata)}_metadata.csv", index=False
    )


def _append_mock_metadata(
    meta_dir: Path,
    current_date: str,
    metadata: dict[str, Any],
    stimuli_params: dict[str, Any],
    functional_params: dict[str, Any],
    runtime: dict[str, Any],
    plan: DotsRunPlan,
) -> None:
    metadata["fish_died"] = False
    all_data = _build_metadata_rows(
        metadata,
        stimuli_params,
        functional_params,
        runtime,
        plan,
        _default_anatomy_params(),
    )
    pd.DataFrame(all_data, columns=["parameter", "value"]).to_csv(
        meta_dir / f"{_session_output_stem(current_date, metadata)}_metadata.csv", index=False
    )


def _build_metadata_rows(
    metadata: dict[str, Any],
    stimuli_params: dict[str, Any],
    functional_params: dict[str, Any],
    runtime: dict[str, Any],
    plan: DotsRunPlan,
    anatomy_params: dict[str, Any] | None = None,
) -> list[tuple[str, Any]]:
    metadata_to_save = dict(metadata)
    metadata_to_save["dots_mode"] = plan.mode
    metadata_to_save["planned_total_duration_sec"] = round(plan.total_duration_sec, 6)
    metadata_to_save["planned_total_trials"] = plan.total_trials
    metadata_to_save["planned_block_count"] = plan.planned_block_count
    metadata_to_save["planned_block_durations_sec"] = ", ".join(
        f"{block.duration_sec:.6f}" for block in plan.planned_blocks
    )
    metadata_to_save["planned_block_frame_counts"] = ", ".join(str(frame_count) for frame_count in plan.planned_block_frame_counts)
    metadata_to_save["planned_total_acquisition_frames"] = plan.planned_total_acquisition_frames
    metadata_to_save["planned_order_locked"] = True
    metadata_to_save["mock_mode"] = bool(runtime.get("mock_mode"))

    all_data = list(metadata_to_save.items()) + list(stimuli_params.items()) + list(functional_params.items())
    if anatomy_params:
        all_data.extend(list(anatomy_params.items()))
    return all_data


def _default_anatomy_params() -> dict[str, Any]:
    return {
        "frames_per_slice_anatomy": 90,
        "step_size_um_anatomy": 2,
        "wavelenght_anatomy": 850,
        "AOM_anatomy": 57,
    }
