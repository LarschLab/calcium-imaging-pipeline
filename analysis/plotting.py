"""Small plotting building blocks for calcium-imaging figures.

Each ``draw_*`` function draws onto a Matplotlib axis passed in and takes its
look (colormap, colour limits, colours) as arguments. Figure layout, sizes and
colour settings live in the notebook, so they can be tweaked without editing
this module.

Adapted from two_p/plotting.py in mp_thesis_2026.
"""

import time
from pathlib import Path

import matplotlib
import numpy as np
from matplotlib.lines import Line2D


DEFAULT_DPI = 300
DEFAULT_RASTER_PERCENTILE = 99.0
MINIMUM_COLOR_RANGE = np.finfo(float).eps


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


def build_stimulus_colors(stimulus_names, colormap_name, fixed_colors=None):
    """Assign one colour per stimulus, to be shared by every figure.

    Args:
        stimulus_names (sequence): Stimulus names in display order.
        colormap_name (str): Matplotlib colormap used for stimuli without a
            fixed colour.
        fixed_colors (dict or None): Optional stimulus names mapped to colours
            that override the colormap.

    Returns:
        dict: Stimulus names mapped to Matplotlib colours.
    """
    stimulus_names = list(stimulus_names)
    fixed_colors = fixed_colors or {}
    color_map = matplotlib.colormaps[colormap_name].resampled(max(len(stimulus_names), 1))
    stimulus_colors = {
        stimulus_name: fixed_colors.get(stimulus_name, color_map(stimulus_index))
        for stimulus_index, stimulus_name in enumerate(stimulus_names)
    }
    return stimulus_colors


def draw_raster(axis, raster, start_sec, end_sec, cmap, vmin, vmax):
    """Draw a neurons-by-time raster, first row at the bottom.

    Args:
        axis (Axes): Axis to draw on.
        raster (ndarray): Activity shaped neurons by time, rows in display order.
        start_sec (float): Time of the first column.
        end_sec (float): Time of the last column.
        cmap (str): Matplotlib colormap name.
        vmin (float): Lower colour limit.
        vmax (float): Upper colour limit.

    Returns:
        None: The raster is drawn onto ``axis``; use ``axis.images[-1]`` for a
        colorbar.
    """
    neuron_count = raster.shape[0]
    axis.imshow(
        raster,
        aspect="auto",
        origin="lower",
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        extent=[start_sec, end_sec, 0, neuron_count],
    )


def draw_population_mean(axis, raster, time_sec, color, linewidth=1.0):
    """Draw the mean over neurons of a neurons-by-time raster.

    Args:
        axis (Axes): Axis to draw on.
        raster (ndarray): Activity shaped neurons by time.
        time_sec (ndarray): Time of each column.
        color (str or tuple): Line colour.
        linewidth (float): Line width in points.

    Returns:
        None: The trace is drawn onto ``axis``.
    """
    population_mean = np.nanmean(raster, axis=0)
    axis.plot(time_sec, population_mean, color=color, linewidth=linewidth)


def draw_vertical_lines(
    axis,
    times_sec,
    color,
    time_limits,
    linestyle="-",
    linewidth=1.0,
    alpha=1.0,
):
    """Draw vertical lines at the given times, skipping those outside the limits.

    Lines outside ``time_limits`` are skipped so that events beyond the
    recording do not stretch the x-axis.

    Args:
        axis (Axes): Axis to draw on.
        times_sec (sequence): Times at which to draw lines.
        color (str or tuple): Line colour.
        time_limits (tuple): ``(start_sec, end_sec)`` range shown on the axis.
        linestyle (str): Matplotlib line style.
        linewidth (float): Line width in points.
        alpha (float): Line opacity.

    Returns:
        None: The lines are drawn onto ``axis``.
    """
    start_sec, end_sec = time_limits
    for time_value in times_sec:
        if not start_sec <= time_value <= end_sec:
            continue
        axis.axvline(
            time_value,
            color=color,
            linestyle=linestyle,
            linewidth=linewidth,
            alpha=alpha,
        )


def draw_stimulus_markers(
    axis,
    marker_times_sec,
    stimulus_names,
    stimulus_colors,
    time_limits,
    linewidth=1.0,
    alpha=1.0,
):
    """Draw one vertical line per stimulus event in that stimulus's colour.

    Args:
        axis (Axes): Axis to draw on.
        marker_times_sec (sequence): Time of each event's marker.
        stimulus_names (sequence): Stimulus name of each event.
        stimulus_colors (dict): Stimulus names mapped to colours.
        time_limits (tuple): ``(start_sec, end_sec)`` range shown on the axis.
        linewidth (float): Line width in points.
        alpha (float): Line opacity.

    Returns:
        None: The markers are drawn onto ``axis``.
    """
    for marker_time, stimulus_name in zip(marker_times_sec, stimulus_names):
        draw_vertical_lines(
            axis,
            [marker_time],
            stimulus_colors[stimulus_name],
            time_limits,
            linewidth=linewidth,
            alpha=alpha,
        )


def stimulus_legend_handles(stimulus_names, stimulus_colors, linewidth=2.0):
    """Create legend entries for the given stimuli.

    Args:
        stimulus_names (sequence): Stimulus names in legend order.
        stimulus_colors (dict): Stimulus names mapped to colours.
        linewidth (float): Line width of each legend entry.

    Returns:
        list: One ``Line2D`` legend handle per stimulus.
    """
    legend_handles = [
        Line2D([], [], color=stimulus_colors[stimulus_name], linewidth=linewidth, label=stimulus_name)
        for stimulus_name in stimulus_names
    ]
    return legend_handles


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
