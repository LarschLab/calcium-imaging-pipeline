"""Put every registered fish's ROIs into the reference brain, one experiment at a time.

Step 3 of the ROI chain (see `roi_to_reference`): reads a fish's ROI position
table (`02_reg/07_2pf-a/<fish_id>_roi_positions.csv`, ROI centres in its
canonical anatomy), moves the centres into the reference brain with the
fish's anatomy -> reference transforms, and writes one table per fish:

    <fish>/02_reg/08_2pa-ref/roi_positions/<reference>/<fish_id>_roi_positions_in_ref.csv

plus a `_metadata.json` sidecar. All suite2p ROIs are kept (not only cells),
so any later selection is a lookup. Existing tables are never overwritten.
The reference fish itself needs no transform: its canonical anatomy *is* the
reference grid. `notebooks/rois_to_reference.ipynb` drives this per experiment.
"""

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from registration.batch_registration import roi_table_path
from registration.reference_qc import (
    CANONICAL_ANATOMY_DIR,
    REFERENCE_STAGE_DIR,
    read_nrrd_stack,
    roi_position_agreement,
    sample_stack_at_voxels,
    warped_anatomy_path,
)
from registration.roi_to_reference import (
    CANONICAL_COLUMNS,
    REFERENCE_VOXEL_COLUMNS,
    apply_reference_transform_to_points,
    build_reference_roi_table,
    read_nrrd_geometry,
    read_point_transform_files,
    voxels_to_um,
)

TRANSFORM_ROW_DIR = "row0"  # the cluster export's single registration row
ROI_POSITIONS_DIR = "roi_positions"
GEOMETRY_TOLERANCE_UM = 1e-6  # reference fish: its canonical grid must equal the reference grid
STATUS_DONE = "done"
STATUS_READY = "ready"
STATUS_NO_FOLDER = "no data folder"
STATUS_NO_ROI_TABLE = "no ROI table"
STATUS_NO_TRANSFORMS = "no transforms"


def canonical_anatomy_path(fish_folder):
    """Return a fish's canonical anatomy NRRD (the image its ROI table refers to).

    Args:
        fish_folder (Path): The fish's data folder.

    Returns:
        Path: `<folder>/02_reg/00_preprocessing/2p_anatomy/<folder>_anatomy_2P_GCaMP.nrrd`.
    """
    anatomy_path = Path(fish_folder) / CANONICAL_ANATOMY_DIR / f"{Path(fish_folder).name}_anatomy_2P_GCaMP.nrrd"
    return anatomy_path


def transform_metadata_path(fish_folder, fish_id, reference_name):
    """Return the metadata JSON that lists a fish's anatomy -> reference transform files.

    Args:
        fish_folder (Path): The fish's data folder.
        fish_id (str): Fish identifier.
        reference_name (str): Reference brain name, e.g. "ref_L433_f02".

    Returns:
        Path: `<fish>/02_reg/08_2pa-ref/transMatrices/<reference>/row0/<fish_id>_2P_to_ref_metadata.json`.
    """
    metadata_path = Path(fish_folder) / REFERENCE_STAGE_DIR / "transMatrices" / reference_name / TRANSFORM_ROW_DIR / f"{fish_id}_2P_to_ref_metadata.json"
    return metadata_path


def reference_roi_table_path(fish_folder, fish_id, reference_name):
    """Return where a fish's ROI table in reference space is written.

    Args:
        fish_folder (Path): The fish's data folder.
        fish_id (str): Fish identifier.
        reference_name (str): Reference brain name.

    Returns:
        Path: `<fish>/02_reg/08_2pa-ref/roi_positions/<reference>/<fish_id>_roi_positions_in_ref.csv`.
    """
    table_path = Path(fish_folder) / REFERENCE_STAGE_DIR / ROI_POSITIONS_DIR / reference_name / f"{fish_id}_roi_positions_in_ref.csv"
    return table_path


def reference_mapping_status(fish_folder, fish_id, reference_name, reference_fish_id):
    """Say whether a fish's ROIs can be, or already are, mapped into the reference.

    Args:
        fish_folder (Path or None): The fish's data folder (None if not found).
        fish_id (str): Fish identifier.
        reference_name (str): Reference brain name.
        reference_fish_id (str): Fish ID of the reference brain (needs no transform).

    Returns:
        str: One of the `STATUS_*` values.
    """
    if fish_folder is None:
        return STATUS_NO_FOLDER
    if reference_roi_table_path(fish_folder, fish_id, reference_name).exists():
        return STATUS_DONE
    if not roi_table_path(fish_folder, fish_id).exists():
        return STATUS_NO_ROI_TABLE
    if fish_id != reference_fish_id and not transform_metadata_path(fish_folder, fish_id, reference_name).exists():
        return STATUS_NO_TRANSFORMS
    return STATUS_READY


def map_fish_rois_to_reference(fish_folder, fish_id, reference_geometry, reference_name, reference_fish_id):
    """Move one fish's ROI centres from its canonical anatomy into the reference brain.

    Args:
        fish_folder (Path): The fish's data folder.
        fish_id (str): Fish identifier.
        reference_geometry (dict): `read_nrrd_geometry` of the reference anatomy.
        reference_name (str): Reference brain name.
        reference_fish_id (str): Fish ID of the reference brain.

    Returns:
        tuple: (pandas.DataFrame from `build_reference_roi_table`, dict of
        provenance for the metadata sidecar).

    Raises:
        ValueError: If the reference fish's grid differs from the reference grid,
            or the transform metadata lists an unexpected point order.
    """
    roi_table = pd.read_csv(roi_table_path(fish_folder, fish_id))
    anatomy_path = canonical_anatomy_path(fish_folder)
    fish_geometry = read_nrrd_geometry(anatomy_path)
    points_um = voxels_to_um(roi_table[list(CANONICAL_COLUMNS)].to_numpy(), fish_geometry)
    provenance = {"fish_id": fish_id, "reference_name": reference_name, "roi_table": str(roi_table_path(fish_folder, fish_id)),
                  "canonical_anatomy": str(anatomy_path), "canonical_spacing_xyz_um": fish_geometry["spacing_xyz_um"],
                  "reference_spacing_xyz_um": reference_geometry["spacing_xyz_um"]}
    if fish_id == reference_fish_id:
        grids_match = all(np.allclose(fish_geometry[key], reference_geometry[key], atol=GEOMETRY_TOLERANCE_UM) for key in ("spacing_xyz_um", "origin_xyz_um"))
        if not grids_match:
            raise ValueError(f"{fish_id} is the reference fish but its canonical grid {fish_geometry} differs from the reference {reference_geometry}")
        points_in_reference_um = points_um  # already on the reference grid
        provenance["transform"] = "identity (this fish is the reference brain)"
    else:
        transform_files = read_point_transform_files(transform_metadata_path(fish_folder, fish_id, reference_name))
        points_in_reference_um = apply_reference_transform_to_points(points_um, transform_files["affine_path"], transform_files["inverse_warp_path"])
        provenance["transform"] = {"order": "affine inverted, then inverse warp (ANTs points convention)",
                                   **{key: str(path) for key, path in transform_files.items()}}
    reference_table = build_reference_roi_table(roi_table, points_in_reference_um, reference_geometry)
    return reference_table, provenance


def write_reference_roi_table(reference_table, table_path, provenance):
    """Write a fish's ROI table in reference space and its metadata sidecar; never overwrite.

    Args:
        reference_table (pandas.DataFrame): From `map_fish_rois_to_reference`.
        table_path (Path): CSV to write (`reference_roi_table_path`).
        provenance (dict): From `map_fish_rois_to_reference`.

    Raises:
        FileExistsError: If the table already exists (delete it by hand to redo a fish).
    """
    table_path = Path(table_path)
    if table_path.exists():
        raise FileExistsError(f"{table_path} already exists; not overwriting it")
    table_path.parent.mkdir(parents=True, exist_ok=True)
    reference_table.to_csv(table_path, index=False)
    metadata = {
        **provenance,
        "n_rois": len(reference_table),
        "n_rois_without_position": int(reference_table[list(REFERENCE_VOXEL_COLUMNS)].isna().any(axis=1).sum()),
        "coordinates": {
            "ref_um": "ROI centre in the reference brain, micrometres (ITK physical space, LPS, reference origin 0)",
            "ref_vox": "same centre in reference anatomy voxels (x = column, y = row, z = slice); ref_um / reference spacing",
            "canonical": "original centre in this fish's canonical anatomy voxels (copied from the ROI position table)",
        },
        "join_to_traces": "plane + suite2p_index match the merged dF/F map's plane + filtered_roi_index",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with table_path.with_name(f"{table_path.stem}_metadata.json").open("w", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2)


def check_plane_depth_order(roi_table):
    """Check that a fish's imaging planes sit at distinct anatomy depths, in order.

    Step 1 matches each functional plane to one canonical-anatomy slice. Planes
    are acquired at increasing depth, so their slices must all differ and run
    in one direction; two planes on one slice, or a plane out of order, means
    step 1 placed a plane wrongly (step 3 then moves that wrong position faithfully).

    Args:
        roi_table (pandas.DataFrame): Table with `plane` and `z_canonical`.

    Returns:
        dict: `plane_depths` ("plane:slice" text, in plane order),
        `duplicate_plane_depths` and `plane_depths_out_of_order` (bool).
    """
    depths = roi_table.groupby("plane")["z_canonical"].median().dropna().sort_index()
    depth_steps = np.diff(depths.to_numpy())
    depth_order = {
        "plane_depths": " ".join(f"{int(plane)}:{depth:g}" for plane, depth in depths.items()),
        "duplicate_plane_depths": bool(depths.duplicated().any()),
        "plane_depths_out_of_order": bool(len(depth_steps) > 0 and not ((depth_steps > 0).all() or (depth_steps < 0).all())),
    }
    return depth_order


def read_warped_anatomy(fish_folder, fish_id, reference_name, reference_stack, reference_fish_id):
    """Read a fish's anatomy on the reference grid (the reference itself for the reference fish).

    Args:
        fish_folder (Path): The fish's data folder.
        fish_id (str): Fish identifier.
        reference_name (str): Reference brain name.
        reference_stack (numpy.ndarray): Reference anatomy, (z, y, x).
        reference_fish_id (str): Fish ID of the reference brain.

    Returns:
        numpy.ndarray: float32 (z, y, x) stack on the reference grid.
    """
    if fish_id == reference_fish_id:
        return reference_stack
    warped_stack = read_nrrd_stack(warped_anatomy_path(fish_folder, fish_id, reference_name))
    return warped_stack


def score_fish_roi_mapping(fish_folder, reference_table, warped_stack, reference_stack):
    """Check that a fish's mapped ROIs land on the same anatomy in the reference grid.

    Compares the fish's canonical anatomy at the original ROI centres with the
    fish's anatomy warped into the reference (`read_warped_anatomy`) at the
    mapped centres. Also reports how well the fish's ROI intensities match the
    *reference* brain (lower: a different fish, read at cell-sized points).

    Args:
        fish_folder (Path): The fish's data folder.
        reference_table (pandas.DataFrame): The fish's ROI table in reference space.
        warped_stack (numpy.ndarray): The fish's anatomy on the reference grid, (z, y, x).
        reference_stack (numpy.ndarray): Reference anatomy, (z, y, x).

    Returns:
        dict: `roi_position_agreement` keys (`correlation`, `n_compared`,
        `fraction_inside`) plus `reference_correlation`, `n_rois` and
        `n_rois_without_position`.
    """
    fish_stack = read_nrrd_stack(canonical_anatomy_path(fish_folder))
    fish_values = sample_stack_at_voxels(fish_stack, reference_table[list(CANONICAL_COLUMNS)].to_numpy())
    del fish_stack
    reference_voxels = reference_table[list(REFERENCE_VOXEL_COLUMNS)].to_numpy()
    agreement = roi_position_agreement(fish_values, sample_stack_at_voxels(warped_stack, reference_voxels))
    reference_agreement = roi_position_agreement(fish_values, sample_stack_at_voxels(reference_stack, reference_voxels))
    score = {
        **agreement,
        "reference_correlation": reference_agreement["correlation"],
        "n_rois": len(reference_table),
        "n_rois_without_position": int(np.isnan(reference_voxels).any(axis=1).sum()),
    }
    return score
