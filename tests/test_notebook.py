"""Validate and execute the visualization notebook with generated fixture data."""

import json
import os
import tempfile
import unittest
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pandas as pd


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = REPOSITORY_ROOT / "notebooks" / "basic_single_fish_analysis.ipynb"


class NotebookTests(unittest.TestCase):
    """Check notebook structure and run its code cells in sequence."""

    def create_fixture_experiment(self, temporary_directory):
        """Create a complete two-block, five-plane experiment fixture.

        Args:
            temporary_directory (Path): Temporary root for generated test data.

        Returns:
            tuple: Experiment directory, stimuli directory, and fish identifier.
        """
        fish_id = "L500_f01"
        experiment_dir = temporary_directory / fish_id
        suite2p_dir = experiment_dir / "03_analysis" / "functional" / "suite2P"
        for plane_index in range(5):
            plane_dir = suite2p_dir / f"plane{plane_index}"
            plane_dir.mkdir(parents=True)
            time_values = np.linspace(0.0, 1.0, 40)[:, None]
            plane_dfof = np.hstack(
                [time_values + plane_index * 0.01, time_values * 0.5]
            )
            np.save(
                plane_dir / f"{fish_id}_plane{plane_index}_dFoF.npy",
                plane_dfof,
            )
            np.save(
                plane_dir / f"{fish_id}_plane{plane_index}_filtered_roi_indices.npy",
                np.array([0, 1]),
            )

        metadata_dir = experiment_dir / "01_raw" / "2p" / "metadata"
        metadata_dir.mkdir(parents=True)
        block_log = pd.DataFrame(
            {
                "event": [
                    "B1_start",
                    "B1_stim1_forward",
                    "B1_stim2_forward",
                    "B2_start",
                    "B2_stim1_forward",
                    "B2_stim2_forward",
                ],
                "timestamp": [0.0, 3.0, 7.0, 0.0, 3.0, 7.0],
            }
        )
        block_log.to_csv(metadata_dir / "fixture_block_log.csv", index=False)

        stimuli_dir = temporary_directory / "stimuli"
        stimuli_dir.mkdir()
        trajectory = pd.DataFrame(
            {"dot_x": [0, 0, 1, 2], "dot_y": [0, 0, 0, 0]}
        )
        trajectory.to_csv(stimuli_dir / "forward_trajectory.csv", index=False)
        return experiment_dir, stimuli_dir, fish_id

    def test_notebook_is_valid_json_with_documented_code_cells(self):
        """Notebook JSON should use version 4 and explain every code step."""
        with NOTEBOOK_PATH.open("r", encoding="utf-8") as notebook_file:
            notebook = json.load(notebook_file)

        self.assertEqual(notebook["nbformat"], 4)
        previous_cell_type = None
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                self.assertEqual(previous_cell_type, "markdown")
                self.assertNotIn("def ", "".join(cell["source"]))
            previous_cell_type = cell["cell_type"]

    def test_notebook_executes_with_generated_fixture(self):
        """Every code cell should execute against a temporary realistic fixture."""
        with tempfile.TemporaryDirectory() as temporary_directory_text:
            temporary_directory = Path(temporary_directory_text)
            experiment_dir, stimuli_dir, fish_id = self.create_fixture_experiment(
                temporary_directory
            )
            with NOTEBOOK_PATH.open("r", encoding="utf-8") as notebook_file:
                notebook = json.load(notebook_file)

            execution_namespace = {
                "__name__": "__main__",
                "EXPERIMENT_DIR": experiment_dir,
                "FISH_ID": fish_id,
                "STIMULI_DIR": stimuli_dir,
                "SELECTED_BLOCKS": ["B1", "B2"],
                "IMAGING_FPS": 2.0,
                "STIMULUS_FPS": 4.0,
                "PLANE_INDICES": "all",
                "PRE_STIMULUS_SEC": 1.0,
                "POST_STIMULUS_SEC": 2.0,
                "RASTER_VMIN": 0.0,
                "RASTER_VMAX": None,
                "SORT_BY_CORRELATION": True,
                "STIMULUS_ORDER": None,
                "SAVE_PLOTS": False,
                "PLOT_DPI": 300,
                "PLOTS_DIR": (
                    experiment_dir / "04_plots" / "basic_calcium_analysis"
                ),
            }
            original_directory = Path.cwd()
            try:
                os.chdir(REPOSITORY_ROOT)
                for cell_index, cell in enumerate(notebook["cells"]):
                    if cell["cell_type"] != "code":
                        continue
                    source = "".join(cell["source"])
                    if source.startswith("EXPERIMENT_DIR ="):
                        continue
                    compiled_cell = compile(
                        source,
                        f"{NOTEBOOK_PATH.name}:cell_{cell_index}",
                        "exec",
                    )
                    exec(compiled_cell, execution_namespace)
            finally:
                os.chdir(original_directory)

            self.assertEqual(execution_namespace["dfof"].shape, (40, 10))
            self.assertEqual(
                execution_namespace["auc_summary"].loc[0, "stimulus"],
                "forward",
            )


if __name__ == "__main__":
    unittest.main()
