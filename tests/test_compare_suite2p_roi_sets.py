from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts import compare_suite2p_roi_sets as compare


def make_roi(y0: int, x0: int, size: int = 2) -> dict:
    ys, xs = np.mgrid[y0 : y0 + size, x0 : x0 + size]
    ypix = ys.ravel()
    xpix = xs.ravel()
    return {
        "ypix": ypix,
        "xpix": xpix,
        "lam": np.ones(len(ypix), dtype=float),
        "med": np.array([float(y0), float(x0)]),
        "npix": len(ypix),
    }


class RoiMatchingTests(unittest.TestCase):
    def test_exact_match(self) -> None:
        reference = np.array([make_roi(1, 1)], dtype=object)
        comparison = np.array([make_roi(1, 1)], dtype=object)

        matches = compare.match_rois(reference, comparison, [0], [0])

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].reference_index, 0)
        self.assertEqual(matches[0].comparison_index, 0)
        self.assertEqual(matches[0].iou, 1.0)
        self.assertEqual(matches[0].centroid_distance, 0.0)

    def test_shifted_centroid_match(self) -> None:
        reference = np.array([make_roi(1, 1, size=3)], dtype=object)
        comparison = np.array([make_roi(2, 1, size=3)], dtype=object)

        matches = compare.match_rois(reference, comparison, [0], [0], max_centroid_distance=5.0, min_iou=0.05)

        self.assertEqual(len(matches), 1)
        self.assertGreater(matches[0].iou, 0.0)
        self.assertEqual(matches[0].centroid_distance, 1.0)

    def test_unmatched_when_too_far(self) -> None:
        reference = np.array([make_roi(1, 1)], dtype=object)
        comparison = np.array([make_roi(20, 20)], dtype=object)

        matches = compare.match_rois(reference, comparison, [0], [0], max_centroid_distance=5.0, min_iou=0.05)

        self.assertEqual(matches, [])

    def test_one_to_one_prefers_highest_iou(self) -> None:
        reference = np.array([make_roi(1, 1), make_roi(10, 10)], dtype=object)
        comparison = np.array([make_roi(1, 1), make_roi(1, 2), make_roi(10, 10)], dtype=object)

        matches = compare.match_rois(reference, comparison, [0, 1], [0, 1, 2])
        pairs = {(match.reference_index, match.comparison_index) for match in matches}

        self.assertEqual(pairs, {(0, 0), (1, 2)})

    def test_trace_quality_metrics_detects_transients(self) -> None:
        trace = np.ones(100)
        trace[20] = 20
        trace[70] = 15

        metrics = compare.trace_quality_metrics(trace)

        self.assertEqual(metrics["robust_transient_count"], 2)
        self.assertGreater(metrics["max_robust_z"], 3)


class PlaneClassificationTests(unittest.TestCase):
    def _write_plane(self, root: Path, stat: np.ndarray, iscell: np.ndarray, fluorescence: np.ndarray) -> None:
        plane_dir = root / "03_analysis/functional/suite2P/plane0"
        plane_dir.mkdir(parents=True)
        np.save(plane_dir / "fish_plane0_stat.npy", stat)
        np.save(plane_dir / "fish_plane0_iscell.npy", iscell)
        np.save(plane_dir / "fish_plane0_F.npy", fluorescence)

    def test_analyze_plane_classifies_rejected_and_unmatched(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            baseline = tmp_path / "baseline"
            comparison = tmp_path / "comparison"
            baseline_stat = np.array([make_roi(1, 1), make_roi(10, 10), make_roi(20, 20)], dtype=object)
            comparison_stat = np.array([make_roi(1, 1), make_roi(10, 10)], dtype=object)
            baseline_iscell = np.array([[1.0, 0.9], [1.0, 0.8], [1.0, 0.7]])
            comparison_iscell = np.array([[1.0, 0.9], [0.0, 0.2]])
            baseline_f = np.tile(np.arange(10, dtype=float), (3, 1))
            comparison_f = np.tile(np.arange(10, dtype=float), (2, 1))
            self._write_plane(baseline, baseline_stat, baseline_iscell, baseline_f)
            self._write_plane(comparison, comparison_stat, comparison_iscell, comparison_f)

            rows, new_rows, summary = compare.analyze_plane(
                baseline,
                comparison,
                "fish",
                0,
                max_centroid_distance=5.0,
                min_iou=0.05,
            )

        categories = [row["category"] for row in rows]
        self.assertEqual(categories, ["matched_accepted", "matched_rejected", "unmatched"])
        self.assertEqual(new_rows, [])
        self.assertEqual(summary["matched_accepted"], 1)
        self.assertEqual(summary["matched_rejected"], 1)
        self.assertEqual(summary["unmatched"], 1)


class RemainderTraceDiagnosticTests(unittest.TestCase):
    def test_zscore_trace_normalizes_each_trace_to_itself(self) -> None:
        trace = np.array([1.0, 2.0, 4.0, 8.0])

        zscored = compare.zscore_trace(trace)

        self.assertIsNotNone(zscored)
        assert zscored is not None
        self.assertAlmostEqual(float(np.mean(zscored)), 0.0)
        self.assertAlmostEqual(float(np.std(zscored)), 1.0)

    def test_zscore_trace_skips_invalid_or_flat_traces(self) -> None:
        self.assertIsNone(compare.zscore_trace(np.ones(4)))
        self.assertIsNone(compare.zscore_trace(np.array([1.0, np.nan, 2.0])))

    def test_baseline_remainder_selection_excludes_matched_accepted(self) -> None:
        rows = [
            {"plane": 0, "baseline_roi_id": 1, "category": "matched_accepted"},
            {"plane": 0, "baseline_roi_id": 2, "category": "matched_rejected"},
            {"plane": 0, "baseline_roi_id": 3, "category": "unmatched"},
            {"plane": 1, "baseline_roi_id": 4, "category": "unmatched"},
        ]

        roi_ids = compare.baseline_remainder_roi_ids(rows, plane=0)

        self.assertEqual(roi_ids, [2, 3])

    def test_new_accepted_selection_uses_comparison_roi_ids(self) -> None:
        rows = [
            {"plane": 0, "comparison_roi_id": 7},
            {"plane": 1, "comparison_roi_id": 8},
            {"plane": 0, "comparison_roi_id": 9},
        ]

        roi_ids = compare.new_accepted_comparison_roi_ids(rows, plane=0)

        self.assertEqual(roi_ids, [7, 9])

    def test_trace_panel_row_count_caps_each_panel_at_five_traces(self) -> None:
        self.assertEqual(compare.trace_panel_row_count(0), 0)
        self.assertEqual(compare.trace_panel_row_count(4), 1)
        self.assertEqual(compare.trace_panel_row_count(5), 1)
        self.assertEqual(compare.trace_panel_row_count(6), 2)
        self.assertEqual(compare.trace_panel_row_count(216), 44)


if __name__ == "__main__":
    unittest.main()
