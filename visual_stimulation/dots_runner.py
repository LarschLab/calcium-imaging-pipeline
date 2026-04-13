from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from dots_protocol import (
    DotsRunPlan,
    MODE_CONTINUOUS_SESSION,
    MODE_LOOP_BLOCKS,
    MODE_LOOP_STIMULI,
    plan_to_schedule_rows,
)
from utils import init_experiment_tree


def run_planned_experiment(plan: DotsRunPlan) -> Path:
    from psychopy import core, monitors, tools, visual
    from pyfirmata import Arduino

    metadata = dict(plan.metadata)
    functional_params = dict(plan.functional_params)
    stimuli_params = dict(plan.stimuli_params)
    runtime = dict(plan.runtime)

    data_root = Path(runtime["data_path"]) / str(metadata["experimenter"])
    data_root_suffix = runtime.get("data_root_suffix")
    if data_root_suffix:
        data_root = data_root / data_root_suffix
    exp_name = str(metadata["fish_ID"])
    paths = init_experiment_tree(data_root, exp_name)
    meta_dir = paths["raw_2p_metadata"]

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

    dot_radius = float(runtime.get("dot_radius_cm") or stimuli_params.get("dot_radius_cm", 0.2))
    dots = [
        visual.Circle(win=win, radius=dot_radius, fillColor="black", pos=[0, 0], units="cm")
        for _ in range(int(stimuli_params["max_n_dots"]))
    ]

    board = Arduino(runtime["arduino_port"])
    pin_acq = board.get_pin(f'd:{int(runtime["acq_trigger_pin"])}:o')
    pin_aux = board.get_pin(f'd:{int(runtime["aux_trigger_pin"])}:o')
    pin_acq.write(0)
    pin_aux.write(0)

    flip_coordinates = str(metadata.get("fish_orientation", "")).lower() == "bottom-left"
    stimulus_frames = {stimulus.runtime_key: stimulus.data_frame for stimulus in plan.stimuli_catalog}

    exp_event_log: list[dict[str, Any]] = []
    block_event_log: list[dict[str, Any]] = []
    trial_sequence: list[Any] = []
    exp_clock = core.Clock()
    block_clock = core.Clock()
    block_num = 0

    def log_event(event_name: str, block_value: int) -> None:
        exp_event_log.append({"event": event_name, "timestamp": exp_clock.getTime()})
        block_event_log.append({"event": event_name, "timestamp": block_clock.getTime()})

    try:
        if plan.mode == MODE_LOOP_STIMULI:
            pin_acq.write(1)
            pin_acq.write(0)
            log_event("B0_start", 0)
            for segment in plan.timeline:
                if segment.kind == "rest":
                    _flip_for_duration(win, segment.duration_sec)
            for trial in plan.trials:
                block_num = 0
                trial_sequence.append(Path(trial.stimulus_path))
                log_event(f"B{block_num}_prestim{trial.trial_index}_pause", block_num)
                _flip_for_duration(win, float(stimuli_params["pre_stim_pause_sec"]))

                pin_acq.write(1)
                pin_acq.write(0)
                log_event(f"B{block_num}_acq_start_stim{trial.trial_index}", block_num)

                pin_aux.write(1)
                pin_aux.write(0)
                print(trial.stimulus_key, "started")
                log_event(f"B{block_num}_stim{trial.trial_index}_{trial.stimulus_key}", block_num)

                data_frame = stimulus_frames[trial.stimulus_key]
                _draw_stimulus(
                    win,
                    dots,
                    data_frame,
                    trial.n_dots,
                    flip_coordinates,
                    dot_radius_mode=runtime.get("dot_radius_mode", "fixed"),
                    fixed_radius=dot_radius,
                    pin_aux=pin_aux,
                    exp_event_log=exp_event_log,
                    block_event_log=block_event_log,
                    exp_clock=exp_clock,
                    block_clock=block_clock,
                    block_num=block_num,
                    trial_index=trial.trial_index,
                    stimulus_key=trial.stimulus_key,
                    use_loom_markers=bool(runtime.get("use_loom_markers")),
                )
                pin_aux.write(1)
                pin_aux.write(0)

                log_event(f"B{block_num}_poststim{trial.trial_index}_pause", block_num)
                _flip_for_duration(win, float(stimuli_params["post_stim_pause_sec"]))

            log_event("B0_end", 0)
        else:
            pin_acq.write(1)
            pin_acq.write(0)
            log_event("B0_start", 0)
            _flip_for_duration(win, float(stimuli_params["pre_stim_resting_sec"]))

            post_pause_key = "pre_stim_pause_sec" if plan.mode == MODE_LOOP_BLOCKS else "post_stim_pause_sec"
            for trial in plan.trials:
                if trial.trial_index % int(stimuli_params["n_trials_per_block"]) == 0:
                    log_event(f"B{block_num}_end", block_num)
                    exp_event_log.append({"event": f"B{block_num}_interblock_pause", "timestamp": exp_clock.getTime()})
                    print("inter_block_pause_sec")
                    _flip_for_duration(win, float(stimuli_params["inter_block_pause_sec"]))

                    block_num += 1
                    block_clock = core.Clock()
                    pin_acq.write(1)
                    pin_acq.write(0)
                    log_event(f"B{block_num}_start", block_num)

                trial_sequence.append(trial.stimulus_name)
                data_frame = stimulus_frames[trial.stimulus_key]

                log_event(f"B{block_num}_prestim{trial.trial_index}_pause", block_num)
                _flip_for_duration(win, float(stimuli_params["pre_stim_pause_sec"]))

                pin_aux.write(1)
                print(trial.stimulus_name, "started")
                log_event(f"B{block_num}_stim{trial.trial_index}_{trial.stimulus_name}", block_num)
                _draw_stimulus(
                    win,
                    dots,
                    data_frame,
                    trial.n_dots,
                    flip_coordinates,
                    dot_radius_mode=runtime.get("dot_radius_mode", "per_frame"),
                    fixed_radius=float(stimuli_params.get("dot_radius_cm", dot_radius)),
                    pin_aux=pin_aux,
                    exp_event_log=exp_event_log,
                    block_event_log=block_event_log,
                    exp_clock=exp_clock,
                    block_clock=block_clock,
                    block_num=block_num,
                    trial_index=trial.trial_index,
                    stimulus_key=trial.stimulus_name,
                    use_loom_markers=False,
                )
                pin_aux.write(0)

                log_event(f"B{block_num}_poststim{trial.trial_index}_pause", block_num)
                _flip_for_duration(win, float(stimuli_params[post_pause_key]))

            log_event(f"B{block_num}_end", block_num)
    except KeyboardInterrupt:
        print("\nManual interruption detected. Finalizing and saving logs...")
    finally:
        print("Experiment ended")
        win.close()
        try:
            board.exit()
        except Exception:
            pass

    current_date = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    _save_outputs(
        meta_dir,
        current_date,
        metadata,
        functional_params,
        stimuli_params,
        plan,
        exp_event_log,
        block_event_log,
        trial_sequence,
    )
    _append_post_run_metadata(meta_dir, current_date, metadata, stimuli_params, functional_params)
    return meta_dir


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
                pin_aux.write(1)
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
                pin_aux.write(0)
                print(f"loom presentation, frame: {frame}")
            if flip_coordinates:
                x, y = -x, -y
            dots[dot_idx].radius = radius if dot_radius_mode == "per_frame" else fixed_radius
            dots[dot_idx].pos = (x, y)
            dots[dot_idx].draw()
        win.flip()


def _flip_for_duration(win: Any, duration_sec: float, fps: int = 60) -> None:
    for _ in range(int(round(fps * float(duration_sec), 1))):
        win.flip()


def _save_outputs(
    meta_dir: Path,
    current_date: str,
    metadata: dict[str, Any],
    functional_params: dict[str, Any],
    stimuli_params: dict[str, Any],
    plan: DotsRunPlan,
    exp_event_log: list[dict[str, Any]],
    block_event_log: list[dict[str, Any]],
    trial_sequence: list[Any],
) -> None:
    fish_id = metadata["fish_ID"]

    pd.DataFrame(exp_event_log).to_csv(meta_dir / f"{current_date}_f{fish_id}_experiment_log.csv", index=False)
    pd.DataFrame(block_event_log).to_csv(meta_dir / f"{current_date}_f{fish_id}_block_log.csv", index=False)
    pd.DataFrame(trial_sequence, columns=["stimulus"]).to_csv(
        meta_dir / f"{current_date}_f{fish_id}_trial_sequence.csv", index=False
    )
    pd.DataFrame(plan_to_schedule_rows(plan)).to_csv(
        meta_dir / f"{current_date}_f{fish_id}_planned_schedule.csv", index=False
    )

    metadata_to_save = dict(metadata)
    metadata_to_save["dots_mode"] = plan.mode
    metadata_to_save["planned_total_duration_sec"] = round(plan.total_duration_sec, 6)
    metadata_to_save["planned_total_trials"] = plan.total_trials
    metadata_to_save["planned_order_locked"] = True

    all_data = list(metadata_to_save.items()) + list(stimuli_params.items()) + list(functional_params.items())
    pd.DataFrame(all_data, columns=["parameter", "value"]).to_csv(
        meta_dir / f"{current_date}_f{fish_id}_metadata.csv", index=False
    )


def _append_post_run_metadata(
    meta_dir: Path,
    current_date: str,
    metadata: dict[str, Any],
    stimuli_params: dict[str, Any],
    functional_params: dict[str, Any],
) -> None:
    from psychopy import core, gui

    metadata["fish_died"] = False
    anatomy_params = {
        "frames_per_slice_anatomy": 90,
        "step_size_um_anatomy": 2,
        "wavelenght_anatomy": 850,
        "AOM_anatomy": 57,
    }

    dlg = gui.DlgFromDict(metadata, title="Metadata", sortKeys=False)
    if not dlg.OK:
        core.quit()
    dlg = gui.DlgFromDict(anatomy_params, title="Anatomy", sortKeys=False)
    if not dlg.OK:
        core.quit()

    all_data = (
        list(metadata.items())
        + list(stimuli_params.items())
        + list(functional_params.items())
        + list(anatomy_params.items())
    )
    pd.DataFrame(all_data, columns=["parameter", "value"]).to_csv(
        meta_dir / f"{current_date}_f{metadata['fish_ID']}_metadata.csv", index=False
    )
