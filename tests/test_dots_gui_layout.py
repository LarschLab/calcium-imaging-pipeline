from __future__ import annotations

import sys
import unittest
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "visual_stimulation"))

from dots_gui import (  # noqa: E402
    DEFAULT_INITIAL_MODE,
    FORM_GROUP_COLUMNS,
    GUI_SETTINGS_STIMULI_PARAMS_BY_MODE_KEY,
    INPUT_GROUP_ROWS,
    build_remembered_gui_settings,
    compute_legend_grid_positions,
    compute_group_grid_positions,
    load_gui_settings,
    save_gui_settings,
)
from dots_protocol import MODE_LOOP_BLOCKS, MODE_LOOP_STIMULI  # noqa: E402


class DotsGuiLayoutTests(unittest.TestCase):
    def test_group_positions_use_fixed_three_column_row(self) -> None:
        positions = compute_group_grid_positions(INPUT_GROUP_ROWS, FORM_GROUP_COLUMNS)
        self.assertEqual(positions["metadata"], (0, 0))
        self.assertEqual(positions["functional_params"], (0, 1))
        self.assertEqual(positions["stimuli_params"], (0, 2))

    def test_group_positions_wrap_after_column_count(self) -> None:
        positions = compute_group_grid_positions(("a", "b", "c", "d"), 3)
        self.assertEqual(positions["d"], (1, 0))

    def test_group_positions_reject_non_positive_columns(self) -> None:
        with self.assertRaises(ValueError):
            compute_group_grid_positions(("metadata",), 0)

    def test_standalone_gui_defaults_to_loop_blocks(self) -> None:
        self.assertEqual(DEFAULT_INITIAL_MODE, MODE_LOOP_BLOCKS)

    def test_remembered_gui_settings_include_only_operator_fields_and_stimuli_dir(self) -> None:
        settings = build_remembered_gui_settings(
            {
                "experiment_name": "exp",
                "experimenter": "operator",
                "fish_ID": "F001",
                "fish_birth": "2026-01-20",
                "genotype": "huc:H2B-GCamp6s",
                "fish_age_dpf": 100,
                "path_to_stimuli": "/ignored",
            },
            "/stimuli",
        )

        self.assertEqual(
            settings,
            {
                "metadata": {
                    "experiment_name": "exp",
                    "experimenter": "operator",
                    "fish_ID": "F001",
                    "fish_birth": "2026-01-20",
                    "genotype": "huc:H2B-GCamp6s",
                },
                "stimuli_dir": "/stimuli",
            },
        )

    def test_gui_settings_round_trip_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            expected = {
                "metadata": {"experimenter": "operator"},
                "stimuli_dir": "/stimuli",
                "ignored_future_key": True,
            }

            save_gui_settings(expected, settings_path)

            self.assertEqual(load_gui_settings(settings_path), expected)

    def test_gui_settings_load_ignores_missing_or_invalid_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = Path(tmpdir) / "missing.json"
            invalid_path = Path(tmpdir) / "invalid.json"
            invalid_path.write_text("{", encoding="utf-8")

            self.assertEqual(load_gui_settings(missing_path), {})
            self.assertEqual(load_gui_settings(invalid_path), {})

    def test_remembered_gui_settings_store_stimulus_params_per_mode(self) -> None:
        settings = build_remembered_gui_settings(
            {"experiment_name": "exp"},
            "/stimuli",
            MODE_LOOP_BLOCKS,
            {"n_rep_stim": 4, "n_trials_per_block": 16},
        )

        self.assertEqual(
            settings[GUI_SETTINGS_STIMULI_PARAMS_BY_MODE_KEY],
            {MODE_LOOP_BLOCKS: {"n_rep_stim": 4, "n_trials_per_block": 16}},
        )

    def test_remembered_gui_settings_preserve_other_mode_stimulus_params(self) -> None:
        existing = {
            GUI_SETTINGS_STIMULI_PARAMS_BY_MODE_KEY: {
                MODE_LOOP_STIMULI: {"n_rep_stim": 2},
            },
        }

        settings = build_remembered_gui_settings(
            {"experiment_name": "exp"},
            "/stimuli",
            MODE_LOOP_BLOCKS,
            {"n_rep_stim": 4},
            existing,
        )

        self.assertEqual(
            settings[GUI_SETTINGS_STIMULI_PARAMS_BY_MODE_KEY],
            {
                MODE_LOOP_STIMULI: {"n_rep_stim": 2},
                MODE_LOOP_BLOCKS: {"n_rep_stim": 4},
            },
        )

    def test_legend_positions_wrap_after_entries_per_row(self) -> None:
        self.assertEqual(
            compute_legend_grid_positions(6, 4),
            [(0, 0), (0, 2), (0, 4), (0, 6), (1, 0), (1, 2)],
        )

    def test_legend_positions_reject_non_positive_entries_per_row(self) -> None:
        with self.assertRaises(ValueError):
            compute_legend_grid_positions(1, 0)


if __name__ == "__main__":
    unittest.main()
