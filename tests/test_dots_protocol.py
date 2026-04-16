import math
import sys
import tempfile
import unittest
from pathlib import Path

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
    get_mode_defaults,
    infer_stimulus_type,
    load_stimuli_catalog,
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

    def test_block_mode_preserves_initial_rollover_quirk(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "stim_a.csv", frames=60)
            self._write_stimulus(tmp_path / "stim_b.csv", frames=60)

            defaults = get_mode_defaults(MODE_LOOP_BLOCKS)
            defaults["stimuli_params"]["n_rep_stim"] = 1
            defaults["stimuli_params"]["n_trials_per_block"] = 2
            defaults["stimuli_params"]["pre_stim_resting_sec"] = 0
            defaults["stimuli_params"]["pre_stim_pause_sec"] = 1
            defaults["stimuli_params"]["post_stim_pause_sec"] = 5
            defaults["stimuli_params"]["inter_block_pause_sec"] = 2
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

            self.assertTrue(all(trial.block_num == 1 for trial in plan.trials))
            post_segments = [segment for segment in plan.timeline if segment.kind == "poststim_pause"]
            self.assertTrue(all(math.isclose(segment.duration_sec, 1.0) for segment in post_segments))

    def test_continuous_session_uses_post_stim_pause(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "stim_a.csv", frames=60)

            defaults = get_mode_defaults(MODE_CONTINUOUS_SESSION)
            defaults["stimuli_params"]["n_rep_stim"] = 1
            defaults["stimuli_params"]["n_trials_per_block"] = 5
            defaults["stimuli_params"]["pre_stim_resting_sec"] = 0
            defaults["stimuli_params"]["pre_stim_pause_sec"] = 1
            defaults["stimuli_params"]["post_stim_pause_sec"] = 7
            defaults["stimuli_params"]["inter_block_pause_sec"] = 0
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

            post_segments = [segment for segment in plan.timeline if segment.kind == "poststim_pause"]
            self.assertEqual(len(post_segments), 1)
            self.assertAlmostEqual(post_segments[0].duration_sec, 7.0, places=6)

    def test_block_mode_summary_accepts_valid_manual_block_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "stim_a.csv", frames=60)
            self._write_stimulus(tmp_path / "stim_b.csv", frames=60)
            plan = self._build_block_mode_plan(MODE_LOOP_BLOCKS, tmp_path, manual_block_frames="120, 180")

            summary = summarize_plan(plan)

            self.assertEqual(summary["manual_block_frames"], "120, 180")
            self.assertEqual(summary["derived_planes_per_block"], [4.0, 6.0])
            self.assertEqual(summary["derived_total_planes"], 10.0)

    def test_block_mode_summary_rejects_manual_block_count_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "stim_a.csv", frames=60)
            self._write_stimulus(tmp_path / "stim_b.csv", frames=60)
            plan = self._build_block_mode_plan(MODE_LOOP_BLOCKS, tmp_path, manual_block_frames="120")

            with self.assertRaisesRegex(ValueError, "does not match planned block count"):
                summarize_plan(plan)

    def test_block_mode_summary_rejects_non_numeric_or_non_positive_manual_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "stim_a.csv", frames=60)
            self._write_stimulus(tmp_path / "stim_b.csv", frames=60)

            non_numeric_plan = self._build_block_mode_plan(MODE_CONTINUOUS_SESSION, tmp_path, manual_block_frames="120, abc")
            with self.assertRaisesRegex(ValueError, "non-numeric value"):
                summarize_plan(non_numeric_plan)

            non_positive_plan = self._build_block_mode_plan(MODE_CONTINUOUS_SESSION, tmp_path, manual_block_frames="120, 0")
            with self.assertRaisesRegex(ValueError, "positive integers"):
                summarize_plan(non_positive_plan)

    def test_block_mode_summary_uses_block_frames_formula(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "stim_a.csv", frames=60)
            self._write_stimulus(tmp_path / "stim_b.csv", frames=60)
            plan = self._build_block_mode_plan(
                MODE_CONTINUOUS_SESSION,
                tmp_path,
                manual_block_frames="60, 90",
                framerate=4,
            )

            summary = summarize_plan(plan)

            self.assertEqual(summary["derived_planes_per_block"], [4.0, 6.0])
            self.assertEqual(summary["derived_total_planes"], 10.0)

    def test_summary_keys_are_mode_specific_for_manual_block_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "stim_a.csv", frames=60)
            self._write_stimulus(tmp_path / "stim_b.csv", frames=60)

            loop_stimuli_defaults = get_mode_defaults(MODE_LOOP_STIMULI)
            metadata, functional, stimuli_params, runtime = prepare_run_config(
                MODE_LOOP_STIMULI,
                loop_stimuli_defaults["metadata"],
                loop_stimuli_defaults["functional_params"],
                loop_stimuli_defaults["stimuli_params"],
                loop_stimuli_defaults["runtime"],
                tmp_path,
            )
            loop_stimuli_catalog = load_stimuli_catalog(tmp_path, MODE_LOOP_STIMULI)
            loop_stimuli_plan = build_run_plan(
                MODE_LOOP_STIMULI,
                metadata,
                functional,
                stimuli_params,
                runtime,
                loop_stimuli_catalog,
            )
            loop_stimuli_summary = summarize_plan(loop_stimuli_plan)
            self.assertNotIn("manual_block_frames", loop_stimuli_summary)
            self.assertNotIn("derived_planes_per_block", loop_stimuli_summary)
            self.assertNotIn("derived_total_planes", loop_stimuli_summary)

            loop_blocks_plan = self._build_block_mode_plan(MODE_LOOP_BLOCKS, tmp_path, manual_block_frames="120, 180")
            loop_blocks_summary = summarize_plan(loop_blocks_plan)
            self.assertIn("manual_block_frames", loop_blocks_summary)
            self.assertIn("derived_planes_per_block", loop_blocks_summary)
            self.assertIn("derived_total_planes", loop_blocks_summary)

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
            self.assertTrue(any(name.endswith("_planned_schedule.csv") for name in written_files))
            metadata_files = [path for path in meta_dir.iterdir() if path.name.endswith("_metadata.csv")]
            self.assertEqual(len(metadata_files), 1)

            metadata_df = pd.read_csv(metadata_files[0])
            metadata_map = dict(zip(metadata_df["parameter"], metadata_df["value"]))
            self.assertEqual(str(metadata_map["mock_mode"]).lower(), "true")
            self.assertEqual(int(metadata_map["planned_total_trials"]), plan.total_trials)

    def test_sample_fixture_catalog_loads(self) -> None:
        catalog = load_stimuli_catalog(SAMPLE_STIMULI_DIR, MODE_LOOP_STIMULI)
        self.assertGreaterEqual(len(catalog), 2)
        self.assertTrue(all(stim.frame_count > 0 for stim in catalog))

    def test_infer_stimulus_type_groups_variants(self) -> None:
        self.assertEqual(infer_stimulus_type("LeConti_trajectory"), "LeConti")
        self.assertEqual(infer_stimulus_type("loom-left-fast"), "loom")
        self.assertEqual(infer_stimulus_type("stimulus"), "stimulus")
        self.assertEqual(infer_stimulus_type(""), "unknown")

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
        manual_block_frames: str,
        framerate: float = 2,
    ):
        defaults = get_mode_defaults(mode)
        defaults["stimuli_params"]["n_rep_stim"] = 2
        defaults["stimuli_params"]["n_trials_per_block"] = 2
        defaults["stimuli_params"]["pre_stim_resting_sec"] = 0
        defaults["stimuli_params"]["pre_stim_pause_sec"] = 0
        defaults["stimuli_params"]["post_stim_pause_sec"] = 0
        defaults["stimuli_params"]["inter_block_pause_sec"] = 0
        defaults["stimuli_params"]["manual_block_frames"] = manual_block_frames
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
