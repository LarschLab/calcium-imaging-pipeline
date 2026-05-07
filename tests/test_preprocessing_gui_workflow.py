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
