"""Load per-plane dF/F traces for one experiment and merge them in memory.

The merged matrix is rebuilt each time it is needed and never saved: each
plane's own dF/F metadata file stays the only record of how its data were made.

Plane loading is adapted from the FishData class in mp_thesis_2026.
"""

import gc
import re
from pathlib import Path

import numpy as np
import pandas as pd


ALL_PLANES = "all"
PLANE_DIRECTORY_PATTERN = re.compile(r"^plane(\d+)$")


def discover_plane_indices(suite2p_dir):
    """Discover numbered Suite2p plane directories.

    Args:
        suite2p_dir (Path): Folder containing directories named ``plane<number>``.

    Returns:
        tuple: Sorted zero-based plane indices found in the directory.

    Raises:
        FileNotFoundError: If the Suite2p directory does not exist.
        ValueError: If no numbered plane directories are found.
    """
    suite2p_dir = Path(suite2p_dir)
    if not suite2p_dir.is_dir():
        raise FileNotFoundError(f"Suite2p directory does not exist: {suite2p_dir}")

    plane_indices = []
    for child_path in suite2p_dir.iterdir():
        if not child_path.is_dir():
            continue
        plane_match = PLANE_DIRECTORY_PATTERN.fullmatch(child_path.name)
        if plane_match:
            plane_indices.append(int(plane_match.group(1)))
    if not plane_indices:
        raise ValueError(f"No plane<number> directories were found in {suite2p_dir}.")

    discovered_indices = tuple(sorted(plane_indices))
    return discovered_indices


def resolve_plane_indices(suite2p_dir, plane_indices):
    """Resolve an automatic or explicit plane selection.

    Args:
        suite2p_dir (Path): Folder containing Suite2p plane directories.
        plane_indices (sequence or str): Integer indices or the string ``all``.

    Returns:
        tuple: Sorted, unique plane indices selected for merging.

    Raises:
        ValueError: If the selector is empty, duplicated, negative, or malformed.
    """
    if isinstance(plane_indices, str):
        if plane_indices.lower() != "all":
            raise ValueError('plane_indices must be "all" or a sequence of integers.')
        selected_indices = discover_plane_indices(suite2p_dir)
        return selected_indices

    try:
        selected_indices = tuple(int(plane_index) for plane_index in plane_indices)
    except (TypeError, ValueError) as error:
        raise ValueError(
            'plane_indices must be "all" or a sequence of integers.'
        ) from error
    if not selected_indices:
        raise ValueError("plane_indices cannot be empty.")
    if any(plane_index < 0 for plane_index in selected_indices):
        raise ValueError("plane_indices cannot contain negative values.")
    if len(set(selected_indices)) != len(selected_indices):
        raise ValueError("plane_indices cannot contain duplicate values.")

    resolved_indices = tuple(sorted(selected_indices))
    return resolved_indices


def find_plane_file(suite2p_dir, fish_id, plane_index, suffix):
    """Find a canonical or legacy per-plane analysis file.

    Args:
        suite2p_dir (Path): Folder containing the Suite2p plane directories.
        fish_id (str): Fish identifier used in filenames.
        plane_index (int): Zero-based plane number.
        suffix (str): Filename suffix such as ``dFoF.npy``.

    Returns:
        Path: Existing file matching the requested plane and suffix.

    Raises:
        FileNotFoundError: If neither supported location contains the file.
    """
    plane_dir = Path(suite2p_dir) / f"plane{plane_index}"
    plane_filename = f"{fish_id}_plane{plane_index}_{suffix}"
    legacy_filename = f"{fish_id}_{suffix}"
    candidates = [
        plane_dir / plane_filename,
        plane_dir / "dFoF" / plane_filename,
        plane_dir / "dFoF" / legacy_filename,
        plane_dir / legacy_filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    checked_paths = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(
        f"Missing plane {plane_index} file for {fish_id}. Checked: {checked_paths}"
    )



def load_plane_record(suite2p_dir, fish_id, plane_index):
    """Load and validate one plane's dF/F array and Suite2P ROI indices.

    Args:
        suite2p_dir (Path): Folder containing the Suite2p plane directories.
        fish_id (str): Fish identifier used in filenames.
        plane_index (int): Zero-based plane number.

    Returns:
        dict or None: Plane number, trace array, ROI indices, and source paths,
        or ``None`` when the plane has no ROI index file or no kept ROIs.

    Raises:
        ValueError: If an input array has an invalid shape or index count.
    """
    dfof_path = find_plane_file(suite2p_dir, fish_id, plane_index, "dFoF.npy")
    try:
        roi_path = find_plane_file(
            suite2p_dir,
            fish_id,
            plane_index,
            "filtered_roi_indices.npy",
        )
    except FileNotFoundError:
        # dF/F column numbers are not Suite2P ROI numbers (the dF/F step drops
        # ROIs), so without this file the plane's ROIs cannot be identified.
        print(
            f"Warning: plane {plane_index} has no filtered ROI index file; "
            "skipping this plane."
        )
        return None

    dfof = np.load(dfof_path)
    if dfof.ndim != 2 or dfof.shape[0] == 0:
        raise ValueError(
            f"Expected a time x neurons array with frames at {dfof_path}, got {dfof.shape}."
        )
    if dfof.shape[1] == 0:
        print(f"Warning: plane {plane_index} has no kept ROIs; skipping this plane.")
        return None

    roi_indices = np.asarray(np.load(roi_path), dtype=int).ravel()
    if roi_indices.size != dfof.shape[1]:
        raise ValueError(
            f"ROI index count {roi_indices.size} does not match the {dfof.shape[1]} "
            f"dF/F columns in {dfof_path}."
        )

    plane_record = {
        "plane_index": plane_index,
        "dfof": dfof,
        "roi_indices": roi_indices,
        "dfof_path": dfof_path,
        "roi_path": roi_path,
    }
    return plane_record


def check_matching_frame_counts(plane_records):
    """Check that every plane has the same number of frames.

    Planes from one recording come from the same volumes, so a different frame
    count means something went wrong upstream (e.g. a plane processed from
    different blocks).

    Args:
        plane_records (list): Plane records ordered by plane number.

    Returns:
        None: The check only raises on failure.

    Raises:
        ValueError: If any plane's frame count differs from the first plane's.
    """
    reference_record = plane_records[0]
    reference_frames = reference_record["dfof"].shape[0]
    for record in plane_records[1:]:
        plane_frames = record["dfof"].shape[0]
        if plane_frames != reference_frames:
            raise ValueError(
                f"Plane {record['plane_index']} has {plane_frames} frames but plane "
                f"{reference_record['plane_index']} has {reference_frames}. Planes from "
                f"one recording must have equal frame counts; check {record['dfof_path']}."
            )


def build_roi_mapping(plane_records):
    """Build the table linking merged dF/F columns back to plane and ROI.

    Args:
        plane_records (list): Plane records ordered by plane number.

    Returns:
        DataFrame: One row per merged column with plane, ROI, and source files.
    """
    mapping_rows = []
    global_column = 0
    for record in plane_records:
        for local_column, filtered_roi_index in enumerate(record["roi_indices"]):
            mapping_rows.append(
                {
                    "plane": f"plane{record['plane_index']}",
                    "plane_index": record["plane_index"],
                    "roi_index_in_plane": local_column,
                    "filtered_roi_index": int(filtered_roi_index),
                    "global_column": global_column,
                    "source_dfof_file": str(record["dfof_path"]),
                    "source_roi_file": str(record["roi_path"]),
                }
            )
            global_column += 1

    mapping = pd.DataFrame(mapping_rows)
    return mapping


def merge_planes(experiment_dir, fish_id, plane_indices=ALL_PLANES):
    """Load the selected planes for one experiment and join their neurons.

    Args:
        experiment_dir (Path): Root of one experiment's standard folder tree.
        fish_id (str): Fish identifier used in per-plane filenames.
        plane_indices (sequence or str): Plane numbers, or ``"all"`` to use
            every ``plane<number>`` folder found.

    Returns:
        dict: Merged time-by-neuron ``dfof`` array and the ``mapping`` table
        linking each column to its plane and Suite2P ROI.

    Raises:
        ValueError: If no selected plane can be used or frame counts differ.
    """
    suite2p_dir = Path(experiment_dir) / "03_analysis" / "functional" / "suite2P"
    plane_indices = resolve_plane_indices(suite2p_dir, plane_indices)

    loaded_records = [
        load_plane_record(suite2p_dir, fish_id, plane_index)
        for plane_index in plane_indices
    ]
    plane_records = [record for record in loaded_records if record is not None]
    if not plane_records:
        raise ValueError(
            f"None of the selected planes {list(plane_indices)} could be used for {fish_id}."
        )
    check_matching_frame_counts(plane_records)

    merged_dfof = np.concatenate([record["dfof"] for record in plane_records], axis=1)
    mapping = build_roi_mapping(plane_records)

    # per-plane arrays are now duplicated inside merged_dfof
    del loaded_records, plane_records
    gc.collect()

    merge_result = {
        "dfof": merged_dfof,
        "mapping": mapping,
    }
    return merge_result
