"""Tests for putting a fish's ROI table into the reference brain (no real transforms)."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import SimpleITK as sitk

from registration.batch_registration import roi_table_path
from registration.batch_roi_to_reference import (
    STATUS_DONE,
    STATUS_NO_FOLDER,
    STATUS_NO_ROI_TABLE,
    STATUS_NO_TRANSFORMS,
    STATUS_READY,
    canonical_anatomy_path,
    check_plane_depth_order,
    map_fish_rois_to_reference,
    reference_mapping_status,
    reference_roi_table_path,
    transform_metadata_path,
    write_reference_roi_table,
)

FISH_ID = "L000_f01"
REFERENCE_FISH_ID = "L000_f09"
REFERENCE_NAME = "ref_L000_f09"
SPACING_XYZ_UM = (0.5, 0.5, 2.0)
STACK_SHAPE_ZYX = (4, 10, 12)


def _touch(path):
    """Create an empty file and its folders.

    Args:
        path (Path): File to create.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def _write_canonical_anatomy(fish_folder, spacing_xyz_um):
    """Write a small canonical anatomy NRRD for a fake fish.

    Args:
        fish_folder (Path): The fake fish folder.
        spacing_xyz_um (tuple): Voxel size.
    """
    image = sitk.GetImageFromArray(np.zeros(STACK_SHAPE_ZYX, dtype=np.uint8))
    image.SetSpacing(spacing_xyz_um)
    anatomy_path = canonical_anatomy_path(fish_folder)
    anatomy_path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(image, str(anatomy_path))


class StatusTests(unittest.TestCase):
    def test_status_progression(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fish_folder = Path(temporary_directory) / f"{FISH_ID}_Exp_0"
            self.assertEqual(reference_mapping_status(None, FISH_ID, REFERENCE_NAME, REFERENCE_FISH_ID), STATUS_NO_FOLDER)
            fish_folder.mkdir()
            self.assertEqual(reference_mapping_status(fish_folder, FISH_ID, REFERENCE_NAME, REFERENCE_FISH_ID), STATUS_NO_ROI_TABLE)
            _touch(roi_table_path(fish_folder, FISH_ID))
            self.assertEqual(reference_mapping_status(fish_folder, FISH_ID, REFERENCE_NAME, REFERENCE_FISH_ID), STATUS_NO_TRANSFORMS)
            # The reference fish needs no transform.
            self.assertEqual(reference_mapping_status(fish_folder, FISH_ID, REFERENCE_NAME, FISH_ID), STATUS_READY)
            _touch(transform_metadata_path(fish_folder, FISH_ID, REFERENCE_NAME))
            self.assertEqual(reference_mapping_status(fish_folder, FISH_ID, REFERENCE_NAME, REFERENCE_FISH_ID), STATUS_READY)
            _touch(reference_roi_table_path(fish_folder, FISH_ID, REFERENCE_NAME))
            self.assertEqual(reference_mapping_status(fish_folder, FISH_ID, REFERENCE_NAME, REFERENCE_FISH_ID), STATUS_DONE)


class ReferenceFishTests(unittest.TestCase):
    def _write_reference_fish(self, temporary_directory, spacing_xyz_um):
        """Build a fake reference fish with two ROIs; return its folder."""
        fish_folder = Path(temporary_directory) / f"{REFERENCE_FISH_ID}_Exp_0"
        _write_canonical_anatomy(fish_folder, spacing_xyz_um)
        table_path = roi_table_path(fish_folder, REFERENCE_FISH_ID)
        table_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"fish_id": [REFERENCE_FISH_ID] * 2, "plane": [0, 1], "suite2p_index": [3, 8], "is_cell": [True, True],
                      "cell_probability": [0.9, 0.8], "x_canonical": [2.0, np.nan], "y_canonical": [4.0, np.nan],
                      "z_canonical": [1.0, np.nan]}).to_csv(table_path, index=False)
        return fish_folder

    def test_reference_fish_maps_onto_itself(self):
        reference_geometry = {"spacing_xyz_um": list(SPACING_XYZ_UM), "origin_xyz_um": [0.0, 0.0, 0.0]}
        with tempfile.TemporaryDirectory() as temporary_directory:
            fish_folder = self._write_reference_fish(temporary_directory, SPACING_XYZ_UM)
            reference_table, provenance = map_fish_rois_to_reference(fish_folder, REFERENCE_FISH_ID, reference_geometry, REFERENCE_NAME, REFERENCE_FISH_ID)
        np.testing.assert_allclose(reference_table.loc[0, ["x_ref_vox", "y_ref_vox", "z_ref_vox"]].to_numpy(float), [2.0, 4.0, 1.0])
        np.testing.assert_allclose(reference_table.loc[0, ["x_ref_um", "y_ref_um", "z_ref_um"]].to_numpy(float), [1.0, 2.0, 2.0])
        self.assertTrue(reference_table.loc[1, ["x_ref_um", "y_ref_um", "z_ref_um"]].isna().all())
        self.assertIn("identity", provenance["transform"])

    def test_reference_fish_on_another_grid_raises(self):
        reference_geometry = {"spacing_xyz_um": [0.6, 0.6, 2.0], "origin_xyz_um": [0.0, 0.0, 0.0]}
        with tempfile.TemporaryDirectory() as temporary_directory:
            fish_folder = self._write_reference_fish(temporary_directory, SPACING_XYZ_UM)
            with self.assertRaises(ValueError):
                map_fish_rois_to_reference(fish_folder, REFERENCE_FISH_ID, reference_geometry, REFERENCE_NAME, REFERENCE_FISH_ID)


class PlaneDepthOrderTests(unittest.TestCase):
    def test_flags_shared_and_out_of_order_depths(self):
        ordered = pd.DataFrame({"plane": [0, 0, 1, 2], "z_canonical": [30.0, 30.0, 26.0, 21.0]})
        shared = pd.DataFrame({"plane": [0, 1, 2], "z_canonical": [30.0, 30.0, 21.0]})
        shuffled = pd.DataFrame({"plane": [0, 1, 2], "z_canonical": [52.0, 25.0, 35.0]})
        self.assertEqual(check_plane_depth_order(ordered),
                         {"plane_depths": "0:30 1:26 2:21", "duplicate_plane_depths": False, "plane_depths_out_of_order": False})
        self.assertTrue(check_plane_depth_order(shared)["duplicate_plane_depths"])
        self.assertTrue(check_plane_depth_order(shuffled)["plane_depths_out_of_order"])


class WriteTableTests(unittest.TestCase):
    def test_writes_table_and_sidecar_but_never_overwrites(self):
        reference_table = pd.DataFrame({"fish_id": [FISH_ID], "x_ref_vox": [1.0], "y_ref_vox": [np.nan], "z_ref_vox": [2.0]})
        with tempfile.TemporaryDirectory() as temporary_directory:
            table_path = reference_roi_table_path(Path(temporary_directory) / FISH_ID, FISH_ID, REFERENCE_NAME)
            write_reference_roi_table(reference_table, table_path, {"fish_id": FISH_ID})
            metadata = json.loads(table_path.with_name(f"{table_path.stem}_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["n_rois_without_position"], 1)
            with self.assertRaises(FileExistsError):
                write_reference_roi_table(reference_table, table_path, {"fish_id": FISH_ID})


if __name__ == "__main__":
    unittest.main()
