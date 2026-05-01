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
    GUI_SETTINGS_FUNCTIONAL_PARAMS_BY_MODE_KEY,
    GUI_SETTINGS_STIMULI_PARAMS_BY_MODE_KEY,
    INPUT_GROUP_ROWS,
    build_pre_run_checklist_items,
    build_remembered_gui_settings,
    compute_legend_grid_positions,
    compute_group_grid_positions,
    count_unique_presented_stimuli,
    derive_standard_trials_per_block,
    format_field_label,
    format_block_volume_count,
    load_gui_settings,
    save_gui_settings,
    should_show_fish_alignment,
)
from dots_protocol import (  # noqa: E402
    DotsRunPlan,
    MODE_CONTINUOUS_SESSION,
    MODE_LOOP_BLOCKS,
    MODE_LOOP_STIMULI,
    PlannedBlock,
    StimulusSpec,
    get_mode_defaults,
)


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

    def test_block_mode_fish_id_defaults_are_string_typed(self) -> None:
        self.assertIsInstance(get_mode_defaults(MODE_LOOP_BLOCKS)["metadata"]["fish_ID"], str)
        self.assertIsInstance(get_mode_defaults(MODE_CONTINUOUS_SESSION)["metadata"]["fish_ID"], str)

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
            {MODE_LOOP_BLOCKS: {"n_rep_stim": 4}},
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

    def test_remembered_gui_settings_store_functional_params_per_mode_without_derived_fields(self) -> None:
        settings = build_remembered_gui_settings(
            {"experiment_name": "exp"},
            "/stimuli",
            MODE_LOOP_BLOCKS,
            {"n_rep_stim": 4},
            None,
            {
                "n_frames": 3,
                "n_slices": 5,
                "n_volumes": 8,
                "framerate": 2.0,
                "AOM_mW": 32,
            },
        )

        self.assertEqual(
            settings[GUI_SETTINGS_FUNCTIONAL_PARAMS_BY_MODE_KEY],
            {MODE_LOOP_BLOCKS: {"n_frames": 3, "n_slices": 5, "AOM_mW": 32}},
        )

    def test_max_n_dots_defaults_remain_mode_specific(self) -> None:
        self.assertEqual(get_mode_defaults(MODE_LOOP_STIMULI)["stimuli_params"]["max_n_dots"], 5)
        self.assertEqual(get_mode_defaults(MODE_LOOP_BLOCKS)["stimuli_params"]["max_n_dots"], 6)
        self.assertEqual(get_mode_defaults(MODE_CONTINUOUS_SESSION)["stimuli_params"]["max_n_dots"], 6)

    def test_stimulus_field_labels_use_operator_friendly_text(self) -> None:
        self.assertEqual(format_field_label("stimuli_params", "pre_stim_resting_sec"), "Pre-stim rest (s)")
        self.assertEqual(format_field_label("stimuli_params", "pre_stim_pause_sec"), "Pre-stim pause (s)")
        self.assertEqual(format_field_label("stimuli_params", "post_stim_pause_sec"), "Post-stim pause (s)")
        self.assertEqual(format_field_label("stimuli_params", "inter_block_pause_sec"), "Inter-block pause (s)")
        self.assertEqual(format_field_label("stimuli_params", "n_trials_per_block"), "Stimuli / block")
        self.assertEqual(format_field_label("stimuli_params", "n_rep_stim"), "Stimuli repetitions")
        self.assertEqual(format_field_label("stimuli_params", "max_n_dots"), "Max number of dots")

    def test_metadata_and_functional_field_labels_use_operator_friendly_text(self) -> None:
        self.assertEqual(format_field_label("metadata", "fish_ID"), "Fish ID")
        self.assertEqual(format_field_label("metadata", "fish_age_dpf"), "Fish age (dpf)")
        self.assertEqual(format_field_label("metadata", "respond_to_omr"), "Responds to OMR")
        self.assertEqual(format_field_label("functional_params", "n_frames"), "Frames / plane")
        self.assertEqual(format_field_label("functional_params", "n_slices"), "Number of planes")
        self.assertEqual(format_field_label("functional_params", "AOM_mW"), "AOM power (mW)")

    def test_field_label_fallback_does_not_change_parameter_key(self) -> None:
        self.assertEqual(format_field_label("metadata", "future_field_name"), "future field name")

    def test_legend_positions_wrap_after_entries_per_row(self) -> None:
        self.assertEqual(
            compute_legend_grid_positions(6, 4),
            [(0, 0), (0, 2), (0, 4), (0, 6), (1, 0), (1, 2)],
        )

    def test_legend_positions_reject_non_positive_entries_per_row(self) -> None:
        with self.assertRaises(ValueError):
            compute_legend_grid_positions(1, 0)

    def test_unique_presented_stimuli_counts_runtime_keys(self) -> None:
        catalog = [
            self._stimulus("stim_a", "stim"),
            self._stimulus("stim_b", "stim"),
            self._stimulus("control", "control"),
        ]

        self.assertEqual(count_unique_presented_stimuli(catalog), 2)

    def test_standard_trials_per_block_is_twice_unique_presented_stimuli(self) -> None:
        catalog = [
            self._stimulus("stim_a", "stim"),
            self._stimulus("stim_b", "stim"),
            self._stimulus("control", "control"),
        ]

        self.assertEqual(derive_standard_trials_per_block(catalog), 4)

    def test_block_volume_count_formats_single_planned_block_volume(self) -> None:
        plan = DotsRunPlan(
            mode=MODE_LOOP_BLOCKS,
            metadata={},
            functional_params={},
            stimuli_params={},
            runtime={},
            stimuli_catalog=[],
            trials=[],
            planned_blocks=[
                PlannedBlock(block_num=0, trial_indices=[0, 1], start_sec=0, end_sec=2, duration_sec=2, acquisition_frame_count=4),
                PlannedBlock(block_num=1, trial_indices=[2, 3], start_sec=5, end_sec=7, duration_sec=2, acquisition_frame_count=4),
            ],
            timeline=[],
            total_duration_sec=7,
        )

        self.assertEqual(format_block_volume_count(plan), "4 volumes")

    def test_pre_run_checklist_items_include_block_volumes_and_light_path(self) -> None:
        plan = DotsRunPlan(
            mode=MODE_LOOP_BLOCKS,
            metadata={"fish_orientation": "top-right"},
            functional_params={},
            stimuli_params={},
            runtime={},
            stimuli_catalog=[],
            trials=[],
            planned_blocks=[
                PlannedBlock(block_num=0, trial_indices=[0, 1], start_sec=0, end_sec=2, duration_sec=2, acquisition_frame_count=4),
            ],
            timeline=[],
            total_duration_sec=2,
        )

        checklist_items = build_pre_run_checklist_items(plan)

        self.assertTrue(any("top-right alignment marker" in item for item in checklist_items))
        self.assertTrue(any("4 volumes" in item for item in checklist_items))
        self.assertTrue(any("light-path levers" in item for item in checklist_items))

    def test_fish_alignment_is_skipped_for_mock_runs_only(self) -> None:
        hardware_plan = DotsRunPlan(
            mode=MODE_LOOP_BLOCKS,
            metadata={},
            functional_params={},
            stimuli_params={},
            runtime={"mock_mode": False},
            stimuli_catalog=[],
            trials=[],
            planned_blocks=[],
            timeline=[],
            total_duration_sec=0,
        )
        mock_plan = DotsRunPlan(
            mode=MODE_LOOP_BLOCKS,
            metadata={},
            functional_params={},
            stimuli_params={},
            runtime={"mock_mode": True},
            stimuli_catalog=[],
            trials=[],
            planned_blocks=[],
            timeline=[],
            total_duration_sec=0,
        )

        self.assertTrue(should_show_fish_alignment(hardware_plan))
        self.assertFalse(should_show_fish_alignment(mock_plan))

    @staticmethod
    def _stimulus(display_name: str, runtime_key: str) -> StimulusSpec:
        return StimulusSpec(
            runtime_key=runtime_key,
            display_name=display_name,
            path=Path(f"{display_name}.csv"),
            frame_count=1,
            n_dots=1,
            duration_sec=1 / 60,
            data_frame=None,
        )


if __name__ == "__main__":
    unittest.main()
