"""Tests for Suite2P registration, NCC gating, and safe workflow resumption."""

from __future__ import annotations

import contextlib
import importlib
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np
import tifffile

from preprocessing import motion_segmentation_suite2p as stage
from preprocessing.spatial_preprocessing import PolarityResolution, write_spatial_manifest


def _declare_planes(fish, planes):
    """Write a minimal canonical manifest declaring the supplied plane TIFFs.

    Args:
        fish (Path): Fish directory the manifest should be written under.
        planes (list[Path]): Paths to the functional plane TIFFs to declare
            in the manifest.

    Returns:
        None: The manifest is written to disk as a side effect.
    """
    write_spatial_manifest(
        fish_dir=fish,
        polarity=PolarityResolution("south", "test", "resolved", None, None),
        functional_planes=[{"output_path": str(path)} for path in planes],
        anatomy={"output_path": str(fish / "canonical_anatomy.nrrd")},
    )


class Suite2PNCCGateTests(unittest.TestCase):
    def test_historical_suite2p_path_does_not_enable_the_gate(self):
        """The historical Suite2P function must retain its original behavior.

        Returns:
            None: The test passes if all assertions hold; otherwise it
            raises an assertion error.
        """
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

    def test_plain_fish_without_spatial_manifest_reaches_suite2p(self):
        """Fish preprocessed without the canonical flip have no manifest and must still run.

        Returns:
            None: The test passes if all assertions hold; otherwise it
            raises an assertion error.
        """
        with tempfile.TemporaryDirectory() as temporary:
            fish = Path(temporary) / "L000_f00"
            planes = fish / "02_reg" / "00_preprocessing" / "2p_functional" / "01_individualPlanes"
            planes.mkdir(parents=True)
            (planes / "L000_f00_plane0.tif").touch()
            with mock.patch.object(stage, "run_suite2p") as run_suite2p, mock.patch.object(
                stage, "collect_suite2p_results", return_value=None
            ):
                stage.run_suite2p_for_fish(fish, {}, [0], fps=2.0)
            self.assertEqual(run_suite2p.call_count, 1)
            self.assertFalse(stage.spatial_manifest_path(fish).exists())

    def test_plane_with_existing_results_is_skipped_not_overwritten(self):
        """A plane whose motion-corrected movie exists must be skipped, with a hint to delete it.

        Returns:
            None: The test passes if all assertions hold; otherwise it
            raises an assertion error.
        """
        with tempfile.TemporaryDirectory() as temporary:
            fish = Path(temporary) / "L000_f00"
            planes = fish / "02_reg" / "00_preprocessing" / "2p_functional" / "01_individualPlanes"
            planes.mkdir(parents=True)
            (planes / "L000_f00_plane0.tif").touch()
            movie = fish / "02_reg" / "00_preprocessing" / "2p_functional" / "02_motionCorrected" / "L000_f00_plane0_mcorrected.tif"
            movie.parent.mkdir(parents=True)
            movie.write_bytes(b"earlier result")
            printed = io.StringIO()
            with mock.patch.object(stage, "run_suite2p") as run_suite2p, contextlib.redirect_stdout(printed):
                stage.run_suite2p_for_fish(fish, {}, [0], fps=2.0)
            run_suite2p.assert_not_called()
            self.assertEqual(movie.read_bytes(), b"earlier result")
            self.assertIn("delete these files first", printed.getvalue())
            self.assertIn(str(movie), printed.getvalue())

    def test_joining_registered_tiffs_refuses_to_overwrite(self):
        """The motion-corrected movie writer must not replace an existing file.

        Returns:
            None: The test passes if all assertions hold; otherwise it
            raises an assertion error.
        """
        with tempfile.TemporaryDirectory() as temporary:
            movie = Path(temporary) / "plane0_mcorrected.tif"
            movie.write_bytes(b"earlier result")
            with self.assertRaises(FileExistsError):
                stage.join_registered_tiffs(Path(temporary) / "reg_tif", movie)
            self.assertEqual(movie.read_bytes(), b"earlier result")

    def test_mirroring_keeps_files_already_on_the_storage_drive(self):
        """Copying results to storage must add new files but never replace existing ones.

        Returns:
            None: The test passes if all assertions hold; otherwise it
            raises an assertion error.
        """
        with tempfile.TemporaryDirectory() as temporary:
            fish = Path(temporary) / "local" / "L000_f00"
            results = fish / "03_analysis" / "functional" / "suite2P" / "plane0"
            results.mkdir(parents=True)
            (results / "L000_f00_plane0_stat.npy").write_bytes(b"new stat")
            (results / "L000_f00_plane0_F.npy").write_bytes(b"new F")
            storage_root = Path(temporary) / "drive"
            stored = storage_root / "L000_f00" / "03_analysis" / "functional" / "suite2P" / "plane0"
            stored.mkdir(parents=True)
            (stored / "L000_f00_plane0_stat.npy").write_bytes(b"stored stat")
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                stage.mirror_results_to_storage(results, fish, storage_root)
            self.assertEqual((stored / "L000_f00_plane0_stat.npy").read_bytes(), b"stored stat")
            self.assertEqual((stored / "L000_f00_plane0_F.npy").read_bytes(), b"new F")
            self.assertIn("already on the storage drive", printed.getvalue())

    def test_plain_results_end_up_in_the_standard_folders(self):
        """The plain workflow's movie and ROI files must land in their usual places, named per plane.

        Returns:
            None: The test passes if all assertions hold; otherwise it
            raises an assertion error.
        """
        with tempfile.TemporaryDirectory() as temporary:
            fish = Path(temporary) / "L000_f00"
            analysis = fish / "03_analysis" / "functional" / "suite2P"
            suite2p_plane = analysis / "suite2p" / "plane0"
            (suite2p_plane / "reg_tif").mkdir(parents=True)
            tifffile.imwrite(suite2p_plane / "reg_tif" / "file000000_chan0.tif", np.zeros((2, 8, 8), dtype=np.int16))
            np.save(suite2p_plane / "stat.npy", np.zeros(1))
            mcorrected = fish / "02_reg" / "00_preprocessing" / "2p_functional" / "02_motionCorrected"
            with contextlib.redirect_stdout(io.StringIO()):
                destination = stage.collect_suite2p_results(0, analysis, mcorrected, fish.name)
            self.assertEqual(destination, analysis / "plane0")
            self.assertTrue((mcorrected / "L000_f00_plane0_mcorrected.tif").exists())
            self.assertTrue((analysis / "plane0" / "L000_f00_plane0_stat.npy").exists())
            self.assertFalse((analysis / "suite2p").exists())  # Suite2p's temporary folder is removed

    def test_drift_check_in_a_separate_python_reads_back_its_manifest(self):
        """With `drift_python`, the drift command runs in that Python and its manifest is returned.

        Returns:
            None: The test passes if all assertions hold; otherwise it
            raises an assertion error.
        """
        with tempfile.TemporaryDirectory() as temporary:
            fish = Path(temporary) / "L000_f00"
            output_dir = Path(temporary) / "ncc_out"

            def fake_drift_command(command, **_kwargs):
                """Stand in for the drift run: write the manifest it would write."""
                output_dir.mkdir(parents=True)
                (output_dir / "functional_anatomy_qc_manifest.json").write_text('{"status": "pass_candidate"}')

            with mock.patch.object(stage.subprocess, "run", side_effect=fake_drift_command) as run:
                manifest = stage._run_drift_check(fish, output_dir, drift_workers=3, drift_python="/envs/ncc/bin/python")
            command = run.call_args.args[0]
            self.assertEqual(command[:3], ["/envs/ncc/bin/python", "-m", "preprocessing.drift_analysis"])
            self.assertEqual(
                command[3:],
                ["--data-root", str(fish.parent), "--fish", fish.name, "--output-dir", str(output_dir), "--workers", "3"],
            )
            self.assertEqual(manifest["status"], "pass_candidate")

    def test_plain_run_gives_each_plane_its_own_fast_disk_folder(self):
        """Without the drift check, planes must also get separate fast-disk folders.

        Returns:
            None: The test passes if all assertions hold; otherwise it
            raises an assertion error.
        """
        with tempfile.TemporaryDirectory() as temporary:
            fish = Path(temporary) / "L000_f00"
            planes = fish / "02_reg" / "00_preprocessing" / "2p_functional" / "01_individualPlanes"
            planes.mkdir(parents=True)
            for plane in (0, 1):
                (planes / f"L000_f00_plane{plane}.tif").touch()
            fast_disk = Path(temporary) / "fast"
            with mock.patch.object(stage, "run_suite2p") as run_suite2p, mock.patch.object(
                stage, "collect_suite2p_results", return_value=None
            ), contextlib.redirect_stdout(io.StringIO()):
                stage.run_suite2p_for_fish(fish, {}, [0, 1], fps=2.0, fast_disk=fast_disk)
            used_fast_disks = [call.args[4] for call in run_suite2p.call_args_list]
            self.assertEqual(used_fast_disks, [fast_disk / "L000_f00/plane0", fast_disk / "L000_f00/plane1"])

    def test_gated_run_skips_a_missing_plane_with_a_warning(self):
        """A missing plane must be skipped (warning), not stop the gated run.

        Returns:
            None: The test passes if all assertions hold; otherwise it
            raises an assertion error.
        """
        with tempfile.TemporaryDirectory() as temporary:
            fish = Path(temporary) / "L000_f00"
            planes = fish / "02_reg" / "00_preprocessing" / "2p_functional" / "01_individualPlanes"
            planes.mkdir(parents=True)
            plane_path = planes / "L000_f00_plane0.tif"
            plane_path.touch()
            _declare_planes(fish, [plane_path])
            fake_ncc_module = types.ModuleType("preprocessing.drift_analysis")
            fake_ncc_module.FunctionalAnatomyQCConfig = lambda **_kwargs: object()
            fake_ncc_module.run_drift_analysis = lambda **_kwargs: {"status": "review_required"}
            printed = io.StringIO()
            with (
                mock.patch.object(stage, "run_suite2p_registration_only", return_value=fish / "registered") as registration,
                mock.patch.object(stage, "join_registered_tiffs"),
                mock.patch.object(stage, "add_suite2p_record_to_manifest"),
                mock.patch.dict(sys.modules, {"preprocessing.drift_analysis": fake_ncc_module}),
                contextlib.redirect_stdout(printed),
            ):
                stage.run_suite2p_for_fish(fish, {}, [0, 1], 2.0, drift_check="enforce", drift_output_dir=fish / "ncc")
            self.assertEqual(registration.call_count, 1)  # plane 1 doesn't exist
            self.assertIn("Plane 1 not found", printed.getvalue())

    def test_fish_with_spatial_manifest_still_checks_declared_planes(self):
        """A plane missing from an existing manifest must stop before Suite2P.

        Returns:
            None: The test passes if all assertions hold; otherwise it
            raises an assertion error.
        """
        with tempfile.TemporaryDirectory() as temporary:
            fish = Path(temporary) / "L000_f00"
            planes = fish / "02_reg" / "00_preprocessing" / "2p_functional" / "01_individualPlanes"
            planes.mkdir(parents=True)
            (planes / "L000_f00_plane0.tif").touch()
            _declare_planes(fish, [planes / "some_other_plane.tif"])
            with mock.patch.object(stage, "run_suite2p") as run_suite2p, self.assertRaises(ValueError):
                stage.run_suite2p_for_fish(fish, {}, [0], fps=2.0)
            run_suite2p.assert_not_called()

    def test_registration_only_sets_required_suite2p_flags(self):
        """Registration-only mode must save the data needed for QC and resumption.

        Returns:
            None: The test passes if all assertions hold; otherwise it
            raises an assertion error.
        """
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

    def test_resume_reuses_registered_binary_without_registration(self):
        """Resuming segmentation must reuse motion correction instead of repeating it.

        Returns:
            None: The test passes if all assertions hold; otherwise it
            raises an assertion error.
        """
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

    def test_enforced_gate_stops_before_segmentation_and_preserves_registration(self):
        """Enforced QC must stop a failed fish while retaining registration outputs.

        Returns:
            None: The test passes if all assertions hold; otherwise it
            raises an assertion error.
        """
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
                mock.patch.object(stage, "join_registered_tiffs"),
                mock.patch.dict(sys.modules, {"preprocessing.drift_analysis": fake_ncc_module}),
                mock.patch.object(stage, "resume_suite2p_segmentation") as resume,
            ):
                result = stage.run_suite2p_for_fish(
                    fish,
                    {},
                    [0],
                    2.0,
                    drift_check="enforce",
                    drift_output_dir=fish / "ncc",
                )

            self.assertFalse(result["segmentation_ran"])
            self.assertEqual(result["drift_manifest"]["status"], "review_required")
            self.assertTrue((fish / "03_analysis/functional/suite2P/_ncc_gate_registration").exists())
            resume.assert_not_called()

    def test_report_only_continues_after_nonpassing_candidate(self):
        """Report-only QC must record concern but allow segmentation to continue.

        Returns:
            None: The test passes if all assertions hold; otherwise it
            raises an assertion error.
        """
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
                mock.patch.object(stage, "join_registered_tiffs"),
                mock.patch.dict(sys.modules, {"preprocessing.drift_analysis": fake_ncc_module}),
                mock.patch.object(stage, "resume_suite2p_segmentation") as resume,
                mock.patch.object(stage, "move_segmented_rois", return_value=fish / "output"),
            ):
                result = stage.run_suite2p_for_fish(
                    fish,
                    {},
                    [0],
                    2.0,
                    drift_check="report_only",
                    drift_output_dir=fish / "ncc",
                )

            self.assertTrue(result["segmentation_ran"])
            resume.assert_called_once_with(registered, delete_bin=True)

    def test_multiplane_registration_uses_isolated_fast_disk_directories(self):
        """Parallel planes must never share a temporary Suite2P directory.

        Returns:
            None: The test passes if all assertions hold; otherwise it
            raises an assertion error.
        """
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
                mock.patch.object(stage, "join_registered_tiffs"),
                mock.patch.dict(sys.modules, {"preprocessing.drift_analysis": fake_ncc_module}),
                mock.patch.object(stage, "resume_suite2p_segmentation"),
                mock.patch.object(stage, "move_segmented_rois", return_value=fish / "output"),
            ):
                stage.run_suite2p_for_fish(
                    fish,
                    {},
                    [0, 1],
                    2.0,
                    fast_disk=fast_disk,
                    drift_check="report_only",
                    drift_output_dir=fish / "ncc",
                )

            self.assertEqual(
                observed_fast_disks,
                [fast_disk / "L000_f00/plane0", fast_disk / "L000_f00/plane1"],
            )
            self.assertNotEqual(observed_fast_disks[0], observed_fast_disks[1])


if __name__ == "__main__":
    unittest.main()
