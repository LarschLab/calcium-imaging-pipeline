"""Rename suite2p's default output files (ops.npy, stat.npy, ...) to the lab's prefixed names.

Older fish (e.g. Exp_1) kept suite2p's defaults; later ones use
`{fish_id}_plane{i}_<name>`. This renames the defaults in each plane folder so
every fish follows one convention. Run from the repo root:

    python -m tools.prefix_suite2p_files --data-root <Lab/Data/2p> --folder-pattern "*_Exp_1_*" --log <rename_log.csv>          # dry run
    python -m tools.prefix_suite2p_files ... --apply                                                                         # rename

Never overwrites: a file whose prefixed name already exists is skipped and
reported. Every rename is appended to the log CSV (old path, new path, time).
Don't point this at a network drive without confirming with the data owner.
"""

import argparse
import csv
import time
from pathlib import Path

from utils import fish_id_from_folder_name

SUITE2P_DEFAULT_FILES = ("F.npy", "Fneu.npy", "iscell.npy", "ops.npy", "spks.npy", "stat.npy")
SUITE2P_DIR = Path("03_analysis") / "functional" / "suite2P"


def planned_renames(fish_folder):
    """List the renames needed in one fish folder.

    Args:
        fish_folder (Path): Fish folder whose name starts with its fish ID.

    Returns:
        list: `(old_path, new_path, conflict)` tuples; `conflict` is True when
        the prefixed name already exists (that file is then left alone).
    """
    fish_id = fish_id_from_folder_name(fish_folder.name)
    renames = []
    for plane_folder in sorted((fish_folder / SUITE2P_DIR).glob("plane[0-9]*")):
        for file_name in SUITE2P_DEFAULT_FILES:
            old_path = plane_folder / file_name
            if not old_path.exists():
                continue
            new_path = plane_folder / f"{fish_id}_{plane_folder.name}_{file_name}"
            renames.append((old_path, new_path, new_path.exists()))
    return renames


def apply_renames(renames, log_path):
    """Rename the non-conflicting files and log each rename.

    Args:
        renames (list): From `planned_renames`.
        log_path (Path): CSV log, appended to (created with a header if new).

    Returns:
        int: Number of files renamed.
    """
    log_path = Path(log_path)
    is_new_log = not log_path.exists()
    renamed_count = 0
    with log_path.open("a", newline="", encoding="utf-8") as log_file:
        writer = csv.writer(log_file)
        if is_new_log:
            writer.writerow(["old_path", "new_path", "renamed_at"])
        for old_path, new_path, conflict in renames:
            if conflict or new_path.exists():  # re-checked just before renaming
                continue
            old_path.rename(new_path)
            writer.writerow([str(old_path), str(new_path), time.strftime("%Y-%m-%d %H:%M:%S")])
            renamed_count += 1
    return renamed_count


def main():
    """Parse the command line, print the plan, and rename only with --apply."""
    parser = argparse.ArgumentParser(description="Prefix suite2p default output file names with {fish_id}_plane{i}_")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--folder-pattern", required=True, help='glob for the fish folders, e.g. "*_Exp_1_*"')
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="rename (default: dry run)")
    args = parser.parse_args()

    all_renames = []
    for fish_folder in sorted(path for path in args.data_root.glob(args.folder_pattern) if path.is_dir()):
        renames = planned_renames(fish_folder)
        conflicts = [old.name for old, _, conflict in renames if conflict]
        print(f"{fish_folder.name}: {len(renames)} files to rename" + (f", CONFLICTS (skipped): {conflicts}" if conflicts else ""))
        all_renames.extend(renames)
    if args.apply:
        print(f"Renamed {apply_renames(all_renames, args.log)} files; log: {args.log}")
    else:
        print(f"Dry run: {len(all_renames)} files would be renamed. Example: {all_renames[0][0].name} -> {all_renames[0][1].name}" if all_renames else "Dry run: nothing to rename.")


if __name__ == "__main__":
    main()
