"""Tests for mapping registered ROIs into the canonical anatomy NRRD's voxels."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import SimpleITK as sitk
import tifffile

from preprocessing.spatial_preprocessing import preprocess_anatomy
from registration.roi_to_reference import convert_rois_to_canonical_space

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


if __name__ == "__main__":
    unittest.main()
