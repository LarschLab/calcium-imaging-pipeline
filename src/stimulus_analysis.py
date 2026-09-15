"""Load stimulus timing and compute basic trial-aligned response measures."""

from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_STIMULUS_FPS = 60.0


def load_trajectory(trajectory_file):
    """Load one stimulus trajectory table.

    Args:
        trajectory_file (Path): CSV trajectory containing x, y, or radius columns.

    Returns:
        DataFrame: Loaded trajectory samples.
    """
    trajectory = pd.read_csv(Path(trajectory_file))
    return trajectory


def calculate_stimulus_duration(
    trajectory,
    stimulus_fps=DEFAULT_STIMULUS_FPS,
    trajectory_name="trajectory",
):
    """Calculate stimulus timing from an in-memory trajectory table.

    Args:
        trajectory (DataFrame): Trajectory containing x, y, or radius columns.
        stimulus_fps (float): Sampling rate of the trajectory in frames per second.
        trajectory_name (str): Source description used in error messages.

    Returns:
        dict: Static, motion, and total stimulus durations and frame counts.

    Raises:
        ValueError: If the trajectory is empty or has no supported columns.
    """
    if trajectory.empty:
        raise ValueError(f"Stimulus trajectory is empty: {trajectory_name}")
    if stimulus_fps <= 0:
        raise ValueError("stimulus_fps must be greater than zero.")

    relevant_columns = [
        column
        for column in trajectory.columns
        if column.endswith(("_x", "_y", "_radius"))
    ]
    if not relevant_columns:
        raise ValueError(
            f"No *_x, *_y, or *_radius columns were found in {trajectory_name}."
        )

    movement_starts = []
    for column in relevant_columns:
        values = trajectory[column].to_numpy()
        if np.all(pd.isna(values)):
            continue
        changed = values != values[0]
        if np.any(changed):
            movement_starts.append(int(np.argmax(changed)))

    movement_start_frame = min(movement_starts) if movement_starts else 0
    total_frames = len(trajectory)
    motion_frames = total_frames - movement_start_frame
    duration = {
        "static_before_sec": movement_start_frame / float(stimulus_fps),
        "motion_sec": motion_frames / float(stimulus_fps),
        "static_after_sec": 0.0,
        "total_sec": total_frames / float(stimulus_fps),
        "total_frames": total_frames,
        "motion_start_frame": movement_start_frame,
        "motion_end_frame": total_frames - 1,
    }
    return duration


def get_stimulus_duration(trajectory_file, stimulus_fps=DEFAULT_STIMULUS_FPS):
    """Load a trajectory file and measure its stimulus timing.

    Args:
        trajectory_file (Path): CSV trajectory containing x, y, or radius columns.
        stimulus_fps (float): Sampling rate of the trajectory in frames per second.

    Returns:
        dict: Static, motion, and total stimulus durations and frame counts.

    Raises:
        ValueError: If the trajectory is empty or has no supported columns.
    """
    trajectory = load_trajectory(trajectory_file)
    duration = calculate_stimulus_duration(
        trajectory,
        stimulus_fps,
        trajectory_name=trajectory_file,
    )
    return duration


def load_stimulus_durations(stimuli_dir, stimulus_fps=DEFAULT_STIMULUS_FPS):
    """Load timing metadata for every trajectory in a stimulus directory.

    Args:
        stimuli_dir (Path): Directory containing ``*trajectory.*`` files.
        stimulus_fps (float): Sampling rate of the trajectory files.

    Returns:
        dict: Stimulus name mapped to its duration metadata.

    Raises:
        FileNotFoundError: If no trajectory files are available.
    """
    stimuli_dir = Path(stimuli_dir)
    trajectory_files = sorted(stimuli_dir.glob("*trajectory.*"))
    if not trajectory_files:
        raise FileNotFoundError(
            f"No '*trajectory.*' stimulus files were found in {stimuli_dir}."
        )

    durations = {}
    for trajectory_file in trajectory_files:
        stimulus_name = trajectory_file.stem
        if stimulus_name.endswith("_trajectory"):
            stimulus_name = stimulus_name[: -len("_trajectory")]
        durations[stimulus_name] = get_stimulus_duration(
            trajectory_file,
            stimulus_fps=stimulus_fps,
        )
    return durations


def file_modified_time(path):
    """Return a path's modification time for deterministic file selection.

    Args:
        path (Path): Existing filesystem path.

    Returns:
        float: Modification timestamp.
    """
    modified_time = path.stat().st_mtime
    return modified_time


def find_latest_block_log(experiment_dir):
    """Find the newest block log in an experiment metadata directory.

    Args:
        experiment_dir (Path): Root of one experiment's standard folder tree.

    Returns:
        Path: Most recently modified ``*block_log.csv`` file.

    Raises:
        FileNotFoundError: If the metadata directory has no block log.
    """
    metadata_dir = Path(experiment_dir) / "01_raw" / "2p" / "metadata"
    block_logs = list(metadata_dir.glob("*block_log.csv"))
    if not block_logs:
        raise FileNotFoundError(f"No '*block_log.csv' file was found in {metadata_dir}.")

    latest_block_log = max(block_logs, key=file_modified_time)
    return latest_block_log


def adjust_block_log(block_log, selected_blocks, block_duration_sec):
    """Select blocks and shift their local timestamps onto one timeline.

    Args:
        block_log (DataFrame): Event log containing ``event`` and ``timestamp``.
        selected_blocks (sequence): Ordered block labels such as ``B1`` and ``B2``.
        block_duration_sec (float): Imaging duration assigned to each selected block.

    Returns:
        DataFrame: Selected events with continuous experiment timestamps.

    Raises:
        ValueError: If columns or selected block events are missing.
    """
    required_columns = {"event", "timestamp"}
    missing_columns = required_columns.difference(block_log.columns)
    if missing_columns:
        missing_text = ", ".join(sorted(missing_columns))
        raise ValueError(f"Block log is missing required column(s): {missing_text}.")
    if not selected_blocks:
        raise ValueError("selected_blocks cannot be empty.")

    adjusted_blocks = []
    event_names = block_log["event"].astype(str)
    for block_position, block_name in enumerate(selected_blocks):
        block_mask = event_names.str.startswith(str(block_name))
        selected_log = block_log.loc[block_mask].copy()
        if selected_log.empty:
            print(f"Warning: selected block {block_name} has no events and will be skipped.")
            continue
        selected_log["timestamp"] = (
            pd.to_numeric(selected_log["timestamp"], errors="raise")
            + block_position * block_duration_sec
        )
        adjusted_blocks.append(selected_log)

    if not adjusted_blocks:
        raise ValueError("None of the selected blocks were found in the block log.")

    adjusted_log = pd.concat(adjusted_blocks, ignore_index=True)
    adjusted_log = adjusted_log.sort_values("timestamp").reset_index(drop=True)
    return adjusted_log


def parse_stimulus_name(event_name, available_names):
    """Resolve a stimulus name from a standard block-log event.

    Args:
        event_name (str): Event formatted as ``B#_stim#_<stimulus>``.
        available_names (collection): Stimulus names with trajectory metadata.

    Returns:
        str or None: Matching stimulus name, or ``None`` for unrelated events.
    """
    event_parts = str(event_name).split("_", 2)
    if len(event_parts) < 3 or not event_parts[1].startswith("stim"):
        return None

    event_stimulus_name = event_parts[2]
    if event_stimulus_name in available_names:
        return event_stimulus_name
    if event_stimulus_name.endswith("_trajectory"):
        shortened_name = event_stimulus_name[: -len("_trajectory")]
        if shortened_name in available_names:
            return shortened_name
    return None


def _add_stimulus_event_to_trace(
    event,
    stimulus_durations,
    stimulus_id_map,
    stimulus_trace,
    stimulus_trace_length,
    stimulus_fps,
):
    """Add one recognized log event to a stimulus trace.

    Args:
        event (Series): One adjusted block-log event.
        stimulus_durations (dict): Per-stimulus trajectory timing metadata.
        stimulus_id_map (dict): Stimulus names mapped to integer IDs.
        stimulus_trace (ndarray): Categorical stimulus trace to update.
        stimulus_trace_length (int): Number of samples in the stimulus trace.
        stimulus_fps (float): Stimulus trajectory sampling rate.

    Returns:
        dict or None: Timeline row for a recognized event, otherwise ``None``.
    """
    stimulus_name = parse_stimulus_name(event["event"], stimulus_durations)
    if stimulus_name is None:
        return None

    onset_time = float(event["timestamp"])
    duration = stimulus_durations[stimulus_name]
    onset_frame = int(round(onset_time * stimulus_fps))
    offset_frame = onset_frame + int(duration["total_frames"])
    clipped_start = max(0, onset_frame)
    clipped_stop = min(stimulus_trace_length, offset_frame)
    if clipped_start < clipped_stop:
        stimulus_trace[clipped_start:clipped_stop] = stimulus_id_map[stimulus_name]

    event_row = {
        "event": event["event"],
        "stimulus_name": stimulus_name,
        "stimulus_id": stimulus_id_map[stimulus_name],
        "onset_time": onset_time,
        "offset_time": onset_time + duration["total_sec"],
    }
    return event_row


def _resample_stimulus_trace(
    stimulus_trace,
    n_imaging_frames,
    imaging_fps,
    stimulus_fps,
):
    """Sample a stimulus-rate categorical trace at imaging-frame times.

    Args:
        stimulus_trace (ndarray): Stimulus IDs sampled at the stimulus rate.
        n_imaging_frames (int): Desired number of imaging-rate samples.
        imaging_fps (float): Imaging sampling rate in frames per second.
        stimulus_fps (float): Stimulus sampling rate in frames per second.

    Returns:
        ndarray: Stimulus IDs sampled at each imaging frame.
    """
    imaging_times = np.arange(n_imaging_frames) / float(imaging_fps)
    stimulus_indices = np.floor(imaging_times * stimulus_fps).astype(int)
    stimulus_indices = np.clip(stimulus_indices, 0, stimulus_trace.size - 1)
    imaging_stimulus_trace = stimulus_trace[stimulus_indices]
    return imaging_stimulus_trace


def build_stimulus_timeline(
    adjusted_log,
    stimulus_durations,
    n_imaging_frames,
    imaging_fps,
    stimulus_fps=DEFAULT_STIMULUS_FPS,
):
    """Build stimulus events and a categorical trace at the imaging rate.

    Args:
        adjusted_log (DataFrame): Block-selected log on a continuous timeline.
        stimulus_durations (dict): Per-stimulus trajectory timing metadata.
        n_imaging_frames (int): Length of the merged dF/F recording.
        imaging_fps (float): Imaging sampling rate in frames per second.
        stimulus_fps (float): Stimulus trajectory sampling rate.

    Returns:
        dict: Event table, stimulus ID map, and imaging-rate stimulus trace.

    Raises:
        ValueError: If rates or recording length are invalid or no events match.
    """
    if n_imaging_frames <= 0:
        raise ValueError("n_imaging_frames must be greater than zero.")
    if imaging_fps <= 0 or stimulus_fps <= 0:
        raise ValueError("imaging_fps and stimulus_fps must be greater than zero.")

    stimulus_names = list(stimulus_durations)
    stimulus_id_map = {
        stimulus_name: stimulus_index + 1
        for stimulus_index, stimulus_name in enumerate(stimulus_names)
    }
    recording_duration_sec = n_imaging_frames / float(imaging_fps)
    stimulus_trace_length = max(1, int(np.ceil(recording_duration_sec * stimulus_fps)))
    stimulus_trace = np.zeros(stimulus_trace_length, dtype=np.int16)
    event_rows = []

    for _, event in adjusted_log.iterrows():
        event_row = _add_stimulus_event_to_trace(
            event,
            stimulus_durations,
            stimulus_id_map,
            stimulus_trace,
            stimulus_trace_length,
            stimulus_fps,
        )
        if event_row is not None:
            event_rows.append(event_row)

    if not event_rows:
        raise ValueError(
            "No stimulus events in the selected block log matched the trajectory names."
        )

    present_stimuli = {event_row["stimulus_name"] for event_row in event_rows}
    stimulus_id_map = {
        stimulus_name: stimulus_id_map[stimulus_name]
        for stimulus_name in stimulus_names
        if stimulus_name in present_stimuli
    }
    imaging_stimulus_trace = _resample_stimulus_trace(
        stimulus_trace,
        n_imaging_frames,
        imaging_fps,
        stimulus_fps,
    )
    stimulus_events = pd.DataFrame(event_rows)
    timeline = {
        "stimulus_events": stimulus_events,
        "stimulus_id_map": stimulus_id_map,
        "stimulus_trace": imaging_stimulus_trace,
    }
    return timeline


def load_experiment_stimuli(
    experiment_dir,
    stimuli_dir,
    selected_blocks,
    n_imaging_frames,
    imaging_fps,
    stimulus_fps=DEFAULT_STIMULUS_FPS,
):
    """Load all stimulus information needed for one imaging experiment.

    Args:
        experiment_dir (Path): Root of one experiment's standard folder tree.
        stimuli_dir (Path): Directory containing trajectory files.
        selected_blocks (sequence): Ordered block labels to include.
        n_imaging_frames (int): Length of the merged dF/F recording.
        imaging_fps (float): Imaging sampling rate in frames per second.
        stimulus_fps (float): Stimulus trajectory sampling rate.

    Returns:
        dict: Adjusted log, durations, event table, ID map, and stimulus trace.

    Raises:
        ValueError: If frames cannot be divided evenly among selected blocks.
    """
    if not selected_blocks:
        raise ValueError("selected_blocks cannot be empty.")
    if n_imaging_frames % len(selected_blocks) != 0:
        raise ValueError(
            f"{n_imaging_frames} imaging frames are not divisible by "
            f"{len(selected_blocks)} selected blocks."
        )

    block_log_path = find_latest_block_log(experiment_dir)
    block_log = pd.read_csv(block_log_path)
    frames_per_block = n_imaging_frames // len(selected_blocks)
    block_duration_sec = frames_per_block / float(imaging_fps)
    adjusted_log = adjust_block_log(block_log, selected_blocks, block_duration_sec)
    stimulus_durations = load_stimulus_durations(stimuli_dir, stimulus_fps)
    timeline = build_stimulus_timeline(
        adjusted_log,
        stimulus_durations,
        n_imaging_frames,
        imaging_fps,
        stimulus_fps,
    )
    experiment_stimuli = {
        "adjusted_log": adjusted_log,
        "block_log_path": block_log_path,
        "stimulus_durations": stimulus_durations,
        "frames_per_block": frames_per_block,
        **timeline,
    }
    return experiment_stimuli


def _alignment_coordinates(
    dfof,
    stimulus_trace,
    imaging_fps,
    pre_stimulus_sec,
    post_stimulus_sec,
):
    """Validate alignment inputs and calculate window coordinates.

    Args:
        dfof (ndarray): Merged time-by-neuron array.
        stimulus_trace (ndarray): Stimulus IDs at the imaging rate.
        imaging_fps (float): Imaging sampling rate in frames per second.
        pre_stimulus_sec (float): Seconds retained before stimulus onset.
        post_stimulus_sec (float): Seconds retained from onset onward.

    Returns:
        tuple: Validated arrays, frame counts, and relative time axis.

    Raises:
        ValueError: If shapes, rates, or requested windows are invalid.
    """
    dfof = np.asarray(dfof)
    stimulus_trace = np.asarray(stimulus_trace)
    if dfof.ndim != 2:
        raise ValueError(f"dfof must be two-dimensional, got shape {dfof.shape}.")
    if stimulus_trace.ndim != 1 or stimulus_trace.size != dfof.shape[0]:
        raise ValueError("stimulus_trace must be one-dimensional and match dfof time.")
    if imaging_fps <= 0 or pre_stimulus_sec < 0 or post_stimulus_sec <= 0:
        raise ValueError("Imaging rate and alignment windows must be positive.")

    pre_frames = int(round(pre_stimulus_sec * imaging_fps))
    post_frames = int(round(post_stimulus_sec * imaging_fps))
    window_frames = pre_frames + post_frames
    time_sec = (np.arange(window_frames) - pre_frames) / float(imaging_fps)
    coordinates = (
        dfof,
        stimulus_trace,
        pre_frames,
        post_frames,
        time_sec,
    )
    return coordinates


def _align_one_stimulus(dfof, stimulus_trace, stimulus_id, pre_frames, post_frames):
    """Extract complete trial windows for one stimulus ID.

    Args:
        dfof (ndarray): Merged time-by-neuron array.
        stimulus_trace (ndarray): Stimulus IDs at the imaging rate.
        stimulus_id (int): ID whose presentation onsets should be aligned.
        pre_frames (int): Frames retained before each onset.
        post_frames (int): Frames retained from each onset onward.

    Returns:
        tuple: Aligned trials, mean raster, found count, and dropped count.
    """
    active_trace = (stimulus_trace == stimulus_id).astype(np.int8)
    transitions = np.diff(active_trace, prepend=0)
    onset_frames = np.flatnonzero(transitions == 1)
    valid_onsets = [
        onset_frame
        for onset_frame in onset_frames
        if onset_frame - pre_frames >= 0
        and onset_frame + post_frames <= dfof.shape[0]
    ]
    dropped_trials = len(onset_frames) - len(valid_onsets)
    window_frames = pre_frames + post_frames
    if valid_onsets:
        aligned_trials = np.stack(
            [
                dfof[onset_frame - pre_frames : onset_frame + post_frames, :].T
                for onset_frame in valid_onsets
            ],
            axis=2,
        )
        mean_raster = np.nanmean(aligned_trials, axis=2)
    else:
        aligned_trials = np.empty((dfof.shape[1], window_frames, 0), dtype=float)
        mean_raster = np.full((dfof.shape[1], window_frames), np.nan)

    aligned_stimulus = (
        aligned_trials,
        mean_raster,
        len(onset_frames),
        dropped_trials,
    )
    return aligned_stimulus


def build_trial_aligned_traces(
    dfof,
    stimulus_trace,
    stimulus_id_map,
    imaging_fps,
    pre_stimulus_sec=5.0,
    post_stimulus_sec=27.0,
):
    """Extract complete peri-stimulus windows for every stimulus repetition.

    Args:
        dfof (ndarray): Merged array shaped time by neurons.
        stimulus_trace (ndarray): Stimulus IDs sampled at the imaging rate.
        stimulus_id_map (dict): Stimulus name to integer ID mapping.
        imaging_fps (float): Imaging sampling rate in frames per second.
        pre_stimulus_sec (float): Seconds retained before stimulus onset.
        post_stimulus_sec (float): Seconds retained from onset onward.

    Returns:
        dict: Trial arrays, mean rasters, time axis, and trial counts.

    Raises:
        ValueError: If shapes, rates, or requested windows are invalid.
    """
    (
        dfof,
        stimulus_trace,
        pre_frames,
        post_frames,
        time_sec,
    ) = _alignment_coordinates(
        dfof,
        stimulus_trace,
        imaging_fps,
        pre_stimulus_sec,
        post_stimulus_sec,
    )
    trial_traces = {}
    mean_rasters = {}
    trial_counts = {}

    for stimulus_name, stimulus_id in stimulus_id_map.items():
        aligned_trials, mean_raster, found_trials, dropped_trials = (
            _align_one_stimulus(
                dfof,
                stimulus_trace,
                stimulus_id,
                pre_frames,
                post_frames,
            )
        )
        if dropped_trials:
            print(
                f"Warning: {stimulus_name} dropped {dropped_trials} boundary trial(s) "
                "without a complete alignment window."
            )

        trial_traces[stimulus_name] = aligned_trials
        mean_rasters[stimulus_name] = mean_raster
        trial_counts[stimulus_name] = {
            "found": found_trials,
            "retained": found_trials - dropped_trials,
            "dropped": dropped_trials,
        }

    aligned_result = {
        "trial_traces": trial_traces,
        "mean_rasters": mean_rasters,
        "trial_counts": trial_counts,
        "time_sec": time_sec,
        "pre_frames": pre_frames,
        "post_frames": post_frames,
    }
    return aligned_result


def compute_response_metrics(mean_rasters, pre_frames, imaging_fps):
    """Compute per-neuron response AUC and maximum amplitude by stimulus.

    Args:
        mean_rasters (dict): Stimulus mean arrays shaped neurons by time.
        pre_frames (int): Index corresponding to stimulus onset.
        imaging_fps (float): Imaging sampling rate in frames per second.

    Returns:
        dict: Per-stimulus ``auc`` and ``maximum_amplitude`` vectors.

    Raises:
        ValueError: If a raster or response interval is invalid.
    """
    if imaging_fps <= 0:
        raise ValueError("imaging_fps must be greater than zero.")

    auc_by_stimulus = {}
    maximum_by_stimulus = {}
    for stimulus_name, mean_raster in mean_rasters.items():
        mean_raster = np.asarray(mean_raster, dtype=float)
        if mean_raster.ndim != 2 or not 0 <= pre_frames < mean_raster.shape[1]:
            raise ValueError(
                f"Invalid mean raster or onset index for stimulus {stimulus_name}."
            )

        response = mean_raster[:, pre_frames:]
        finite_neurons = np.all(np.isfinite(response), axis=1)
        auc_values = np.full(response.shape[0], np.nan)
        maximum_values = np.full(response.shape[0], np.nan)
        if np.any(finite_neurons):
            finite_response = response[finite_neurons]
            auc_values[finite_neurons] = np.trapezoid(
                finite_response,
                dx=1.0 / float(imaging_fps),
                axis=1,
            )
            maximum_values[finite_neurons] = np.max(finite_response, axis=1)

        auc_by_stimulus[stimulus_name] = auc_values
        maximum_by_stimulus[stimulus_name] = maximum_values

    metrics = {
        "auc": auc_by_stimulus,
        "maximum_amplitude": maximum_by_stimulus,
    }
    return metrics


def _validate_mean_raster(mean_raster, stimulus_name, expected_neurons):
    """Validate one stimulus mean raster and its neuron count.

    Args:
        mean_raster (ndarray): Candidate neurons-by-time mean raster.
        stimulus_name (str): Name used in descriptive errors.
        expected_neurons (int or None): Required neuron count, if established.

    Returns:
        ndarray: Validated floating-point mean raster.

    Raises:
        ValueError: If the raster shape or neuron count is inconsistent.
    """
    mean_raster = np.asarray(mean_raster, dtype=float)
    if mean_raster.ndim != 2:
        raise ValueError(
            f"Mean raster for {stimulus_name} must be neurons by time, "
            f"got {mean_raster.shape}."
        )
    if expected_neurons is not None and mean_raster.shape[0] != expected_neurons:
        raise ValueError(
            f"Mean raster for {stimulus_name} has {mean_raster.shape[0]} neurons; "
            f"expected {expected_neurons}."
        )
    return mean_raster


def _stimulus_segment(
    stimulus_name,
    mean_raster,
    duration,
    pre_frames,
    imaging_fps,
    start,
):
    """Describe the coordinates of one concatenated stimulus segment.

    Args:
        stimulus_name (str): Stimulus display name.
        mean_raster (ndarray): Stimulus mean raster shaped neurons by time.
        duration (dict): Stimulus trajectory timing metadata.
        pre_frames (int): Frames before stimulus presentation onset.
        imaging_fps (float): Imaging sampling rate in frames per second.
        start (int): First frame of this segment in the concatenated raster.

    Returns:
        dict: Segment boundaries and presentation and movement onsets.
    """
    segment_frames = mean_raster.shape[1]
    movement_delay_frames = int(round(duration["static_before_sec"] * imaging_fps))
    segment = {
        "stimulus_name": stimulus_name,
        "start_frame": start,
        "end_frame": start + segment_frames,
        "center_frame": start + segment_frames / 2.0,
        "presentation_onset_frame": start + pre_frames,
        "movement_onset_frame": start + pre_frames + movement_delay_frames,
    }
    return segment


def concatenate_stimulus_mean_rasters(
    mean_rasters,
    stimulus_durations,
    pre_frames,
    imaging_fps,
    stimulus_order=None,
):
    """Concatenate repeat-averaged stimulus responses into one raster.

    Args:
        mean_rasters (dict): Stimulus names mapped to neurons-by-time averages.
        stimulus_durations (dict): Per-stimulus trajectory timing metadata.
        pre_frames (int): Number of frames before stimulus presentation onset.
        imaging_fps (float): Imaging sampling rate in frames per second.
        stimulus_order (sequence or None): Desired left-to-right stimulus order.

    Returns:
        dict: Concatenated raster and a table describing every stimulus segment.

    Raises:
        ValueError: If inputs are empty, inconsistent, or contain no finite responses.
    """
    if not mean_rasters:
        raise ValueError("At least one mean stimulus raster is required.")
    if imaging_fps <= 0 or pre_frames < 0:
        raise ValueError("imaging_fps must be positive and pre_frames cannot be negative.")

    if stimulus_order is None:
        stimulus_order = list(mean_rasters)
    else:
        stimulus_order = list(stimulus_order)

    concatenated_parts = []
    segment_rows = []
    expected_neurons = None
    current_frame = 0
    for stimulus_name in stimulus_order:
        if stimulus_name not in mean_rasters:
            print(f"Warning: stimulus {stimulus_name} has no mean raster and will be skipped.")
            continue
        if stimulus_name not in stimulus_durations:
            raise ValueError(f"Missing duration metadata for stimulus {stimulus_name}.")

        mean_raster = _validate_mean_raster(
            mean_rasters[stimulus_name],
            stimulus_name,
            expected_neurons,
        )
        if expected_neurons is None:
            expected_neurons = mean_raster.shape[0]
        if not np.any(np.isfinite(mean_raster)):
            print(
                f"Warning: stimulus {stimulus_name} has no finite aligned trials "
                "and will be skipped."
            )
            continue

        segment = _stimulus_segment(
            stimulus_name,
            mean_raster,
            stimulus_durations[stimulus_name],
            pre_frames,
            imaging_fps,
            current_frame,
        )
        segment_rows.append(segment)
        concatenated_parts.append(mean_raster)
        current_frame = segment["end_frame"]

    if not concatenated_parts:
        raise ValueError("No finite stimulus-average rasters were available to concatenate.")

    concatenated_raster = np.concatenate(concatenated_parts, axis=1)
    concatenated_result = {
        "raster": concatenated_raster,
        "segments": pd.DataFrame(segment_rows),
    }
    return concatenated_result


def summarize_metric(metric_by_stimulus):
    """Summarize per-neuron stimulus metrics as population mean and SEM.

    Args:
        metric_by_stimulus (dict): Stimulus names mapped to neuron-level values.

    Returns:
        DataFrame: Stimulus, mean, SEM, and finite-neuron count.
    """
    summary_rows = []
    for stimulus_name, metric_values in metric_by_stimulus.items():
        metric_values = np.asarray(metric_values, dtype=float)
        finite_values = metric_values[np.isfinite(metric_values)]
        if finite_values.size == 0:
            population_mean = np.nan
            population_sem = np.nan
        elif finite_values.size == 1:
            population_mean = float(finite_values[0])
            population_sem = 0.0
        else:
            population_mean = float(np.mean(finite_values))
            population_sem = float(
                np.std(finite_values, ddof=1) / np.sqrt(finite_values.size)
            )
        summary_rows.append(
            {
                "stimulus": stimulus_name,
                "mean": population_mean,
                "sem": population_sem,
                "n_neurons": int(finite_values.size),
            }
        )
    summary = pd.DataFrame(summary_rows)
    return summary
