from __future__ import annotations

import sys
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "visual_stimulation"))

from dots_gui import (  # noqa: E402
    BASE_TIMELINE_COLORS,
    DARK_CONSOLE_THEME,
    DARK_TTK_STYLE_NAMES,
    DEFAULT_INITIAL_MODE,
    FORM_GROUP_COLUMNS,
    GUI_SETTINGS_FUNCTIONAL_PARAMS_BY_MODE_KEY,
    GUI_SETTINGS_STIMULI_PARAMS_BY_MODE_KEY,
    INPUT_GROUP_ROWS,
    DotsGuiApp,
    build_compact_preview_summary,
    build_pre_run_checklist_items,
    build_remembered_gui_settings,
    build_timeline_segment_description,
    clamp_timeline_view,
    compute_legend_grid_positions,
    compute_group_grid_positions,
    collect_timeline_stimulus_identities,
    count_unique_presented_stimuli,
    derive_standard_trials_per_block,
    format_field_label,
    format_block_volume_count,
    load_gui_settings,
    pan_timeline_view,
    save_gui_settings,
    should_show_fish_alignment,
    visible_timeline_block_spans,
    zoom_timeline_view,
)
from dots_protocol import (  # noqa: E402
    DotsRunPlan,
    MODE_CONTINUOUS_SESSION,
    MODE_LOOP_BLOCKS,
    MODE_LOOP_STIMULI,
    PlannedBlock,
    PlannedTrial,
    StimulusSpec,
    TimelineSegment,
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

    def test_compact_preview_summary_is_single_line(self) -> None:
        plan = DotsRunPlan(
            mode=MODE_LOOP_BLOCKS,
            metadata={},
            functional_params={"n_volumes": 1610},
            stimuli_params={},
            runtime={"mock_mode": False},
            stimuli_catalog=[self._stimulus("stim_a", "stim_a"), self._stimulus("stim_b", "stim_b")],
            trials=[
                PlannedTrial(0, 1, "stim_a", "stim_a", Path("stim_a.csv"), 60, 1, 1.0),
                PlannedTrial(1, 1, "stim_b", "stim_b", Path("stim_b.csv"), 60, 1, 1.0),
            ],
            planned_blocks=[PlannedBlock(0, [], 0, 2, 2, 4), PlannedBlock(1, [0, 1], 3, 5, 2, 4)],
            timeline=[],
            total_duration_sec=5,
        )

        summary = build_compact_preview_summary(plan)

        self.assertEqual(
            summary,
            "Loop Blocks | 2 stimuli | 2 trials | 0:05 total | 1610 volumes | 2 blocks | Mock: no",
        )
        self.assertNotIn("\n", summary)

    def test_run_plan_prints_diagnostics_around_runner_call(self) -> None:
        app = self._fake_app_for_run(mock_mode=True)

        with (
            patch("dots_gui.PreRunChecklistDialog", return_value=type("Checklist", (), {"accepted": True})()),
            patch("dots_gui.run_planned_experiment", return_value=Path("/tmp/meta")),
            patch("dots_gui.messagebox.showinfo"),
            patch("builtins.print") as print_mock,
        ):
            app.run_plan()

        messages = [call.args[0] for call in print_mock.call_args_list]
        self.assertIn("[dots_gui] Run button handler entered", messages)
        self.assertIn("[dots_gui] Pre-run checklist accepted", messages)
        self.assertIn("[dots_gui] GUI withdrawn", messages)
        self.assertIn("[dots_gui] Calling run_planned_experiment()", messages)
        self.assertIn("[dots_gui] run_planned_experiment() returned: /tmp/meta", messages)

    def test_run_plan_prints_diagnostics_when_runner_raises(self) -> None:
        app = self._fake_app_for_run(mock_mode=True)

        with (
            patch("dots_gui.PreRunChecklistDialog", return_value=type("Checklist", (), {"accepted": True})()),
            patch("dots_gui.run_planned_experiment", side_effect=RuntimeError("boom")),
            patch("dots_gui.messagebox.showerror"),
            patch("builtins.print") as print_mock,
        ):
            app.run_plan()

        messages = [call.args[0] for call in print_mock.call_args_list]
        self.assertIn("[dots_gui] Calling run_planned_experiment()", messages)
        self.assertIn("[dots_gui] run_planned_experiment() raised: boom", messages)

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

    def test_timeline_stimulus_identities_use_full_stems(self) -> None:
        timeline = [
            TimelineSegment(order=0, kind="stimulus", start_sec=0, duration_sec=1, label="a", stimulus_name="Ll_RB_trajectory"),
            TimelineSegment(order=1, kind="stimulus", start_sec=1, duration_sec=1, label="b", stimulus_name="Ll_RC_trajectory"),
            TimelineSegment(order=2, kind="stimulus", start_sec=2, duration_sec=1, label="c", stimulus_name="Rl_RB_trajectory"),
            TimelineSegment(order=3, kind="stimulus", start_sec=3, duration_sec=1, label="d", stimulus_name="Rl_RC_trajectory"),
        ]

        identities = collect_timeline_stimulus_identities(timeline)

        self.assertEqual(
            identities,
            [
                "Ll_RB_trajectory",
                "Ll_RC_trajectory",
                "Rl_RB_trajectory",
                "Rl_RC_trajectory",
            ],
        )
        self.assertNotIn("Ll", identities)
        self.assertNotIn("Rl", identities)

    def test_dark_console_palette_covers_timeline_and_block_guides(self) -> None:
        self.assertEqual(
            set(BASE_TIMELINE_COLORS),
            {"rest", "prestim_pause", "poststim_pause", "interblock_pause"},
        )
        for color_key in (
            "canvas_bg",
            "grid",
            "trigger",
            "hover_outline",
            "baseline_block",
            "stimulus_block",
            "primary",
            "panel_bg",
            "text_fg",
        ):
            self.assertRegex(DARK_CONSOLE_THEME[color_key], r"^#[0-9a-fA-F]{6}$")

    def test_dark_console_theme_uses_tk_labelframe_style_names(self) -> None:
        self.assertIn("TLabelframe", DARK_TTK_STYLE_NAMES)
        self.assertIn("TLabelframe.Label", DARK_TTK_STYLE_NAMES)
        self.assertNotIn("TLabelFrame", DARK_TTK_STYLE_NAMES)
        self.assertNotIn("TLabelFrame.Label", DARK_TTK_STYLE_NAMES)

    def test_timeline_view_clamps_to_total_duration(self) -> None:
        self.assertEqual(clamp_timeline_view(-5, 20, 10), (0.0, 10.0))
        self.assertEqual(clamp_timeline_view(8, 14, 10), (4.0, 10.0))

    def test_timeline_zoom_preserves_anchor_and_clamps(self) -> None:
        start, end = zoom_timeline_view(0, 100, 100, 25, 0.5)
        self.assertEqual((start, end), (12.5, 62.5))

        start, end = zoom_timeline_view(start, end, 100, 25, 10)
        self.assertEqual((start, end), (0.0, 100.0))

    def test_timeline_pan_clamps_at_bounds(self) -> None:
        self.assertEqual(pan_timeline_view(10, 30, 100, -15), (0.0, 20.0))
        self.assertEqual(pan_timeline_view(70, 90, 100, 20), (80.0, 100.0))

    def test_visible_timeline_block_spans_clip_to_viewport(self) -> None:
        blocks = [
            PlannedBlock(
                block_num=0,
                trial_indices=[],
                start_sec=0,
                end_sec=10,
                duration_sec=10,
                acquisition_frame_count=20,
                block_kind="baseline_rest",
            ),
            PlannedBlock(
                block_num=1,
                trial_indices=[0],
                start_sec=15,
                end_sec=30,
                duration_sec=15,
                acquisition_frame_count=30,
            ),
            PlannedBlock(
                block_num=2,
                trial_indices=[1],
                start_sec=40,
                end_sec=50,
                duration_sec=10,
                acquisition_frame_count=20,
            ),
        ]

        spans = visible_timeline_block_spans(blocks, 5, 35)

        self.assertEqual(
            [(block.block_num, block.block_kind, start, end) for block, start, end in spans],
            [(0, "baseline_rest", 5, 10), (1, "stimulus_block", 15, 30)],
        )

    def test_visible_timeline_block_spans_omit_outside_and_zero_width_blocks(self) -> None:
        blocks = [
            PlannedBlock(block_num=0, trial_indices=[], start_sec=0, end_sec=5, duration_sec=5, acquisition_frame_count=10),
            PlannedBlock(block_num=1, trial_indices=[], start_sec=6, end_sec=6, duration_sec=0, acquisition_frame_count=0),
            PlannedBlock(block_num=2, trial_indices=[], start_sec=8, end_sec=12, duration_sec=4, acquisition_frame_count=8),
        ]

        spans = visible_timeline_block_spans(blocks, 6, 7)

        self.assertEqual(spans, [])

    def test_timeline_segment_description_includes_stimulus_details(self) -> None:
        plan = self._plan_for_timeline_description()
        segment = TimelineSegment(
            order=1,
            kind="stimulus",
            start_sec=2.0,
            duration_sec=0.5,
            label="stim_a",
            trial_index=0,
            block_num=1,
            stimulus_key="stim",
            stimulus_name="stim_a",
            stimulus_path="stim_a.csv",
        )

        description = build_timeline_segment_description(plan, segment)

        self.assertIn("stim_a", description)
        self.assertIn("Duration: 30 frames / 0.50 sec", description)
        self.assertIn("Block: B1", description)
        self.assertIn("Trial: 1", description)
        self.assertIn("Dots: 3", description)
        self.assertIn("Path: stim_a.csv", description)

    def test_timeline_segment_description_labels_video_stimuli(self) -> None:
        plan = self._plan_for_timeline_description(media_type="video", stimulus_path=Path("stim_a.mp4"), n_dots=0)
        segment = TimelineSegment(
            order=1,
            kind="stimulus",
            start_sec=2.0,
            duration_sec=0.5,
            label="stim_a",
            trial_index=0,
            block_num=1,
            stimulus_key="stim",
            stimulus_name="stim_a",
            stimulus_path="stim_a.mp4",
        )

        description = build_timeline_segment_description(plan, segment)

        self.assertIn("Media: MP4 video", description)
        self.assertNotIn("Dots: 0", description)
        self.assertIn("Path: stim_a.mp4", description)

    def test_timeline_segment_description_includes_pause_duration_frames(self) -> None:
        plan = self._plan_for_timeline_description()
        segment = TimelineSegment(
            order=2,
            kind="poststim_pause",
            start_sec=2.5,
            duration_sec=1.25,
            label="Trial 1 post-pause",
            trial_index=0,
            block_num=1,
            stimulus_key="stim",
            stimulus_name="stim_a",
        )

        description = build_timeline_segment_description(plan, segment)

        self.assertIn("Type: poststim pause", description)
        self.assertIn("Duration: 75 frames / 1.25 sec", description)
        self.assertIn("Stimulus: stim_a", description)

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

    @staticmethod
    def _plan_for_timeline_description(
        media_type: str = "csv",
        stimulus_path: Path = Path("stim_a.csv"),
        n_dots: int = 3,
    ) -> DotsRunPlan:
        return DotsRunPlan(
            mode=MODE_LOOP_BLOCKS,
            metadata={},
            functional_params={},
            stimuli_params={},
            runtime={},
            stimuli_catalog=[],
            trials=[
                PlannedTrial(
                    trial_index=0,
                    block_num=1,
                    stimulus_key="stim",
                    stimulus_name="stim_a",
                    stimulus_path=stimulus_path,
                    frame_count=30,
                    n_dots=n_dots,
                    duration_sec=0.5,
                    media_type=media_type,
                )
            ],
            planned_blocks=[],
            timeline=[],
            total_duration_sec=4,
        )

    @staticmethod
    def _fake_app_for_run(mock_mode: bool) -> DotsGuiApp:
        app = object.__new__(DotsGuiApp)

        class Root:
            def withdraw(self) -> None:
                pass

            def deiconify(self) -> None:
                pass

            def destroy(self) -> None:
                pass

        class Status:
            def set(self, _: str) -> None:
                pass

        app.root = Root()
        app.status_var = Status()
        app.run_block_reason = None
        app.preview_is_current = True
        app.current_plan = DotsRunPlan(
            mode=MODE_LOOP_STIMULI,
            metadata={"fish_orientation": "bottom-left"},
            functional_params={},
            stimuli_params={},
            runtime={"mock_mode": mock_mode},
            stimuli_catalog=[],
            trials=[],
            planned_blocks=[],
            timeline=[],
            total_duration_sec=0,
        )
        return app


if __name__ == "__main__":
    unittest.main()
