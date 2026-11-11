"""Tests for the anatomy-only mode of the canonical preprocessing."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import SimpleITK as sitk
import tifffile

from preprocessing.canonical_preprocessing import batch_canonical_anatomy, canonical_anatomy_path
from preprocessing.spatial_preprocessing import preprocess_anatomy


def write_fake_raw_fish(fish_folder, orientation="north"):
    """Write a raw anatomy TIFF and a metadata CSV for one fake fish.

    Args:
        fish_folder (Path): Fish folder to create.
        orientation (str or None): `fish_orientation` written to the metadata; None leaves it out.

    Returns:
        Path: The raw anatomy TIFF.
    """
    anatomy_dir = fish_folder / "01_raw" / "2p" / "anatomy"
    metadata_dir = fish_folder / "01_raw" / "2p" / "metadata"
    anatomy_dir.mkdir(parents=True)
    metadata_dir.mkdir(parents=True)
    anatomy_tiff = anatomy_dir / f"{fish_folder.name}_anatomy.tif"
    stack = np.random.default_rng(0).integers(0, 4000, size=(6, 40, 48)).astype(np.uint16)
    tifffile.imwrite(anatomy_tiff, stack, photometric="minisblack")
    rows = ["pixel_size_um_anatomy,0.8", "step_size_um_anatomy,2"]
    if orientation is not None:
        rows.append(f"fish_orientation,{orientation}")
    (metadata_dir / f"{fish_folder.name}_metadata.csv").write_text("\n".join(rows))
    return anatomy_tiff


class CanonicalAnatomyOnlyTests(unittest.TestCase):
    def test_anatomy_only_writes_nrrd_and_sidecar_and_never_overwrites(self):
        """The NRRD matches preprocess_anatomy, gets a sidecar, and a rerun changes nothing.

        Returns:
            None: The test passes if all assertions hold; otherwise it
            raises an assertion error.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fish_folder = root / "L500_f01"
            anatomy_tiff = write_fake_raw_fish(fish_folder, orientation="north")

            # A missing fish is skipped with a warning; the other one is processed.
            written = batch_canonical_anatomy(root, ["L500_f01", "L999_f99"], target_xy_shape=(32, 32))
            self.assertEqual(list(written), ["L500_f01"])

            nrrd_path = canonical_anatomy_path(fish_folder)
            expected_path = root / "expected.nrrd"
            preprocess_anatomy(anatomy_path=anatomy_tiff, output_path=expected_path, polarity="north",
                               source_spacing_xyz_um=(0.8, 0.8, 2.0), target_xy_shape=(32, 32))
            np.testing.assert_array_equal(sitk.GetArrayFromImage(sitk.ReadImage(str(nrrd_path))),
                                          sitk.GetArrayFromImage(sitk.ReadImage(str(expected_path))))

            sidecar_path = nrrd_path.with_name(f"{nrrd_path.stem}_metadata.json")
            sidecar = json.loads(sidecar_path.read_text())
            self.assertEqual(sidecar["fish_id"], "L500_f01")
            self.assertEqual(sidecar["polarity"], "north")
            self.assertFalse((fish_folder / "02_reg" / "00_preprocessing" / "spatial_preprocessing_manifest.json").exists())

            first_outputs = {path: path.read_bytes() for path in (nrrd_path, sidecar_path)}
            self.assertEqual(batch_canonical_anatomy(root, ["L500_f01"], target_xy_shape=(32, 32)), {})
            self.assertEqual({path: path.read_bytes() for path in first_outputs}, first_outputs)

    def test_anatomy_only_needs_a_polarity(self):
        """Without orientation in the metadata, the fish is skipped unless a reviewed polarity is given.

        Returns:
            None: The test passes if all assertions hold; otherwise it
            raises an assertion error.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_fake_raw_fish(root / "L501_f01", orientation=None)
            self.assertEqual(batch_canonical_anatomy(root, ["L501_f01"], target_xy_shape=(32, 32)), {})
            written = batch_canonical_anatomy(root, ["L501_f01"], reviewed_polarity="south", target_xy_shape=(32, 32))
            self.assertEqual(written["L501_f01"]["polarity"], "south")


if __name__ == "__main__":
    unittest.main()
