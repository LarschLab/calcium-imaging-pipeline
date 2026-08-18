"""Tests for the plane-to-anatomy matching primitives."""

import unittest

import numpy as np
from skimage.transform import resize

from registration.plane_matching import match_plane_to_anatomy, refine_peak_depth

ANATOMY_DEPTH = 12
ANATOMY_HEIGHT = 120
ANATOMY_WIDTH = 120
TRUE_DEPTH = 7
TRUE_SCALE = 1.2
TRUE_X = 20
TRUE_Y = 30
CROP_HEIGHT = 60
CROP_WIDTH = 60
RANDOM_SEED = 0


def _build_synthetic_anatomy_stack():
    """Build a small synthetic anatomy volume with a handful of blobs.

    Each depth gets its own random blob layout so the correct depth is
    distinguishable from its neighbors, mimicking real anatomy stacks where
    structure changes gradually across Z.

    Returns:
        numpy.ndarray: Anatomy volume, shaped
        (ANATOMY_DEPTH, ANATOMY_HEIGHT, ANATOMY_WIDTH).
    """
    random_generator = np.random.default_rng(RANDOM_SEED)
    anatomy_stack = np.zeros((ANATOMY_DEPTH, ANATOMY_HEIGHT, ANATOMY_WIDTH), dtype=np.float32)
    for depth_index in range(ANATOMY_DEPTH):
        blob_centers = random_generator.integers(10, ANATOMY_HEIGHT - 10, size=(15, 2))
        for center_row, center_col in blob_centers:
            row_grid, col_grid = np.ogrid[:ANATOMY_HEIGHT, :ANATOMY_WIDTH]
            distance_squared = (row_grid - center_row) ** 2 + (col_grid - center_col) ** 2
            anatomy_stack[depth_index] += np.exp(-distance_squared / 20.0)
    return anatomy_stack


def _build_synthetic_reference_image(anatomy_stack):
    """Crop, resize, and shift a known anatomy slice into a reference image.

    Args:
        anatomy_stack (numpy.ndarray): Synthetic anatomy volume built by
            `_build_synthetic_anatomy_stack`.

    Returns:
        numpy.ndarray: Reference image derived from slice `TRUE_DEPTH` of
        `anatomy_stack`, cropped at `(TRUE_Y, TRUE_X)` and resized by
        `TRUE_SCALE`.
    """
    true_slice = anatomy_stack[TRUE_DEPTH]
    cropped = true_slice[TRUE_Y : TRUE_Y + CROP_HEIGHT, TRUE_X : TRUE_X + CROP_WIDTH]
    resized_shape = (round(CROP_HEIGHT * TRUE_SCALE), round(CROP_WIDTH * TRUE_SCALE))
    return resize(cropped, resized_shape, order=1, preserve_range=True, anti_aliasing=True).astype(np.float32)


class PlaneMatchingTests(unittest.TestCase):
    def test_match_plane_to_anatomy_recovers_known_depth_scale_and_position(self):
        anatomy_stack = _build_synthetic_anatomy_stack()
        reference_image = _build_synthetic_reference_image(anatomy_stack)

        # `reference_image` was cropped out of the true slice and then
        # enlarged by `TRUE_SCALE`, so matching it back needs to undo that
        # enlargement: the recovered scale should land near 1 / TRUE_SCALE
        # (~0.83), which the default scale range brackets.
        match = match_plane_to_anatomy(reference_image, anatomy_stack)

        self.assertEqual(match["best_depth"], TRUE_DEPTH)
        self.assertAlmostEqual(match["best_depth_subslice"], TRUE_DEPTH, delta=0.6)
        self.assertAlmostEqual(match["scale"], 1.0 / TRUE_SCALE, delta=0.1)
        self.assertAlmostEqual(match["x"], TRUE_X, delta=3)
        self.assertAlmostEqual(match["y"], TRUE_Y, delta=3)

    def test_refine_peak_depth_recovers_known_non_integer_peak(self):
        # Samples of the parabola f(i) = 1 - (i - 2.25) ** 2, whose true
        # peak sits at the non-integer index 2.25.
        scores = np.array([-4.0625, -0.5625, 0.9375, 0.4375, -2.0625])

        peak_depth = refine_peak_depth(scores)

        self.assertAlmostEqual(peak_depth, 2.25, delta=1e-6)

    def test_refine_peak_depth_falls_back_to_integer_index_at_boundary(self):
        scores = np.array([0.9, 0.5, 0.2, 0.1])

        peak_depth = refine_peak_depth(scores)

        self.assertEqual(peak_depth, 0.0)


if __name__ == "__main__":
    unittest.main()
