"""Tests for stimulus timing, trial alignment, and response metrics."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.stimulus_analysis import (
    adjust_block_log,
    build_stimulus_timeline,
    build_trial_aligned_traces,
    concatenate_stimulus_mean_rasters,
    compute_response_metrics,
    get_stimulus_duration,
    summarize_metric,
)


class StimulusAnalysisTests(unittest.TestCase):
    """Verify stimulus processing with small hand-checkable arrays."""

    def test_trajectory_duration_detects_first_change(self):
        """Static and motion durations should follow the first trajectory change."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            trajectory_path = Path(temporary_directory) / "forward_trajectory.csv"
            pd.DataFrame({"dot_x": [0, 0, 1, 1], "dot_y": [0, 0, 0, 0]}).to_csv(
                trajectory_path,
                index=False,
            )
            duration = get_stimulus_duration(trajectory_path, stimulus_fps=2.0)

        self.assertEqual(duration["motion_start_frame"], 2)
        self.assertEqual(duration["static_before_sec"], 1.0)
        self.assertEqual(duration["motion_sec"], 1.0)
        self.assertEqual(duration["total_sec"], 2.0)

    def test_block_selection_and_timeline_resampling(self):
        """Selected block timestamps should be shifted and sampled at imaging rate."""
        block_log = pd.DataFrame(
            {
                "event": ["B1_start", "B1_stim1_forward", "B2_stim1_forward"],
                "timestamp": [0.0, 1.0, 1.0],
            }
        )
        adjusted_log = adjust_block_log(block_log, ["B1", "B2"], 4.0)
        durations = {
            "forward": {
                "static_before_sec": 0.0,
                "motion_sec": 1.0,
                "static_after_sec": 0.0,
                "total_sec": 1.0,
                "total_frames": 4,
            }
        }
        timeline = build_stimulus_timeline(
            adjusted_log,
            durations,
            n_imaging_frames=16,
            imaging_fps=2.0,
            stimulus_fps=4.0,
        )

        self.assertEqual(timeline["stimulus_events"]["onset_time"].tolist(), [1.0, 5.0])
        np.testing.assert_array_equal(
            np.flatnonzero(timeline["stimulus_trace"] == 1),
            np.array([2, 3, 10, 11]),
        )

    def test_trial_alignment_averages_repetitions_and_drops_boundaries(self):
        """Only complete windows should contribute to the mean stimulus raster."""
        dfof = np.arange(40, dtype=float).reshape(20, 2)
        stimulus_trace = np.zeros(20, dtype=int)
        stimulus_trace[1:2] = 1
        stimulus_trace[5:7] = 1
        stimulus_trace[12:14] = 1

        aligned = build_trial_aligned_traces(
            dfof,
            stimulus_trace,
            {"forward": 1},
            imaging_fps=2.0,
            pre_stimulus_sec=1.0,
            post_stimulus_sec=2.0,
        )

        self.assertEqual(aligned["trial_traces"]["forward"].shape, (2, 6, 2))
        self.assertEqual(aligned["trial_counts"]["forward"]["dropped"], 1)
        expected_mean = np.mean(
            np.stack([dfof[3:9].T, dfof[10:16].T], axis=2),
            axis=2,
        )
        np.testing.assert_array_equal(aligned["mean_rasters"]["forward"], expected_mean)

    def test_auc_maximum_and_sem_match_hand_calculation(self):
        """Response summaries should match exact values for simple traces."""
        mean_rasters = {
            "forward": np.array(
                [
                    [0.0, 1.0, 3.0, 5.0],
                    [0.0, 2.0, 2.0, 2.0],
                    [0.0, np.nan, 1.0, 2.0],
                ]
            )
        }
        metrics = compute_response_metrics(mean_rasters, pre_frames=1, imaging_fps=2.0)
        np.testing.assert_allclose(metrics["auc"]["forward"][:2], [3.0, 2.0])
        np.testing.assert_allclose(
            metrics["maximum_amplitude"]["forward"][:2],
            [5.0, 2.0],
        )
        self.assertTrue(np.isnan(metrics["auc"]["forward"][2]))

        summary = summarize_metric(metrics["auc"])
        self.assertEqual(summary.loc[0, "mean"], 2.5)
        self.assertEqual(summary.loc[0, "sem"], 0.5)
        self.assertEqual(summary.loc[0, "n_neurons"], 2)

    def test_stimulus_means_concatenate_with_aligned_markers(self):
        """Stimulus averages should concatenate with correct segment coordinates."""
        mean_rasters = {
            "forward": np.ones((2, 6)),
            "right": np.full((2, 6), 2.0),
        }
        durations = {
            "forward": {"static_before_sec": 0.5},
            "right": {"static_before_sec": 1.0},
        }
        concatenated = concatenate_stimulus_mean_rasters(
            mean_rasters,
            durations,
            pre_frames=2,
            imaging_fps=2.0,
            stimulus_order=["right", "forward"],
        )

        self.assertEqual(concatenated["raster"].shape, (2, 12))
        np.testing.assert_array_equal(concatenated["raster"][:, :6], 2.0)
        self.assertEqual(
            concatenated["segments"]["stimulus_name"].tolist(),
            ["right", "forward"],
        )
        self.assertEqual(
            concatenated["segments"]["movement_onset_frame"].tolist(),
            [4, 9],
        )


if __name__ == "__main__":
    unittest.main()
