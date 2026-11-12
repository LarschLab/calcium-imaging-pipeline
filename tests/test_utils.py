"""Tests for reading the fish ID from a fish folder's name and staging files for ITK tools."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import SimpleITK as sitk

from preprocessing.spatial_preprocessing import write_registration_nrrd
from utils import fish_id_from_folder_name, itk_readable_paths, itk_safe_directory


class ItkStagingTest(unittest.TestCase):
    """ITK tools get ASCII paths; files still end up at their non-ASCII destination."""

    def test_readable_paths_copy_only_non_ascii_files(self):
        """ASCII paths pass through; non-ASCII files are copied to an ASCII staging path."""
        with tempfile.TemporaryDirectory() as temporary_directory, itk_safe_directory() as staging_directory:
            accented_file = Path(temporary_directory) / "Université" / "t.mat"
            accented_file.parent.mkdir()
            accented_file.write_bytes(b"transform")
            ascii_file = Path(temporary_directory) / "plain.mat"

            readable = itk_readable_paths([ascii_file, accented_file], staging_directory)

            self.assertEqual(readable[0], str(ascii_file))
            self.assertTrue(readable[1].isascii())
            self.assertEqual(Path(readable[1]).read_bytes(), b"transform")

    def test_write_registration_nrrd_under_accented_folder(self):
        """The canonical anatomy NRRD is written even under "Université"."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "Université" / "anatomy.nrrd"
            write_registration_nrrd(np.ones((2, 3, 4), dtype=np.uint8), output_path, (1.0, 1.0, 2.0))
            written = sitk.GetArrayFromImage(sitk.ReadImage(itk_readable_paths([output_path], Path(temporary_directory))[0]))
            self.assertEqual(written.shape, (2, 3, 4))


class FishIdFromFolderNameTest(unittest.TestCase):
    """Fish IDs are read from the start of the folder name, whatever follows."""

    def test_plain_fish_id_folder(self):
        """A folder named just by its fish ID returns that ID."""
        self.assertEqual(fish_id_from_folder_name("L676_f01"), "L676_f01")

    def test_folder_with_experiment_suffix(self):
        """An experiment suffix after the fish ID is ignored."""
        self.assertEqual(fish_id_from_folder_name("L433_f02_Exp_1_flickering"), "L433_f02")

    def test_multi_letter_prefix(self):
        """Prefixes with several letters (e.g. other users' fish) are accepted."""
        self.assertEqual(fish_id_from_folder_name("LC001_f05"), "LC001_f05")

    def test_name_without_fish_id_raises(self):
        """Folders that don't start with a fish ID are rejected."""
        for folder_name in ("L978_test", "0 new folder", "Microscopy"):
            with self.subTest(folder_name=folder_name), self.assertRaises(ValueError):
                fish_id_from_folder_name(folder_name)


if __name__ == "__main__":
    unittest.main()
