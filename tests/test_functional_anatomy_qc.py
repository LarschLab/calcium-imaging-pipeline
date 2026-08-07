from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
import tifffile

from preprocessing.functional_anatomy_qc import (
    FunctionalAnatomyQCConfig,
    anatomy_z_spacing_um,
    block_third_bounds,
    block_third_labels,
    quadratic_peak_z,
    read_raw_anatomy,
    run_functional_anatomy_qc,
)


def _spot(shape: tuple[int, int], y: int, x: int) -> np.ndarray:
    yy, xx = np.indices(shape)
    return np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / 5.0).astype(np.float32)


def _make_fish(root: Path, *, drifting: bool = False) -> Path:
    fish = root / "L000_f00"
    anatomy_dir = fish / "01_raw" / "2p" / "anatomy"
    metadata_dir = fish / "01_raw" / "2p" / "metadata"
    movie_dir = fish / "02_reg" / "00_preprocessing" / "2p_functional" / "02_motionCorrected"
    pre_dir = fish / "02_reg" / "00_preprocessing" / "2p_functional" / "01_individualPlanes"
    for directory in (anatomy_dir, metadata_dir, movie_dir, pre_dir):
        directory.mkdir(parents=True)

    anatomy = np.zeros((7, 32, 32), dtype=np.uint16)
    for z_index in range(anatomy.shape[0]):
        image = _spot((32, 32), 14, 14) + 0.65 * _spot((32, 32), 8 + z_index, 20)
        anatomy[z_index] = np.rint(image / image.max() * 50000).astype(np.uint16)
    tifffile.imwrite(anatomy_dir / "L000_f00_anatomy_00001.tif", anatomy, photometric="minisblack")
    with (metadata_dir / "run_metadata.csv").open("w", newline="") as handle:
        csv.writer(handle).writerow(["step_size_um_anatomy", "2"])

    stable_or_drifting = (
        ((0, (0, 2, 5)), (1, (1, 3, 6)))
        if drifting
        else ((0, (0, 2, 2)), (1, (1, 3, 3)))
    )
    for plane_index, z_by_block in stable_or_drifting:
        frames = []
        for z_index in z_by_block:
            crop = anatomy[z_index, 6:22, 7:23]
            frames.extend([crop] * 9)
        tifffile.imwrite(
            movie_dir / f"L000_f00_plane{plane_index}_mcorrected.tif",
            np.asarray(frames, dtype=np.uint16),
            photometric="minisblack",
        )
    metadata = {
        "fish_id": "L000_f00",
        "sessions": [
            {
                "session_label": "r1",
                "session_number": 1,
                "output_planes": [0, 1],
                "selected_tiffs": ["block0.tif", "block1.tif", "block2.tif"],
            }
        ],
    }
    (pre_dir / "L000_f00_preprocessing_metadata.json").write_text(json.dumps(metadata))
    return fish


class FunctionalAnatomyQCTests(unittest.TestCase):
    def test_blocks_are_split_into_thirds_and_block_zero_is_named_explicitly(self) -> None:
        self.assertEqual(
            block_third_bounds(30, 3),
            (
                (0, 3),
                (3, 6),
                (6, 10),
                (10, 13),
                (13, 16),
                (16, 20),
                (20, 23),
                (23, 26),
                (26, 30),
            ),
        )
        self.assertEqual(
            block_third_labels(2),
            (
                "Block 0\nfirst third",
                "Block 0\nmiddle third",
                "Block 0\nfinal third",
                "Block 1\nfirst third",
                "Block 1\nmiddle third",
                "Block 1\nfinal third",
            ),
        )

    def test_quadratic_peak_reports_subslice_location(self) -> None:
        self.assertTrue(np.isclose(quadratic_peak_z(np.asarray([0.0, 0.5, 1.0, 0.75, 0.0])), 2.1666666667))

    def test_raw_anatomy_preserves_page_order_and_signed_dtype(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stack = (np.arange(5 * 8 * 9).reshape(5, 8, 9) - 100).astype(np.int16)
            path = root / "fish_anatomy_00001.tif"
            tifffile.imwrite(path, stack, photometric="minisblack")
            loaded = read_raw_anatomy(path)
            self.assertEqual(loaded.data_zyx.shape, stack.shape)
            self.assertEqual(loaded.source_dtype, "int16")
            np.testing.assert_array_equal(loaded.data_zyx, stack)

    def test_anatomy_spacing_comes_from_metadata_and_must_agree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("first_metadata.csv", "second_metadata.csv"):
                with (root / name).open("w", newline="") as handle:
                    csv.writer(handle).writerow(["step_size_um_anatomy", "2"])
            spacing, sources = anatomy_z_spacing_um(root)
            self.assertEqual(spacing, 2.0)
            self.assertEqual(len(sources), 2)

    def test_end_to_end_qc_shows_block_zero_but_excludes_it_from_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fish = _make_fish(root)
            output = root / "output"
            manifest = run_functional_anatomy_qc(
                fish_dir=fish,
                output_dir=output,
                config=FunctionalAnatomyQCConfig(
                    sampled_frames_per_window=3,
                    top_correlated_frames=2,
                    scale_coarse=(1.0, 1.0, 0.1),
                    scale_fine_half_window=0,
                    scale_xfine_half_window=0,
                    local_xy_radius_px=2,
                    workers=2,
                ),
            )
            intervals = pd.read_csv(output / "ncc_drift_intervals.csv")
            self.assertEqual(set(intervals["block_index"]), {0, 1, 2})
            self.assertFalse(intervals.loc[intervals["block_index"] == 0, "included_in_drift_gate"].any())
            self.assertTrue(intervals.loc[intervals["block_index"] > 0, "included_in_drift_gate"].all())
            summary = pd.read_csv(output / "ncc_drift_session_summary.csv")
            self.assertEqual(set(summary["status"]), {"pass_candidate"})
            self.assertEqual(manifest["status"], "pass_candidate")
            comparison = pd.read_csv(output / "ncc_xy_engine_comparison.csv")
            self.assertLess(float(comparison["best_z_difference_slices"].abs().max()), 0.1)
            self.assertGreater(float(comparison["profile_correlation"].median()), 0.95)
            self.assertGreater((output / "ncc_drift_tracks.png").stat().st_size, 0)
            self.assertGreater((output / "ncc_xy_engine_comparison.png").stat().st_size, 0)

    def test_end_to_end_qc_fails_coherent_post_block_zero_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fish = _make_fish(root, drifting=True)
            output = root / "output"
            manifest = run_functional_anatomy_qc(
                fish_dir=fish,
                output_dir=output,
                config=FunctionalAnatomyQCConfig(
                    sampled_frames_per_window=3,
                    top_correlated_frames=2,
                    scale_coarse=(1.0, 1.0, 0.1),
                    scale_fine_half_window=0,
                    scale_xfine_half_window=0,
                    local_xy_radius_px=2,
                    workers=2,
                ),
            )
            summary = pd.read_csv(output / "ncc_drift_session_summary.csv")
            self.assertEqual(set(summary["status"]), {"fail_candidate"})
            self.assertEqual(manifest["status"], "fail_candidate")
            self.assertTrue((summary["consensus_change_slices"].abs() >= 2).all())


if __name__ == "__main__":
    unittest.main()
