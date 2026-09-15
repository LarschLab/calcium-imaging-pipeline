"""Load, align, and concatenate per-plane dF/F traces for one experiment."""

import gc
import json
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

from utils import init_experiment_tree


DEFAULT_PLANE_INDICES = tuple(range(5))
MERGED_FOLDER_NAME = "merged_dFoF"
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
    """Load and validate one plane's dF/F array and ROI indices.

    Args:
        suite2p_dir (Path): Folder containing the Suite2p plane directories.
        fish_id (str): Fish identifier used in filenames.
        plane_index (int): Zero-based plane number.

    Returns:
        dict: Plane number, trace array, ROI indices, and source paths.

    Raises:
        ValueError: If an input array has an invalid shape or index count.
    """
    dfof_path = find_plane_file(suite2p_dir, fish_id, plane_index, "dFoF.npy")
    dfof = np.load(dfof_path)
    if dfof.ndim != 2 or min(dfof.shape) == 0:
        raise ValueError(
            f"Expected a non-empty time x neurons array at {dfof_path}, got {dfof.shape}."
        )

    try:
        roi_path = find_plane_file(
            suite2p_dir,
            fish_id,
            plane_index,
            "filtered_roi_indices.npy",
        )
        roi_indices = np.asarray(np.load(roi_path), dtype=int).ravel()
    except FileNotFoundError:
        roi_path = None
        roi_indices = np.arange(dfof.shape[1], dtype=int)
        print(
            f"Warning: plane {plane_index} has no filtered ROI index file; "
            "using dF/F column indices."
        )

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


def merge_plane_records(plane_records):
    """Truncate planes to a common duration and concatenate their neurons.

    Args:
        plane_records (list): Valid plane records ordered by plane number.

    Returns:
        tuple: Merged time-by-neuron array, provenance DataFrame, and input shapes.

    Raises:
        ValueError: If no plane records are provided.
    """
    if not plane_records:
        raise ValueError("At least one plane record is required for merging.")

    input_shapes = [list(record["dfof"].shape) for record in plane_records]
    common_frames = min(shape[0] for shape in input_shapes)
    merged_parts = []
    mapping_rows = []
    global_column = 0

    for record in plane_records:
        truncated_dfof = record["dfof"][:common_frames, :]
        merged_parts.append(truncated_dfof)
        for local_column, filtered_roi_index in enumerate(record["roi_indices"]):
            mapping_rows.append(
                {
                    "plane": f"plane{record['plane_index']}",
                    "plane_index": record["plane_index"],
                    "roi_index_in_plane": local_column,
                    "filtered_roi_index": int(filtered_roi_index),
                    "global_column": global_column,
                    "source_dfof_file": str(record["dfof_path"]),
                    "source_roi_file": (
                        str(record["roi_path"]) if record["roi_path"] else ""
                    ),
                }
            )
            global_column += 1

    merged_dfof = np.concatenate(merged_parts, axis=1)
    mapping = pd.DataFrame(mapping_rows)
    return merged_dfof, mapping, input_shapes


def merge_five_planes(experiment_dir, fish_id, plane_indices=DEFAULT_PLANE_INDICES):
    """Load and merge the selected planes for one experiment.

    Args:
        experiment_dir (Path): Root of one experiment's standard folder tree.
        fish_id (str): Fish identifier used in per-plane filenames.
        plane_indices (sequence or str): Plane numbers or ``all`` for discovery.

    Returns:
        dict: Merged dF/F, mapping table, metadata, and canonical output paths.
    """
    experiment_dir = Path(experiment_dir)
    suite2p_dir = experiment_dir / "03_analysis" / "functional" / "suite2P"
    plane_indices = resolve_plane_indices(suite2p_dir, plane_indices)

    plane_records = [
        load_plane_record(suite2p_dir, fish_id, plane_index)
        for plane_index in plane_indices
    ]
    merged_dfof, mapping, input_shapes = merge_plane_records(plane_records)
    source_files = [str(record["dfof_path"]) for record in plane_records]
    metadata = {
        "fish_id": fish_id,
        "params": {
            "plane_indices": list(plane_indices),
            "alignment_mode": "truncate",
        },
        "shapes": {
            "input_time_by_neurons": input_shapes,
            "merged_time_by_neurons": list(merged_dfof.shape),
        },
        "source_files": source_files,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    output_paths = merged_output_paths(experiment_dir, fish_id, plane_indices)

    for record in plane_records:
        del record["dfof"]
    del plane_records
    gc.collect()

    merge_result = {
        "dfof": merged_dfof,
        "mapping": mapping,
        "metadata": metadata,
        "paths": output_paths,
        "experiment_dir": experiment_dir,
    }
    return merge_result


def merged_output_paths(experiment_dir, fish_id, plane_indices=None):
    """Build canonical merged-output paths without creating directories.

    Args:
        experiment_dir (Path): Root of one experiment's standard folder tree.
        fish_id (str): Fish identifier used in output filenames.
        plane_indices (sequence or None): Selection included in filenames, when set.

    Returns:
        dict: Output directory and paths for the array, map, and metadata.
    """
    output_dir = (
        Path(experiment_dir)
        / "03_analysis"
        / "functional"
        / "suite2P"
        / MERGED_FOLDER_NAME
    )
    if plane_indices is None:
        output_prefix = fish_id
    else:
        plane_text = "-".join(str(plane_index) for plane_index in plane_indices)
        output_prefix = f"{fish_id}_planes_{plane_text}"
    output_paths = {
        "output_dir": output_dir,
        "dfof": output_dir / f"{output_prefix}_dFoF_merged.npy",
        "mapping": output_dir / f"{output_prefix}_dFoF_merged_map.csv",
        "metadata": output_dir / f"{output_prefix}_dFoF_merged_metadata.json",
    }
    return output_paths


def save_merged_result(merge_result):
    """Save a merged result without overwriting existing artifacts.

    Args:
        merge_result (dict): Result returned by :func:`merge_five_planes`.

    Returns:
        dict: Paths of the saved merged artifacts.

    Raises:
        FileExistsError: If any canonical output already exists.
    """
    paths = merge_result["paths"]
    existing_paths = [path for key, path in paths.items() if key != "output_dir" and path.exists()]
    if existing_paths:
        existing_names = ", ".join(path.name for path in existing_paths)
        raise FileExistsError(
            f"Refusing to overwrite existing merged output(s): {existing_names}"
        )

    experiment_dir = Path(merge_result["experiment_dir"])
    init_experiment_tree(experiment_dir.parent, experiment_dir.name)
    np.save(paths["dfof"], merge_result["dfof"])
    merge_result["mapping"].to_csv(paths["mapping"], index=False, encoding="utf-8")
    with paths["metadata"].open("x", encoding="utf-8") as metadata_file:
        json.dump(merge_result["metadata"], metadata_file, indent=2)
    return paths


def load_merged_result(experiment_dir, fish_id, plane_indices=None):
    """Load a complete set of previously merged artifacts.

    Args:
        experiment_dir (Path): Root of one experiment's standard folder tree.
        fish_id (str): Fish identifier used in output filenames.
        plane_indices (sequence or None): Plane selection encoded in filenames.

    Returns:
        dict: Loaded dF/F array, mapping, metadata, and paths.

    Raises:
        FileNotFoundError: If the merged artifact set is incomplete.
    """
    paths = merged_output_paths(experiment_dir, fish_id, plane_indices)
    required_paths = [paths["dfof"], paths["mapping"], paths["metadata"]]
    missing_paths = [path for path in required_paths if not path.exists()]
    if missing_paths:
        missing_names = ", ".join(path.name for path in missing_paths)
        raise FileNotFoundError(f"Incomplete merged output set; missing: {missing_names}")

    with paths["metadata"].open("r", encoding="utf-8") as metadata_file:
        metadata = json.load(metadata_file)
    loaded_result = {
        "dfof": np.load(paths["dfof"]),
        "mapping": pd.read_csv(paths["mapping"]),
        "metadata": metadata,
        "paths": paths,
        "experiment_dir": Path(experiment_dir),
    }
    return loaded_result


def prepare_merged_dfof(experiment_dir, fish_id, plane_indices=DEFAULT_PLANE_INDICES):
    """Load existing merged outputs or safely create them once.

    Args:
        experiment_dir (Path): Root of one experiment's standard folder tree.
        fish_id (str): Fish identifier used in filenames.
        plane_indices (sequence or str): Required plane numbers or ``all``.

    Returns:
        dict: Loaded or newly created merged result.
    """
    experiment_dir = Path(experiment_dir)
    init_experiment_tree(experiment_dir.parent, experiment_dir.name)
    suite2p_dir = experiment_dir / "03_analysis" / "functional" / "suite2P"
    resolved_indices = resolve_plane_indices(suite2p_dir, plane_indices)
    try:
        merged_result = load_merged_result(
            experiment_dir,
            fish_id,
            resolved_indices,
        )
        print(f"Loaded existing merged dF/F for {fish_id}.")
        return merged_result
    except FileNotFoundError:
        pass

    try:
        legacy_result = load_merged_result(experiment_dir, fish_id)
        legacy_indices = tuple(legacy_result["metadata"]["params"]["plane_indices"])
        if legacy_indices == resolved_indices:
            print(f"Loaded compatible legacy merged dF/F for {fish_id}.")
            return legacy_result
    except (FileNotFoundError, KeyError, TypeError):
        pass

    merged_result = merge_five_planes(experiment_dir, fish_id, resolved_indices)
    save_merged_result(merged_result)
    print(
        f"Created merged dF/F for {fish_id} using planes "
        f"{list(resolved_indices)}."
    )
    return merged_result
