"""Map registered suite2p ROIs towards the reference brain.

An ROI reaches the reference brain through three coordinate changes:

1. Functional plane -> raw anatomy: the in-plane registration
   (`registration.plane_registration.warp_roi_masks_to_anatomy`).
2. Raw anatomy -> canonical anatomy: the fixed index mapping that
   `preprocessing.spatial_preprocessing.preprocess_anatomy` applies to build
   the 8-bit anatomy NRRD (polarity X/Y flip, Z reversal, X/Y resize).
   No fitting involved -- it depends only on the polarity and the raw shape.
3. Canonical anatomy -> reference brain: the ANTs transform (affine + SyN
   warp) of the anatomy -> reference registration, applied to points.

This module holds the coordinate math of steps 2 and 3. Points move in the
opposite direction to images: an image is warped with `1Warp` + the affine,
a point with the *inverted* affine + `1InverseWarp`
(`*_2P_to_ref_metadata.json`, key `points_to_ref`). Reading and writing the
per-fish tables is in `registration.batch_roi_to_reference`.
"""
import json
import re
from pathlib import Path

import ants
import numpy as np
import pandas as pd

from preprocessing.spatial_preprocessing import normalize_polarity
from utils import itk_readable_paths, itk_safe_directory

# ANTs / ITK physical space. Canonical NRRDs are written in LPS with an
# identity direction, so physical position = origin + voxel index * spacing.
SUPPORTED_NRRD_SPACE = "left-posterior-superior"
N_SPATIAL_DIMENSIONS = 3
# One entry of the transform metadata's `points_to_ref` list: "[file.mat,1]" means "invert".
INVERTED_TRANSFORM_PATTERN = re.compile(r"^\[(?P<file>[^,\]]+),\s*1\]$")
CANONICAL_COLUMNS = ("x_canonical", "y_canonical", "z_canonical")
REFERENCE_UM_COLUMNS = ("x_ref_um", "y_ref_um", "z_ref_um")
REFERENCE_VOXEL_COLUMNS = ("x_ref_vox", "y_ref_vox", "z_ref_vox")
ROI_IDENTITY_COLUMNS = ("fish_id", "plane", "suite2p_index", "is_cell", "cell_probability")


def _rescale_pixel_coordinates(coordinates, source_size, target_size):
    """Map pixel coordinates onto a resized axis (skimage `resize` convention).

    `resize` aligns pixel centres, so a source pixel `i` maps to
    `(i + 0.5) * target_size / source_size - 0.5` on the resized axis.

    Args:
        coordinates (numpy.ndarray): Pixel coordinates along one axis.
        source_size (int): Axis length before resizing.
        target_size (int): Axis length after resizing.

    Returns:
        numpy.ndarray: Float coordinates on the resized axis.
    """
    rescaled_coordinates = (coordinates + 0.5) * target_size / source_size - 0.5
    return rescaled_coordinates


def convert_rois_to_canonical_space(warped_rois, anatomy_shape_zyx, polarity, target_xy_shape=(750, 750)):
    """Convert warped ROI coordinates into the canonical anatomy NRRD's voxels.

    Applies `preprocess_anatomy`'s steps, in its order, to coordinates instead
    of images: the polarity X/Y flip (north flips Y, south flips X), the Z
    reversal, then the X/Y rescale to `target_xy_shape`. Coordinates stay
    floats, because rescaling places pixels between voxel centres.

    Args:
        warped_rois (list): ROI dicts from
            `registration.plane_registration.warp_roi_masks_to_anatomy`, with
            `xpix_aligned`, `ypix_aligned` and `z_pix` in raw-anatomy voxels.
        anatomy_shape_zyx (tuple): `(n_slices, height, width)` of the raw
            anatomy stack the ROIs were registered to.
        polarity (str): Fish orientation, `"north"` or `"south"` (or an alias
            accepted by `normalize_polarity`); the one used for the NRRD.
        target_xy_shape (tuple): `(height, width)` of the canonical NRRD
            (`preprocess_anatomy`'s `target_xy_shape`).

    Returns:
        list: Copies of `warped_rois` with `xpix_canonical`, `ypix_canonical`,
        `zpix_canonical` (float arrays, NRRD voxel indices) and
        `med_canonical` (`[y, x]` median) added.

    Raises:
        ValueError: If `polarity` isn't north/south.
    """
    resolved_polarity = normalize_polarity(polarity)
    if resolved_polarity not in {"north", "south"}:
        raise ValueError(f"polarity must be 'north' or 'south', got {polarity!r}")
    n_slices, height, width = (int(size) for size in anatomy_shape_zyx)
    target_height, target_width = (int(size) for size in target_xy_shape)

    canonical_rois = []
    for roi in warped_rois:
        x = np.asarray(roi["xpix_aligned"], dtype=np.float64)
        y = np.asarray(roi["ypix_aligned"], dtype=np.float64)
        z = np.asarray(roi["z_pix"], dtype=np.float64)
        # 1. Polarity flip, as `apply_canonical_xy`: north flips Y, south flips X.
        if resolved_polarity == "north":
            y = (height - 1) - y
        else:
            x = (width - 1) - x
        # 2. Z reversal, as `np.flip(stack, axis=0)`.
        z = (n_slices - 1) - z
        # 3. X/Y rescale onto the canonical grid.
        x = _rescale_pixel_coordinates(x, width, target_width)
        y = _rescale_pixel_coordinates(y, height, target_height)

        canonical_roi = dict(roi)
        canonical_roi["xpix_canonical"] = x
        canonical_roi["ypix_canonical"] = y
        canonical_roi["zpix_canonical"] = z
        canonical_roi["med_canonical"] = [float(np.median(y)), float(np.median(x))] if x.size > 0 else [np.nan, np.nan]
        canonical_rois.append(canonical_roi)
    return canonical_rois


def _parse_nrrd_vector(text):
    """Parse one NRRD vector such as "(0.5,0,0)" into floats.

    Args:
        text (str): The vector, with parentheses.

    Returns:
        list: Its float components.
    """
    components = [float(value) for value in text.strip().strip("()").split(",")]
    return components


def read_nrrd_header(nrrd_path):
    """Read the text header of a NRRD file (everything before the first blank line).

    Pure Python, so it works on non-ASCII paths that ITK can't open.

    Args:
        nrrd_path (Path): NRRD file.

    Returns:
        dict: Field name -> raw string value (comments skipped).
    """
    header = {}
    with Path(nrrd_path).open("rb") as nrrd_file:
        for raw_line in nrrd_file:
            line = raw_line.decode("ascii", errors="replace").strip()
            if not line:  # a blank line ends the header; the data follow
                break
            if line.startswith("#") or ":" not in line:  # comment or the "NRRD0004" magic line
                continue
            field, value = line.split(":", 1)
            header[field.strip()] = value.strip()
    return header


def read_nrrd_geometry(nrrd_path):
    """Read a 3D NRRD's grid: voxel size, origin and size, in x, y, z order.

    Args:
        nrrd_path (Path): NRRD file.

    Returns:
        dict: `spacing_xyz_um`, `origin_xyz_um` (lists of 3 floats) and
        `size_xyz` (list of 3 ints).

    Raises:
        ValueError: If the NRRD isn't 3D LPS with axis-aligned, positive voxel
            directions (the only layout the voxel <-> micrometre math supports).
    """
    header = read_nrrd_header(nrrd_path)
    if header.get("space") != SUPPORTED_NRRD_SPACE:
        raise ValueError(f"{nrrd_path}: space is {header.get('space')!r}, expected {SUPPORTED_NRRD_SPACE!r}")
    directions = np.array([_parse_nrrd_vector(vector) for vector in header["space directions"].split()])
    if directions.shape != (N_SPATIAL_DIMENSIONS, N_SPATIAL_DIMENSIONS):
        raise ValueError(f"{nrrd_path}: expected 3 space directions, got {header['space directions']!r}")
    spacing = np.diag(directions)
    if not np.allclose(directions, np.diag(spacing)) or np.any(spacing <= 0):
        raise ValueError(f"{nrrd_path}: voxel axes must be aligned with x, y, z and positive, got {directions.tolist()}")
    origin = _parse_nrrd_vector(header.get("space origin", "(0,0,0)"))
    geometry = {
        "spacing_xyz_um": spacing.tolist(),
        "origin_xyz_um": origin,
        "size_xyz": [int(size) for size in header["sizes"].split()],
    }
    return geometry


def voxels_to_um(voxels_xyz, geometry):
    """Convert voxel indices of a grid into physical positions (micrometres).

    Args:
        voxels_xyz (numpy.ndarray): (n, 3) voxel indices, x, y, z columns (NaN allowed).
        geometry (dict): From `read_nrrd_geometry`.

    Returns:
        numpy.ndarray: (n, 3) positions in micrometres.
    """
    points_um = np.asarray(geometry["origin_xyz_um"]) + np.asarray(voxels_xyz, dtype=np.float64) * np.asarray(geometry["spacing_xyz_um"])
    return points_um


def um_to_voxels(points_um, geometry):
    """Convert physical positions (micrometres) into voxel indices of a grid.

    Args:
        points_um (numpy.ndarray): (n, 3) positions, x, y, z columns (NaN allowed).
        geometry (dict): From `read_nrrd_geometry`.

    Returns:
        numpy.ndarray: (n, 3) float voxel indices.
    """
    voxels_xyz = (np.asarray(points_um, dtype=np.float64) - np.asarray(geometry["origin_xyz_um"])) / np.asarray(geometry["spacing_xyz_um"])
    return voxels_xyz


def read_point_transform_files(transform_metadata_path):
    """Read which transform files map points into the reference, and check their order.

    The registration export lists them under `points_to_ref` as
    `["[<affine>.mat,1]", "<InverseWarp>.nii.gz"]`: the affine inverted, then
    the inverse warp. Anything else is refused rather than guessed.

    Args:
        transform_metadata_path (Path): `<fish_id>_2P_to_ref_metadata.json`.

    Returns:
        dict: `affine_path` and `inverse_warp_path`, next to the metadata file.

    Raises:
        ValueError: If `points_to_ref` doesn't have that form.
    """
    transform_metadata_path = Path(transform_metadata_path)
    metadata = json.loads(transform_metadata_path.read_text(encoding="utf-8"))
    point_transforms = metadata.get("transforms", {}).get("points_to_ref", [])
    affine_match = INVERTED_TRANSFORM_PATTERN.match(point_transforms[0]) if len(point_transforms) == 2 else None
    if affine_match is None or "InverseWarp" not in point_transforms[1]:
        raise ValueError(f"{transform_metadata_path}: expected points_to_ref = ['[<affine>,1]', '<InverseWarp>'], got {point_transforms}")
    transform_files = {
        "affine_path": transform_metadata_path.parent / affine_match.group("file"),
        "inverse_warp_path": transform_metadata_path.parent / point_transforms[1],
    }
    return transform_files


def apply_reference_transform_to_points(points_um, affine_path, inverse_warp_path):
    """Move points from a fish's canonical anatomy into the reference brain with ANTs.

    Rows with any NaN coordinate are skipped and stay NaN. Transform files on
    non-ASCII paths are staged in an ASCII folder first (ITK can't open them).

    Args:
        points_um (numpy.ndarray): (n, 3) positions in the fish's canonical
            anatomy, micrometres, x, y, z columns.
        affine_path (Path): `<fish_id>_2P_to_ref_0GenericAffine.mat`.
        inverse_warp_path (Path): `<fish_id>_2P_to_ref_1InverseWarp.nii.gz`.

    Returns:
        numpy.ndarray: (n, 3) positions in the reference brain, micrometres.
    """
    points_um = np.asarray(points_um, dtype=np.float64)
    points_in_reference_um = np.full(points_um.shape, np.nan)
    valid_rows = np.isfinite(points_um).all(axis=1)
    if not valid_rows.any():
        return points_in_reference_um
    point_table = pd.DataFrame(points_um[valid_rows], columns=["x", "y", "z"])
    with itk_safe_directory() as staging_directory:
        readable_affine, readable_warp = itk_readable_paths([affine_path, inverse_warp_path], staging_directory)
        # Points use the affine inverted, then the inverse warp (the reverse of images).
        moved_table = ants.apply_transforms_to_points(N_SPATIAL_DIMENSIONS, point_table, transformlist=[readable_affine, readable_warp], whichtoinvert=[True, False])
    points_in_reference_um[valid_rows] = moved_table[["x", "y", "z"]].to_numpy()
    return points_in_reference_um


def build_reference_roi_table(roi_table, points_in_reference_um, reference_geometry):
    """Combine a fish's ROI table with its ROI centres in the reference brain.

    Args:
        roi_table (pandas.DataFrame): The fish's `<fish_id>_roi_positions.csv`.
        points_in_reference_um (numpy.ndarray): (n, 3) reference positions,
            same row order as `roi_table`.
        reference_geometry (dict): `read_nrrd_geometry` of the reference anatomy.

    Returns:
        pandas.DataFrame: One row per ROI: identity columns, reference position
        in micrometres and in reference voxels, and the original canonical voxels.

    Raises:
        ValueError: If the row counts differ.
    """
    if len(roi_table) != len(points_in_reference_um):
        raise ValueError(f"{len(roi_table)} ROIs but {len(points_in_reference_um)} reference points")
    reference_voxels = um_to_voxels(points_in_reference_um, reference_geometry)
    identity_columns = [column for column in ROI_IDENTITY_COLUMNS if column in roi_table.columns]
    reference_table = roi_table[identity_columns].reset_index(drop=True).copy()
    for column_index, column in enumerate(REFERENCE_UM_COLUMNS):
        reference_table[column] = points_in_reference_um[:, column_index]
    for column_index, column in enumerate(REFERENCE_VOXEL_COLUMNS):
        reference_table[column] = reference_voxels[:, column_index]
    for column in CANONICAL_COLUMNS:
        reference_table[column] = roi_table[column].to_numpy()
    return reference_table
