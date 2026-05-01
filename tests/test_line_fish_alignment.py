from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "visual_stimulation"))

import line_fish_alignment  # noqa: E402


class LineFishAlignmentTests(unittest.TestCase):
    def test_module_import_has_no_psychopy_side_effects(self) -> None:
        self.assertTrue(hasattr(line_fish_alignment, "show_fish_alignment"))

    def test_alignment_geometry_matches_existing_dot_positions(self) -> None:
        top_right = line_fish_alignment.compute_alignment_geometry("top-right", 10)
        bottom_left = line_fish_alignment.compute_alignment_geometry("bottom-left", 10)

        self.assertTrue(top_right["dot_pos"][0] < 0)
        self.assertTrue(top_right["dot_pos"][1] > 0)
        self.assertTrue(bottom_left["dot_pos"][0] > 0)
        self.assertTrue(bottom_left["dot_pos"][1] < 0)
        self.assertAlmostEqual(top_right["dot_size"], 1.0)
        self.assertAlmostEqual(bottom_left["dot_size"], 1.0)
        self.assertAlmostEqual(top_right["line_start"][0], -line_fish_alignment.LINE_LENGTH_CM * 10 / math.sqrt(2))

    def test_alignment_geometry_rejects_unknown_dot_position(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported dot position"):
            line_fish_alignment.compute_alignment_geometry("center", 10)


if __name__ == "__main__":
    unittest.main()
