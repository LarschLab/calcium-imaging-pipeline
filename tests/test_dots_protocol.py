import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "visual_stimulation"))

from dots_protocol import (  # noqa: E402
    MODE_CONTINUOUS_SESSION,
    MODE_LOOP_BLOCKS,
    MODE_LOOP_STIMULI,
    FPS,
    SAMPLE_STIMULI_DIR,
    build_run_plan,
    derive_functional_framerate,
    get_mode_defaults,
    load_stimuli_catalog,
    normalize_session,
    plan_to_planned_block_rows,
    plan_to_schedule_rows,
    prepare_run_config,
    summarize_plan,
)
from dots_runner import run_planned_experiment  # noqa: E402


class DotsProtocolTests(unittest.TestCase):
    def test_sequential_duration_matches_trial_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "stim1.csv", frames=60)
            self._write_stimulus(tmp_path / "stim2.csv", frames=120)

            defaults = get_mode_defaults(MODE_LOOP_STIMULI)
            metadata, functional, stimuli_params, runtime = prepare_run_config(
                MODE_LOOP_STIMULI,
                defaults["metadata"],
                defaults["functional_params"],
                defaults["stimuli_params"],
                defaults["runtime"],
                tmp_path,
            )
            catalog = load_stimuli_catalog(tmp_path, MODE_LOOP_STIMULI)
            plan = build_run_plan(MODE_LOOP_STIMULI, metadata, functional, stimuli_params, runtime, catalog)

            expected = (60 + 120) / FPS
            self.assertAlmostEqual(plan.total_duration_sec, expected, places=6)
            self.assertEqual([trial.stimulus_name for trial in plan.trials], ["stim1", "stim2"])

    def test_random_order_is_locked_into_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "alpha.csv", frames=30)
            self._write_stimulus(tmp_path / "beta.csv", frames=30)
            self._write_stimulus(tmp_path / "gamma.csv", frames=30)

            defaults = get_mode_defaults(MODE_LOOP_BLOCKS)
            defaults["stimuli_params"]["n_rep_stim"] = 2
            defaults["stimuli_params"]["pre_stim_resting_sec"] = 0
            defaults["stimuli_params"]["pre_stim_pause_sec"] = 0
            defaults["stimuli_params"]["post_stim_pause_sec"] = 0
            defaults["stimuli_params"]["inter_block_pause_sec"] = 0
            metadata, functional, stimuli_params, runtime = prepare_run_config(
                MODE_LOOP_BLOCKS,
                defaults["metadata"],
                defaults["functional_params"],
                defaults["stimuli_params"],
                defaults["runtime"],
                tmp_path,
            )
            catalog = load_stimuli_catalog(tmp_path, MODE_LOOP_BLOCKS)
            plan = build_run_plan(MODE_LOOP_BLOCKS, metadata, functional, stimuli_params, runtime, catalog)

            self.assertEqual(len(plan.trials), 6)
            first_order = [trial.stimulus_name for trial in plan.trials]
            second_order = [row["stimulus_name"] for row in plan_to_schedule_rows(plan) if row["kind"] == "stimulus"]
            self.assertEqual(first_order, second_order)

    def test_seeded_random_order_is_stable_across_plan_builds(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "alpha.csv", frames=30)
            self._write_stimulus(tmp_path / "beta.csv", frames=30)
            self._write_stimulus(tmp_path / "gamma.csv", frames=30)

            defaults = get_mode_defaults(MODE_LOOP_BLOCKS)
            defaults["stimuli_params"]["n_rep_stim"] = 2
            defaults["stimuli_params"]["pre_stim_resting_sec"] = 0
            defaults["stimuli_params"]["pre_stim_pause_sec"] = 0
            defaults["stimuli_params"]["post_stim_pause_sec"] = 0
            defaults["stimuli_params"]["inter_block_pause_sec"] = 0
            defaults["runtime"]["stimulus_shuffle_seed"] = 12345
            metadata, functional, stimuli_params, runtime = prepare_run_config(
                MODE_LOOP_BLOCKS,
                defaults["metadata"],
                defaults["functional_params"],
                defaults["stimuli_params"],
                defaults["runtime"],
                tmp_path,
            )
            catalog = load_stimuli_catalog(tmp_path, MODE_LOOP_BLOCKS)

            first_plan = build_run_plan(MODE_LOOP_BLOCKS, metadata, functional, stimuli_params, runtime, catalog)
            second_plan = build_run_plan(MODE_LOOP_BLOCKS, metadata, functional, stimuli_params, runtime, catalog)

            self.assertEqual(
                [trial.stimulus_name for trial in first_plan.trials],
                [trial.stimulus_name for trial in second_plan.trials],
            )

    def test_prepare_run_config_preserves_valid_session_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            defaults = get_mode_defaults(MODE_LOOP_BLOCKS)
            defaults["metadata"]["session"] = "2"

            metadata, _, _, _ = prepare_run_config(
                MODE_LOOP_BLOCKS,
                defaults["metadata"],
                defaults["functional_params"],
                defaults["stimuli_params"],
                defaults["runtime"],
                tmpdir,
            )

        self.assertEqual(metadata["session"], 2)

    def test_normalize_session_rejects_invalid_values(self) -> None:
        for value in ("", "two", 0, -1):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "session must be an integer"):
                    normalize_session(value)

    def test_block_mode_keeps_underscore_stems_as_distinct_stimuli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "Ll_RB_trajectory.csv", frames=30)
            self._write_stimulus(tmp_path / "Ll_RC_trajectory.csv", frames=30)
            self._write_stimulus(tmp_path / "Rl_RB_trajectory.csv", frames=30)
            self._write_stimulus(tmp_path / "Rl_RC_trajectory.csv", frames=30)

            defaults = get_mode_defaults(MODE_LOOP_BLOCKS)
            defaults["stimuli_params"]["n_rep_stim"] = 1
            defaults["stimuli_params"]["n_trials_per_block"] = 4
            defaults["stimuli_params"]["pre_stim_resting_sec"] = 0
            defaults["stimuli_params"]["pre_stim_pause_sec"] = 0
            defaults["stimuli_params"]["post_stim_pause_sec"] = 0
            defaults["stimuli_params"]["inter_block_pause_sec"] = 0
            defaults["runtime"]["stimulus_order"] = "sequential"
            metadata, functional, stimuli_params, runtime = prepare_run_config(
                MODE_LOOP_BLOCKS,
                defaults["metadata"],
                defaults["functional_params"],
                defaults["stimuli_params"],
                defaults["runtime"],
                tmp_path,
            )
            catalog = load_stimuli_catalog(tmp_path, MODE_LOOP_BLOCKS)
            plan = build_run_plan(MODE_LOOP_BLOCKS, metadata, functional, stimuli_params, runtime, catalog)

            expected_names = [
                "Ll_RB_trajectory",
                "Ll_RC_trajectory",
                "Rl_RB_trajectory",
                "Rl_RC_trajectory",
            ]
            self.assertEqual([stimulus.runtime_key for stimulus in catalog], expected_names)
            self.assertEqual([stimulus.display_name for stimulus in catalog], expected_names)
            self.assertEqual([trial.stimulus_name for trial in plan.trials], expected_names)

    def test_catalog_loads_mp4_only_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            video_path = tmp_path / "stim1.mp4"
            video_path.write_bytes(b"not-a-real-video")

            with patch("dots_protocol._read_video_duration_sec", return_value=2.5):
                catalog = load_stimuli_catalog(tmp_path, MODE_LOOP_STIMULI)

            self.assertEqual(len(catalog), 1)
            self.assertEqual(catalog[0].path, video_path)
            self.assertEqual(catalog[0].media_type, "video")
            self.assertEqual(catalog[0].frame_count, 150)
            self.assertEqual(catalog[0].n_dots, 0)
            self.assertIsNone(catalog[0].data_frame)
            self.assertAlmostEqual(catalog[0].duration_sec, 2.5, places=6)

    def test_catalog_loads_mixed_csv_and_mp4_in_numeric_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "stim2.csv", frames=60)
            (tmp_path / "stim1.mp4").write_bytes(b"not-a-real-video")

            with patch("dots_protocol._read_video_duration_sec", return_value=0.5):
                catalog = load_stimuli_catalog(tmp_path, MODE_LOOP_STIMULI)

            self.assertEqual([stimulus.path.name for stimulus in catalog], ["stim1.mp4", "stim2.csv"])
            self.assertEqual([stimulus.media_type for stimulus in catalog], ["video", "csv"])

    def test_mp4_duration_contributes_to_block_planning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            (tmp_path / "video_a.mp4").write_bytes(b"not-a-real-video")
            self._write_stimulus(tmp_path / "stim_b.csv", frames=60)

            defaults = get_mode_defaults(MODE_LOOP_BLOCKS)
            defaults["stimuli_params"]["n_rep_stim"] = 1
            defaults["stimuli_params"]["n_trials_per_block"] = 2
            defaults["stimuli_params"]["pre_stim_resting_sec"] = 0
            defaults["stimuli_params"]["pre_stim_pause_sec"] = 0
            defaults["stimuli_params"]["post_stim_pause_sec"] = 0
            defaults["stimuli_params"]["inter_block_pause_sec"] = 0
            defaults["runtime"]["stimulus_order"] = "sequential"
            metadata, functional, stimuli_params, runtime = prepare_run_config(
                MODE_LOOP_BLOCKS,
                defaults["metadata"],
                defaults["functional_params"],
                defaults["stimuli_params"],
                defaults["runtime"],
                tmp_path,
            )
            with patch("dots_protocol._read_video_duration_sec", return_value=2.0):
                catalog = load_stimuli_catalog(tmp_path, MODE_LOOP_BLOCKS)
            plan = build_run_plan(MODE_LOOP_BLOCKS, metadata, functional, stimuli_params, runtime, catalog)

            self.assertEqual([trial.media_type for trial in plan.trials], ["csv", "video"])
            self.assertAlmostEqual(plan.planned_blocks[0].duration_sec, 3.0, places=6)
            self.assertAlmostEqual(plan.planned_blocks[1].duration_sec, 3.0, places=6)
            self.assertEqual(plan.planned_block_frame_counts, [6, 6])

    def test_unreadable_mp4_raises_clear_catalog_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            video_path = tmp_path / "bad.mp4"
            video_path.write_bytes(b"not-a-real-video")

            with patch("dots_protocol._read_video_duration_sec", side_effect=ValueError(f"Could not read MP4 stimulus duration: {video_path}")):
                with self.assertRaisesRegex(ValueError, "Could not read MP4 stimulus duration"):
                    load_stimuli_catalog(tmp_path, MODE_LOOP_STIMULI)

    def test_block_mode_plans_baseline_rest_before_stimulus_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "stim_a.csv", frames=60)
            self._write_stimulus(tmp_path / "stim_b.csv", frames=60)
            self._write_stimulus(tmp_path / "stim_c.csv", frames=60)
            self._write_stimulus(tmp_path / "stim_d.csv", frames=60)

            defaults = get_mode_defaults(MODE_LOOP_BLOCKS)
            defaults["stimuli_params"]["n_rep_stim"] = 1
            defaults["stimuli_params"]["n_trials_per_block"] = 2
            defaults["stimuli_params"]["pre_stim_resting_sec"] = 2.5
            defaults["stimuli_params"]["pre_stim_pause_sec"] = 0
            defaults["stimuli_params"]["post_stim_pause_sec"] = 0
            defaults["stimuli_params"]["inter_block_pause_sec"] = 3.5
            metadata, functional, stimuli_params, runtime = prepare_run_config(
                MODE_LOOP_BLOCKS,
                defaults["metadata"],
                defaults["functional_params"],
                defaults["stimuli_params"],
                defaults["runtime"],
                tmp_path,
            )
            catalog = load_stimuli_catalog(tmp_path, MODE_LOOP_BLOCKS)
            plan = build_run_plan(MODE_LOOP_BLOCKS, metadata, functional, stimuli_params, runtime, catalog)

            self.assertEqual([trial.block_num for trial in plan.trials], [1, 1, 2, 2])
            self.assertEqual([block.block_num for block in plan.planned_blocks], [0, 1, 2])
            self.assertEqual([block.block_kind for block in plan.planned_blocks], ["baseline_rest", "stimulus_block", "stimulus_block"])
            self.assertEqual(plan.timeline[0].label, "B0_start")
            self.assertEqual(plan.timeline[1].kind, "rest")
            self.assertAlmostEqual(plan.stimuli_params["pre_stim_resting_sec"], 2.0, places=6)
            self.assertAlmostEqual(plan.planned_blocks[0].start_sec, 0.0, places=6)
            self.assertAlmostEqual(plan.planned_blocks[0].duration_sec, 2.0, places=6)
            self.assertEqual(plan.planned_blocks[0].acquisition_frame_count, 4)
            self.assertAlmostEqual(plan.planned_blocks[1].start_sec, plan.planned_blocks[0].end_sec + 3.5, places=6)
            self.assertAlmostEqual(plan.planned_blocks[1].duration_sec, 2.0, places=6)
            self.assertEqual(plan.planned_blocks[1].acquisition_frame_count, 4)
            self.assertAlmostEqual(plan.planned_blocks[2].start_sec, plan.planned_blocks[1].end_sec + 3.5, places=6)
            self.assertAlmostEqual(plan.planned_blocks[2].duration_sec, 2.0, places=6)
            self.assertEqual(plan.planned_blocks[2].acquisition_frame_count, 4)
            self.assertAlmostEqual(plan.total_duration_sec, 13.0, places=6)

    def test_block_mode_acquisition_frames_use_duration_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "stim_a.csv", frames=15)

            defaults = get_mode_defaults(MODE_CONTINUOUS_SESSION)
            defaults["stimuli_params"]["n_rep_stim"] = 1
            defaults["stimuli_params"]["n_trials_per_block"] = 1
            defaults["stimuli_params"]["pre_stim_resting_sec"] = 1.0
            defaults["stimuli_params"]["pre_stim_pause_sec"] = 0
            defaults["stimuli_params"]["post_stim_pause_sec"] = 0
            defaults["stimuli_params"]["inter_block_pause_sec"] = 0
            defaults["functional_params"]["framerate"] = 2
            metadata, functional, stimuli_params, runtime = prepare_run_config(
                MODE_CONTINUOUS_SESSION,
                defaults["metadata"],
                defaults["functional_params"],
                defaults["stimuli_params"],
                defaults["runtime"],
                tmp_path,
            )
            catalog = load_stimuli_catalog(tmp_path, MODE_CONTINUOUS_SESSION)
            plan = build_run_plan(MODE_CONTINUOUS_SESSION, metadata, functional, stimuli_params, runtime, catalog)

            self.assertEqual([block.block_kind for block in plan.planned_blocks], ["baseline_rest", "stimulus_block"])
            self.assertEqual(plan.planned_blocks[0].acquisition_frame_count, 1)
            self.assertAlmostEqual(plan.planned_blocks[0].duration_sec, 0.25, places=6)
            self.assertEqual(plan.planned_blocks[1].acquisition_frame_count, 1)
            self.assertAlmostEqual(plan.planned_blocks[1].duration_sec, 0.25, places=6)
            self.assertAlmostEqual(plan.total_duration_sec, 0.5, places=6)
            self.assertEqual(summarize_plan(plan)["planned_total_acquisition_frames"], 2)

    def test_functional_framerate_is_derived_from_frames_and_slices(self) -> None:
        self.assertAlmostEqual(
            derive_functional_framerate({"n_frames": 3, "n_slices": 5, "framerate": 999}),
            2.0,
            places=6,
        )

    def test_plan_functional_params_include_derived_framerate_and_n_volumes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "stim_a.csv", frames=60)
            self._write_stimulus(tmp_path / "stim_b.csv", frames=60)

            defaults = get_mode_defaults(MODE_LOOP_BLOCKS)
            defaults["stimuli_params"]["n_rep_stim"] = 1
            defaults["stimuli_params"]["n_trials_per_block"] = 2
            defaults["stimuli_params"]["pre_stim_resting_sec"] = 0
            defaults["stimuli_params"]["pre_stim_pause_sec"] = 0
            defaults["stimuli_params"]["post_stim_pause_sec"] = 0
            defaults["stimuli_params"]["inter_block_pause_sec"] = 0
            defaults["functional_params"]["n_frames"] = 3
            defaults["functional_params"]["n_slices"] = 5
            defaults["functional_params"]["framerate"] = 999
            defaults["functional_params"]["n_volumes"] = 999
            metadata, functional, stimuli_params, runtime = prepare_run_config(
                MODE_LOOP_BLOCKS,
                defaults["metadata"],
                defaults["functional_params"],
                defaults["stimuli_params"],
                defaults["runtime"],
                tmp_path,
            )
            catalog = load_stimuli_catalog(tmp_path, MODE_LOOP_BLOCKS)
            plan = build_run_plan(MODE_LOOP_BLOCKS, metadata, functional, stimuli_params, runtime, catalog)

            self.assertAlmostEqual(functional["framerate"], 2.0, places=6)
            self.assertAlmostEqual(plan.functional_params["framerate"], 2.0, places=6)
            self.assertEqual(plan.functional_params["n_volumes"], plan.planned_total_acquisition_frames)
            self.assertEqual(plan.functional_params["n_volumes"], 8)

    def test_mock_run_writes_canonical_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            stimuli_dir = tmp_path / "stimuli"
            stimuli_dir.mkdir()
            self._write_stimulus(stimuli_dir / "stim1.csv", frames=60)
            self._write_stimulus(stimuli_dir / "stim2.csv", frames=60)

            defaults = get_mode_defaults(MODE_LOOP_STIMULI)
            defaults["stimuli_params"]["pre_stim_resting_sec"] = 0
            defaults["stimuli_params"]["pre_stim_pause_sec"] = 0
            defaults["stimuli_params"]["post_stim_pause_sec"] = 0
            defaults["runtime"]["mock_mode"] = True
            defaults["runtime"]["mock_output_root"] = str(tmp_path / "mock_runs")

            metadata, functional, stimuli_params, runtime = prepare_run_config(
                MODE_LOOP_STIMULI,
                defaults["metadata"],
                defaults["functional_params"],
                defaults["stimuli_params"],
                defaults["runtime"],
                stimuli_dir,
            )
            catalog = load_stimuli_catalog(stimuli_dir, MODE_LOOP_STIMULI)
            plan = build_run_plan(MODE_LOOP_STIMULI, metadata, functional, stimuli_params, runtime, catalog)

            meta_dir = run_planned_experiment(plan)

            expected_meta_dir = (
                Path(runtime["mock_output_root"]) / str(metadata["fish_ID"]) / "01_raw" / "2p" / "metadata"
            )
            self.assertEqual(meta_dir, expected_meta_dir)
            written_files = {path.name for path in meta_dir.iterdir()}
            self.assertTrue(any(name.endswith("_experiment_log.csv") for name in written_files))
            self.assertTrue(any(name.endswith("_block_log.csv") for name in written_files))
            self.assertTrue(any(name.endswith("_trial_sequence.csv") for name in written_files))
            self.assertTrue(any(name.endswith("_planned_blocks.csv") for name in written_files))
            self.assertTrue(any(name.endswith("_planned_schedule.csv") for name in written_files))
            metadata_files = [path for path in meta_dir.iterdir() if path.name.endswith("_metadata.csv")]
            self.assertEqual(len(metadata_files), 1)

            metadata_df = pd.read_csv(metadata_files[0])
            metadata_map = dict(zip(metadata_df["parameter"], metadata_df["value"]))
            self.assertEqual(str(metadata_map["mock_mode"]).lower(), "true")
            self.assertEqual(int(metadata_map["planned_total_trials"]), plan.total_trials)
            self.assertEqual(int(metadata_map["planned_block_count"]), plan.planned_block_count)
            self.assertEqual(int(metadata_map["planned_total_acquisition_frames"]), plan.planned_total_acquisition_frames)

            planned_blocks_df = pd.read_csv(next(path for path in meta_dir.iterdir() if path.name.endswith("_planned_blocks.csv")))
            self.assertEqual(len(planned_blocks_df), plan.planned_block_count)
            self.assertEqual(list(planned_blocks_df["acquisition_frame_count"]), plan.planned_block_frame_counts)
            self.assertEqual(planned_blocks_df.to_dict("records"), plan_to_planned_block_rows(plan))

    def test_mock_run_session_two_writes_suffix_files_in_same_fish_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            stimuli_dir = tmp_path / "stimuli"
            stimuli_dir.mkdir()
            self._write_stimulus(stimuli_dir / "stim1.csv", frames=60)

            defaults = get_mode_defaults(MODE_LOOP_STIMULI)
            defaults["metadata"]["fish_ID"] = "L758_f02"
            defaults["metadata"]["session"] = 2
            defaults["stimuli_params"]["pre_stim_resting_sec"] = 0
            defaults["stimuli_params"]["pre_stim_pause_sec"] = 0
            defaults["stimuli_params"]["post_stim_pause_sec"] = 0
            defaults["runtime"]["mock_mode"] = True
            defaults["runtime"]["mock_output_root"] = str(tmp_path / "mock_runs")

            metadata, functional, stimuli_params, runtime = prepare_run_config(
                MODE_LOOP_STIMULI,
                defaults["metadata"],
                defaults["functional_params"],
                defaults["stimuli_params"],
                defaults["runtime"],
                stimuli_dir,
            )
            catalog = load_stimuli_catalog(stimuli_dir, MODE_LOOP_STIMULI)
            plan = build_run_plan(MODE_LOOP_STIMULI, metadata, functional, stimuli_params, runtime, catalog)

            meta_dir = run_planned_experiment(plan)

            expected_meta_dir = Path(runtime["mock_output_root"]) / "L758_f02" / "01_raw" / "2p" / "metadata"
            self.assertEqual(meta_dir, expected_meta_dir)
            written_files = {path.name for path in meta_dir.iterdir()}
            self.assertTrue(any(name.endswith("_fL758_f02_r2_experiment_log.csv") for name in written_files))
            self.assertTrue(any(name.endswith("_fL758_f02_r2_block_log.csv") for name in written_files))
            self.assertTrue(any(name.endswith("_fL758_f02_r2_trial_sequence.csv") for name in written_files))
            self.assertTrue(any(name.endswith("_fL758_f02_r2_planned_blocks.csv") for name in written_files))
            self.assertTrue(any(name.endswith("_fL758_f02_r2_planned_schedule.csv") for name in written_files))
            metadata_file = next(path for path in meta_dir.iterdir() if path.name.endswith("_fL758_f02_r2_metadata.csv"))
            metadata_map = dict(zip(pd.read_csv(metadata_file)["parameter"], pd.read_csv(metadata_file)["value"]))
            self.assertEqual(int(metadata_map["session"]), 2)

    def test_mock_run_accepts_mp4_stimulus(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            stimuli_dir = tmp_path / "stimuli"
            stimuli_dir.mkdir()
            (stimuli_dir / "video1.mp4").write_bytes(b"not-a-real-video")

            defaults = get_mode_defaults(MODE_LOOP_STIMULI)
            defaults["stimuli_params"]["pre_stim_resting_sec"] = 0
            defaults["stimuli_params"]["pre_stim_pause_sec"] = 0
            defaults["stimuli_params"]["post_stim_pause_sec"] = 0
            defaults["runtime"]["mock_mode"] = True
            defaults["runtime"]["mock_output_root"] = str(tmp_path / "mock_runs")

            metadata, functional, stimuli_params, runtime = prepare_run_config(
                MODE_LOOP_STIMULI,
                defaults["metadata"],
                defaults["functional_params"],
                defaults["stimuli_params"],
                defaults["runtime"],
                stimuli_dir,
            )
            with patch("dots_protocol._read_video_duration_sec", return_value=1.25):
                catalog = load_stimuli_catalog(stimuli_dir, MODE_LOOP_STIMULI)
            plan = build_run_plan(MODE_LOOP_STIMULI, metadata, functional, stimuli_params, runtime, catalog)

            meta_dir = run_planned_experiment(plan)
            trial_sequence = pd.read_csv(next(path for path in meta_dir.iterdir() if path.name.endswith("_trial_sequence.csv")))

            self.assertEqual(plan.trials[0].media_type, "video")
            self.assertIn("video1.mp4", trial_sequence["stimulus"].iloc[0])

    def test_mock_block_run_uses_zero_based_block_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            stimuli_dir = tmp_path / "stimuli"
            stimuli_dir.mkdir()
            self._write_stimulus(stimuli_dir / "stim1.csv", frames=60)
            self._write_stimulus(stimuli_dir / "stim2.csv", frames=60)
            self._write_stimulus(stimuli_dir / "stim3.csv", frames=60)
            self._write_stimulus(stimuli_dir / "stim4.csv", frames=60)

            defaults = get_mode_defaults(MODE_LOOP_BLOCKS)
            defaults["stimuli_params"]["n_rep_stim"] = 1
            defaults["stimuli_params"]["n_trials_per_block"] = 2
            defaults["stimuli_params"]["pre_stim_resting_sec"] = 0
            defaults["stimuli_params"]["pre_stim_pause_sec"] = 0
            defaults["stimuli_params"]["post_stim_pause_sec"] = 0
            defaults["stimuli_params"]["inter_block_pause_sec"] = 1
            defaults["runtime"]["mock_mode"] = True
            defaults["runtime"]["mock_output_root"] = str(tmp_path / "mock_runs")

            metadata, functional, stimuli_params, runtime = prepare_run_config(
                MODE_LOOP_BLOCKS,
                defaults["metadata"],
                defaults["functional_params"],
                defaults["stimuli_params"],
                defaults["runtime"],
                stimuli_dir,
            )
            catalog = load_stimuli_catalog(stimuli_dir, MODE_LOOP_BLOCKS)
            plan = build_run_plan(MODE_LOOP_BLOCKS, metadata, functional, stimuli_params, runtime, catalog)

            meta_dir = run_planned_experiment(plan)
            block_log = pd.read_csv(next(path for path in meta_dir.iterdir() if path.name.endswith("_block_log.csv")))
            marker_events = [
                event
                for event in block_log["event"].tolist()
                if event.endswith("_start") or event.endswith("_end") or "interblock" in event
            ]
            self.assertEqual(
                marker_events,
                [
                    "B0_start",
                    "B0_end",
                    "B0_interblock_pause",
                    "B1_start",
                    "B1_end",
                    "B1_interblock_pause",
                    "B2_start",
                    "B2_end",
                ],
            )
            planned_blocks_df = pd.read_csv(next(path for path in meta_dir.iterdir() if path.name.endswith("_planned_blocks.csv")))
            self.assertEqual(list(planned_blocks_df["block_num"]), [0, 1, 2])
            self.assertEqual(list(planned_blocks_df["block_kind"]), ["baseline_rest", "stimulus_block", "stimulus_block"])

    def test_sample_fixture_catalog_loads(self) -> None:
        catalog = load_stimuli_catalog(SAMPLE_STIMULI_DIR, MODE_LOOP_STIMULI)
        self.assertGreaterEqual(len(catalog), 2)
        self.assertTrue(all(stim.frame_count > 0 for stim in catalog))

    @staticmethod
    def _write_stimulus(path: Path, frames: int) -> None:
        data = pd.DataFrame(
            {
                "dot0_x": list(range(frames)),
                "dot0_y": list(range(frames)),
                "dot0_radius": [0.2] * frames,
            }
        )
        data.to_csv(path, index=False)

    @staticmethod
    def _build_block_mode_plan(
        mode: str,
        stimuli_dir: Path,
        n_trials_per_block: int = 2,
        pre_stim_resting_sec: float = 0,
        pre_stim_pause_sec: float = 0,
        post_stim_pause_sec: float = 0,
        inter_block_pause_sec: float = 0,
        framerate: float = 2,
    ):
        defaults = get_mode_defaults(mode)
        defaults["stimuli_params"]["n_rep_stim"] = 2
        defaults["stimuli_params"]["n_trials_per_block"] = n_trials_per_block
        defaults["stimuli_params"]["pre_stim_resting_sec"] = pre_stim_resting_sec
        defaults["stimuli_params"]["pre_stim_pause_sec"] = pre_stim_pause_sec
        defaults["stimuli_params"]["post_stim_pause_sec"] = post_stim_pause_sec
        defaults["stimuli_params"]["inter_block_pause_sec"] = inter_block_pause_sec
        defaults["functional_params"]["framerate"] = framerate
        metadata, functional, stimuli_params, runtime = prepare_run_config(
            mode,
            defaults["metadata"],
            defaults["functional_params"],
            defaults["stimuli_params"],
            defaults["runtime"],
            stimuli_dir,
        )
        catalog = load_stimuli_catalog(stimuli_dir, mode)
        return build_run_plan(mode, metadata, functional, stimuli_params, runtime, catalog)


if __name__ == "__main__":
    unittest.main()
