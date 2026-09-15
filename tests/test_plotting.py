"""Smoke tests for calcium-analysis figures and safe figure saving."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.plotting import (
    correlation_sort_order,
    plot_concatenated_stimulus_responses,
    plot_full_activity,
    plot_metric_bars,
    save_figure_safely,
)


class PlottingTests(unittest.TestCase):
    """Ensure plotting helpers return figures for representative inputs."""

    def tearDown(self):
        """Close figures so tests do not retain Matplotlib state."""
        plt.close("all")

    def test_all_requested_plots_render(self):
        """Full activity, stimulus rasters, and metric bars should render."""
        dfof = np.linspace(0.0, 1.0, 60).reshape(20, 3)
        stimulus_events = pd.DataFrame(
            {"stimulus_name": ["forward"], "onset_time": [2.0]}
        )
        stimulus_durations = {"forward": {"static_before_sec": 0.5}}
        full_figure, full_axes = plot_full_activity(
            dfof,
            imaging_fps=2.0,
            fish_id="L500_f01",
            stimulus_events=stimulus_events,
            stimulus_durations=stimulus_durations,
        )
        stimulus_segments = pd.DataFrame(
            {
                "stimulus_name": ["forward"],
                "start_frame": [0],
                "end_frame": [6],
                "center_frame": [3.0],
                "presentation_onset_frame": [2],
                "movement_onset_frame": [3],
            }
        )
        raster_figure, raster_axes = plot_concatenated_stimulus_responses(
            dfof[:6].T,
            stimulus_segments,
            imaging_fps=2.0,
            fish_id="L500_f01",
        )
        summary = pd.DataFrame(
            {"stimulus": ["forward"], "mean": [1.0], "sem": [0.1], "n_neurons": [3]}
        )
        bar_figure, bar_axis = plot_metric_bars(summary, "AUC", "Response AUC")

        self.assertEqual(len(full_axes), 2)
        self.assertEqual(len(raster_axes), 2)
        self.assertAlmostEqual(
            raster_axes[0].get_position().x0,
            raster_axes[1].get_position().x0,
        )
        np.testing.assert_allclose(
            raster_axes[1].lines[0].get_ydata(),
            np.mean(dfof[:6].T, axis=0),
        )
        self.assertEqual(len(bar_axis.patches), 1)
        self.assertIsNotNone(full_figure)
        self.assertIsNotNone(raster_figure)
        self.assertIsNotNone(bar_figure)

    def test_full_activity_axes_align_and_respect_neuron_order(self):
        """Raster and mean axes should align while raster rows follow the order."""
        dfof = np.arange(24, dtype=float).reshape(8, 3)
        neuron_order = np.array([2, 0, 1])
        figure, axes = plot_full_activity(
            dfof,
            imaging_fps=2.0,
            fish_id="L500_f01",
            neuron_order=neuron_order,
        )
        figure.canvas.draw()

        self.assertAlmostEqual(axes[0].get_position().x0, axes[1].get_position().x0)
        self.assertAlmostEqual(axes[0].get_position().x1, axes[1].get_position().x1)
        colorbar_axis = figure.axes[2]
        legend_axis = figure.axes[3]
        self.assertGreater(colorbar_axis.get_position().x0, axes[0].get_position().x1)
        self.assertGreater(legend_axis.get_position().x0, colorbar_axis.get_position().x1)
        np.testing.assert_array_equal(
            axes[0].images[0].get_array(),
            dfof[:, neuron_order].T,
        )

    def test_correlation_sort_groups_similar_traces_and_appends_constants(self):
        """Correlation clustering should group similar traces and retain bad rows."""
        base_trace = np.arange(6, dtype=float)
        dfof = np.column_stack(
            [base_trace, base_trace * 2.0, base_trace[::-1], np.ones(6)]
        )
        neuron_order = correlation_sort_order(dfof)

        self.assertEqual(sorted(neuron_order.tolist()), [0, 1, 2, 3])
        self.assertEqual(neuron_order[-1], 3)
        positions = {neuron: position for position, neuron in enumerate(neuron_order)}
        self.assertEqual(abs(positions[0] - positions[1]), 1)

    def test_safe_save_uses_unique_alternative_names(self):
        """Repeated saves in one second should preserve every figure file."""
        figure, axis = plt.subplots()
        axis.plot([0, 1], [0, 1])
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            with patch(
                "src.plotting.time.strftime",
                return_value="20260915_164500",
            ):
                first_path = save_figure_safely(figure, output_dir, "plot.png")
                second_path = save_figure_safely(figure, output_dir, "plot.png")
                third_path = save_figure_safely(figure, output_dir, "plot.png")

            self.assertTrue(first_path.exists())
            self.assertTrue(second_path.exists())
            self.assertTrue(third_path.exists())
            self.assertEqual(first_path.name, "plot.png")
            self.assertEqual(second_path.name, "plot_20260915_164500.png")
            self.assertEqual(third_path.name, "plot_20260915_164500_2.png")


if __name__ == "__main__":
    unittest.main()
