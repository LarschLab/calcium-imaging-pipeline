import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "visual_stimulation"))

from dots_gui import (  # noqa: E402
    build_base_preview_summary,
    enrich_preview_summary_with_block_planning,
)
from dots_protocol import (  # noqa: E402
    MODE_LOOP_BLOCKS,
    MODE_LOOP_STIMULI,
    build_run_plan,
    get_mode_defaults,
    load_stimuli_catalog,
    prepare_run_config,
)


class DotsGuiPreviewSummaryTests(unittest.TestCase):
    def test_block_mode_preview_shows_computed_block_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "stim_a.csv", frames=60)
            self._write_stimulus(tmp_path / "stim_b.csv", frames=60)
            self._write_stimulus(tmp_path / "stim_c.csv", frames=60)
            self._write_stimulus(tmp_path / "stim_d.csv", frames=60)
            plan = self._build_block_mode_plan(tmp_path)

            base_summary = build_base_preview_summary(plan)
            summary_text, run_block_reason = enrich_preview_summary_with_block_planning(plan, base_summary)

            self.assertTrue(summary_text.startswith(base_summary))
            self.assertIn("Planned blocks: 2", summary_text)
            self.assertIn("B0: 0:04 (4.50 sec, 9 frames)", summary_text)
            self.assertIn("B1: 0:02 (2.00 sec, 4 frames)", summary_text)
            self.assertIn("Total planned acquisition frames: 13", summary_text)
            self.assertNotIn("Manual frame list", summary_text)
            self.assertIsNone(run_block_reason)

    def test_loop_stimuli_mode_preview_summary_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "stim_a.csv", frames=60)
            self._write_stimulus(tmp_path / "stim_b.csv", frames=60)
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

            base_summary = build_base_preview_summary(plan)
            summary_text, run_block_reason = enrich_preview_summary_with_block_planning(plan, base_summary)

            self.assertEqual(summary_text, base_summary)
            self.assertIsNone(run_block_reason)

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
    def _build_block_mode_plan(stimuli_dir: Path):
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
            stimuli_dir,
        )
        catalog = load_stimuli_catalog(stimuli_dir, MODE_LOOP_BLOCKS)
        return build_run_plan(MODE_LOOP_BLOCKS, metadata, functional, stimuli_params, runtime, catalog)


if __name__ == "__main__":
    unittest.main()
