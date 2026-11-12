"""Tests for the per-experiment batch registration helpers (no ANTs runs)."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import tifffile

from registration.batch_registration import (
    ANATOMY_DIR,
    REGISTRATION_STAGE_DIR,
    build_roi_rows,
    collect_fish_summary,
    find_anatomy_tiff,
    fish_status,
    list_experiment_fish,
    qc_figure_paths,
    read_anatomy_z_step_um,
    roi_table_path,
)

FISH_ID = "L000_f01"
OVERVIEW_HEADER = "Experiment,Fish,Final decision\n"


def _touch(path):
    """Create an empty file and its folders.

    Args:
        path (Path): File to create.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


class ExperimentFishTest(unittest.TestCase):
    """The experiment's fish come from the overview, without excluded ones."""

    def test_excluded_and_other_experiments_are_left_out(self):
        """Only this experiment's non-excluded fish are listed, in order."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            overview = Path(temporary_directory) / "overview.csv"
            overview.write_text(OVERVIEW_HEADER + "Exp_9,L1_f01,use\nExp_9,L1_f02,exclude\nExp_8,L2_f01,use\nExp_9,L1_f03,review\n", encoding="utf-8")
            fish = list_experiment_fish(overview, "Exp_9")
        self.assertEqual([entry["fish_id"] for entry in fish], ["L1_f01", "L1_f03"])


class FishStatusTest(unittest.TestCase):
    """A fish is done only when its ROI table and every QC figure exist."""

    def test_status_progression(self):
        """no_folder -> todo -> qc_missing (table only, never re-registered) -> done (table + figures)."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            fish_folder, qc_dir = Path(temporary_directory) / FISH_ID, Path(temporary_directory) / "qc"
            self.assertEqual(fish_status(None, FISH_ID, qc_dir), "no_folder")
            fish_folder.mkdir()
            self.assertEqual(fish_status(fish_folder, FISH_ID, qc_dir), "todo")
            _touch(roi_table_path(fish_folder, FISH_ID))
            self.assertEqual(fish_status(fish_folder, FISH_ID, qc_dir), "qc_missing")
            for figure_path in qc_figure_paths(qc_dir, FISH_ID).values():
                _touch(figure_path)
            self.assertEqual(fish_status(fish_folder, FISH_ID, qc_dir), "done")


class FindAnatomyTest(unittest.TestCase):
    """Exactly one in-vivo anatomy TIFF is needed, and none may be half-written."""

    def test_cases(self):
        """One file is found; ex-vivo is ignored; two files or a .partial file are refused."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            fish_folder = Path(temporary_directory)
            anatomy_dir = fish_folder / ANATOMY_DIR
            _touch(anatomy_dir / "L000_f01_anatomy_00001.tif")
            _touch(anatomy_dir / "L000_f01_ex_vivo_00001.tif")
            self.assertEqual(find_anatomy_tiff(fish_folder)[0].name, "L000_f01_anatomy_00001.tif")
            _touch(anatomy_dir / "L000_f01_anatomy_00002.tif")
            self.assertIsNone(find_anatomy_tiff(fish_folder)[0])
            (anatomy_dir / "L000_f01_anatomy_00002.tif").unlink()
            _touch(anatomy_dir / "L000_f01_anatomy_00003_averaged.tif.partial")
            path, problem = find_anatomy_tiff(fish_folder)
            self.assertIsNone(path)
            self.assertIn("partial", problem)


class AnatomyZStepTest(unittest.TestCase):
    """The Z step comes from the metadata CSV, else from the anatomy file's own record."""

    def test_csv_first_then_averaging_sidecar_then_error(self):
        """CSV value wins; without it the averaged file's sidecar is used; with neither, it raises."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            fish_folder = Path(temporary_directory)
            anatomy_path = fish_folder / ANATOMY_DIR / "L000_f01_anatomy_00001_averaged.tif"
            anatomy_path.parent.mkdir(parents=True)
            tifffile.imwrite(anatomy_path, np.zeros((2, 4, 4), dtype=np.int16))  # no ScanImage header
            metadata_csv = fish_folder / "01_raw" / "2p" / "metadata" / "x_L000_f01_metadata.csv"
            metadata_csv.parent.mkdir(parents=True)

            metadata_csv.write_text("parameter,value\nstep_size,10\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_anatomy_z_step_um(fish_folder, anatomy_path)

            sidecar = anatomy_path.with_name(f"{anatomy_path.stem}_metadata.json")
            sidecar.write_text(json.dumps({"source_header": {"z_step_um": 2.000000000000004}}), encoding="utf-8")
            z_step, source = read_anatomy_z_step_um(fish_folder, anatomy_path)
            self.assertEqual(z_step, 2.0)
            self.assertIn("via", source)

            metadata_csv.write_text("parameter,value\nstep_size_um_anatomy,3\n", encoding="utf-8")
            z_step, source = read_anatomy_z_step_um(fish_folder, anatomy_path)
            self.assertEqual(z_step, 3.0)
            self.assertIn("metadata CSV", source)


class RoiRowsTest(unittest.TestCase):
    """ROI rows keep the suite2p index and cell call, even when ROIs were skipped."""

    def test_rows_use_suite2p_index_not_list_position(self):
        """With ROI 0 skipped, the first row is suite2p ROI 1, with ROI 1's iscell values."""
        warped_rois = [{"suite2p_index": 1, "med_aligned": [20.0, 10.0], "xpix_aligned": np.array([9, 10, 11])}]
        canonical_rois = [{"med_canonical": [30.0, 15.0], "zpix_canonical": np.array([50.0, 50.0, 50.0])}]
        iscell = np.array([[0.0, 0.1], [1.0, 0.9]])
        plane_result = {"plane_index": 2, "best_depth": 18, "warped_rois": warped_rois, "iscell": iscell}

        rows = build_roi_rows(FISH_ID, plane_result, canonical_rois)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["plane"], row["suite2p_index"], row["is_cell"], row["cell_probability"]), (2, 1, True, 0.9))
        self.assertEqual((row["x_anatomy"], row["y_anatomy"], row["z_anatomy"]), (10.0, 20.0, 18))
        self.assertEqual((row["x_canonical"], row["y_canonical"], row["z_canonical"]), (15.0, 30.0, 50.0))


class SummaryTest(unittest.TestCase):
    """The experiment summary is read back from the saved per-plane metadata."""

    def test_collect_fish_summary_reads_only_finished_planes(self):
        """No ROI table -> nothing; otherwise only the planes its run recorded, ignoring stale JSONs."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            fish_folder = Path(temporary_directory)
            logs_dir = fish_folder / REGISTRATION_STAGE_DIR / "logs"
            logs_dir.mkdir(parents=True)
            metadata = {
                "match": {"best_z": 2, "scale": 0.85, "scores": [0.5, 0.6, 0.8, 0.6]},
                "ncc_placement": {"score": 0.88}, "pre_ants_ncc": 0.77, "post_ncc": 0.79,
                "ants_lowered_fit": False, "valid_fraction": 0.73, "rois": {"warped": 450},
                "timestamp": "2026-11-11 16:38:00",
            }
            for plane_index in (0, 1, 7):  # plane 7: left over from an older run
                (logs_dir / f"{FISH_ID}_plane{plane_index}_to_anatomy_registration_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
            self.assertEqual(collect_fish_summary(fish_folder, FISH_ID), [])  # failed/unfinished run

            table_path = roi_table_path(fish_folder, FISH_ID)
            _touch(table_path)
            table_path.with_name(f"{table_path.stem}_metadata.json").write_text(json.dumps({"planes": [0, 1]}), encoding="utf-8")
            rows = collect_fish_summary(fish_folder, FISH_ID)

        self.assertEqual([row["plane"] for row in rows], [0, 1])
        self.assertAlmostEqual(rows[0]["peak_delta"], 0.2)
        self.assertEqual(rows[0]["n_rois_warped"], 450)


if __name__ == "__main__":
    unittest.main()
