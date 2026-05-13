from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import tifffile as tf


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "preprocessing"))

import preprocessing_cli  # noqa: E402
import preprocessing_gui  # noqa: E402
import preprocessing_workflow  # noqa: E402


class PreprocessingWorkflowConfigTests(unittest.TestCase):
    def test_preprocessing_config_defaults_to_streaming_multi_fish(self) -> None:
        config = preprocessing_workflow.preprocessing_config_from_dict(
            {
                "fish_ids": "fish01, fish02",
                "data_root": "/data",
                "protocol": "resonant",
                "n_planes": "5",
                "n_frames_per_plane": "3",
                "blocks": "1,2",
                "volume_flyback_frames": "0",
                "remove_first_frame": "true",
                "workers": "auto",
            }
        )

        self.assertEqual(config.fish_ids, ["fish01", "fish02"])
        self.assertEqual(config.input_base, Path("/data"))
        self.assertEqual(config.output_base, Path("/data"))
        self.assertEqual(config.mode, preprocessing_workflow.PREPROCESSING_MODE_STREAMING)
        self.assertEqual(config.blocks, [1, 2])
        self.assertTrue(config.remove_first_frame)
        self.assertEqual(config.workers, "auto")

    def test_linear_preprocessing_ignores_resonant_plane_fields(self) -> None:
        config = preprocessing_workflow.preprocessing_config_from_dict(
            {
                "fish_ids": ["fish01"],
                "input_base": "/input",
                "output_base": "/output",
                "protocol": "linear",
                "n_planes": "",
                "n_frames_per_plane": "",
            }
        )

        self.assertIsNone(config.n_planes)
        self.assertIsNone(config.n_frames_per_plane)

    def test_preprocessing_blocks_all_processes_all_blocks(self) -> None:
        for blocks_value in ("all", "ALL", " all "):
            with self.subTest(blocks=blocks_value):
                config = preprocessing_workflow.preprocessing_config_from_dict(
                    {
                        "fish_ids": "fish01",
                        "data_root": "/data",
                        "protocol": "resonant",
                        "n_planes": "5",
                        "n_frames_per_plane": "3",
                        "blocks": blocks_value,
                    }
                )

                self.assertIsNone(config.blocks)

    def test_suite2p_validation_blocks_missing_plane_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ops_path = tmp_path / "ops.npy"
            np.save(ops_path, {"dummy": True})

            config = preprocessing_workflow.Suite2PConfig(
                data_root=tmp_path,
                ops_path=ops_path,
                fps=2.0,
                fish_ids=["fish01"],
                selected_planes=[0],
            )

            with self.assertRaisesRegex(ValueError, "Missing preprocessing folder"):
                preprocessing_workflow.raise_for_invalid_suite2p_inputs(config)

    def test_suite2p_validation_accepts_metadata_and_selected_planes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ops_path = tmp_path / "ops.npy"
            np.save(ops_path, {"dummy": True})
            pre_dir = preprocessing_workflow.individual_planes_dir(tmp_path, "fish01")
            pre_dir.mkdir(parents=True)
            (pre_dir / "fish01_preprocessing_metadata.json").write_text(
                json.dumps({"protocol": "resonant"}),
                encoding="utf-8",
            )
            (pre_dir / "fish01_plane0.tif").write_bytes(b"placeholder")

            config = preprocessing_workflow.Suite2PConfig(
                data_root=tmp_path,
                ops_path=ops_path,
                fps=2.0,
                fish_ids=["fish01"],
                selected_planes=[0],
            )

            preprocessing_workflow.raise_for_invalid_suite2p_inputs(config)

    def test_suite2p_all_planes_expands_from_preprocessing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ops_path = tmp_path / "ops.npy"
            np.save(ops_path, {"dummy": True})
            pre_dir = preprocessing_workflow.individual_planes_dir(tmp_path, "fish01")
            pre_dir.mkdir(parents=True)
            (pre_dir / "fish01_preprocessing_metadata.json").write_text(
                json.dumps({"protocol": "resonant"}),
                encoding="utf-8",
            )
            (pre_dir / "fish01_plane0.tif").write_bytes(b"placeholder")
            (pre_dir / "fish01_plane5.tif").write_bytes(b"placeholder")

            config = preprocessing_workflow.suite2p_config_from_dict(
                {
                    "data_root": str(tmp_path),
                    "ops_path": str(ops_path),
                    "fps": "2.0",
                    "fish_ids": "fish01",
                    "selected_planes": "all",
                }
            )

            self.assertIsNone(config.selected_planes)
            preprocessing_workflow.raise_for_invalid_suite2p_inputs(config)
            self.assertEqual(preprocessing_workflow.selected_planes_for_fish(tmp_path, "fish01", config.selected_planes), [0, 5])

    def test_run_suite2p_config_delegates_to_batch_process_with_storage_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ops_path = tmp_path / "ops.npy"
            np.save(ops_path, {"dummy": True})
            pre_dir = preprocessing_workflow.individual_planes_dir(tmp_path, "fish01")
            pre_dir.mkdir(parents=True)
            (pre_dir / "fish01_preprocessing_metadata.json").write_text(
                json.dumps({"protocol": "resonant"}),
                encoding="utf-8",
            )
            (pre_dir / "fish01_plane0.tif").write_bytes(b"placeholder")

            fake_suite2p = types.ModuleType("suite2p")
            fake_suite2p.run_s2p = lambda ops: None
            with patch.dict(sys.modules, {"suite2p": fake_suite2p}):
                import motion_segmentation_suite2p  # noqa: E402

                with patch.object(motion_segmentation_suite2p, "batch_process") as batch_process:
                    preprocessing_workflow.run_suite2p_config(
                        preprocessing_workflow.Suite2PConfig(
                            data_root=tmp_path,
                            ops_path=ops_path,
                            fps=2.0,
                            fish_ids=["fish01"],
                            selected_planes=[0],
                            storage_root=tmp_path / "mirror",
                        )
                    )

            batch_process.assert_called_once()
            self.assertEqual(batch_process.call_args.kwargs["storage_root"], tmp_path / "mirror")
            self.assertEqual(batch_process.call_args.kwargs["selected_planes_by_fish"], {"fish01": [0]})


class Suite2PRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if "suite2p" not in sys.modules:
            fake_suite2p = types.ModuleType("suite2p")
            fake_suite2p.run_s2p = lambda **_kwargs: None
            sys.modules["suite2p"] = fake_suite2p

    def test_join_reg_tiffs_accepts_current_suite2p_chunk_names(self) -> None:
        import motion_segmentation_suite2p  # noqa: E402

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            reg_dir = tmp_path / "reg_tif"
            reg_dir.mkdir()
            tf.imwrite(reg_dir / "file 0001.tif", np.full((1, 2, 2), 2, dtype=np.int16))
            tf.imwrite(reg_dir / "file 0000.tif", np.full((1, 2, 2), 1, dtype=np.int16))

            out_tiff = tmp_path / "joined.tif"
            motion_segmentation_suite2p.join_reg_tiffs_to_one(reg_dir, out_tiff)

            joined = tf.imread(out_tiff)
            self.assertEqual(joined.shape, (2, 2, 2))
            np.testing.assert_array_equal(joined[0], np.full((2, 2), 1, dtype=np.int16))
            np.testing.assert_array_equal(joined[1], np.full((2, 2), 2, dtype=np.int16))

    def test_run_suite2p_legacy_ops_api_preserves_legacy_values(self) -> None:
        import motion_segmentation_suite2p  # noqa: E402

        captured = {}

        def run_s2p(*, ops):
            captured["ops"] = ops

        fake_suite2p = types.SimpleNamespace(run_s2p=run_s2p)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            plane_file = tmp_path / "planes" / "fish01_plane0.tif"
            plane_file.parent.mkdir()
            plane_file.write_bytes(b"placeholder")
            save_path = tmp_path / "suite2p_out"

            with patch.object(motion_segmentation_suite2p, "suite2p", fake_suite2p):
                motion_segmentation_suite2p.run_suite2p(
                    plane_file,
                    {"tau": 3.0, "do_bidiphase": True, "bidiphase": 0.0, "diameter": 0},
                    save_path,
                    fps=2.0,
                    fast_disk=tmp_path / "fast",
                )

        self.assertEqual(captured["ops"]["input_format"], "tif")
        self.assertEqual(captured["ops"]["fs"], 2.0)
        self.assertEqual(captured["ops"]["data_path"], [str(plane_file.parent)])
        self.assertEqual(captured["ops"]["filelist"], [str(plane_file)])
        self.assertEqual(captured["ops"]["file_list"], [plane_file.name])
        self.assertEqual(captured["ops"]["tiff_list"], [str(plane_file)])
        self.assertEqual(captured["ops"]["save_path0"], str(save_path))
        self.assertEqual(captured["ops"]["save_folder"], "suite2p")
        self.assertEqual(captured["ops"]["fast_disk"], str(tmp_path / "fast"))
        self.assertFalse(captured["ops"]["keep_movie_raw"])
        self.assertTrue(captured["ops"]["delete_bin"])
        self.assertEqual(captured["ops"]["batch_size"], 500)
        self.assertTrue(captured["ops"]["do_bidiphase"])
        self.assertEqual(captured["ops"]["bidiphase"], 0.0)
        self.assertEqual(captured["ops"]["diameter"], 0)
        self.assertEqual(captured["ops"]["pretrained_model"], motion_segmentation_suite2p.resolve_default_cellpose_model())
        self.assertEqual(captured["ops"]["anatomical_only"], motion_segmentation_suite2p.DEFAULT_CELLPOSE_ANATOMICAL_ONLY)
        self.assertNotIn("torch_device", captured["ops"])

    def test_legacy_ops_api_force_cpu_patches_cellpose_without_ops_device(self) -> None:
        import motion_segmentation_suite2p  # noqa: E402

        captured = {}

        def run_s2p(*, ops):
            captured["ops"] = ops

        fake_suite2p = types.SimpleNamespace(run_s2p=run_s2p)
        fake_core = types.SimpleNamespace(use_gpu=lambda *args, **kwargs: True)
        fake_cellpose = types.ModuleType("cellpose")
        fake_cellpose.core = fake_core

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            plane_file = tmp_path / "planes" / "fish01_plane0.tif"
            plane_file.parent.mkdir()
            plane_file.write_bytes(b"placeholder")

            with patch.object(motion_segmentation_suite2p, "suite2p", fake_suite2p), patch.dict(
                sys.modules,
                {"cellpose": fake_cellpose, "cellpose.core": fake_core},
            ), patch.dict(
                "os.environ",
                {motion_segmentation_suite2p.FORCE_CPU_ENV_VAR: "1"},
            ):
                motion_segmentation_suite2p.run_suite2p(
                    plane_file,
                    {"tau": 3.0},
                    tmp_path / "suite2p_out",
                    fps=2.0,
                )

        self.assertNotIn("torch_device", captured["ops"])
        self.assertFalse(fake_core.use_gpu())

    def test_runtime_ops_disable_zero_bidiphase_shift(self) -> None:
        import motion_segmentation_suite2p  # noqa: E402

        ops = {"do_bidiphase": True, "bidiphase": 0.0, "two_step_registration": 0.0, "diameter": 0}

        with patch.object(motion_segmentation_suite2p, "best_available_torch_device", return_value="mps"):
            normalized = motion_segmentation_suite2p.normalize_runtime_ops(ops)

        self.assertIs(normalized, ops)
        self.assertFalse(normalized["do_bidiphase"])
        self.assertIs(normalized["two_step_registration"], False)
        self.assertEqual(normalized["diameter"], [12.0, 12.0])
        self.assertEqual(normalized["torch_device"], "mps")

    def test_runtime_ops_respect_explicit_cpu_device(self) -> None:
        import motion_segmentation_suite2p  # noqa: E402

        ops = {"torch_device": "cpu"}

        with patch.object(motion_segmentation_suite2p, "best_available_torch_device", return_value="mps"):
            normalized = motion_segmentation_suite2p.normalize_runtime_ops(ops)

        self.assertEqual(normalized["torch_device"], "cpu")

    def test_current_suite2p_maps_legacy_cellpose_settings(self) -> None:
        import motion_segmentation_suite2p  # noqa: E402

        settings = {"detection": {"cellpose_settings": {}}}
        ops = {
            "anatomical_only": 2,
            "pretrained_model": motion_segmentation_suite2p.DEFAULT_CELLPOSE_MODEL,
            "flow_threshold": 0.5,
            "cellprob_threshold": 0.4,
            "spatial_hp_cp": 0.0,
        }

        returned = motion_segmentation_suite2p.apply_legacy_cellpose_settings_to_current(settings, ops)

        self.assertIs(returned, settings)
        self.assertEqual(settings["detection"]["algorithm"], "cellpose")
        self.assertEqual(settings["detection"]["cellpose_settings"]["img"], "meanImg")
        self.assertEqual(
            settings["detection"]["cellpose_settings"]["cellpose_model"],
            motion_segmentation_suite2p.DEFAULT_CELLPOSE_MODEL,
        )
        self.assertEqual(settings["detection"]["cellpose_settings"]["flow_threshold"], 0.5)
        self.assertEqual(settings["detection"]["cellpose_settings"]["cellprob_threshold"], 0.4)
        self.assertEqual(settings["detection"]["cellpose_settings"]["highpass_spatial"], 0.0)

    def test_default_cellpose_model_overrides_runtime_ops(self) -> None:
        import motion_segmentation_suite2p  # noqa: E402

        ops = {"pretrained_model": "cyto", "anatomical_only": 0}

        returned = motion_segmentation_suite2p.apply_default_cellpose_model(ops)

        self.assertIs(returned, ops)
        self.assertEqual(ops["pretrained_model"], motion_segmentation_suite2p.resolve_default_cellpose_model())
        self.assertEqual(ops["anatomical_only"], motion_segmentation_suite2p.DEFAULT_CELLPOSE_ANATOMICAL_ONLY)

    def test_default_cellpose_model_resolves_from_plane_data_root(self) -> None:
        import motion_segmentation_suite2p  # noqa: E402

        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            local_model = data_root / "cellpose/models" / motion_segmentation_suite2p.DEFAULT_CELLPOSE_MODEL_NAME
            local_model.parent.mkdir(parents=True)
            local_model.write_bytes(b"model")
            plane_file = (
                data_root
                / "fish01/02_reg/00_preprocessing/2p_functional/01_individualPlanes/fish01_plane0.tif"
            )
            plane_file.parent.mkdir(parents=True)
            plane_file.write_bytes(b"placeholder")

            self.assertEqual(
                motion_segmentation_suite2p.resolve_default_cellpose_model(plane_file),
                str(local_model.resolve()),
            )

    def test_default_cellpose_model_falls_back_to_historical_path(self) -> None:
        import motion_segmentation_suite2p  # noqa: E402

        with patch.object(motion_segmentation_suite2p, "DEFAULT_CELLPOSE_MODEL_LOCAL_CANDIDATES", ()):
            self.assertEqual(
                motion_segmentation_suite2p.resolve_default_cellpose_model("/tmp/not/in/data/root/fish_plane0.tif"),
                motion_segmentation_suite2p.DEFAULT_CELLPOSE_MODEL,
            )

    def test_current_ops_api_force_cpu_patches_cellpose(self) -> None:
        import motion_segmentation_suite2p  # noqa: E402

        captured = {}

        def run_s2p(*, db, settings):
            captured["settings"] = settings

        def convert_settings_orig(settings_in, db, settings):
            settings["torch_device"] = settings_in.pop("torch_device")
            settings["fs"] = settings_in.pop("fs")
            settings["io"]["delete_bin"] = settings_in.pop("delete_bin")
            return db, settings, settings_in

        fake_suite2p = types.SimpleNamespace(
            run_s2p=run_s2p,
            default_db=lambda: {},
            default_settings=lambda: {"io": {}, "registration": {}, "extraction": {}, "detection": {"cellpose_settings": {}}},
        )
        fake_parameters = types.ModuleType("suite2p.parameters")
        fake_parameters.convert_settings_orig = convert_settings_orig
        fake_core = types.SimpleNamespace(use_gpu=lambda *args, **kwargs: True)
        fake_cellpose = types.ModuleType("cellpose")
        fake_cellpose.core = fake_core

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            plane_file = tmp_path / "planes" / "fish01_plane0.tif"
            plane_file.parent.mkdir()
            plane_file.write_bytes(b"placeholder")

            with patch.object(motion_segmentation_suite2p, "suite2p", fake_suite2p), patch.dict(
                sys.modules,
                {"suite2p.parameters": fake_parameters, "cellpose": fake_cellpose, "cellpose.core": fake_core},
            ), patch.dict(
                "os.environ",
                {motion_segmentation_suite2p.FORCE_CPU_ENV_VAR: "1"},
            ):
                motion_segmentation_suite2p.run_suite2p(
                    plane_file,
                    {"tau": 3.0},
                    tmp_path / "suite2p_out",
                    fps=2.0,
                )

        self.assertEqual(captured["settings"]["torch_device"], "cpu")
        self.assertFalse(fake_core.use_gpu())

    def test_mps_spatial_taper_patch_uses_float32(self) -> None:
        import motion_segmentation_suite2p  # noqa: E402

        fake_utils = types.SimpleNamespace()
        fake_rigid = types.SimpleNamespace()
        fake_registration = types.SimpleNamespace(rigid=fake_rigid, utils=fake_utils)
        fake_suite2p = types.ModuleType("suite2p")
        fake_suite2p.registration = fake_registration

        with patch.dict(
            sys.modules,
            {
                "suite2p": fake_suite2p,
                "suite2p.registration": fake_registration,
                "suite2p.registration.rigid": fake_rigid,
                "suite2p.registration.utils": fake_utils,
            },
        ):
            motion_segmentation_suite2p.patch_suite2p_mps_float64_ops()

        mask = fake_utils.spatial_taper(3.45, 8, 8)
        self.assertEqual(str(mask.dtype), "torch.float32")
        self.assertIs(fake_utils.spatial_taper, fake_rigid.spatial_taper)

    def test_run_suite2p_converts_flat_ops_for_current_suite2p_api(self) -> None:
        import motion_segmentation_suite2p  # noqa: E402

        captured = {}

        def run_s2p(*, db, settings):
            captured["db"] = db
            captured["settings"] = settings

        def convert_settings_orig(settings_in, db, settings):
            for key in ("input_format", "data_path", "file_list", "save_path0", "save_folder", "keep_movie_raw", "fast_disk"):
                if key in settings_in:
                    db[key] = settings_in.pop(key)
            settings["fs"] = settings_in.pop("fs")
            settings["io"]["delete_bin"] = settings_in.pop("delete_bin")
            settings["registration"]["reg_tif"] = settings_in.pop("reg_tif", False)
            settings["registration"]["batch_size"] = settings_in.pop("batch_size")
            settings["extraction"]["batch_size"] = settings_in.get("extraction_batch_size", 100)
            return db, settings, settings_in

        fake_suite2p = types.SimpleNamespace(
            run_s2p=run_s2p,
            default_db=lambda: {},
            default_settings=lambda: {"io": {}, "registration": {}, "extraction": {}, "detection": {"cellpose_settings": {}}},
        )
        fake_parameters = types.ModuleType("suite2p.parameters")
        fake_parameters.convert_settings_orig = convert_settings_orig

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            plane_file = tmp_path / "planes" / "fish01_plane0.tif"
            plane_file.parent.mkdir()
            plane_file.write_bytes(b"placeholder")
            save_path = tmp_path / "suite2p_out"

            with patch.object(motion_segmentation_suite2p, "suite2p", fake_suite2p), patch.dict(
                sys.modules,
                {"suite2p.parameters": fake_parameters},
            ):
                motion_segmentation_suite2p.run_suite2p(
                    plane_file,
                    {"tau": 3.0, "reg_tif": False},
                    save_path,
                    fps=2.0,
                )

        self.assertEqual(captured["db"]["input_format"], "tif")
        self.assertEqual(captured["db"]["data_path"], [str(plane_file.parent)])
        self.assertEqual(captured["db"]["file_list"], [plane_file.name])
        self.assertEqual(captured["db"]["save_path0"], str(save_path))
        self.assertEqual(captured["db"]["save_folder"], "suite2p")
        self.assertFalse(captured["db"]["keep_movie_raw"])
        self.assertNotIn("fast_disk", captured["db"])
        self.assertEqual(captured["settings"]["fs"], 2.0)
        self.assertTrue(captured["settings"]["io"]["delete_bin"])
        self.assertTrue(captured["settings"]["registration"]["reg_tif"])
        self.assertEqual(captured["settings"]["registration"]["batch_size"], 500)
        self.assertEqual(captured["settings"]["extraction"]["batch_size"], 500)
        self.assertEqual(
            captured["settings"]["detection"]["cellpose_settings"]["cellpose_model"],
            motion_segmentation_suite2p.resolve_default_cellpose_model(plane_file),
        )


class PreprocessingCliAndGuiTests(unittest.TestCase):
    def test_gui_defaults_to_streaming_mode(self) -> None:
        self.assertEqual(
            preprocessing_gui.default_settings()["mode"],
            preprocessing_workflow.PREPROCESSING_MODE_STREAMING,
        )
        self.assertEqual(preprocessing_gui.default_settings()["selected_planes"], "all")
        self.assertEqual(preprocessing_gui.default_settings()["workers"], "auto")

    def test_gui_builds_separate_stage_commands(self) -> None:
        config_path = Path("/tmp/config.json")
        preprocess_command = preprocessing_gui.build_preprocessing_subprocess_command(config_path)
        suite2p_command = preprocessing_gui.build_suite2p_subprocess_command(config_path)

        self.assertEqual(preprocess_command[1:], [str(preprocessing_gui.CLI_PATH), "preprocess", "--config", str(config_path)])
        self.assertEqual(preprocess_command[0], sys.executable)
        self.assertEqual(suite2p_command[0], str(preprocessing_gui.LEGACY_SUITE2P_PYTHON))
        self.assertEqual(suite2p_command[1:], [str(preprocessing_gui.CLI_PATH), "suite2p", "--config", str(config_path)])

    def test_suite2p_subprocess_env_clears_force_cpu(self) -> None:
        env = preprocessing_gui.build_suite2p_subprocess_env(
            {
                preprocessing_gui.FORCE_CPU_ENV_VAR: "1",
                "KEEP_ME": "yes",
            }
        )

        self.assertNotIn(preprocessing_gui.FORCE_CPU_ENV_VAR, env)
        self.assertEqual(env["KEEP_ME"], "yes")

    def test_find_default_suite2p_ops_prefers_legacy_mps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            (tmp_path / "suite2p_ops_legacy_cpu.npy").write_bytes(b"cpu")
            (tmp_path / "suite2p_ops_legacy_mps.npy").write_bytes(b"mps")

            self.assertEqual(
                preprocessing_gui.find_default_suite2p_ops_path(tmp_path),
                tmp_path / "suite2p_ops_legacy_mps.npy",
            )

    def test_find_default_suite2p_ops_falls_back_to_repo_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(
                preprocessing_gui.find_default_suite2p_ops_path(tmpdir),
                preprocessing_gui.REPO_DEFAULT_SUITE2P_OPS_PATH,
            )

    def test_resolve_suite2p_ops_replaces_missing_saved_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_saved_path = Path(tmpdir) / "missing_ops.npy"

            self.assertEqual(
                preprocessing_gui.resolve_suite2p_ops_path(missing_saved_path, tmpdir),
                preprocessing_gui.REPO_DEFAULT_SUITE2P_OPS_PATH,
            )

    def test_resolve_suite2p_ops_keeps_existing_saved_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            saved_path = tmp_path / "custom_ops.npy"
            saved_path.write_bytes(b"ops")

            self.assertEqual(
                preprocessing_gui.resolve_suite2p_ops_path(saved_path, tmpdir),
                saved_path,
            )

    def test_find_default_suite2p_ops_returns_none_for_empty_root(self) -> None:
        self.assertIsNone(preprocessing_gui.find_default_suite2p_ops_path(""))

    def test_legacy_suite2p_preflight_success(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["python"],
            returncode=0,
            stdout=(
                "extra import output\n"
                'CALCIUM_SUITE2P_PREFLIGHT {"cellpose": "4.0.6", "cellpose_gpu": true, '
                '"mps": true, "suite2p": "0.14.6", "torch": "2.11.0"}\n'
            ),
            stderr="",
        )

        with patch.object(Path, "exists", return_value=True), patch("preprocessing_gui.subprocess.run", return_value=completed):
            payload = preprocessing_gui.check_legacy_suite2p_mps_runtime(Path("/legacy/python"))

        self.assertEqual(payload["suite2p"], "0.14.6")
        self.assertTrue(payload["mps"])

    def test_legacy_suite2p_preflight_blocks_missing_python(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not exist"):
            preprocessing_gui.check_legacy_suite2p_mps_runtime(Path("/missing/python"))

    def test_legacy_suite2p_preflight_blocks_missing_mps(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["python"],
            returncode=0,
            stdout=(
                'CALCIUM_SUITE2P_PREFLIGHT {"cellpose": "4.0.6", "cellpose_gpu": true, '
                '"mps": false, "suite2p": "0.14.6", "torch": "2.11.0"}\n'
            ),
            stderr="",
        )

        with patch.object(Path, "exists", return_value=True), patch("preprocessing_gui.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(ValueError, "MPS is unavailable"):
                preprocessing_gui.check_legacy_suite2p_mps_runtime(Path("/legacy/python"))

    def test_gui_routes_carriage_return_progress_to_status_events(self) -> None:
        output_queue = preprocessing_gui.queue.Queue()
        pending = preprocessing_gui.queue_subprocess_output("scan 1/3\rscan 2/3\rDone\n", output_queue)

        self.assertEqual(pending, "")
        self.assertEqual(output_queue.get_nowait(), ("__STATUS__", "scan 1/3"))
        self.assertEqual(output_queue.get_nowait(), ("__STATUS__", "scan 2/3"))
        self.assertEqual(output_queue.get_nowait(), "Done\n")
        self.assertTrue(output_queue.empty())

    def test_cli_dispatches_preprocess_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "fish_ids": "fish01",
                        "input_base": "/input",
                        "output_base": "/output",
                        "protocol": "resonant",
                        "n_planes": 2,
                        "n_frames_per_plane": 3,
                    }
                ),
                encoding="utf-8",
            )

            with patch("preprocessing_cli.run_preprocessing_config") as runner:
                exit_code = preprocessing_cli.main(["preprocess", "--config", str(config_path)])

            self.assertEqual(exit_code, 0)
            runner.assert_called_once()


if __name__ == "__main__":
    unittest.main()
