"""Tests for the NCC-placed ANTs plane-to-anatomy registration."""

import json
import tempfile
import unittest
from pathlib import Path

import ants
import numpy as np
from skimage.transform import resize

from preprocessing.spatial_preprocessing import (
    ACQUISITION_XY_FRAME,
    CANONICAL_XY_FRAME,
    REGISTRATION_Z_FRAME,
    canonical_manifest_path,
)
from registration.image_utils import norm01
from registration.plane_matching import scale_image
from registration.plane_registration import (
    PREPROCESSING_METADATA_DIR,
    _ants_image_from_array,
    _build_roi_label_image,
    _place_on_canvas,
    _square_around_placement,
    read_functional_xy_frame,
    register_plane_to_anatomy,
    warp_roi_masks_to_anatomy,
    write_registration_metadata,
)

ANATOMY_SIZE = 200
PIXEL_SIZE_UM = 1.0
BLOB_COUNT = 60
BLOB_WIDTH_SQUARED = 12.0
RANDOM_SEED = 0
# The functional patch is cut far from the (0, 0) corner, so an unseeded
# registration would have to travel a long way to find it.
TRUE_ROW = 110
TRUE_COL = 20
CROP_SIZE = 80
# The functional plane is acquired at a higher zoom: the crop is enlarged
# by 1 / TRUE_SCALE, so resizing it by TRUE_SCALE maps it back.
TRUE_SCALE = 0.8
PLACEMENT_TOLERANCE_PX = 2
MIN_POST_NCC = 0.8
VALID_FRACTION_TOLERANCE = 0.02
# Square ROI in reference-image pixels.
ROI_ROW_START = 40
ROI_COL_START = 30
ROI_SIZE = 10


def _build_synthetic_anatomy_slice():
    """Build a synthetic anatomy slice made of random Gaussian blobs.

    Returns:
        numpy.ndarray: Float32 image, shaped (ANATOMY_SIZE, ANATOMY_SIZE).
    """
    random_generator = np.random.default_rng(RANDOM_SEED)
    anatomy_slice = np.zeros((ANATOMY_SIZE, ANATOMY_SIZE), dtype=np.float32)
    row_grid, col_grid = np.ogrid[:ANATOMY_SIZE, :ANATOMY_SIZE]
    for center_row, center_col in random_generator.integers(5, ANATOMY_SIZE - 5, size=(BLOB_COUNT, 2)):
        distance_squared = (row_grid - center_row) ** 2 + (col_grid - center_col) ** 2
        anatomy_slice += np.exp(-distance_squared / BLOB_WIDTH_SQUARED)
    return anatomy_slice


def _build_reference_image(anatomy_slice):
    """Crop the known patch out of the anatomy and enlarge it like a zoomed functional plane.

    Args:
        anatomy_slice (numpy.ndarray): Synthetic anatomy slice.

    Returns:
        numpy.ndarray: Float32 reference image, shaped
        (CROP_SIZE / TRUE_SCALE, CROP_SIZE / TRUE_SCALE).
    """
    cropped = anatomy_slice[TRUE_ROW : TRUE_ROW + CROP_SIZE, TRUE_COL : TRUE_COL + CROP_SIZE]
    enlarged_size = round(CROP_SIZE / TRUE_SCALE)
    reference_image = resize(cropped, (enlarged_size, enlarged_size), order=1, preserve_range=True, anti_aliasing=True).astype(np.float32)
    return reference_image


def _square_roi(row_start, col_start, size):
    """Build a suite2p-style ROI dict covering a square of pixels.

    Args:
        row_start (int): Top row of the square.
        col_start (int): Left column of the square.
        size (int): Side length, in pixels.

    Returns:
        dict: ROI with `xpix`, `ypix` and an all-False `overlap`.
    """
    rows, cols = np.mgrid[row_start : row_start + size, col_start : col_start + size]
    roi = {"ypix": rows.ravel(), "xpix": cols.ravel(), "overlap": np.zeros(rows.size, dtype=bool)}
    return roi


class PlaneRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.output_dir = Path(cls.temporary_directory.name)
        cls.anatomy_slice = _build_synthetic_anatomy_slice()
        cls.reference_image = _build_reference_image(cls.anatomy_slice)
        cls.registration = register_plane_to_anatomy(
            cls.reference_image, cls.anatomy_slice, PIXEL_SIZE_UM, TRUE_SCALE, cls.output_dir / "run_a_"
        )

    @classmethod
    def tearDownClass(cls):
        cls.temporary_directory.cleanup()

    def test_ncc_placement_and_fit_recover_known_patch(self):
        placement = self.registration["ncc_placement"]

        self.assertAlmostEqual(placement["x0"], TRUE_COL, delta=PLACEMENT_TOLERANCE_PX)
        self.assertAlmostEqual(placement["y0"], TRUE_ROW, delta=PLACEMENT_TOLERANCE_PX)
        self.assertGreater(self.registration["post_ncc"], MIN_POST_NCC)
        # The placement is already exact here, so ANTs should keep (not
        # worsen) the fit measured by the same score.
        self.assertGreater(self.registration["pre_ants_ncc"], MIN_POST_NCC)
        self.assertGreaterEqual(self.registration["post_ncc"], self.registration["pre_ants_ncc"] - 0.01)
        # The valid region is the plane's footprint on the anatomy canvas.
        expected_valid_fraction = CROP_SIZE**2 / ANATOMY_SIZE**2
        self.assertAlmostEqual(self.registration["valid_fraction"], expected_valid_fraction, delta=VALID_FRACTION_TOLERANCE)

    def test_roi_lands_at_its_true_anatomy_position(self):
        stat_array = np.array([_square_roi(ROI_ROW_START, ROI_COL_START, ROI_SIZE)], dtype=object)

        warped_rois = warp_roi_masks_to_anatomy(stat_array, self.registration, self.reference_image.shape, best_depth=0)

        # Pixel-centre mapping of the ROI centre through the resize by
        # TRUE_SCALE, then the patch offset in the anatomy.
        roi_center_row = ROI_ROW_START + (ROI_SIZE - 1) / 2
        roi_center_col = ROI_COL_START + (ROI_SIZE - 1) / 2
        expected_row = TRUE_ROW + (roi_center_row + 0.5) * TRUE_SCALE - 0.5
        expected_col = TRUE_COL + (roi_center_col + 0.5) * TRUE_SCALE - 0.5
        median_row, median_col = warped_rois[0]["med_aligned"]
        self.assertAlmostEqual(median_row, expected_row, delta=PLACEMENT_TOLERANCE_PX)
        self.assertAlmostEqual(median_col, expected_col, delta=PLACEMENT_TOLERANCE_PX)

    def test_square_matches_danins_region_and_stays_on_canvas(self):
        # 80 px plane, 10% margin -> 88 px square centred on the plane's centre (60, 150).
        self.assertEqual(_square_around_placement(20, 110, (80, 80), (200, 200), 0.10), (16, 106, 104, 194))
        # Near the top-right corner the square is shifted inward, not cropped.
        self.assertEqual(_square_around_placement(150, 0, (80, 80), (200, 200), 0.10), (112, 0, 200, 88))

    def test_registration_uses_square_around_its_placement(self):
        placement = self.registration["ncc_placement"]

        expected_square = _square_around_placement(placement["x0"], placement["y0"], placement["source_shape"], placement["canvas_shape"], 0.10)
        self.assertEqual(self.registration["fixed_region_xyxy"], expected_square)

    def test_fixed_random_seed_makes_runs_identical(self):
        second_registration = register_plane_to_anatomy(
            self.reference_image, self.anatomy_slice, PIXEL_SIZE_UM, TRUE_SCALE, self.output_dir / "run_b_"
        )

        first_parameters = ants.read_transform(self.registration["transformlist"][0]).parameters
        second_parameters = ants.read_transform(second_registration["transformlist"][0]).parameters
        np.testing.assert_array_equal(first_parameters, second_parameters)

    def test_transformlist_reproduces_ants_warped_image(self):
        # Start the plane a few pixels off, so the Rigid stage has a real
        # correction to make; applying it twice would then show up.
        shifted_reference = np.roll(self.reference_image, (4, -3), axis=(0, 1))
        registration = register_plane_to_anatomy(shifted_reference, self.anatomy_slice, PIXEL_SIZE_UM, TRUE_SCALE, self.output_dir / "shifted_")
        placement = registration["ncc_placement"]
        moving_source = norm01(scale_image(shifted_reference, TRUE_SCALE), 5, 95)
        moving_canvas = _place_on_canvas(moving_source, placement["canvas_shape"], placement["x0"], placement["y0"])

        warped = ants.apply_transforms(
            fixed=_ants_image_from_array(registration["fixed_image"], PIXEL_SIZE_UM),
            moving=_ants_image_from_array(moving_canvas, PIXEL_SIZE_UM),
            transformlist=registration["transformlist"],
        ).numpy()

        self.assertEqual(len(registration["transformlist"]), 1)
        # ANTs should fix the small shift, not pull the plane to a wrong fit.
        self.assertGreater(registration["post_ncc"], MIN_POST_NCC)
        valid = registration["warped_image"] != 0
        np.testing.assert_allclose(warped[valid], registration["warped_image"][valid], atol=1e-4)

    def test_registration_metadata_records_match_sources_and_roi_counts(self):
        stat_array = np.array([_square_roi(ROI_ROW_START, ROI_COL_START, ROI_SIZE), {"ypix": np.array([0]), "xpix": np.array([999])}], dtype=object)
        warped_rois = warp_roi_masks_to_anatomy(stat_array, self.registration, self.reference_image.shape, best_depth=0)
        match = {"best_z": 0, "best_z_subslice": 0.2, "scale": TRUE_SCALE, "score": np.float32(0.9),
                 "scores": np.array([0.9], dtype=np.float32), "params": {"scale_start": 0.5}}
        metadata_path = self.output_dir / "registration_metadata.json"

        write_registration_metadata(self.registration, match, stat_array, warped_rois, {"anatomy_path": "anatomy.tif"}, "L000_f00", metadata_path)
        metadata = json.loads(metadata_path.read_text())

        self.assertEqual(metadata["sources"]["anatomy_path"], "anatomy.tif")
        self.assertEqual(metadata["match"]["scale"], TRUE_SCALE)
        self.assertEqual(metadata["rois"], {"in_suite2p": 2, "warped": 1, "skipped_out_of_bounds": 1, "empty_after_warp": 0})
        self.assertFalse(metadata["ants_lowered_fit"])

    def test_label_image_excludes_overlap_pixels_and_skips_bad_rois(self):
        first_roi = _square_roi(0, 0, 4)
        second_roi = _square_roi(0, 2, 4)
        # Columns 2-3 are shared by both squares; suite2p flags them.
        first_roi["overlap"] = first_roi["xpix"] >= 2
        second_roi["overlap"] = second_roi["xpix"] <= 3
        out_of_bounds_roi = {"ypix": np.array([0]), "xpix": np.array([50])}
        stat_array = np.array([first_roi, second_roi, out_of_bounds_roi], dtype=object)

        label_image, kept_roi_indices = _build_roi_label_image(stat_array, (10, 10))

        self.assertEqual(kept_roi_indices, [0, 1])
        self.assertTrue(np.all(label_image[:4, 2:4] == 0))
        self.assertTrue(np.all(label_image[:4, :2] == 1))
        self.assertTrue(np.all(label_image[:4, 4:6] == 2))


class FunctionalXyFrameTests(unittest.TestCase):
    def test_fish_without_preprocessing_record_is_assumed_unflipped(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            xy_frame, source = read_functional_xy_frame(Path(temporary_directory) / "L000_f00")

        self.assertEqual(xy_frame, ACQUISITION_XY_FRAME)
        self.assertIn("assumed", source)

    def test_preprocessing_metadata_frame_is_read(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fish_dir = Path(temporary_directory) / "L000_f00"
            metadata_dir = fish_dir / PREPROCESSING_METADATA_DIR
            metadata_dir.mkdir(parents=True)
            (metadata_dir / "L000_f00_preprocessing_metadata.json").write_text(json.dumps({"output_xy_frame": CANONICAL_XY_FRAME}))

            xy_frame, _ = read_functional_xy_frame(fish_dir)

        self.assertEqual(xy_frame, CANONICAL_XY_FRAME)

    def test_canonical_manifest_means_flipped(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fish_dir = Path(temporary_directory) / "L000_f00"
            manifest_path = canonical_manifest_path(fish_dir)
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(json.dumps({
                "stage": "canonical_spatial_preprocessing",
                "status": "complete",
                "coordinate_frames": {
                    "canonical_functional_xy": CANONICAL_XY_FRAME,
                    "canonical_anatomy_xy": CANONICAL_XY_FRAME,
                    "canonical_anatomy_z": REGISTRATION_Z_FRAME,
                },
            }))

            xy_frame, source = read_functional_xy_frame(fish_dir)

        self.assertEqual(xy_frame, CANONICAL_XY_FRAME)
        self.assertEqual(source, str(manifest_path))


if __name__ == "__main__":
    unittest.main()
