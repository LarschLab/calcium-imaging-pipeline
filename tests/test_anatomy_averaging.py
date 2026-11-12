"""Tests for classifying anatomy stacks and averaging their repeated frames per depth."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import tifffile

from preprocessing.anatomy_averaging import (
    STATUS_ALREADY_AVERAGED,
    STATUS_NEEDS_AVERAGING,
    STATUS_REVIEW,
    average_page_group,
    averaged_output_name,
    classify_stack,
    copy_without_overwrite,
    write_averaged_stack,
)
from registration.image_utils import read_pixel_size_um

NUM_DEPTHS = 3
FRAMES_PER_DEPTH = 4
PAGE_SHAPE = (8, 6)
PIXELS_PER_CM = 16215  # ~0.617 um pixels, as in the real anatomy stacks
CENTIMETER_UNIT = 3


def _header(n_pages, num_slices=NUM_DEPTHS, frames_per_slice=FRAMES_PER_DEPTH, log_average_factor=1, n_channels=1, num_volumes=1):
    """Build a header dict like `read_stack_header` returns.

    Returns:
        dict: Minimal header for `classify_stack`.
    """
    return {"n_pages": n_pages, "num_slices": num_slices, "frames_per_slice": frames_per_slice,
            "log_average_factor": log_average_factor, "n_channels": n_channels, "num_volumes": num_volumes}


class ClassifyStackTest(unittest.TestCase):
    """The header plus the page count decide what to do with a stack."""

    def test_scanimage_averaged_stack(self):
        """logAverageFactor == framesPerSlice and one page per depth -> copy as is."""
        status, frames, _ = classify_stack(_header(NUM_DEPTHS, log_average_factor=FRAMES_PER_DEPTH))
        self.assertEqual((status, frames), (STATUS_ALREADY_AVERAGED, 1))

    def test_all_frames_stack(self):
        """No ScanImage averaging and N pages per depth -> average N frames."""
        status, frames, _ = classify_stack(_header(NUM_DEPTHS * FRAMES_PER_DEPTH))
        self.assertEqual((status, frames), (STATUS_NEEDS_AVERAGING, FRAMES_PER_DEPTH))

    def test_page_count_mismatch_needs_review(self):
        """An aborted stack (fewer pages than the header predicts) is not guessed."""
        status, frames, _ = classify_stack(_header(NUM_DEPTHS * FRAMES_PER_DEPTH - 1))
        self.assertEqual((status, frames), (STATUS_REVIEW, None))

    def test_two_channels_need_review(self):
        """Interleaved channels would be averaged together, so they are flagged."""
        status, _, _ = classify_stack(_header(2 * NUM_DEPTHS * FRAMES_PER_DEPTH, n_channels=2))
        self.assertEqual(status, STATUS_REVIEW)

    def test_missing_header_needs_review(self):
        """A file without a ScanImage header is flagged."""
        status, _, _ = classify_stack(_header(NUM_DEPTHS, frames_per_slice=None))
        self.assertEqual(status, STATUS_REVIEW)


class AveragingTest(unittest.TestCase):
    """Averaging keeps every depth separate, the dtype, and the pixel size."""

    def test_average_page_group_rounds_to_source_dtype(self):
        """The mean of int16 frames is rounded and stays int16."""
        pages = [np.full(PAGE_SHAPE, value, dtype=np.int16) for value in (-3, 0, 1, 4)]
        averaged = average_page_group(pages)
        self.assertEqual(averaged.dtype, np.int16)
        self.assertTrue(np.all(averaged == 0))  # mean 0.5 rounds to 0 (round half to even)

    def test_write_averaged_stack_averages_each_depth_separately(self):
        """Each output page is the mean of its own depth's consecutive frames, with the pixel size kept."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "L000_f01_anatomy_00001.tif"
            # Depth d's frames hold values 100*d + 0..N-1, so its mean is 100*d + (N-1)/2.
            frames = [np.full(PAGE_SHAPE, 100 * depth + frame, dtype=np.int16)
                      for depth in range(NUM_DEPTHS) for frame in range(FRAMES_PER_DEPTH)]
            tifffile.imwrite(source_path, np.stack(frames), resolution=(PIXELS_PER_CM, PIXELS_PER_CM), resolutionunit=CENTIMETER_UNIT)
            header = {"x_resolution": (PIXELS_PER_CM, 1), "resolution_unit": CENTIMETER_UNIT}
            output_path = Path(temporary_directory) / averaged_output_name(source_path)

            write_averaged_stack(source_path, output_path, FRAMES_PER_DEPTH, NUM_DEPTHS, header)

            averaged = tifffile.imread(output_path)
            expected_means = [np.rint(100 * depth + (FRAMES_PER_DEPTH - 1) / 2) for depth in range(NUM_DEPTHS)]
            self.assertEqual(averaged.shape, (NUM_DEPTHS, *PAGE_SHAPE))
            np.testing.assert_array_equal(averaged[:, 0, 0], expected_means)
            self.assertAlmostEqual(read_pixel_size_um(output_path), read_pixel_size_um(source_path), places=6)
            self.assertFalse(output_path.with_name(output_path.name + ".partial").exists())

    def test_write_averaged_stack_averages_only_the_chosen_pass(self):
        """With two passes saved back to back, only the requested pass's frames are averaged."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "L000_f06_anatomy_00002.tif"
            # Pass p, depth d holds 1000*p + 100*d; frames within a depth are identical.
            frames = [np.full(PAGE_SHAPE, 1000 * volume + 100 * depth, dtype=np.int16)
                      for volume in range(2) for depth in range(NUM_DEPTHS) for _ in range(FRAMES_PER_DEPTH)]
            tifffile.imwrite(source_path, np.stack(frames))
            header = {"x_resolution": None}
            for volume_index in (0, 1):
                output_path = Path(temporary_directory) / f"pass{volume_index}.tif"
                write_averaged_stack(source_path, output_path, FRAMES_PER_DEPTH, NUM_DEPTHS, header, num_volumes=2, volume_index=volume_index)
                expected = [1000 * volume_index + 100 * depth for depth in range(NUM_DEPTHS)]
                np.testing.assert_array_equal(tifffile.imread(output_path)[:, 0, 0], expected)

    def test_write_averaged_stack_refuses_to_overwrite(self):
        """An existing output is never replaced."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "existing.tif"
            output_path.write_bytes(b"keep me")
            with self.assertRaises(FileExistsError):
                write_averaged_stack(output_path, output_path, FRAMES_PER_DEPTH, NUM_DEPTHS, {"x_resolution": None})
            self.assertEqual(output_path.read_bytes(), b"keep me")

    def test_averaged_output_name_keeps_source_stem(self):
        """The averaged file is named after its source."""
        self.assertEqual(averaged_output_name(Path("x/L800_f09-anatomy_00001.tif")), "L800_f09-anatomy_00001_averaged.tif")


class CopyTest(unittest.TestCase):
    """Copies are complete and never overwrite."""

    def test_copy_without_overwrite(self):
        """A new file is copied; copying onto it again is refused."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "source.tif"
            source_path.write_bytes(b"anatomy")
            destination_path = Path(temporary_directory) / "copy.tif"
            copy_without_overwrite(source_path, destination_path)
            self.assertEqual(destination_path.read_bytes(), b"anatomy")
            with self.assertRaises(FileExistsError):
                copy_without_overwrite(source_path, destination_path)


if __name__ == "__main__":
    unittest.main()
