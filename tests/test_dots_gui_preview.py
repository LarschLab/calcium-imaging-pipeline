import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "visual_stimulation"))

from dots_gui import (  # noqa: E402
    build_base_preview_summary,
    enrich_preview_summary_with_manual_block_frames,
)
from dots_protocol import (  # noqa: E402
    MODE_CONTINUOUS_SESSION,
    MODE_LOOP_BLOCKS,
    MODE_LOOP_STIMULI,
    build_run_plan,
    get_mode_defaults,
    load_stimuli_catalog,
    prepare_run_config,
)


class DotsGuiPreviewSummaryTests(unittest.TestCase):
    def test_block_mode_blank_manual_frames_keeps_base_preview_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "stim_a.csv", frames=60)
            self._write_stimulus(tmp_path / "stim_b.csv", frames=60)
            plan = self._build_block_mode_plan(MODE_LOOP_BLOCKS, tmp_path, manual_block_frames="")

            base_summary = build_base_preview_summary(plan)
            summary_text, run_block_reason = enrich_preview_summary_with_manual_block_frames(plan, base_summary)

            self.assertIn("Mode:", base_summary)
            self.assertIn("Trials:", base_summary)
            self.assertTrue(summary_text.startswith(base_summary))
            self.assertIn("Derived planes per block: unavailable", summary_text)
            self.assertIsNotNone(run_block_reason)
            self.assertIn("required for block-based modes", run_block_reason or "")

    def test_block_mode_invalid_manual_frames_keep_preview_and_block_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "stim_a.csv", frames=60)
            self._write_stimulus(tmp_path / "stim_b.csv", frames=60)
            cases = (
                ("120", "does not match planned block count"),
                ("120, abc", "non-numeric value"),
                ("120, 0", "positive integers"),
            )
            for manual_block_frames, expected_error in cases:
                with self.subTest(manual_block_frames=manual_block_frames):
                    plan = self._build_block_mode_plan(MODE_CONTINUOUS_SESSION, tmp_path, manual_block_frames)
                    base_summary = build_base_preview_summary(plan)
                    summary_text, run_block_reason = enrich_preview_summary_with_manual_block_frames(plan, base_summary)

                    self.assertTrue(summary_text.startswith(base_summary))
                    self.assertIn("Derived final planes: unavailable", summary_text)
                    self.assertIsNotNone(run_block_reason)
                    self.assertIn(expected_error, run_block_reason or "")

    def test_block_mode_valid_manual_frames_show_derived_planes_and_allow_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self._write_stimulus(tmp_path / "stim_a.csv", frames=60)
            self._write_stimulus(tmp_path / "stim_b.csv", frames=60)
            plan = self._build_block_mode_plan(MODE_LOOP_BLOCKS, tmp_path, manual_block_frames="120, 180")

            base_summary = build_base_preview_summary(plan)
            summary_text, run_block_reason = enrich_preview_summary_with_manual_block_frames(plan, base_summary)

            self.assertIn("Manual frame list: 120, 180", summary_text)
            self.assertIn("Derived planes per block: Block 1: 4.00, Block 2: 6.00", summary_text)
            self.assertIn("Derived final planes: 10.00", summary_text)
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
            summary_text, run_block_reason = enrich_preview_summary_with_manual_block_frames(plan, base_summary)

            self.assertEqual(summary_text, base_summary)
            self.assertNotIn("Manual frame list:", summary_text)
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
    def _build_block_mode_plan(mode: str, stimuli_dir: Path, manual_block_frames: str):
        defaults = get_mode_defaults(mode)
        defaults["stimuli_params"]["n_rep_stim"] = 2
        defaults["stimuli_params"]["n_trials_per_block"] = 2
        defaults["stimuli_params"]["pre_stim_resting_sec"] = 0
        defaults["stimuli_params"]["pre_stim_pause_sec"] = 0
        defaults["stimuli_params"]["post_stim_pause_sec"] = 0
        defaults["stimuli_params"]["inter_block_pause_sec"] = 0
        defaults["stimuli_params"]["manual_block_frames"] = manual_block_frames
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
