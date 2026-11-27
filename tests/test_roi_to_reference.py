"""Tests for mapping registered ROIs into the canonical anatomy and the reference brain."""

import json
import tempfile
import unittest
from pathlib import Path

import ants
import numpy as np
import pandas as pd
import SimpleITK as sitk
import tifffile

from preprocessing.spatial_preprocessing import preprocess_anatomy
from registration.roi_to_reference import (
    apply_reference_transform_to_points,
    build_reference_roi_table,
    convert_rois_to_canonical_space,
    read_nrrd_geometry,
    read_point_transform_files,
    um_to_voxels,
    voxels_to_um,
)

ANATOMY_SHAPE_ZYX = (6, 64, 48)
TARGET_XY_SHAPE = (94, 70)
PIXEL_SIZE_UM = 1.0
Z_STEP_UM = 2.0
ROI_VOXEL_ZYX = (1, 10, 35)
BRIGHT_VALUE = 3000
# The bright voxel spreads over neighbours when upsampled; its peak should
# still fall within this distance of the converted coordinate.
PEAK_TOLERANCE_PX = 1.0


def _single_voxel_roi():
    """Build one warped ROI made of the single voxel `ROI_VOXEL_ZYX`.

    Returns:
        dict: ROI with `xpix_aligned`, `ypix_aligned` and `z_pix`.
    """
    z, y, x = ROI_VOXEL_ZYX
    roi = {"xpix_aligned": np.array([x]), "ypix_aligned": np.array([y]), "z_pix": np.array([z])}
    return roi


class ConvertRoisToCanonicalSpaceTests(unittest.TestCase):
    def test_converted_roi_lands_on_preprocess_anatomy_voxel(self):
        raw_stack = np.zeros(ANATOMY_SHAPE_ZYX, dtype=np.int16)
        raw_stack[ROI_VOXEL_ZYX] = BRIGHT_VALUE
        with tempfile.TemporaryDirectory() as temporary_directory:
            raw_path = Path(temporary_directory) / "anatomy.tif"
            tifffile.imwrite(raw_path, raw_stack)
            for polarity in ("north", "south"):
                with self.subTest(polarity=polarity):
                    nrrd_path = Path(temporary_directory) / f"canonical_{polarity}.nrrd"
                    preprocess_anatomy(anatomy_path=raw_path, output_path=nrrd_path, polarity=polarity,
                                       source_spacing_xyz_um=(PIXEL_SIZE_UM, PIXEL_SIZE_UM, Z_STEP_UM), target_xy_shape=TARGET_XY_SHAPE)
                    canonical_anatomy = sitk.GetArrayFromImage(sitk.ReadImage(str(nrrd_path)))
                    peak_z, peak_y, peak_x = np.unravel_index(np.argmax(canonical_anatomy), canonical_anatomy.shape)

                    canonical_rois = convert_rois_to_canonical_space([_single_voxel_roi()], ANATOMY_SHAPE_ZYX, polarity, TARGET_XY_SHAPE)

                    self.assertEqual(canonical_rois[0]["zpix_canonical"][0], peak_z)
                    self.assertAlmostEqual(canonical_rois[0]["ypix_canonical"][0], peak_y, delta=PEAK_TOLERANCE_PX)
                    self.assertAlmostEqual(canonical_rois[0]["xpix_canonical"][0], peak_x, delta=PEAK_TOLERANCE_PX)

    def test_missing_polarity_raises(self):
        with self.assertRaises(ValueError):
            convert_rois_to_canonical_space([_single_voxel_roi()], ANATOMY_SHAPE_ZYX, None)


NRRD_SPACING_XYZ_UM = (0.45, 0.45, 2.0)
NRRD_SIZE_XYZ = (8, 6, 4)
AFFINE_TRANSLATION_UM = np.array([3.0, -2.0, 5.0])
WARP_DISPLACEMENT_UM = np.array([1.0, 0.5, -1.0])
WARP_GRID_SHAPE = (20, 20, 20)
WARP_GRID_ORIGIN_UM = (-50.0, -50.0, -50.0)
WARP_GRID_SPACING_UM = (5.0, 5.0, 5.0)


def _write_point_transforms(directory):
    """Write a pure-translation affine and a constant inverse warp as ANTs files.

    Args:
        directory (Path): Where to write them.

    Returns:
        tuple: (affine path, inverse warp path).
    """
    affine = ants.create_ants_transform(transform_type="AffineTransform", dimension=3, translation=tuple(AFFINE_TRANSLATION_UM))
    affine_path = Path(directory) / "fish_2P_to_ref_0GenericAffine.mat"
    ants.write_transform(affine, str(affine_path))
    displacement = np.tile(WARP_DISPLACEMENT_UM, (*WARP_GRID_SHAPE, 1)).astype(np.float32)
    warp_image = ants.from_numpy(displacement, origin=WARP_GRID_ORIGIN_UM, spacing=WARP_GRID_SPACING_UM, has_components=True)
    inverse_warp_path = Path(directory) / "fish_2P_to_ref_1InverseWarp.nii.gz"
    ants.image_write(warp_image, str(inverse_warp_path))
    return affine_path, inverse_warp_path


class NrrdGeometryTests(unittest.TestCase):
    def test_reads_spacing_origin_and_size_of_a_simpleitk_nrrd(self):
        image = sitk.GetImageFromArray(np.zeros(NRRD_SIZE_XYZ[::-1], dtype=np.uint8))
        image.SetSpacing(NRRD_SPACING_XYZ_UM)
        with tempfile.TemporaryDirectory() as temporary_directory:
            nrrd_path = Path(temporary_directory) / "anatomy.nrrd"
            sitk.WriteImage(image, str(nrrd_path))
            geometry = read_nrrd_geometry(nrrd_path)
        np.testing.assert_allclose(geometry["spacing_xyz_um"], NRRD_SPACING_XYZ_UM)
        np.testing.assert_allclose(geometry["origin_xyz_um"], (0, 0, 0))
        self.assertEqual(geometry["size_xyz"], list(NRRD_SIZE_XYZ))

    def test_voxels_and_micrometres_round_trip(self):
        geometry = {"spacing_xyz_um": [0.5, 0.25, 2.0], "origin_xyz_um": [1.0, 0.0, -2.0]}
        voxels = np.array([[10.0, 4.0, 3.0], [np.nan, 1.0, 1.0]])
        points_um = voxels_to_um(voxels, geometry)
        np.testing.assert_allclose(points_um[0], [6.0, 1.0, 4.0])
        np.testing.assert_allclose(um_to_voxels(points_um, geometry), voxels)


class PointTransformTests(unittest.TestCase):
    def test_point_transform_files_follow_the_metadata(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            metadata_path = Path(temporary_directory) / "fish_2P_to_ref_metadata.json"
            metadata_path.write_text(json.dumps({"transforms": {"points_to_ref": ["[fish_0GenericAffine.mat,1]", "fish_1InverseWarp.nii.gz"]}}))
            transform_files = read_point_transform_files(metadata_path)
        self.assertEqual(transform_files["affine_path"].name, "fish_0GenericAffine.mat")
        self.assertEqual(transform_files["inverse_warp_path"].name, "fish_1InverseWarp.nii.gz")

    def test_unexpected_point_order_raises(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            metadata_path = Path(temporary_directory) / "fish_2P_to_ref_metadata.json"
            metadata_path.write_text(json.dumps({"transforms": {"points_to_ref": ["fish_1Warp.nii.gz", "fish_0GenericAffine.mat"]}}))
            with self.assertRaises(ValueError):
                read_point_transform_files(metadata_path)

    def test_points_get_inverted_affine_and_inverse_warp(self):
        points_um = np.array([[10.0, 20.0, 1.0], [np.nan, 0.0, 0.0], [0.0, 0.0, 0.0]])
        with tempfile.TemporaryDirectory() as temporary_directory:
            affine_path, inverse_warp_path = _write_point_transforms(temporary_directory)
            moved_points = apply_reference_transform_to_points(points_um, affine_path, inverse_warp_path)
        # Inverted translation affine subtracts t; the inverse warp adds its displacement.
        expected_points = points_um - AFFINE_TRANSLATION_UM + WARP_DISPLACEMENT_UM
        np.testing.assert_allclose(moved_points[[0, 2]], expected_points[[0, 2]], atol=1e-4)
        self.assertTrue(np.isnan(moved_points[1]).all())


class BuildReferenceRoiTableTests(unittest.TestCase):
    def test_table_keeps_identity_and_adds_reference_positions(self):
        roi_table = pd.DataFrame({"fish_id": ["L1_f01"] * 2, "plane": [0, 1], "suite2p_index": [4, 7], "is_cell": [True, False],
                                  "x_canonical": [1.0, 2.0], "y_canonical": [3.0, 4.0], "z_canonical": [5.0, 6.0]})
        points_in_reference_um = np.array([[1.0, 2.0, 4.0], [np.nan, np.nan, np.nan]])
        reference_geometry = {"spacing_xyz_um": [0.5, 0.5, 2.0], "origin_xyz_um": [0.0, 0.0, 0.0]}
        reference_table = build_reference_roi_table(roi_table, points_in_reference_um, reference_geometry)
        self.assertEqual(reference_table["suite2p_index"].tolist(), [4, 7])
        np.testing.assert_allclose(reference_table.loc[0, ["x_ref_vox", "y_ref_vox", "z_ref_vox"]].to_numpy(float), [2.0, 4.0, 2.0])
        self.assertTrue(reference_table.loc[1, ["x_ref_um", "y_ref_um", "z_ref_um"]].isna().all())
        np.testing.assert_allclose(reference_table["z_canonical"], [5.0, 6.0])

    def test_row_count_mismatch_raises(self):
        roi_table = pd.DataFrame({"x_canonical": [1.0], "y_canonical": [1.0], "z_canonical": [1.0]})
        with self.assertRaises(ValueError):
            build_reference_roi_table(roi_table, np.zeros((2, 3)), {"spacing_xyz_um": [1, 1, 1], "origin_xyz_um": [0, 0, 0]})


if __name__ == "__main__":
    unittest.main()
