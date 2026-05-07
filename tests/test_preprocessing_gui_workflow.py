from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np


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
    def test_run_suite2p_uses_legacy_ops_api_when_available(self) -> None:
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
                    {"tau": 3.0},
                    save_path,
                    fps=2.0,
                    fast_disk=tmp_path / "fast",
                )

        self.assertEqual(captured["ops"]["input_format"], "tif")
        self.assertEqual(captured["ops"]["fs"], 2.0)
        self.assertEqual(captured["ops"]["data_path"], [str(plane_file.parent)])
        self.assertEqual(captured["ops"]["file_list"], [plane_file.name])
        self.assertEqual(captured["ops"]["tiff_list"], [str(plane_file)])
        self.assertEqual(captured["ops"]["save_path0"], str(save_path))
        self.assertEqual(captured["ops"]["save_folder"], "suite2p")
        self.assertEqual(captured["ops"]["fast_disk"], str(tmp_path / "fast"))
        self.assertFalse(captured["ops"]["keep_movie_raw"])
        self.assertTrue(captured["ops"]["delete_bin"])
        self.assertEqual(captured["ops"]["batch_size"], 500)

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
            default_settings=lambda: {"io": {}, "registration": {}, "extraction": {}},
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
        self.assertEqual(suite2p_command[1:], [str(preprocessing_gui.CLI_PATH), "suite2p", "--config", str(config_path)])

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
