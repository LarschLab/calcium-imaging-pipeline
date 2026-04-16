from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "visual_stimulation"))

from dots_gui import FORM_GROUP_COLUMNS, INPUT_GROUP_ROWS, compute_group_grid_positions  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
