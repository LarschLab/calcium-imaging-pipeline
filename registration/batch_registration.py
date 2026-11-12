"""Register every fish of one experiment: planes -> own anatomy, ROI positions, canonical anatomy.

Wraps the steps of `notebooks/register_plane_to_anatomy.ipynb` so
`notebooks/register_experiment.ipynb` can loop over fish:

1. Pick the experiment's fish from the Paper overview (minus "exclude").
2. Skip fish already done: the ROI position table, written last, marks a
   registered fish. A registered fish with a missing QC figure is reported
   ("qc_missing") but never re-registered automatically; delete its ROI
   table to force a full rerun.
3. Per plane: match depth/scale, register with ANTs, warp the ROIs, write
   the transform + metadata JSON into the fish folder (`02_reg/07_2pf-a/`).
4. Write the fish's ROI position table (centres in anatomy and canonical
   space) + a metadata sidecar, and the canonical anatomy NRRD.

Outputs follow the lab's per-fish folder convention; QC figures and the
experiment summary go to a separate review folder chosen by the caller.
"""

import csv
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import tifffile

from preprocessing.anatomy_averaging import PARTIAL_SUFFIX, index_fish_folders, read_file_z_step_um
from preprocessing.canonical_preprocessing import preprocess_canonical_anatomy
from preprocessing.spatial_preprocessing import _metadata_value, anatomy_z_spacing_um, read_raw_metadata_polarity
from registration.image_utils import read_pixel_size_um
from registration.plane_matching import match_plane_to_anatomy
from registration.plane_registration import (
    load_suite2p_plane,
    register_plane_to_anatomy,
    suite2p_file_path,
    warp_roi_masks_to_anatomy,
    write_registration_metadata,
)
from registration.roi_to_reference import convert_rois_to_canonical_space

REGISTRATION_STAGE_DIR = Path("02_reg") / "07_2pf-a"  # functional plane -> 2P anatomy
ANATOMY_DIR = Path("01_raw") / "2p" / "anatomy"
SUITE2P_DIR = Path("03_analysis") / "functional" / "suite2P"
EXCLUDED_DECISION = "exclude"
CSV_Z_STEP_KEY = "step_size_um_anatomy"  # anatomy slice spacing in the experimenter's metadata CSV
EX_VIVO_MARKERS = ("ex_vivo", "exvivo")
QC_FIGURE_NAMES = ("registration_overlays", "depth_profiles", "roi_overlays", "mean_vs_anatomy")
QC_FIGURE_EXTENSION = ".png"


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


def roi_table_path(fish_folder, fish_id):
    """Return where a fish's ROI position table is written (lab folder convention).

    Args:
        fish_folder (Path): The fish's data folder.
        fish_id (str): Fish identifier.

    Returns:
        Path: `<fish>/02_reg/07_2pf-a/<fish_id>_roi_positions.csv`.
    """
    table_path = Path(fish_folder) / REGISTRATION_STAGE_DIR / f"{fish_id}_roi_positions.csv"
    return table_path


def qc_figure_paths(qc_dir, fish_id):
    """Return the QC figure files of one fish.

    Args:
        qc_dir (Path): The experiment's QC folder.
        fish_id (str): Fish identifier.

    Returns:
        dict: figure name (one of QC_FIGURE_NAMES) -> Path.
    """
    figure_paths = {name: Path(qc_dir) / f"{fish_id}_{name}{QC_FIGURE_EXTENSION}" for name in QC_FIGURE_NAMES}
    return figure_paths


def fish_status(fish_folder, fish_id, qc_dir):
    """Say how far a fish has been processed.

    Args:
        fish_folder (Path or None): The fish's data folder, None if not found.
        fish_id (str): Fish identifier.
        qc_dir (Path): The experiment's QC folder.

    Returns:
        str: "no_folder"; "todo" (no ROI table yet); "qc_missing" (registered,
        but a QC figure is missing -- never re-registered automatically, so
        finished outputs aren't silently rewritten); or "done".
    """
    if fish_folder is None:
        return "no_folder"
    if not roi_table_path(fish_folder, fish_id).exists():
        return "todo"
    figures_exist = all(path.exists() for path in qc_figure_paths(qc_dir, fish_id).values())
    status = "done" if figures_exist else "qc_missing"
    return status


def find_anatomy_tiff(fish_folder):
    """Find the fish's single in-vivo anatomy TIFF.

    Args:
        fish_folder (Path): The fish's data folder.

    Returns:
        tuple: `(path, problem)` -- the TIFF and None, or None and a reason
        (none found, several found, or an averaging still being written).
    """
    anatomy_dir = Path(fish_folder) / ANATOMY_DIR
    if any(anatomy_dir.glob(f"*{PARTIAL_SUFFIX}")):
        return None, f".partial file in {anatomy_dir}: averaging/copy still running, or an earlier one failed (then delete it and rerun the averaging)"
    candidates = sorted(
        path for path in anatomy_dir.glob("*.tif*")
        if not any(marker in path.name.lower() for marker in EX_VIVO_MARKERS)
    )
    if len(candidates) != 1:
        return None, f"{len(candidates)} anatomy TIFFs in {anatomy_dir} (need exactly one)"
    return candidates[0], None


def load_anatomy_stack(anatomy_path):
    """Load a single-channel anatomy stack and its pixel size.

    Args:
        anatomy_path (Path): Anatomy TIFF, one page per depth.

    Returns:
        tuple: `(stack, pixel_size_um)` -- float32 (depth, height, width) array and float.

    Raises:
        ValueError: If ScanImage saved more than one channel (pages interleaved).
    """
    with tifffile.TiffFile(anatomy_path) as anatomy_tiff:
        frame_data = (anatomy_tiff.scanimage_metadata or {}).get("FrameData", {})
        stack = np.stack([page.asarray() for page in anatomy_tiff.pages], axis=0).astype(np.float32)
    channel_save = frame_data.get("SI.hChannels.channelSave")
    if isinstance(channel_save, list) and len(channel_save) > 1:
        raise ValueError(f"{anatomy_path.name} has {len(channel_save)} channels; expected one")
    pixel_size_um = read_pixel_size_um(anatomy_path)
    return stack, pixel_size_um


def read_anatomy_z_step_um(fish_folder, anatomy_path):
    """Read the anatomy Z step: the metadata CSV first, else the anatomy file itself.

    Only a *missing* CSV value falls back to the file; conflicting CSV values
    still raise.

    Args:
        fish_folder (Path): The fish's data folder.
        anatomy_path (Path): The anatomy TIFF being registered.

    Returns:
        tuple: `(z_step_um, source)` -- float and a description of where it came from.

    Raises:
        ValueError: If CSV values conflict, or neither source records the step.
    """
    metadata_dir = Path(fish_folder) / "01_raw" / "2p" / "metadata"
    csv_records_step = any(_metadata_value(path, CSV_Z_STEP_KEY) is not None for path in sorted(metadata_dir.glob("*_metadata.csv")))
    if csv_records_step:
        z_step_um, csv_paths = anatomy_z_spacing_um(metadata_dir)
        return z_step_um, f"metadata CSV {[str(path) for path in csv_paths]}"
    z_step_um, source = read_file_z_step_um(anatomy_path)
    if z_step_um is None:
        raise ValueError(f"no {CSV_Z_STEP_KEY} in {metadata_dir} and no Z step in {anatomy_path.name}'s header")
    return z_step_um, source


def load_iscell(plane_folder, file_prefix):
    """Load suite2p's cell classification for one plane.

    Args:
        plane_folder (Path): The plane's suite2p folder.
        file_prefix (str): e.g. "L978_f01_plane0".

    Returns:
        numpy.ndarray or None: `(n_rois, 2)` array of [is_cell, probability], None if missing.
    """
    iscell_path = suite2p_file_path(plane_folder, file_prefix, "iscell.npy")
    iscell = np.load(iscell_path) if iscell_path.exists() else None
    return iscell


def register_plane(fish_folder, fish_id, plane_index, anatomy_stack, anatomy_pixel_size_um, anatomy_sources):
    """Match, register, and warp the ROIs of one plane; write its transform and metadata.

    Args:
        fish_folder (Path): The fish's data folder.
        fish_id (str): Fish identifier (file prefix).
        plane_index (int): Suite2p plane number.
        anatomy_stack (numpy.ndarray): (depth, height, width) anatomy.
        anatomy_pixel_size_um (float): Anatomy pixel size.
        anatomy_sources (dict): Input provenance recorded in the metadata.

    Returns:
        dict: Same keys as the notebook's `plane_results` entries, plus `iscell`.
    """
    file_prefix = f"{fish_id}_plane{plane_index}"
    plane_folder = Path(fish_folder) / SUITE2P_DIR / f"plane{plane_index}"
    reference_image, stat_array = load_suite2p_plane(plane_folder, file_prefix)
    match = match_plane_to_anatomy(reference_image, anatomy_stack)
    best_depth = match["best_z"]
    anatomy_slice = anatomy_stack[best_depth]
    transform_prefix = Path(fish_folder) / REGISTRATION_STAGE_DIR / "transMatrices" / f"{file_prefix}_to_anatomy_"
    registration = register_plane_to_anatomy(reference_image, anatomy_slice, anatomy_pixel_size_um, match["scale"], transform_prefix)
    warped_rois = warp_roi_masks_to_anatomy(stat_array, registration, reference_image.shape, best_depth)
    metadata_path = Path(fish_folder) / REGISTRATION_STAGE_DIR / "logs" / f"{file_prefix}_to_anatomy_registration_metadata.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    write_registration_metadata(registration, match, stat_array, warped_rois, {**anatomy_sources, "suite2p_folder": str(plane_folder)}, fish_id, metadata_path)
    plane_result = {
        "plane_index": plane_index, "file_prefix": file_prefix, "reference_image": reference_image,
        "match": match, "best_depth": best_depth, "anatomy_slice": anatomy_slice, "registration": registration,
        "warped_image": registration["warped_image"], "fixed_image": registration["fixed_image"],
        "warped_rois": warped_rois, "iscell": load_iscell(plane_folder, file_prefix),
    }
    return plane_result


def build_roi_rows(fish_id, plane_result, canonical_rois):
    """Turn one plane's warped ROIs into ROI position table rows (one per ROI).

    Args:
        fish_id (str): Fish identifier.
        plane_result (dict): From `register_plane`.
        canonical_rois (list): `convert_rois_to_canonical_space` output for the
            plane's `warped_rois`, in the same order.

    Returns:
        list: dicts with fish/plane/ROI identifiers, suite2p cell call, and the
        ROI centre in anatomy pixels and canonical-anatomy voxels.
    """
    iscell = plane_result["iscell"]
    rows = []
    for roi, canonical_roi in zip(plane_result["warped_rois"], canonical_rois):
        suite2p_index = int(roi["suite2p_index"])
        center_y, center_x = roi["med_aligned"]  # [row, col], NaN if no pixels survived warping
        canonical_y, canonical_x = canonical_roi["med_canonical"]
        canonical_z = float(np.median(canonical_roi["zpix_canonical"])) if canonical_roi["zpix_canonical"].size else np.nan
        rows.append({
            "fish_id": fish_id,
            "plane": plane_result["plane_index"],
            "suite2p_index": suite2p_index,
            "is_cell": bool(iscell[suite2p_index, 0]) if iscell is not None else None,
            "cell_probability": float(iscell[suite2p_index, 1]) if iscell is not None else None,
            "n_pixels_anatomy": int(roi["xpix_aligned"].size),
            "x_anatomy": center_x, "y_anatomy": center_y, "z_anatomy": int(plane_result["best_depth"]),
            "x_canonical": canonical_x, "y_canonical": canonical_y, "z_canonical": canonical_z,
        })
    return rows


def write_roi_table(rows, table_path, provenance):
    """Write a fish's ROI position table and its metadata sidecar.

    Args:
        rows (list): From `build_roi_rows`, all planes.
        table_path (Path): CSV to write.
        provenance (dict): Polarity, anatomy shape/spacing, source files, etc.
    """
    table_path = Path(table_path)
    table_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(table_path, index=False)
    metadata = {
        **provenance,
        "n_rois": len(rows),
        "coordinates": {
            "anatomy": "x/y = median pixel (column/row) of the warped ROI in the raw anatomy slice; z = matched anatomy slice index",
            "canonical": "same centre in the canonical anatomy NRRD's voxels (polarity flip, Z reversal, 750x750 resize)",
        },
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with table_path.with_name(f"{table_path.stem}_metadata.json").open("w", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2)


def register_fish(fish_folder, fish_id):
    """Run the whole per-fish registration and write its outputs into the fish folder.

    Args:
        fish_folder (Path): The fish's data folder.
        fish_id (str): Fish identifier.

    Returns:
        list: Plane results (see `register_plane`), for QC plotting.

    Raises:
        ValueError: If the fish has no usable anatomy, polarity, or suite2p planes.
    """
    fish_folder = Path(fish_folder)
    anatomy_path, problem = find_anatomy_tiff(fish_folder)
    if problem:
        raise ValueError(problem)
    polarity, polarity_source = read_raw_metadata_polarity(fish_folder)
    if polarity is None:
        raise ValueError("no fish_orientation in the raw metadata")
    plane_indices = sorted(int(folder.name.removeprefix("plane")) for folder in (fish_folder / SUITE2P_DIR).glob("plane[0-9]*"))
    if not plane_indices:
        raise ValueError(f"no suite2p plane folders in {fish_folder / SUITE2P_DIR}")

    anatomy_stack, pixel_size_um = load_anatomy_stack(anatomy_path)
    z_step_um, z_step_source = read_anatomy_z_step_um(fish_folder, anatomy_path)
    anatomy_sources = {"anatomy_path": str(anatomy_path), "anatomy_shape_zyx": list(anatomy_stack.shape),
                       "anatomy_pixel_size_um": pixel_size_um, "anatomy_z_step_um": z_step_um,
                       "anatomy_z_step_source": z_step_source}
    plane_results = [register_plane(fish_folder, fish_id, plane_index, anatomy_stack, pixel_size_um, anatomy_sources)
                     for plane_index in plane_indices]

    # Canonical anatomy NRRD (kept if it already exists), then the ROI table, written last as the "done" marker.
    preprocess_canonical_anatomy(fish_folder, anatomy_xy_spacing_um=pixel_size_um, anatomy_z_spacing_um=z_step_um)
    roi_rows = []
    for plane_result in plane_results:
        canonical_rois = convert_rois_to_canonical_space(plane_result["warped_rois"], anatomy_stack.shape, polarity)
        roi_rows.extend(build_roi_rows(fish_id, plane_result, canonical_rois))
    provenance = {"fish_id": fish_id, "planes": plane_indices, "polarity": polarity, "polarity_source": polarity_source, **anatomy_sources}
    write_roi_table(roi_rows, roi_table_path(fish_folder, fish_id), provenance)
    return plane_results


def plane_summary_row(metadata):
    """Summarize one plane's matching and registration quality (the notebook's 5.4 table).

    Args:
        metadata (dict): A plane's `..._registration_metadata.json` content.

    Returns:
        dict: One summary row.
    """
    depth_scores = np.asarray(metadata["match"]["scores"], dtype=np.float64)
    best_depth = metadata["match"]["best_z"]
    best_score = depth_scores[best_depth]
    second_best_score = np.partition(depth_scores, -2)[-2]  # runner-up depth score
    summary_row = {
        "best_depth": best_depth, "scale": metadata["match"]["scale"],
        "ncc_placement_score": metadata["ncc_placement"]["score"],
        "pre_ants_ncc": metadata["pre_ants_ncc"], "post_ncc": metadata["post_ncc"],
        "ants_lowered_fit": metadata["ants_lowered_fit"], "valid_fraction": metadata["valid_fraction"],
        "peak_delta": best_score - second_best_score,
        "peak_zscore": (best_score - depth_scores.mean()) / (depth_scores.std() + 1e-6),  # 1e-6: flat profile guard
        "n_rois_warped": metadata["rois"]["warped"],
        "registered_at": metadata["timestamp"],
    }
    return summary_row


def collect_fish_summary(fish_folder, fish_id):
    """Read a finished fish's per-plane registration metadata into summary rows.

    Only fish with an ROI table (a completed run) are summarized, and only the
    planes that run recorded, so metadata left by failed or older runs is ignored.

    Args:
        fish_folder (Path): The fish's data folder.
        fish_id (str): Fish identifier.

    Returns:
        list: One `plane_summary_row` dict per registered plane, with `fish_id`
        and `plane`; empty if the fish has no finished run.
    """
    table_path = roi_table_path(fish_folder, fish_id)
    sidecar_path = table_path.with_name(f"{table_path.stem}_metadata.json")
    if not table_path.exists() or not sidecar_path.exists():
        return []
    registered_planes = json.loads(sidecar_path.read_text(encoding="utf-8"))["planes"]
    logs_dir = Path(fish_folder) / REGISTRATION_STAGE_DIR / "logs"
    rows = []
    for plane_index in registered_planes:
        metadata_path = logs_dir / f"{fish_id}_plane{plane_index}_to_anatomy_registration_metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        rows.append({"fish_id": fish_id, "plane": plane_index, **plane_summary_row(metadata)})
    return rows


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
