"""Tests for loading, truncating, mapping, and saving plane dF/F arrays."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.plane_merge import (
    discover_plane_indices,
    load_merged_result,
    merge_five_planes,
    save_merged_result,
)


class PlaneMergeTests(unittest.TestCase):
    """Verify the five-plane merge contract with temporary experiment data."""

    def setUp(self):
        """Create a temporary canonical experiment with five planes."""
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.experiment_dir = Path(self.temporary_directory.name) / "L500_f01"
        self.fish_id = "L500_f01"
        suite2p_dir = (
            self.experiment_dir / "03_analysis" / "functional" / "suite2P"
        )
        self.expected_parts = []
        for plane_index in range(5):
            plane_dir = suite2p_dir / f"plane{plane_index}"
            if plane_index == 4:
                plane_dir = plane_dir / "dFoF"
            plane_dir.mkdir(parents=True)
            frame_count = 8 + plane_index
            plane_dfof = (
                np.arange(frame_count * 2, dtype=float).reshape(frame_count, 2)
                + plane_index * 100
            )
            roi_indices = np.array([plane_index * 10, plane_index * 10 + 1])
            np.save(
                plane_dir / f"{self.fish_id}_plane{plane_index}_dFoF.npy",
                plane_dfof,
            )
            np.save(
                plane_dir
                / f"{self.fish_id}_plane{plane_index}_filtered_roi_indices.npy",
                roi_indices,
            )
            self.expected_parts.append(plane_dfof[:8])

    def tearDown(self):
        """Release temporary files after each test."""
        self.temporary_directory.cleanup()

    def test_merge_truncates_and_concatenates_in_plane_order(self):
        """The output should retain every ROI and use the shortest duration."""
        merge_result = merge_five_planes(self.experiment_dir, self.fish_id)
        expected_dfof = np.concatenate(self.expected_parts, axis=1)

        np.testing.assert_array_equal(merge_result["dfof"], expected_dfof)
        self.assertEqual(merge_result["dfof"].shape, (8, 10))
        self.assertEqual(
            merge_result["mapping"]["global_column"].tolist(),
            list(range(10)),
        )
        self.assertEqual(
            merge_result["mapping"]["plane"].tolist(),
            [f"plane{plane_index}" for plane_index in range(5) for _ in range(2)],
        )
        self.assertEqual(
            merge_result["mapping"]["filtered_roi_index"].tolist(),
            [0, 1, 10, 11, 20, 21, 30, 31, 40, 41],
        )

    def test_save_and_load_preserve_outputs_and_metadata(self):
        """Saved artifacts should round-trip and refuse accidental replacement."""
        merge_result = merge_five_planes(self.experiment_dir, self.fish_id)
        saved_paths = save_merged_result(merge_result)
        loaded_result = load_merged_result(
            self.experiment_dir,
            self.fish_id,
            plane_indices=range(5),
        )

        np.testing.assert_array_equal(loaded_result["dfof"], merge_result["dfof"])
        self.assertEqual(len(loaded_result["mapping"]), 10)
        self.assertEqual(loaded_result["metadata"]["fish_id"], self.fish_id)
        with saved_paths["metadata"].open("r", encoding="utf-8") as metadata_file:
            saved_metadata = json.load(metadata_file)
        self.assertIn("timestamp", saved_metadata)
        with self.assertRaises(FileExistsError):
            save_merged_result(merge_result)

    def test_legacy_filenames_without_plane_are_supported(self):
        """Reference-pipeline files may omit the plane number from filenames."""
        plane_dir = (
            self.experiment_dir
            / "03_analysis"
            / "functional"
            / "suite2P"
            / "plane0"
        )
        legacy_dir = plane_dir / "dFoF"
        legacy_dir.mkdir()
        canonical_dfof = plane_dir / f"{self.fish_id}_plane0_dFoF.npy"
        canonical_indices = (
            plane_dir / f"{self.fish_id}_plane0_filtered_roi_indices.npy"
        )
        canonical_dfof.rename(legacy_dir / f"{self.fish_id}_dFoF.npy")
        canonical_indices.rename(
            legacy_dir / f"{self.fish_id}_filtered_roi_indices.npy"
        )

        merge_result = merge_five_planes(self.experiment_dir, self.fish_id)

        self.assertEqual(merge_result["dfof"].shape, (8, 10))
        self.assertEqual(
            Path(merge_result["mapping"].loc[0, "source_dfof_file"]).name,
            f"{self.fish_id}_dFoF.npy",
        )

    def test_all_discovers_planes_and_explicit_selection_uses_subset(self):
        """Automatic discovery and explicit plane subsets should both be supported."""
        suite2p_dir = (
            self.experiment_dir / "03_analysis" / "functional" / "suite2P"
        )
        self.assertEqual(discover_plane_indices(suite2p_dir), tuple(range(5)))

        all_result = merge_five_planes(
            self.experiment_dir,
            self.fish_id,
            plane_indices="all",
        )
        subset_result = merge_five_planes(
            self.experiment_dir,
            self.fish_id,
            plane_indices=[1, 2],
        )

        self.assertEqual(all_result["dfof"].shape, (8, 10))
        self.assertEqual(subset_result["dfof"].shape, (9, 4))
        self.assertEqual(
            subset_result["metadata"]["params"]["plane_indices"],
            [1, 2],
        )
        self.assertIn("planes_1-2", subset_result["paths"]["dfof"].name)

    def test_invalid_plane_selectors_are_rejected(self):
        """Malformed, duplicated, and negative plane selections should fail."""
        with self.assertRaisesRegex(ValueError, "cannot contain duplicate"):
            merge_five_planes(
                self.experiment_dir,
                self.fish_id,
                plane_indices=[0, 0],
            )
        with self.assertRaisesRegex(ValueError, "cannot contain negative"):
            merge_five_planes(
                self.experiment_dir,
                self.fish_id,
                plane_indices=[-1],
            )
        with self.assertRaisesRegex(ValueError, 'must be "all"'):
            merge_five_planes(
                self.experiment_dir,
                self.fish_id,
                plane_indices="first_five",
            )

    def test_missing_plane_raises_descriptive_error(self):
        """A missing required plane should stop the single-experiment workflow."""
        missing_path = (
            self.experiment_dir
            / "03_analysis"
            / "functional"
            / "suite2P"
            / "plane2"
            / f"{self.fish_id}_plane2_dFoF.npy"
        )
        missing_path.unlink()

        with self.assertRaisesRegex(FileNotFoundError, "Missing plane 2"):
            merge_five_planes(self.experiment_dir, self.fish_id)

    def test_roi_count_mismatch_raises_descriptive_error(self):
        """ROI provenance must contain exactly one entry per dF/F column."""
        roi_path = (
            self.experiment_dir
            / "03_analysis"
            / "functional"
            / "suite2P"
            / "plane1"
            / f"{self.fish_id}_plane1_filtered_roi_indices.npy"
        )
        np.save(roi_path, np.array([1]))

        with self.assertRaisesRegex(ValueError, "ROI index count"):
            merge_five_planes(self.experiment_dir, self.fish_id)


if __name__ == "__main__":
    unittest.main()
