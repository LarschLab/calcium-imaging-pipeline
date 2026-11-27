"""Tests for the anatomy -> reference registration QC helpers."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from registration.reference_qc import (
    add_decision_columns,
    common_depths,
    covered_depths,
    data_bounding_box,
    fish_mean_image,
    overlap_correlation,
    read_previous_decisions,
    roi_position_agreement,
    sample_stack_at_voxels,
    scale_fish_image,
    spread_depths,
    summarize_fish,
)

STACK_SHAPE_ZYX = (10, 20, 30)
FISH_Z_RANGE = (3, 7)  # depths (inclusive) the fake fish covers
FISH_Y_RANGE = (5, 15)  # end-exclusive
FISH_X_RANGE = (8, 22)  # end-exclusive
Z_SPACING_UM = 2.0
RANDOM_SEED = 0


def _reference_and_fish():
    """Build a random reference and a fish that copies it inside a box, 0 outside.

    Returns:
        tuple: (reference_stack, warped_stack), float32 (z, y, x).
    """
    random_generator = np.random.default_rng(RANDOM_SEED)
    reference_stack = random_generator.uniform(10, 200, STACK_SHAPE_ZYX).astype(np.float32)
    warped_stack = np.zeros(STACK_SHAPE_ZYX, dtype=np.float32)
    box = (slice(FISH_Z_RANGE[0], FISH_Z_RANGE[1] + 1), slice(*FISH_Y_RANGE), slice(*FISH_X_RANGE))
    warped_stack[box] = 2 * reference_stack[box] + 5  # linear copy: correlation exactly 1
    return reference_stack, warped_stack


class OverlapCorrelationTests(unittest.TestCase):
    def test_matches_numpy_on_masked_voxels(self):
        random_generator = np.random.default_rng(RANDOM_SEED)
        fish = random_generator.normal(size=STACK_SHAPE_ZYX).astype(np.float32)
        reference = (fish + random_generator.normal(size=STACK_SHAPE_ZYX)).astype(np.float32)
        mask = random_generator.random(STACK_SHAPE_ZYX) > 0.5
        expected = np.corrcoef(fish[mask], reference[mask])[0, 1]
        self.assertAlmostEqual(overlap_correlation(fish, reference, mask), expected, places=5)

    def test_empty_mask_gives_nan(self):
        stack = np.ones(STACK_SHAPE_ZYX, dtype=np.float32)
        empty_mask = np.zeros(STACK_SHAPE_ZYX, dtype=bool)
        self.assertTrue(np.isnan(overlap_correlation(stack, stack, empty_mask)))


class SummarizeFishTests(unittest.TestCase):
    def test_reports_range_box_and_perfect_correlation(self):
        reference_stack, warped_stack = _reference_and_fish()
        summary = summarize_fish(warped_stack, reference_stack, Z_SPACING_UM)
        self.assertAlmostEqual(summary["correlation"], 1.0, places=5)
        self.assertEqual((summary["z_first"], summary["z_last"]), FISH_Z_RANGE)
        self.assertEqual(summary["depth_first_um"], FISH_Z_RANGE[0] * Z_SPACING_UM)
        self.assertEqual(summary["bounding_box_yxyx"], (*FISH_Y_RANGE, *FISH_X_RANGE))

    def test_shape_mismatch_raises(self):
        reference_stack, warped_stack = _reference_and_fish()
        with self.assertRaises(ValueError):
            summarize_fish(warped_stack[:-1], reference_stack, Z_SPACING_UM)


class DepthTests(unittest.TestCase):
    def test_covered_depths_ignores_sparse_edge_slices(self):
        mask = np.zeros(STACK_SHAPE_ZYX, dtype=bool)
        mask[2:8] = True
        mask[1, 0, 0] = True  # a single stray voxel: below MIN_SLICE_COVERAGE
        self.assertEqual(covered_depths(mask), (2, 7))

    def test_covered_depths_none_when_empty(self):
        self.assertIsNone(covered_depths(np.zeros(STACK_SHAPE_ZYX, dtype=bool)))

    def test_spread_depths_stays_inside_range(self):
        depths = spread_depths(10, 70, 5)
        self.assertEqual(depths, [20, 30, 40, 50, 60])

    def test_common_depths_uses_median_range(self):
        depth_ranges = [(10, 70), (10, 70), (100, 170)]
        self.assertEqual(common_depths(depth_ranges, 5), spread_depths(10, 70, 5))

    def test_bounding_box_none_when_empty(self):
        self.assertIsNone(data_bounding_box(np.zeros(STACK_SHAPE_ZYX, dtype=bool)))


class ScaleFishImageTests(unittest.TestCase):
    def test_scales_on_data_pixels_only(self):
        fish_image = np.zeros((4, 4), dtype=np.float32)
        fish_image[:, 2:] = np.linspace(100, 200, 8).reshape(4, 2)  # data in the right half
        scaled_image = scale_fish_image(fish_image, 0.0, 100.0)
        self.assertEqual(scaled_image[:, 2:].min(), 0.0)  # dimmest data pixel -> 0, not the empty area
        self.assertEqual(scaled_image[:, 2:].max(), 1.0)
        self.assertTrue((scaled_image[:, :2] == 0.0).all())


class FishMeanImageTests(unittest.TestCase):
    def test_averages_only_where_fish_have_data(self):
        left_fish = np.zeros((4, 4), dtype=np.float32)
        left_fish[:, :2] = np.arange(8).reshape(4, 2) + 10  # data in the left half only
        right_fish = np.zeros((4, 4), dtype=np.float32)
        right_fish[:, 2:] = np.arange(8).reshape(4, 2) + 10  # data in the right half only
        mean_image = fish_mean_image([left_fish, right_fish])
        self.assertFalse(np.isnan(mean_image).any())  # every pixel covered by one fish
        self.assertGreaterEqual(mean_image.min(), 0.0)
        self.assertLessEqual(mean_image.max(), 1.0)

    def test_nan_where_no_fish_has_data(self):
        empty_fish = np.zeros((4, 4), dtype=np.float32)
        self.assertTrue(np.isnan(fish_mean_image([empty_fish, empty_fish])).all())


class DecisionColumnTests(unittest.TestCase):
    def test_keeps_earlier_decisions_and_blanks_new_fish(self):
        qc_table = pd.DataFrame({"fish_id": ["fish_a", "fish_b"], "correlation": [0.7, 0.4]})
        with tempfile.TemporaryDirectory() as temporary_directory:
            table_path = Path(temporary_directory) / "qc.csv"
            pd.DataFrame({"fish_id": ["fish_a"], "correlation": [0.6], "decision": ["ok"], "comment": ["fine"]}).to_csv(table_path, index=False)
            merged = add_decision_columns(qc_table, read_previous_decisions(table_path))
        self.assertEqual(merged["decision"].tolist(), ["ok", ""])
        self.assertEqual(merged["comment"].tolist(), ["fine", ""])
        self.assertEqual(merged["correlation"].tolist(), [0.7, 0.4])  # new numbers, not the old ones

    def test_no_previous_table_gives_blank_columns(self):
        qc_table = pd.DataFrame({"fish_id": ["fish_a"]})
        merged = add_decision_columns(qc_table, read_previous_decisions(Path("does_not_exist.csv")))
        self.assertEqual(merged["decision"].tolist(), [""])


class RoiSamplingTests(unittest.TestCase):
    def test_samples_xyz_positions_and_nan_outside(self):
        stack = np.arange(np.prod(STACK_SHAPE_ZYX), dtype=np.float32).reshape(STACK_SHAPE_ZYX)
        voxels_xyz = np.array([[4.0, 2.0, 1.0], [4.5, 2.0, 1.0], [-1.0, 0.0, 0.0], [np.nan, 1.0, 1.0], [29.0, 19.0, 9.0]])
        values = sample_stack_at_voxels(stack, voxels_xyz)
        self.assertEqual(values[0], stack[1, 2, 4])
        self.assertAlmostEqual(values[1], (stack[1, 2, 4] + stack[1, 2, 5]) / 2)  # linear between x = 4 and 5
        self.assertTrue(np.isnan(values[2]) and np.isnan(values[3]))
        self.assertEqual(values[4], stack[9, 19, 29])  # last voxel is still inside

    def test_agreement_is_one_for_identical_values_and_counts_outside(self):
        fish_values = np.array([1.0, 5.0, 2.0, 8.0, np.nan])
        warped_values = np.array([2.0, 10.0, 4.0, np.nan, 3.0])
        agreement = roi_position_agreement(fish_values, warped_values)
        self.assertAlmostEqual(agreement["correlation"], 1.0)
        self.assertEqual(agreement["n_compared"], 3)
        self.assertAlmostEqual(agreement["fraction_inside"], 3 / 4)


if __name__ == "__main__":
    unittest.main()
