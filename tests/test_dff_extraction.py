"""Tests for the dF/F extraction: outputs, metadata, and never overwriting."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from preprocessing.dFoF_extraction import SUITE2P_ANALYSIS_SUBFOLDER, batch_dff_extraction, process_suite2p_fluorescence

DFF_SETTINGS = {"fps": 2.0, "tau": 0.1, "percentile": 8, "instability_ratio": 0.1,
                "min_window_s": 15, "window_tau_multiplier": 40, "dim_threshold_std": 2}


def write_fake_suite2p_plane(plane_path, file_prefix):
    """Write Suite2P-like F.npy and iscell.npy files for one plane.

    Args:
        plane_path (Path): Plane folder to create.
        file_prefix (str): Filename prefix, e.g. "L000_f00_plane0".

    Returns:
        None: The two files are written to `plane_path`.
    """
    rng = np.random.default_rng(0)
    traces = rng.gamma(5.0, 40.0, size=(12, 120))  # ROIs x frames, as Suite2P saves them
    traces[4, 60:] *= 0.01  # a baseline that collapses: dropped as unstable
    is_cell = np.ones(12, dtype=bool)
    is_cell[[1, 7]] = False  # two non-cell ROIs
    plane_path.mkdir(parents=True)
    np.save(plane_path / f"{file_prefix}_F.npy", traces)
    np.save(plane_path / f"{file_prefix}_iscell.npy", np.column_stack([is_cell, np.full(12, 0.5)]))


class DffExtractionTests(unittest.TestCase):
    def test_plane_outputs_metadata_and_no_overwrite(self):
        """A plane gets dF/F, ROI indices and full metadata; a rerun changes nothing.

        Returns:
            None: The test passes if all assertions hold; otherwise it
            raises an assertion error.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plane_path = root / "L000_f00" / SUITE2P_ANALYSIS_SUBFOLDER / "plane0"
            write_fake_suite2p_plane(plane_path, "L000_f00_plane0")

            # Plane 1 has no Suite2P files and a missing fish is listed: both are skipped.
            batch_dff_extraction(root, ["L000_f00", "L999_f99"], [0, 1], DFF_SETTINGS)
            expected_dff, expected_indices = process_suite2p_fluorescence("L000_f00_plane0", plane_path, **DFF_SETTINGS)
            np.testing.assert_array_equal(np.load(plane_path / "L000_f00_plane0_dFoF.npy"), expected_dff)
            np.testing.assert_array_equal(np.load(plane_path / "L000_f00_plane0_filtered_roi_indices.npy"), expected_indices)
            self.assertNotIn(4, expected_indices)  # unstable ROI dropped
            self.assertNotIn(1, expected_indices)  # non-cell ROI dropped
            metadata = json.loads((plane_path / "L000_f00_plane0_dFoF_metadata.json").read_text())
            self.assertEqual(metadata["params"], DFF_SETTINGS)
            self.assertEqual(metadata["shapes"]["dFoF_TxN"], list(expected_dff.shape))

            first_outputs = {path.name: path.read_bytes() for path in plane_path.iterdir()}
            batch_dff_extraction(root, ["L000_f00"], [0], {**DFF_SETTINGS, "percentile": 20})
            second_outputs = {path.name: path.read_bytes() for path in plane_path.iterdir()}
            self.assertEqual(second_outputs, first_outputs)


if __name__ == "__main__":
    unittest.main()
