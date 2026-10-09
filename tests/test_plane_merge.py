"""Tests for loading, validating, and merging plane dF/F arrays in memory."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from analysis.plane_merge import discover_plane_indices, merge_planes


FRAME_COUNT = 8
PLANE_COUNT = 5


class PlaneMergeTests(unittest.TestCase):
    """Verify the plane merge contract with temporary experiment data."""

    def setUp(self):
        """Create a temporary canonical experiment with five planes."""
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.experiment_dir = Path(self.temporary_directory.name) / "L500_f01"
        self.fish_id = "L500_f01"
        self.suite2p_dir = (
            self.experiment_dir / "03_analysis" / "functional" / "suite2P"
        )
        self.expected_parts = []
        for plane_index in range(PLANE_COUNT):
            plane_dir = self.suite2p_dir / f"plane{plane_index}"
            if plane_index == 4:
                plane_dir = plane_dir / "dFoF"
            plane_dir.mkdir(parents=True)
            plane_dfof = (
                np.arange(FRAME_COUNT * 2, dtype=float).reshape(FRAME_COUNT, 2)
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
            self.expected_parts.append(plane_dfof)

    def tearDown(self):
        """Release temporary files after each test."""
        self.temporary_directory.cleanup()

    def plane_file(self, plane_index, suffix):
        """Return the canonical path of one fixture plane file.

        Args:
            plane_index (int): Plane number in the fixture (0 to 3).
            suffix (str): Filename suffix such as ``dFoF.npy``.

        Returns:
            Path: Fixture file path.
        """
        file_path = (
            self.suite2p_dir
            / f"plane{plane_index}"
            / f"{self.fish_id}_plane{plane_index}_{suffix}"
        )
        return file_path

    def test_merge_concatenates_in_plane_order(self):
        """The output should retain every ROI in plane order."""
        merge_result = merge_planes(self.experiment_dir, self.fish_id)
        expected_dfof = np.concatenate(self.expected_parts, axis=1)

        np.testing.assert_array_equal(merge_result["dfof"], expected_dfof)
        self.assertEqual(merge_result["dfof"].shape, (FRAME_COUNT, 10))
        self.assertEqual(
            merge_result["mapping"]["global_column"].tolist(),
            list(range(10)),
        )
        self.assertEqual(
            merge_result["mapping"]["plane"].tolist(),
            [f"plane{plane_index}" for plane_index in range(PLANE_COUNT) for _ in range(2)],
        )
        self.assertEqual(
            merge_result["mapping"]["filtered_roi_index"].tolist(),
            [0, 1, 10, 11, 20, 21, 30, 31, 40, 41],
        )

    def test_legacy_filenames_without_plane_are_supported(self):
        """Reference-pipeline files may omit the plane number from filenames."""
        legacy_dir = self.suite2p_dir / "plane0" / "dFoF"
        legacy_dir.mkdir()
        self.plane_file(0, "dFoF.npy").rename(legacy_dir / f"{self.fish_id}_dFoF.npy")
        self.plane_file(0, "filtered_roi_indices.npy").rename(
            legacy_dir / f"{self.fish_id}_filtered_roi_indices.npy"
        )

        merge_result = merge_planes(self.experiment_dir, self.fish_id)

        self.assertEqual(merge_result["dfof"].shape, (FRAME_COUNT, 10))
        self.assertEqual(
            Path(merge_result["mapping"].loc[0, "source_dfof_file"]).name,
            f"{self.fish_id}_dFoF.npy",
        )

    def test_all_discovers_planes_and_explicit_selection_uses_subset(self):
        """Automatic discovery and explicit plane subsets should both be supported."""
        self.assertEqual(
            discover_plane_indices(self.suite2p_dir),
            tuple(range(PLANE_COUNT)),
        )

        all_result = merge_planes(self.experiment_dir, self.fish_id, plane_indices="all")
        subset_result = merge_planes(
            self.experiment_dir,
            self.fish_id,
            plane_indices=[1, 2],
        )

        self.assertEqual(all_result["dfof"].shape, (FRAME_COUNT, 10))
        self.assertEqual(subset_result["dfof"].shape, (FRAME_COUNT, 4))
        self.assertEqual(subset_result["mapping"]["plane_index"].unique().tolist(), [1, 2])

    def test_invalid_plane_selectors_are_rejected(self):
        """Malformed, duplicated, and negative plane selections should fail."""
        with self.assertRaisesRegex(ValueError, "cannot contain duplicate"):
            merge_planes(self.experiment_dir, self.fish_id, plane_indices=[0, 0])
        with self.assertRaisesRegex(ValueError, "cannot contain negative"):
            merge_planes(self.experiment_dir, self.fish_id, plane_indices=[-1])
        with self.assertRaisesRegex(ValueError, 'must be "all"'):
            merge_planes(self.experiment_dir, self.fish_id, plane_indices="first_five")

    def test_missing_plane_raises_descriptive_error(self):
        """A missing dF/F file for a selected plane should stop the merge."""
        self.plane_file(2, "dFoF.npy").unlink()

        with self.assertRaisesRegex(FileNotFoundError, "Missing plane 2"):
            merge_planes(self.experiment_dir, self.fish_id)

    def test_roi_count_mismatch_raises_descriptive_error(self):
        """ROI provenance must contain exactly one entry per dF/F column."""
        np.save(self.plane_file(1, "filtered_roi_indices.npy"), np.array([1]))

        with self.assertRaisesRegex(ValueError, "ROI index count"):
            merge_planes(self.experiment_dir, self.fish_id)

    def test_missing_roi_index_file_skips_plane(self):
        """Without ROI indices a plane cannot be mapped, so it is left out."""
        self.plane_file(1, "filtered_roi_indices.npy").unlink()

        merge_result = merge_planes(self.experiment_dir, self.fish_id)

        self.assertEqual(merge_result["dfof"].shape, (FRAME_COUNT, 8))
        self.assertNotIn("plane1", merge_result["mapping"]["plane"].tolist())

    def test_plane_without_kept_rois_is_skipped(self):
        """A plane whose dF/F step kept zero ROIs should not stop the merge."""
        np.save(self.plane_file(3, "dFoF.npy"), np.empty((FRAME_COUNT, 0)))
        np.save(self.plane_file(3, "filtered_roi_indices.npy"), np.array([], dtype=int))

        merge_result = merge_planes(self.experiment_dir, self.fish_id)

        self.assertEqual(merge_result["dfof"].shape, (FRAME_COUNT, 8))
        self.assertNotIn("plane3", merge_result["mapping"]["plane"].tolist())

    def test_frame_count_mismatch_raises_naming_the_plane(self):
        """Planes of one recording must have equal frame counts; no truncation."""
        np.save(self.plane_file(2, "dFoF.npy"), np.zeros((FRAME_COUNT + 3, 2)))

        with self.assertRaisesRegex(ValueError, "Plane 2 has 11 frames"):
            merge_planes(self.experiment_dir, self.fish_id)

    def test_no_usable_plane_raises(self):
        """If every selected plane is skipped there is nothing to merge."""
        self.plane_file(0, "filtered_roi_indices.npy").unlink()

        with self.assertRaisesRegex(ValueError, "None of the selected planes"):
            merge_planes(self.experiment_dir, self.fish_id, plane_indices=[0])


if __name__ == "__main__":
    unittest.main()
