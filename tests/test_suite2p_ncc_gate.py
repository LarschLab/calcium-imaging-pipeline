"""Tests for Suite2P registration, NCC gating, and safe workflow resumption."""

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
from preprocessing.spatial_preprocessing import PolarityResolution, write_spatial_manifest


def _declare_planes(fish: Path, planes: list[Path]) -> None:
    """Write a minimal canonical manifest declaring the supplied plane TIFFs."""
    write_spatial_manifest(
        fish_dir=fish,
        polarity=PolarityResolution("south", "test", "resolved", None, None),
        functional_planes=[{"output_path": str(path)} for path in planes],
        anatomy={"output_path": str(fish / "canonical_anatomy.nrrd")},
    )


class Suite2PNCCGateTests(unittest.TestCase):
    def test_historical_suite2p_path_does_not_enable_the_gate(self) -> None:
        """The historical Suite2P function must retain its original behavior."""
        captured = {}

        def fake_run_s2p(*, ops):
            """Capture historical Suite2P settings without running Suite2P."""
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
        """Registration-only mode must save the data needed for QC and resumption."""
        captured = {}

        def fake_run_s2p(*, ops):
            """Create the minimal files returned by registration-only Suite2P."""
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
        """Resuming segmentation must reuse motion correction instead of repeating it."""
        with tempfile.TemporaryDirectory() as temporary:
            plane_dir = Path(temporary)
            binary = plane_dir / "data.bin"
            binary.touch()
            np.save(
                plane_dir / "ops.npy",
                {"reg_file": str(binary), "nframes": 100, "Ly": 8, "Lx": 8},
            )

            def fake_run_plane(ops, ops_path=None):
                """Pretend to segment an existing registered binary."""
                self.assertEqual(ops["do_registration"], 0)
                self.assertTrue(ops["roidetect"])
                np.save(plane_dir / "stat.npy", np.asarray([], dtype=object))
                return ops

            run_s2p_module = types.ModuleType("suite2p.run_s2p")
            run_s2p_module.run_plane = fake_run_plane
            suite2p_module = types.ModuleType("suite2p")
            suite2p_module.run_s2p = run_s2p_module
            with mock.patch.dict(
                sys.modules,
                {"suite2p": suite2p_module, "suite2p.run_s2p": run_s2p_module},
            ):
                stage.resume_suite2p_segmentation(plane_dir, delete_bin=False)

    def test_enforced_gate_stops_before_segmentation_and_preserves_registration(self) -> None:
        """Enforced QC must stop a failed fish while retaining registration outputs."""
        with tempfile.TemporaryDirectory() as temporary:
            fish = Path(temporary) / "L000_f00"
            preprocessed = fish / "02_reg/00_preprocessing/2p_functional/01_individualPlanes"
            preprocessed.mkdir(parents=True)
            plane_path = preprocessed / "L000_f00_plane0.tif"
            plane_path.touch()
            _declare_planes(fish, [plane_path])
            def fake_registration(_plane_file, _ops, save_path0, _fps, _fast_disk):
                """Create an empty registered-plane directory for gate testing."""
                registered = Path(save_path0) / "suite2p/plane0"
                registered.mkdir(parents=True)
                return registered

            fake_ncc_module = types.ModuleType("preprocessing.drift_analysis")
            fake_ncc_module.FunctionalAnatomyQCConfig = lambda **_kwargs: object()
            fake_ncc_module.run_drift_analysis = lambda **_kwargs: {"status": "review_required"}

            with (
                mock.patch.object(stage, "run_suite2p_registration_only", side_effect=fake_registration),
                mock.patch.object(stage, "join_reg_tiffs_to_one"),
                mock.patch.dict(sys.modules, {"preprocessing.drift_analysis": fake_ncc_module}),
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
        """Report-only QC must record concern but allow segmentation to continue."""
        with tempfile.TemporaryDirectory() as temporary:
            fish = Path(temporary) / "L000_f00"
            preprocessed = fish / "02_reg/00_preprocessing/2p_functional/01_individualPlanes"
            preprocessed.mkdir(parents=True)
            plane_path = preprocessed / "L000_f00_plane0.tif"
            plane_path.touch()
            _declare_planes(fish, [plane_path])
            registered = fish / "03_analysis/functional/suite2P/_ncc_gate_registration/plane0/suite2p/plane0"

            def fake_registration(_plane_file, _ops, save_path0, _fps, _fast_disk):
                """Create the expected registered-plane directory."""
                result = Path(save_path0) / "suite2p/plane0"
                result.mkdir(parents=True)
                return result

            fake_ncc_module = types.ModuleType("preprocessing.drift_analysis")
            fake_ncc_module.FunctionalAnatomyQCConfig = lambda **_kwargs: object()
            fake_ncc_module.run_drift_analysis = lambda **_kwargs: {"status": "fail_candidate"}

            with (
                mock.patch.object(stage, "run_suite2p_registration_only", side_effect=fake_registration),
                mock.patch.object(stage, "join_reg_tiffs_to_one"),
                mock.patch.dict(sys.modules, {"preprocessing.drift_analysis": fake_ncc_module}),
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
        """Parallel planes must never share a temporary Suite2P directory."""
        with tempfile.TemporaryDirectory() as temporary:
            fish = Path(temporary) / "L000_f00"
            preprocessed = fish / "02_reg/00_preprocessing/2p_functional/01_individualPlanes"
            preprocessed.mkdir(parents=True)
            for plane in (0, 1):
                (preprocessed / f"L000_f00_plane{plane}.tif").touch()
            _declare_planes(fish, [preprocessed / f"L000_f00_plane{plane}.tif" for plane in (0, 1)])
            fast_disk = Path(temporary) / "fast"
            observed_fast_disks = []

            def fake_registration(_plane_file, _ops, save_path0, _fps, plane_fast_disk):
                """Record the temporary directory assigned to each plane."""
                observed_fast_disks.append(Path(plane_fast_disk))
                registered = Path(save_path0) / "suite2p/plane0"
                registered.mkdir(parents=True)
                return registered

            fake_ncc_module = types.ModuleType("preprocessing.drift_analysis")
            fake_ncc_module.FunctionalAnatomyQCConfig = lambda **_kwargs: object()
            fake_ncc_module.run_drift_analysis = lambda **_kwargs: {"status": "review_required"}

            with (
                mock.patch.object(stage, "run_suite2p_registration_only", side_effect=fake_registration),
                mock.patch.object(stage, "join_reg_tiffs_to_one"),
                mock.patch.dict(sys.modules, {"preprocessing.drift_analysis": fake_ncc_module}),
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
