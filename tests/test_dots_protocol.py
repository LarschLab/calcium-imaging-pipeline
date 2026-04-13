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
    build_run_plan,
    get_mode_defaults,
    load_stimuli_catalog,
    plan_to_schedule_rows,
    prepare_run_config,
)


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


if __name__ == "__main__":
    unittest.main()
