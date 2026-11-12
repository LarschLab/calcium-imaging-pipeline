"""Prepare one averaged anatomy z-stack per fish for registration (see registration/ANATOMY_AVERAGING_PLAN.md).

Three steps, run from the repo root:

    python -m tools.prepare_anatomy_stacks inventory [--max-file-gb 1]
    python -m tools.prepare_anatomy_stacks copy
    python -m tools.prepare_anatomy_stacks average

`inventory` reads the network originals (read-only) and writes a CSV of every
in-scope anatomy file and what to do with it. `copy` copies the files ScanImage
already averaged; `average` averages the all-frames files. Both read their work
list from the inventory, never overwrite, and skip a failing fish with a warning.
"""

import argparse
import csv
import time
from pathlib import Path

from preprocessing.anatomy_averaging import (
    STATUS_ALREADY_AVERAGED,
    STATUS_NEEDS_AVERAGING,
    STATUS_REVIEW,
    averaged_output_name,
    classify_stack,
    copy_without_overwrite,
    find_anatomy_files,
    index_fish_folders,
    read_csv_frames_per_slice,
    read_stack_header,
    write_averaged_stack,
    write_averaging_metadata,
)

ONEDRIVE_LAB = Path(r"C:\Users\suribear\OneDrive - Université de Lausanne\Lab")
NETWORK_ROOT = Path(r"Z:\FAC\FBM\CIG\jlarsch\default\D2c\07_Data\Alejandro")
LOOSE_FOLDER = NETWORK_ROOT / "0 new folder"
DESTINATION_ROOT = ONEDRIVE_LAB / "Data" / "2p"
OVERVIEW_CSV = ONEDRIVE_LAB / "Results" / "Paper" / "2p_derived" / "global" / "overview.csv"
INVENTORY_CSV = ONEDRIVE_LAB / "Results" / "Paper" / "2p_derived" / "registration" / "anatomy_inventory.csv"

EXPERIMENTS_IN_SCOPE = ("Exp_1_flickering", "Exp_5_map_positions", "Exp_7_trans_stat", "Exp_8_accumulation_ev", "Exp_9_RF_memory_inhibition")
EXCLUDED_DECISION = "exclude"
BYTES_PER_GB = 1024 ** 3
ACTION_COPY, ACTION_AVERAGE, ACTION_NONE, ACTION_DONE = "copy", "average", "none", "done"
INVENTORY_COLUMNS = [
    "experiment", "fish_id", "final_decision", "network_folder", "onedrive_folder", "source_file", "location",
    "size_gb", "n_pages", "num_slices", "frames_per_slice", "log_average_factor", "n_channels",
    "csv_frames_per_slice", "status", "frames_per_depth", "action", "destination", "note", "review_reason",
]


def load_fish_in_scope(overview_csv):
    """Read the fish of the in-scope experiments whose final decision isn't "exclude".

    Args:
        overview_csv (Path): The Paper project's global overview CSV.

    Returns:
        list: dicts with `experiment`, `fish_id`, `final_decision`.
    """
    with Path(overview_csv).open(newline="", encoding="utf-8-sig") as overview_file:
        rows = list(csv.DictReader(overview_file))
    fish_in_scope = [
        {"experiment": row["Experiment"], "fish_id": row["Fish"], "final_decision": row["Final decision"]}
        for row in rows
        if row["Experiment"] in EXPERIMENTS_IN_SCOPE and row["Final decision"] != EXCLUDED_DECISION
    ]
    return fish_in_scope


def describe_file(source_path, max_file_gb):
    """Read and classify one anatomy file, skipping the slow header read for files above a size limit.

    Args:
        source_path (Path): Anatomy TIFF on the network drive.
        max_file_gb (float or None): Files larger than this are listed but not inspected.

    Returns:
        dict: Inventory columns describing the file itself.
    """
    size_gb = source_path.stat().st_size / BYTES_PER_GB
    description = {"source_file": str(source_path), "size_gb": round(size_gb, 3)}
    if max_file_gb is not None and size_gb > max_file_gb:
        description.update(status="not_inspected", note=f"larger than {max_file_gb} GB; inspected in a later run")
        return description
    try:
        header = read_stack_header(source_path)
    except Exception as error:  # unreadable/corrupt file: report it, keep going
        description.update(status=STATUS_REVIEW, note=f"unreadable: {error}")
        return description
    status, frames_per_depth, note = classify_stack(header)
    description.update({key: header[key] for key in ("n_pages", "num_slices", "frames_per_slice", "log_average_factor", "n_channels")})
    description.update(status=status, frames_per_depth=frames_per_depth, note=note)
    return description


def plan_action(row, onedrive_folder):
    """Fill in the action and destination of an inventory row.

    Args:
        row (dict): Inventory row with `status` and `source_file`.
        onedrive_folder (Path or None): The fish's OneDrive folder, if exactly one exists.

    Returns:
        dict: The row with `action` and `destination` set.
    """
    if onedrive_folder is None or row["status"] not in (STATUS_ALREADY_AVERAGED, STATUS_NEEDS_AVERAGING):
        return {**row, "action": ACTION_NONE, "destination": ""}
    source_path = Path(row["source_file"])
    is_copy = row["status"] == STATUS_ALREADY_AVERAGED
    file_name = source_path.name if is_copy else averaged_output_name(source_path)
    destination = Path(onedrive_folder) / "01_raw" / "2p" / "anatomy" / file_name
    action = ACTION_DONE if destination.exists() else (ACTION_COPY if is_copy else ACTION_AVERAGE)
    return {**row, "action": action, "destination": str(destination)}


def inventory_rows_for_fish(fish, network_folders, onedrive_folders, max_file_gb):
    """Build the inventory rows (one per anatomy file) of one fish.

    Args:
        fish (dict): From `load_fish_in_scope`.
        network_folders (list): The fish's network folders.
        onedrive_folders (list): The fish's OneDrive folders.
        max_file_gb (float or None): Size limit for header inspection.

    Returns:
        list: Inventory row dicts.
    """
    fish_id = fish["fish_id"]
    network_folder = network_folders[0] if len(network_folders) == 1 else None
    onedrive_folder = onedrive_folders[0] if len(onedrive_folders) == 1 else None
    base = {**fish, "network_folder": str(network_folder or network_folders),
            "onedrive_folder": str(onedrive_folder or onedrive_folders)}
    anatomy_files = find_anatomy_files(network_folder, LOOSE_FOLDER, fish_id)
    csv_frames = read_csv_frames_per_slice(network_folder) if network_folder else None

    folder_problems = []
    if network_folder is None:
        folder_problems.append(f"{len(network_folders)} network folders")
    if onedrive_folder is None:
        folder_problems.append(f"{len(onedrive_folders)} OneDrive folders")
    if not anatomy_files:
        return [{**base, "status": "no_anatomy", "action": ACTION_NONE, "review_reason": "; ".join(folder_problems + ["no anatomy file"])}]

    rows = []
    for source_path, location in anatomy_files:
        row = {**base, "location": location, "csv_frames_per_slice": csv_frames, **describe_file(source_path, max_file_gb)}
        reasons = list(folder_problems)
        if len(anatomy_files) > 1:
            reasons.append(f"{len(anatomy_files)} anatomy files: choose one before registration")
        if location == "loose":
            reasons.append("file found outside the fish folder")
        if row["status"] == STATUS_REVIEW:
            reasons.append(row["note"])
        row["review_reason"] = "; ".join(reasons)
        rows.append(plan_action(row, onedrive_folder))
    return rows


def run_inventory(max_file_gb):
    """Build and write the inventory CSV for all in-scope fish.

    Args:
        max_file_gb (float or None): Files larger than this are listed without reading their header.
    """
    network_index = index_fish_folders(NETWORK_ROOT)
    onedrive_index = index_fish_folders(DESTINATION_ROOT)
    rows = []
    for fish in load_fish_in_scope(OVERVIEW_CSV):
        fish_rows = inventory_rows_for_fish(fish, network_index.get(fish["fish_id"], []), onedrive_index.get(fish["fish_id"], []), max_file_gb)
        for row in fish_rows:
            print(f"{row['fish_id']}: {row.get('status')} -> {row.get('action')} {row.get('review_reason', '')}")
        rows.extend(fish_rows)
    INVENTORY_CSV.parent.mkdir(parents=True, exist_ok=True)
    with INVENTORY_CSV.open("w", newline="", encoding="utf-8") as inventory_file:
        writer = csv.DictWriter(inventory_file, fieldnames=INVENTORY_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {INVENTORY_CSV}")


def read_inventory(action):
    """Read the inventory rows that have a given action.

    Args:
        action (str): ACTION_COPY or ACTION_AVERAGE.

    Returns:
        list: Matching inventory row dicts.
    """
    with INVENTORY_CSV.open(newline="", encoding="utf-8") as inventory_file:
        matching_rows = [row for row in csv.DictReader(inventory_file) if row["action"] == action]
    return matching_rows


def run_copy():
    """Copy every already-averaged anatomy file listed in the inventory."""
    for row in read_inventory(ACTION_COPY):
        destination = Path(row["destination"])
        if destination.exists():
            print(f"{row['fish_id']}: already there, skipped")
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            copy_without_overwrite(Path(row["source_file"]), destination)
        except OSError as error:
            print(f"WARNING {row['fish_id']}: copy failed, skipped ({error})")
            continue
        print(f"{row['fish_id']}: copied {destination.name}")


def run_average():
    """Average every all-frames anatomy file listed in the inventory, one fish at a time."""
    rows = read_inventory(ACTION_AVERAGE)
    for index, row in enumerate(rows, start=1):
        source_path, destination = Path(row["source_file"]), Path(row["destination"])
        if destination.exists():
            print(f"[{index}/{len(rows)}] {row['fish_id']}: already there, skipped")
            continue
        start = time.time()
        try:
            header = read_stack_header(source_path)  # re-read: the inventory may be stale
            status, frames_per_depth, note = classify_stack(header)
            if status != STATUS_NEEDS_AVERAGING:
                print(f"WARNING {row['fish_id']}: now classified {status} ({note}), skipped")
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            write_averaged_stack(source_path, destination, frames_per_depth, int(header["num_slices"]), header)
            write_averaging_metadata(destination.with_name(f"{destination.stem}_metadata.json"), source_path, destination, header, frames_per_depth, row["fish_id"])
        except (OSError, ValueError) as error:
            print(f"WARNING {row['fish_id']}: averaging failed, skipped ({error})")
            continue
        print(f"[{index}/{len(rows)}] {row['fish_id']}: averaged {frames_per_depth} frames/depth in {(time.time() - start) / 60:.1f} min")


def main():
    """Parse the command line and run the requested step."""
    parser = argparse.ArgumentParser(description="Inventory, copy, or average anatomy z-stacks for registration")
    parser.add_argument("step", choices=["inventory", "copy", "average"])
    parser.add_argument("--max-file-gb", type=float, default=None, help="inventory: list larger files without reading their header")
    args = parser.parse_args()
    if args.step == "inventory":
        run_inventory(args.max_file_gb)
    elif args.step == "copy":
        run_copy()
    else:
        run_average()


if __name__ == "__main__":
    main()
