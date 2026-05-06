from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "visual_stimulation"))

import visual_test_bouts  # noqa: E402


class VisualTestBoutsTests(unittest.TestCase):
    def test_module_import_has_no_psychopy_side_effects(self) -> None:
        self.assertTrue(hasattr(visual_test_bouts, "main"))

    def test_parse_args_accepts_gui_supplied_fish_orientation(self) -> None:
        args = visual_test_bouts.parse_args(["--fish-orientation", "top-right"])

        self.assertEqual(args.fish_orientation, "top-right")

    def test_parse_args_defaults_to_dialog_orientation(self) -> None:
        args = visual_test_bouts.parse_args([])

        self.assertIsNone(args.fish_orientation)


if __name__ == "__main__":
    unittest.main()
