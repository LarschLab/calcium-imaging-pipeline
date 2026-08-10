from __future__ import annotations

import importlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np

from preprocessing import motion_segmentation_suite2p as stage


class Suite2PNCCGateTests(unittest.TestCase):
    def test_historical_suite2p_path_does_not_enable_the_gate(self) -> None:
        captured = {}

        def fake_run_s2p(*, ops):
            captured.update(ops)

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            stage.suite2p, "run_s2p", side_effect=fake_run_s2p
        ):
            root = Path(temporary)
            plane = root / "plane0.tif"
            plane.touch()
            stage.run_suite2p(plane, {"custom": 1}, root / "output", fps=2.0)
        self.assertEqual(captured["custom"], 1)
        self.assertTrue(captured["delete_bin"])
        self.assertNotIn("roidetect", captured)

    def test_registration_only_sets_required_suite2p_flags(self) -> None:
        captured = {}

        def fake_run_s2p(*, ops):
            captured.update(ops)
            plane_dir = Path(ops["save_path0"]) / "suite2p" / "plane0"
            (plane_dir / "reg_tif").mkdir(parents=True)
            (plane_dir / "data.bin").touch()
            saved = dict(ops)
            saved["reg_file"] = str(plane_dir / "data.bin")
            np.save(plane_dir / "ops.npy", saved)

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            stage.suite2p, "run_s2p", side_effect=fake_run_s2p
        ):
            root = Path(temporary)
            plane = root / "plane0.tif"
            plane.touch()
            result = stage.run_suite2p_registration_only(plane, {}, root / "output", fps=2.0)
            self.assertEqual(result, root / "output" / "suite2p" / "plane0")
        self.assertFalse(captured["roidetect"])
        self.assertFalse(captured["delete_bin"])
        self.assertTrue(captured["reg_tif"])

    def test_resume_reuses_registered_binary_without_registration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plane_dir = Path(temporary)
            binary = plane_dir / "data.bin"
            binary.touch()
            np.save(
                plane_dir / "ops.npy",
                {"reg_file": str(binary), "nframes": 100, "Ly": 8, "Lx": 8},
            )

            def fake_run_plane(ops, ops_path=None):
                self.assertEqual(ops["do_registration"], 0)
                self.assertTrue(ops["roidetect"])
                np.save(plane_dir / "stat.npy", np.asarray([], dtype=object))
                return ops

            run_s2p_module = importlib.import_module("suite2p.run_s2p")
            with mock.patch.object(run_s2p_module, "run_plane", side_effect=fake_run_plane):
                stage.resume_suite2p_segmentation(plane_dir, delete_bin=False)

    def test_enforced_gate_stops_before_segmentation_and_preserves_registration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fish = Path(temporary) / "L000_f00"
            preprocessed = fish / "02_reg/00_preprocessing/2p_functional/01_individualPlanes"
            preprocessed.mkdir(parents=True)
            (preprocessed / "L000_f00_plane0.tif").touch()
            def fake_registration(_plane_file, _ops, save_path0, _fps, _fast_disk):
                registered = Path(save_path0) / "suite2p/plane0"
                registered.mkdir(parents=True)
                return registered

            fake_ncc_module = types.ModuleType("preprocessing.functional_anatomy_qc")
            fake_ncc_module.FunctionalAnatomyQCConfig = lambda **_kwargs: object()
            fake_ncc_module.run_functional_anatomy_qc = lambda **_kwargs: {"status": "review_required"}

            with (
                mock.patch.object(stage, "run_suite2p_registration_only", side_effect=fake_registration),
                mock.patch.object(stage, "join_reg_tiffs_to_one"),
                mock.patch.dict(sys.modules, {"preprocessing.functional_anatomy_qc": fake_ncc_module}),
                mock.patch.object(stage, "resume_suite2p_segmentation") as resume,
            ):
                result = stage.process_fish_with_ncc_gate(
                    fish,
                    {},
                    [0],
                    2.0,
                    gate_mode="enforce",
                    ncc_output_dir=fish / "ncc",
                )

            self.assertFalse(result["segmentation_ran"])
            self.assertEqual(result["ncc_manifest"]["status"], "review_required")
            self.assertTrue((fish / "03_analysis/functional/suite2P/_ncc_gate_registration").exists())
            resume.assert_not_called()

    def test_report_only_continues_after_nonpassing_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fish = Path(temporary) / "L000_f00"
            preprocessed = fish / "02_reg/00_preprocessing/2p_functional/01_individualPlanes"
            preprocessed.mkdir(parents=True)
            (preprocessed / "L000_f00_plane0.tif").touch()
            registered = fish / "03_analysis/functional/suite2P/_ncc_gate_registration/plane0/suite2p/plane0"

            def fake_registration(_plane_file, _ops, save_path0, _fps, _fast_disk):
                result = Path(save_path0) / "suite2p/plane0"
                result.mkdir(parents=True)
                return result

            fake_ncc_module = types.ModuleType("preprocessing.functional_anatomy_qc")
            fake_ncc_module.FunctionalAnatomyQCConfig = lambda **_kwargs: object()
            fake_ncc_module.run_functional_anatomy_qc = lambda **_kwargs: {"status": "fail_candidate"}

            with (
                mock.patch.object(stage, "run_suite2p_registration_only", side_effect=fake_registration),
                mock.patch.object(stage, "join_reg_tiffs_to_one"),
                mock.patch.dict(sys.modules, {"preprocessing.functional_anatomy_qc": fake_ncc_module}),
                mock.patch.object(stage, "resume_suite2p_segmentation") as resume,
                mock.patch.object(stage, "move_segmentation_files", return_value=fish / "output"),
            ):
                result = stage.process_fish_with_ncc_gate(
                    fish,
                    {},
                    [0],
                    2.0,
                    gate_mode="report_only",
                    ncc_output_dir=fish / "ncc",
                )

            self.assertTrue(result["segmentation_ran"])
            resume.assert_called_once_with(registered, delete_bin=True)

    def test_multiplane_registration_uses_isolated_fast_disk_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fish = Path(temporary) / "L000_f00"
            preprocessed = fish / "02_reg/00_preprocessing/2p_functional/01_individualPlanes"
            preprocessed.mkdir(parents=True)
            for plane in (0, 1):
                (preprocessed / f"L000_f00_plane{plane}.tif").touch()
            fast_disk = Path(temporary) / "fast"
            observed_fast_disks = []

            def fake_registration(_plane_file, _ops, save_path0, _fps, plane_fast_disk):
                observed_fast_disks.append(Path(plane_fast_disk))
                registered = Path(save_path0) / "suite2p/plane0"
                registered.mkdir(parents=True)
                return registered

            fake_ncc_module = types.ModuleType("preprocessing.functional_anatomy_qc")
            fake_ncc_module.FunctionalAnatomyQCConfig = lambda **_kwargs: object()
            fake_ncc_module.run_functional_anatomy_qc = lambda **_kwargs: {"status": "review_required"}

            with (
                mock.patch.object(stage, "run_suite2p_registration_only", side_effect=fake_registration),
                mock.patch.object(stage, "join_reg_tiffs_to_one"),
                mock.patch.dict(sys.modules, {"preprocessing.functional_anatomy_qc": fake_ncc_module}),
                mock.patch.object(stage, "resume_suite2p_segmentation"),
                mock.patch.object(stage, "move_segmentation_files", return_value=fish / "output"),
            ):
                stage.process_fish_with_ncc_gate(
                    fish,
                    {},
                    [0, 1],
                    2.0,
                    fast_disk=fast_disk,
                    gate_mode="report_only",
                    ncc_output_dir=fish / "ncc",
                )

            self.assertEqual(
                observed_fast_disks,
                [fast_disk / "L000_f00/plane0", fast_disk / "L000_f00/plane1"],
            )
            self.assertNotEqual(observed_fast_disks[0], observed_fast_disks[1])


if __name__ == "__main__":
    unittest.main()
