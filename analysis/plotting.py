"""Plot merged and stimulus-aligned calcium-imaging results."""

import time
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import pdist


DEFAULT_DPI = 300
DEFAULT_RASTER_PERCENTILE = 99.0
MINIMUM_COLOR_RANGE = np.finfo(float).eps
ACTIVITY_FIGURE_SIZE = (15, 7)
ACTIVITY_WIDTH_RATIOS = [1.0, 0.035, 0.18]
ACTIVITY_HEIGHT_RATIOS = [4, 1]


def correlation_sort_order(dfof):
    """Order neurons by average-linkage clustering of correlation distance.

    Args:
        dfof (ndarray): Calcium activity shaped time by neurons.

    Returns:
        ndarray: Original neuron-column indices in correlation-cluster order.

    Raises:
        ValueError: If the input is not a non-empty two-dimensional array.
    """
    dfof = np.asarray(dfof, dtype=float)
    if dfof.ndim != 2 or min(dfof.shape) == 0:
        raise ValueError(f"dfof must be a non-empty time x neurons array, got {dfof.shape}.")

    neuron_traces = dfof.T
    finite_neurons = np.all(np.isfinite(neuron_traces), axis=1)
    variable_neurons = np.nanstd(neuron_traces, axis=1) > 0
    sortable_neurons = finite_neurons & variable_neurons
    sortable_indices = np.flatnonzero(sortable_neurons)
    unsortable_indices = np.flatnonzero(~sortable_neurons)

    if unsortable_indices.size:
        print(
            f"Warning: placing {unsortable_indices.size} non-finite or constant "
            "neuron trace(s) after the correlation-sorted neurons."
        )
    if sortable_indices.size < 2:
        neuron_order = np.concatenate([sortable_indices, unsortable_indices])
        return neuron_order

    correlation_distances = pdist(
        neuron_traces[sortable_neurons],
        metric="correlation",
    )
    if not np.all(np.isfinite(correlation_distances)):
        raise ValueError("Correlation distances contain non-finite values after filtering.")

    correlation_tree = linkage(correlation_distances, method="average")
    relative_order = leaves_list(correlation_tree)
    neuron_order = np.concatenate(
        [sortable_indices[relative_order], unsortable_indices]
    )
    return neuron_order


def validate_neuron_order(neuron_order, neuron_count):
    """Validate or create a complete neuron-column permutation.

    Args:
        neuron_order (sequence or None): Requested neuron-column order.
        neuron_count (int): Number of neuron columns in the plotted data.

    Returns:
        ndarray: Validated integer permutation.

    Raises:
        ValueError: If the supplied order is not a complete permutation.
    """
    if neuron_order is None:
        validated_order = np.arange(neuron_count, dtype=int)
        return validated_order

    validated_order = np.asarray(neuron_order, dtype=int).ravel()
    expected_order = np.arange(neuron_count, dtype=int)
    if validated_order.size != neuron_count or not np.array_equal(
        np.sort(validated_order),
        expected_order,
    ):
        raise ValueError(
            f"neuron_order must contain every index from 0 to {neuron_count - 1} once."
        )
    return validated_order


def robust_color_limit(arrays, percentile=DEFAULT_RASTER_PERCENTILE, minimum=0.0):
    """Calculate a finite percentile-based upper color limit.

    Args:
        arrays (sequence): Numeric arrays whose finite values define the limit.
        percentile (float): Percentile used for robust scaling.
        minimum (float): Lower color limit that the result must exceed.

    Returns:
        float: Upper color limit suitable for an image plot.

    Raises:
        ValueError: If no finite values are present or percentile is invalid.
    """
    if not 0 < percentile <= 100:
        raise ValueError("percentile must be in the interval (0, 100].")
    finite_parts = []
    for values in arrays:
        values = np.asarray(values, dtype=float)
        finite_values = values[np.isfinite(values)]
        if finite_values.size:
            finite_parts.append(finite_values)
    if not finite_parts:
        raise ValueError("Cannot calculate color limits without finite values.")

    combined_values = np.concatenate(finite_parts)
    upper_limit = float(np.percentile(combined_values, percentile))
    if upper_limit <= minimum:
        upper_limit = minimum + max(float(np.max(np.abs(combined_values))), MINIMUM_COLOR_RANGE)
    return upper_limit


def build_stimulus_colors(stimulus_names):
    """Assign stable plotting colors in the supplied stimulus order.

    Args:
        stimulus_names (sequence): Ordered display names for stimuli.

    Returns:
        dict: Stimulus names mapped to RGBA colors.
    """
    stimulus_names = list(stimulus_names)
    color_map = matplotlib.colormaps["tab20"].resampled(max(len(stimulus_names), 1))
    colors = {
        stimulus_name: color_map(stimulus_index)
        for stimulus_index, stimulus_name in enumerate(stimulus_names)
    }
    return colors


def add_stimulus_markers(axes, stimulus_events, stimulus_durations, colors):
    """Add stimulus movement-onset lines to one or more time-series axes.

    Args:
        axes (sequence): Matplotlib axes sharing an experiment time coordinate.
        stimulus_events (DataFrame): Stimulus names and presentation onset times.
        stimulus_durations (dict): Per-stimulus timing metadata.
        colors (dict): Stimulus names mapped to line colors.

    Returns:
        list: Legend handles representing stimuli present in the event table.
    """
    axes = np.atleast_1d(axes).ravel()
    seen_stimuli = []
    for _, stimulus_event in stimulus_events.iterrows():
        stimulus_name = stimulus_event["stimulus_name"]
        duration = stimulus_durations[stimulus_name]
        movement_onset = (
            float(stimulus_event["onset_time"]) + duration["static_before_sec"]
        )
        for axis in axes:
            axis.axvline(
                movement_onset,
                color=colors[stimulus_name],
                linewidth=1.0,
                alpha=0.75,
            )
        if stimulus_name not in seen_stimuli:
            seen_stimuli.append(stimulus_name)

    legend_handles = [
        plt.Line2D(
            [],
            [],
            color=colors[stimulus_name],
            linewidth=2.0,
            label=stimulus_name,
        )
        for stimulus_name in seen_stimuli
    ]
    return legend_handles


def _create_activity_figure():
    """Create the shared raster, mean-trace, colorbar, and legend layout.

    Returns:
        tuple: Figure, activity axes, colorbar axis, and legend axis.
    """
    figure = plt.figure(figsize=ACTIVITY_FIGURE_SIZE, constrained_layout=True)
    figure_grid = figure.add_gridspec(
        2,
        3,
        width_ratios=ACTIVITY_WIDTH_RATIOS,
        height_ratios=ACTIVITY_HEIGHT_RATIOS,
    )
    raster_axis = figure.add_subplot(figure_grid[0, 0])
    mean_axis = figure.add_subplot(figure_grid[1, 0], sharex=raster_axis)
    colorbar_axis = figure.add_subplot(figure_grid[0, 1])
    legend_axis = figure.add_subplot(figure_grid[0, 2])
    legend_axis.axis("off")
    activity_axes = np.array([raster_axis, mean_axis])
    return figure, activity_axes, colorbar_axis, legend_axis


def _hide_activity_axis_spines(axes):
    """Hide the upper and right spines of activity axes.

    Args:
        axes (sequence): Matplotlib axes to format.

    Returns:
        None: Axes are modified in place.
    """
    for axis in axes:
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)


def _add_full_activity_legend(
    axes,
    legend_axis,
    stimulus_events,
    stimulus_durations,
):
    """Add stimulus markers and their legend when timing data are available.

    Args:
        axes (sequence): Activity axes using experiment time.
        legend_axis (Axes): Axis reserved for the stimulus legend.
        stimulus_events (DataFrame or None): Optional stimulus event table.
        stimulus_durations (dict or None): Optional stimulus timing metadata.

    Returns:
        None: Axes are modified in place.
    """
    if stimulus_events is None or stimulus_durations is None:
        return

    stimulus_names = stimulus_events["stimulus_name"].drop_duplicates().tolist()
    colors = build_stimulus_colors(stimulus_names)
    legend_handles = add_stimulus_markers(
        axes,
        stimulus_events,
        stimulus_durations,
        colors,
    )
    legend_axis.legend(
        handles=legend_handles,
        frameon=False,
        loc="upper left",
        borderaxespad=0.0,
    )


def plot_full_activity(
    dfof,
    imaging_fps,
    fish_id,
    stimulus_events=None,
    stimulus_durations=None,
    raster_vmin=0.0,
    raster_vmax=None,
    raster_percentile=DEFAULT_RASTER_PERCENTILE,
    neuron_order=None,
):
    """Plot the merged neuron raster and population-average activity over time.

    Args:
        dfof (ndarray): Merged array shaped time by neurons.
        imaging_fps (float): Imaging sampling rate in frames per second.
        fish_id (str): Fish identifier displayed in the figure title.
        stimulus_events (DataFrame): Optional stimulus event table.
        stimulus_durations (dict): Optional per-stimulus timing metadata.
        raster_vmin (float): Lower raster color limit.
        raster_vmax (float or None): Upper limit, or ``None`` for robust scaling.
        raster_percentile (float): Percentile used for automatic upper scaling.
        neuron_order (sequence or None): Optional neuron-column plotting order.

    Returns:
        tuple: Matplotlib figure and its two axes.

    Raises:
        ValueError: If dF/F or imaging rate is invalid.
    """
    dfof = np.asarray(dfof, dtype=float)
    if dfof.ndim != 2 or min(dfof.shape) == 0:
        raise ValueError(f"dfof must be a non-empty time x neurons array, got {dfof.shape}.")
    if imaging_fps <= 0:
        raise ValueError("imaging_fps must be greater than zero.")
    if raster_vmax is None:
        raster_vmax = robust_color_limit([dfof], raster_percentile, raster_vmin)

    neuron_order = validate_neuron_order(neuron_order, dfof.shape[1])
    display_dfof = dfof[:, neuron_order]
    time_sec = np.arange(dfof.shape[0]) / float(imaging_fps)
    figure, axes, colorbar_axis, legend_axis = _create_activity_figure()
    raster_axis, mean_axis = axes
    raster_image = raster_axis.imshow(
        display_dfof.T,
        aspect="auto",
        origin="lower",
        cmap="gray_r",
        vmin=raster_vmin,
        vmax=raster_vmax,
        extent=[time_sec[0], time_sec[-1], 0, dfof.shape[1]],
    )
    raster_axis.set_ylabel("Neuron")
    raster_axis.set_title(f"{fish_id} merged dF/F")
    figure.colorbar(raster_image, cax=colorbar_axis, label="dF/F")

    population_mean = np.nanmean(dfof, axis=1)
    mean_axis.plot(time_sec, population_mean, color="black", linewidth=1.0)
    mean_axis.set_xlabel("Time (s)")
    mean_axis.set_ylabel("Mean dF/F")

    _add_full_activity_legend(
        axes,
        legend_axis,
        stimulus_events,
        stimulus_durations,
    )
    _hide_activity_axis_spines(axes)
    return figure, axes


def _add_segment_markers(axes, stimulus_segments, imaging_fps, colors):
    """Draw segment, presentation-onset, and movement-onset markers.

    Args:
        axes (sequence): Activity axes using concatenated stimulus time.
        stimulus_segments (DataFrame): Segment boundary and onset coordinates.
        imaging_fps (float): Imaging sampling rate in frames per second.
        colors (dict): Stimulus names mapped to line colors.

    Returns:
        None: Axes are modified in place.
    """
    for _, segment in stimulus_segments.iterrows():
        stimulus_name = segment["stimulus_name"]
        start_sec = segment["start_frame"] / float(imaging_fps)
        presentation_onset_sec = (
            segment["presentation_onset_frame"] / float(imaging_fps)
        )
        movement_onset_sec = segment["movement_onset_frame"] / float(imaging_fps)
        for axis in axes:
            axis.axvline(start_sec, color="0.65", linestyle="--", linewidth=0.8)
            axis.axvline(
                presentation_onset_sec,
                color="0.35",
                linestyle=":",
                linewidth=0.9,
            )
            axis.axvline(
                movement_onset_sec,
                color=colors[stimulus_name],
                linewidth=1.4,
            )


def _add_concatenated_labels(
    axes,
    legend_axis,
    stimulus_segments,
    stimulus_names,
    colors,
    imaging_fps,
    total_duration_sec,
):
    """Add the terminal boundary, segment labels, and stimulus legend.

    Args:
        axes (sequence): Raster and population-mean axes.
        legend_axis (Axes): Axis reserved for the stimulus legend.
        stimulus_segments (DataFrame): Segment boundary and onset coordinates.
        stimulus_names (sequence): Ordered stimulus display names.
        colors (dict): Stimulus names mapped to line colors.
        imaging_fps (float): Imaging sampling rate in frames per second.
        total_duration_sec (float): End of the concatenated time axis.

    Returns:
        None: Axes are modified in place.
    """
    for axis in axes:
        axis.axvline(
            total_duration_sec,
            color="0.65",
            linestyle="--",
            linewidth=0.8,
        )

    segment_label_axis = axes[0].secondary_xaxis("top")
    label_positions = (
        stimulus_segments["center_frame"].to_numpy(dtype=float) / imaging_fps
    )
    segment_label_axis.set_xticks(label_positions, stimulus_names, rotation=45, ha="left")
    segment_label_axis.tick_params(length=0, pad=4)
    legend_handles = [
        plt.Line2D([], [], color=colors[name], linewidth=2.0, label=name)
        for name in stimulus_names
    ]
    legend_axis.legend(
        handles=legend_handles,
        title="Movement onset",
        frameon=False,
        loc="upper left",
        borderaxespad=0.0,
    )


def _prepare_concatenated_plot_data(
    concatenated_raster,
    stimulus_segments,
    imaging_fps,
    raster_vmin,
    raster_vmax,
    raster_percentile,
    neuron_order,
):
    """Validate and prepare arrays used by the concatenated activity plot.

    Args:
        concatenated_raster (ndarray): Repeat-averaged neurons-by-time data.
        stimulus_segments (DataFrame): Segment boundaries and onset positions.
        imaging_fps (float): Imaging sampling rate in frames per second.
        raster_vmin (float): Lower raster color limit.
        raster_vmax (float or None): Upper raster color limit.
        raster_percentile (float): Percentile for automatic upper scaling.
        neuron_order (sequence or None): Optional neuron-row order.

    Returns:
        tuple: Source raster, display raster, time axis, duration, and upper limit.

    Raises:
        ValueError: If raster, segments, or imaging rate are invalid.
    """
    concatenated_raster = np.asarray(concatenated_raster, dtype=float)
    if concatenated_raster.ndim != 2 or min(concatenated_raster.shape) == 0:
        raise ValueError(
            "concatenated_raster must be a non-empty neurons by time array."
        )
    if stimulus_segments.empty:
        raise ValueError("stimulus_segments cannot be empty.")
    if imaging_fps <= 0:
        raise ValueError("imaging_fps must be greater than zero.")
    if raster_vmax is None:
        raster_vmax = robust_color_limit(
            [concatenated_raster],
            raster_percentile,
            raster_vmin,
        )

    neuron_order = validate_neuron_order(neuron_order, concatenated_raster.shape[0])
    display_raster = concatenated_raster[neuron_order, :]
    total_frames = display_raster.shape[1]
    total_duration_sec = total_frames / float(imaging_fps)
    time_sec = np.arange(total_frames) / float(imaging_fps)
    plot_data = (
        concatenated_raster,
        display_raster,
        time_sec,
        total_duration_sec,
        raster_vmax,
    )
    return plot_data


def _draw_concatenated_activity(
    figure,
    axes,
    colorbar_axis,
    concatenated_raster,
    display_raster,
    time_sec,
    total_duration_sec,
    fish_id,
    raster_vmin,
    raster_vmax,
):
    """Draw the concatenated raster and population-average trace.

    Args:
        figure (Figure): Figure containing the activity axes.
        axes (sequence): Raster and population-mean axes.
        colorbar_axis (Axes): Axis reserved for the raster colorbar.
        concatenated_raster (ndarray): Original neurons-by-time data.
        display_raster (ndarray): Neuron-ordered raster for display.
        time_sec (ndarray): Time coordinate for the mean trace.
        total_duration_sec (float): End of the concatenated time axis.
        fish_id (str): Fish identifier displayed in the title.
        raster_vmin (float): Lower raster color limit.
        raster_vmax (float): Upper raster color limit.

    Returns:
        None: Figure axes are modified in place.
    """
    raster_axis, mean_axis = axes
    raster_image = raster_axis.imshow(
        display_raster,
        aspect="auto",
        origin="lower",
        cmap="gray_r",
        vmin=raster_vmin,
        vmax=raster_vmax,
        extent=[0.0, total_duration_sec, 0, display_raster.shape[0]],
    )
    raster_axis.set_ylabel("Neuron")
    raster_axis.set_title(f"{fish_id} average responses by stimulus")
    figure.colorbar(raster_image, cax=colorbar_axis, label="Mean dF/F")

    population_mean = np.nanmean(concatenated_raster, axis=0)
    mean_axis.plot(time_sec, population_mean, color="black", linewidth=1.0)
    mean_axis.set_xlabel("Concatenated stimulus time (s)")
    mean_axis.set_ylabel("Mean dF/F")


def plot_concatenated_stimulus_responses(
    concatenated_raster,
    stimulus_segments,
    imaging_fps,
    fish_id,
    raster_vmin=0.0,
    raster_vmax=None,
    raster_percentile=DEFAULT_RASTER_PERCENTILE,
    neuron_order=None,
):
    """Plot concatenated stimulus averages and their population mean.

    Args:
        concatenated_raster (ndarray): Repeat-averaged data shaped neurons by time.
        stimulus_segments (DataFrame): Segment boundaries and onset positions.
        imaging_fps (float): Imaging sampling rate in frames per second.
        fish_id (str): Fish identifier displayed in the title.
        raster_vmin (float): Lower raster color limit.
        raster_vmax (float or None): Shared upper limit, or ``None`` for automatic.
        raster_percentile (float): Percentile used for automatic upper scaling.
        neuron_order (sequence or None): Optional neuron-row plotting order.

    Returns:
        tuple: Matplotlib figure and aligned raster/population axes.

    Raises:
        ValueError: If raster, segments, or imaging rate are invalid.
    """
    (
        concatenated_raster,
        display_raster,
        time_sec,
        total_duration_sec,
        raster_vmax,
    ) = _prepare_concatenated_plot_data(
        concatenated_raster,
        stimulus_segments,
        imaging_fps,
        raster_vmin,
        raster_vmax,
        raster_percentile,
        neuron_order,
    )
    figure, axes, colorbar_axis, legend_axis = _create_activity_figure()
    _draw_concatenated_activity(
        figure,
        axes,
        colorbar_axis,
        concatenated_raster,
        display_raster,
        time_sec,
        total_duration_sec,
        fish_id,
        raster_vmin,
        raster_vmax,
    )
    stimulus_names = stimulus_segments["stimulus_name"].tolist()
    colors = build_stimulus_colors(stimulus_names)
    _add_segment_markers(axes, stimulus_segments, imaging_fps, colors)
    _add_concatenated_labels(
        axes,
        legend_axis,
        stimulus_segments,
        stimulus_names,
        colors,
        imaging_fps,
        total_duration_sec,
    )
    axes[0].set_xlim(0.0, total_duration_sec)
    _hide_activity_axis_spines(axes)
    return figure, axes


def plot_metric_bars(metric_summary, ylabel, title):
    """Plot population mean and SEM bars for a stimulus response metric.

    Args:
        metric_summary (DataFrame): Table from ``summarize_metric``.
        ylabel (str): Vertical-axis label.
        title (str): Figure title.

    Returns:
        tuple: Matplotlib figure and axis.

    Raises:
        ValueError: If the summary table lacks required columns or rows.
    """
    required_columns = {"stimulus", "mean", "sem", "n_neurons"}
    missing_columns = required_columns.difference(metric_summary.columns)
    if missing_columns or metric_summary.empty:
        missing_text = ", ".join(sorted(missing_columns))
        raise ValueError(
            f"Metric summary is empty or missing required columns: {missing_text}."
        )
    if not np.any(np.isfinite(metric_summary["mean"].to_numpy(dtype=float))):
        raise ValueError("Metric summary has no finite neuron responses to plot.")

    stimulus_names = metric_summary["stimulus"].tolist()
    colors = build_stimulus_colors(stimulus_names)
    bar_colors = [colors[stimulus_name] for stimulus_name in stimulus_names]
    bar_positions = np.arange(len(stimulus_names))
    figure_width = max(6, 0.7 * len(stimulus_names))
    figure, axis = plt.subplots(figsize=(figure_width, 4.5))
    axis.bar(
        bar_positions,
        metric_summary["mean"].to_numpy(),
        yerr=metric_summary["sem"].to_numpy(),
        color=bar_colors,
        edgecolor="black",
        linewidth=0.6,
        capsize=3,
    )
    axis.axhline(0.0, color="black", linewidth=0.7)
    axis.set_xticks(bar_positions, stimulus_names, rotation=45, ha="right")
    axis.set_ylabel(ylabel)
    axis.set_title(title)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    figure.tight_layout()
    return figure, axis


def _available_figure_path(output_path):
    """Find a timestamped figure path without replacing an existing file.

    Args:
        output_path (Path): Preferred output path.

    Returns:
        Path: Preferred path or an unused timestamped alternative.
    """
    if not output_path.exists():
        return output_path

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    timestamped_stem = f"{output_path.stem}_{timestamp}"
    candidate_path = output_path.with_name(
        f"{timestamped_stem}{output_path.suffix}"
    )
    duplicate_number = 2
    while candidate_path.exists():
        candidate_path = output_path.with_name(
            f"{timestamped_stem}_{duplicate_number}{output_path.suffix}"
        )
        duplicate_number += 1
    return candidate_path


def save_figure_safely(figure, output_dir, filename, dpi=DEFAULT_DPI):
    """Save a figure using a timestamped alternative if the target exists.

    Args:
        figure (Figure): Matplotlib figure to save.
        output_dir (Path): Destination directory inside the experiment tree.
        filename (str): Desired PNG filename.
        dpi (int): Raster resolution in dots per inch.

    Returns:
        Path: Actual output path used.

    Raises:
        FileNotFoundError: If the standard plot directory has not been initialized.
    """
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        raise FileNotFoundError(
            f"Plot directory does not exist: {output_dir}. "
            "Create the experiment tree with init_experiment_tree first."
        )
    preferred_path = output_dir / filename
    output_path = _available_figure_path(preferred_path)
    figure.savefig(output_path, dpi=dpi, bbox_inches="tight")
    return output_path
