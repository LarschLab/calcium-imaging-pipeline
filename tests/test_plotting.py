"""Tests for the plotting building blocks and safe figure saving."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from analysis.plotting import (
    build_stimulus_colors,
    draw_population_mean,
    draw_raster,
    draw_stimulus_markers,
    draw_vertical_lines,
    robust_color_limit,
    save_figure_safely,
    stimulus_legend_handles,
)


class PlottingTests(unittest.TestCase):
    """Check what each building block draws onto the axis it is given."""

    def setUp(self):
        """Create a fresh figure and axis for each test."""
        self.figure, self.axis = plt.subplots()

    def tearDown(self):
        """Close figures so tests do not retain Matplotlib state."""
        plt.close("all")

    def test_raster_draws_rows_in_given_order_with_time_extent(self):
        """The raster image should hold the array as given and span the time range."""
        raster = np.arange(12, dtype=float).reshape(3, 4)
        draw_raster(self.axis, raster, 0.0, 1.5, "gray_r", 0.0, 10.0)

        image = self.axis.images[-1]
        np.testing.assert_array_equal(image.get_array(), raster)
        self.assertEqual(list(image.get_extent()), [0.0, 1.5, 0, 3])
        self.assertEqual(image.get_clim(), (0.0, 10.0))

    def test_population_mean_averages_over_neurons(self):
        """The trace should be the mean across raster rows at each time point."""
        raster = np.array([[0.0, 2.0, 4.0], [2.0, 4.0, np.nan]])
        draw_population_mean(self.axis, raster, np.array([0.0, 0.5, 1.0]), "black")

        np.testing.assert_allclose(self.axis.lines[0].get_ydata(), [1.0, 3.0, 4.0])

    def test_lines_outside_time_limits_are_skipped(self):
        """Events outside the shown range should not stretch the x-axis."""
        draw_vertical_lines(self.axis, [-5.0, 1.0, 2.0, 50.0], "0.5", (0.0, 10.0))

        drawn_times = [line.get_xdata()[0] for line in self.axis.lines]
        self.assertEqual(drawn_times, [1.0, 2.0])

    def test_stimulus_markers_use_the_shared_colors(self):
        """Each marker should use its stimulus's colour from the shared dict."""
        stimulus_colors = build_stimulus_colors(["forward", "right"], "tab20", {"right": "red"})
        draw_stimulus_markers(
            self.axis,
            [1.0, 2.0, 99.0],
            ["forward", "right", "forward"],
            stimulus_colors,
            (0.0, 10.0),
        )

        self.assertEqual(len(self.axis.lines), 2)
        self.assertEqual(self.axis.lines[1].get_color(), "red")
        self.assertEqual(self.axis.lines[0].get_color(), stimulus_colors["forward"])

    def test_stimulus_colors_are_independent_of_figure(self):
        """Colours depend only on the stimulus list, so every figure matches."""
        stimulus_names = ["forward", "left", "right"]
        first_colors = build_stimulus_colors(stimulus_names, "tab20")
        second_colors = build_stimulus_colors(stimulus_names, "tab20")
        handles = stimulus_legend_handles(["right", "forward"], first_colors)

        self.assertEqual(first_colors, second_colors)
        self.assertEqual([handle.get_label() for handle in handles], ["right", "forward"])
        self.assertEqual(handles[0].get_color(), first_colors["right"])

    def test_robust_color_limit_uses_percentile_and_exceeds_minimum(self):
        """The upper limit follows the percentile but always exceeds the minimum."""
        self.assertAlmostEqual(robust_color_limit([np.arange(101.0)], 99.0), 99.0)
        self.assertGreater(robust_color_limit([np.zeros(5)], 99.0, minimum=0.0), 0.0)
        with self.assertRaises(ValueError):
            robust_color_limit([np.array([np.nan])])

    def test_safe_save_uses_unique_alternative_names(self):
        """Repeated saves in one second should preserve every figure file."""
        self.axis.plot([0, 1], [0, 1])
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            with patch(
                "analysis.plotting.time.strftime",
                return_value="20260915_164500",
            ):
                first_path = save_figure_safely(self.figure, output_dir, "plot.png")
                second_path = save_figure_safely(self.figure, output_dir, "plot.png")
                third_path = save_figure_safely(self.figure, output_dir, "plot.png")

            self.assertTrue(first_path.exists())
            self.assertTrue(second_path.exists())
            self.assertTrue(third_path.exists())
            self.assertEqual(first_path.name, "plot.png")
            self.assertEqual(second_path.name, "plot_20260915_164500.png")
            self.assertEqual(third_path.name, "plot_20260915_164500_2.png")


if __name__ == "__main__":
    unittest.main()
