"""Find an experiment's fish and their data folders.

Reads the Paper overview table to list one experiment's fish (leaving out
excluded ones) and locates each fish's data folder by name. Kept apart from
`batch_registration.py` so notebooks that only need the fish list (e.g. the
reference-registration QC) don't have to import ANTs.
"""

import csv
from pathlib import Path

from preprocessing.anatomy_averaging import index_fish_folders

EXCLUDED_DECISION = "exclude"


def list_experiment_fish(overview_csv, experiment):
    """List one experiment's fish from the Paper overview, leaving out excluded ones.

    Args:
        overview_csv (Path): `2p_derived/global/overview.csv`.
        experiment (str): Experiment name, e.g. "Exp_9_RF_memory_inhibition".

    Returns:
        list: dicts with `fish_id` and `final_decision`, in overview order.
    """
    with Path(overview_csv).open(newline="", encoding="utf-8-sig") as overview_file:
        rows = list(csv.DictReader(overview_file))
    experiment_fish = [
        {"fish_id": row["Fish"], "final_decision": row["Final decision"]}
        for row in rows
        if row["Experiment"] == experiment and row["Final decision"] != EXCLUDED_DECISION
    ]
    return experiment_fish


def find_experiment_fish_folders(data_root, experiment_fish):
    """Locate each fish's data folder by the fish ID at the start of the folder name.

    Args:
        data_root (Path): Folder holding one sub-folder per fish.
        experiment_fish (list): From `list_experiment_fish`.

    Returns:
        dict: fish_id -> Path, or None if zero or several folders match.
    """
    folders_by_fish = index_fish_folders(data_root)
    fish_folders = {}
    for fish in experiment_fish:
        matches = folders_by_fish.get(fish["fish_id"], [])
        fish_folders[fish["fish_id"]] = matches[0] if len(matches) == 1 else None
    return fish_folders
