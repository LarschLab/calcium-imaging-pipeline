"""Quality check of the anatomy -> reference brain registrations (step 3).

Loads each fish's warped anatomy (`<fish>_2P_in_ref.nrrd`, on the reference
grid), scores how well it matches the reference (Pearson correlation where
the fish has data, coverage, covered depth range), and picks the reference
depths and low-resolution slices that the QC notebook
(`notebooks/qc_reference_registration.ipynb`) plots. Plotting itself stays in
the notebook.
"""

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import SimpleITK as sitk
from skimage.transform import downscale_local_mean

from utils import itk_readable_paths, itk_safe_directory

REFERENCE_STAGE_DIR = Path("02_reg") / "08_2pa-ref"  # 2P anatomy -> reference brain
CANONICAL_ANATOMY_DIR = Path("02_reg") / "00_preprocessing" / "2p_anatomy"
DATA_THRESHOLD = 1.0  # warped voxels above this hold fish data; outside the fish ANTs writes 0
MIN_SLICE_COVERAGE = 0.05  # a depth counts as covered when >= 5% of its voxels hold fish data
DECISION_COLUMNS = ("decision", "comment")  # filled in by hand, kept across reruns


def warped_anatomy_path(fish_folder, fish_id, reference_name):
    """Return where a fish's anatomy, warped onto the reference, is stored.

    Args:
        fish_folder (Path): The fish's data folder.
        fish_id (str): Fish identifier, e.g. "L978_f01".
        reference_name (str): Reference brain name, e.g. "ref_L433_f02".

    Returns:
        Path: `<fish>/02_reg/08_2pa-ref/aligned/<reference>/<fish_id>_2P_in_ref.nrrd`.
    """
    warped_path = Path(fish_folder) / REFERENCE_STAGE_DIR / "aligned" / reference_name / f"{fish_id}_2P_in_ref.nrrd"
    return warped_path


def reference_anatomy_path(reference_folder):
    """Return the canonical anatomy NRRD of the fish used as reference brain.

    Args:
        reference_folder (Path): The reference fish's data folder.

    Returns:
        Path: `<folder>/02_reg/00_preprocessing/2p_anatomy/<folder>_anatomy_2P_GCaMP.nrrd`.
    """
    reference_path = Path(reference_folder) / CANONICAL_ANATOMY_DIR / f"{Path(reference_folder).name}_anatomy_2P_GCaMP.nrrd"
    return reference_path


def read_nrrd_stack(nrrd_path):
    """Read a 3D NRRD as a float32 (z, y, x) array.

    SimpleITK can't open non-ASCII paths (the UNIL OneDrive), so the file is
    read from an ASCII staging copy when needed.

    Args:
        nrrd_path (Path): NRRD file.

    Returns:
        numpy.ndarray: float32 stack, shape (z, y, x).
    """
    with itk_safe_directory() as staging_directory:
        readable_path = itk_readable_paths([nrrd_path], staging_directory)[0]
        stack = sitk.GetArrayFromImage(sitk.ReadImage(readable_path)).astype(np.float32)
    return stack


def data_mask(warped_stack, threshold=DATA_THRESHOLD):
    """Mark the voxels where the warped fish holds data.

    Args:
        warped_stack (numpy.ndarray): Warped fish, (z, y, x).
        threshold (float): Voxels above this count as data.

    Returns:
        numpy.ndarray: bool mask, same shape.
    """
    mask = warped_stack > threshold
    return mask


def covered_depths(mask, min_slice_coverage=MIN_SLICE_COVERAGE):
    """Find the first and last reference depth the fish covers.

    Args:
        mask (numpy.ndarray): bool data mask, (z, y, x).
        min_slice_coverage (float): Fraction of a slice that must hold data
            for that depth to count (ignores the wavy edges of the warp).

    Returns:
        tuple or None: (first_z, last_z) slice indices, or None if no depth is covered.
    """
    slice_coverage = mask.mean(axis=(1, 2))
    covered_z = np.flatnonzero(slice_coverage >= min_slice_coverage)
    if covered_z.size == 0:
        return None
    depth_range = (int(covered_z[0]), int(covered_z[-1]))
    return depth_range


def overlap_correlation(warped_stack, reference_stack, mask):
    """Pearson correlation of fish and reference over the voxels where the fish has data.

    Sums are accumulated slice by slice in float64, so no full-stack float64
    copy is made (a stack is ~100 M voxels).

    Args:
        warped_stack (numpy.ndarray): Warped fish, (z, y, x).
        reference_stack (numpy.ndarray): Reference, same shape.
        mask (numpy.ndarray): bool data mask, same shape.

    Returns:
        float: Pearson r, or NaN if the overlap is empty or flat.
    """
    sums = np.zeros(6)  # n, sum_x, sum_y, sum_xx, sum_yy, sum_xy
    for fish_slice, reference_slice, mask_slice in zip(warped_stack, reference_stack, mask):
        fish_values = fish_slice[mask_slice].astype(np.float64)
        reference_values = reference_slice[mask_slice].astype(np.float64)
        sums += (fish_values.size, fish_values.sum(), reference_values.sum(),
                 fish_values @ fish_values, reference_values @ reference_values, fish_values @ reference_values)
    n_voxels, sum_x, sum_y, sum_xx, sum_yy, sum_xy = sums
    if n_voxels == 0:
        return float("nan")
    covariance = sum_xy - sum_x * sum_y / n_voxels
    variance_product = (sum_xx - sum_x ** 2 / n_voxels) * (sum_yy - sum_y ** 2 / n_voxels)
    if variance_product <= 0:
        return float("nan")
    correlation = float(covariance / np.sqrt(variance_product))
    return correlation


def data_bounding_box(mask):
    """Return the y/x extent of the fish's data over all depths.

    Args:
        mask (numpy.ndarray): bool data mask, (z, y, x).

    Returns:
        tuple or None: (y0, y1, x0, x1), end-exclusive, or None if the mask is empty.
    """
    rows = np.flatnonzero(mask.any(axis=(0, 2)))
    columns = np.flatnonzero(mask.any(axis=(0, 1)))
    if rows.size == 0:
        return None
    bounding_box = (int(rows[0]), int(rows[-1]) + 1, int(columns[0]), int(columns[-1]) + 1)
    return bounding_box


def summarize_fish(warped_stack, reference_stack, z_spacing_um):
    """Score one fish's registration and describe which part of the reference it covers.

    Args:
        warped_stack (numpy.ndarray): Warped fish, (z, y, x).
        reference_stack (numpy.ndarray): Reference, same shape.
        z_spacing_um (float): Reference slice spacing.

    Returns:
        dict: `correlation`, `coverage` (fraction of the reference volume),
        `z_first`, `z_last` (slice indices, None if nothing covered),
        `depth_first_um`, `depth_last_um`, `bounding_box_yxyx` (y0, y1, x0, x1).
    """
    if warped_stack.shape != reference_stack.shape:
        raise ValueError(f"Warped fish shape {warped_stack.shape} != reference shape {reference_stack.shape}")
    mask = data_mask(warped_stack)
    depth_range = covered_depths(mask)
    z_first, z_last = depth_range if depth_range else (None, None)
    summary = {
        "correlation": overlap_correlation(warped_stack, reference_stack, mask),
        "coverage": float(mask.mean()),
        "z_first": z_first,
        "z_last": z_last,
        "depth_first_um": z_first * z_spacing_um if depth_range else None,
        "depth_last_um": z_last * z_spacing_um if depth_range else None,
        "bounding_box_yxyx": data_bounding_box(mask),
    }
    return summary


def spread_depths(z_first, z_last, n_depths):
    """Pick depths evenly spread inside a range, leaving out its very edges.

    Args:
        z_first (int): First covered slice.
        z_last (int): Last covered slice.
        n_depths (int): How many depths to pick.

    Returns:
        list: Sorted, unique slice indices.
    """
    # n_depths + 2 points, dropping both ends: the edge slices are only partly covered.
    depths = np.linspace(z_first, z_last, n_depths + 2)[1:-1]
    picked_depths = sorted({int(round(depth)) for depth in depths})
    return picked_depths


def common_depths(depth_ranges, n_depths):
    """Pick reference depths that most fish of an experiment cover.

    Uses the median first and last covered slice over fish, so a single
    fish covering an odd range doesn't move the depths shown for everyone.

    Args:
        depth_ranges (list): (z_first, z_last) per fish.
        n_depths (int): How many depths to pick.

    Returns:
        list: Sorted slice indices.
    """
    if not depth_ranges:
        raise ValueError("No covered depth range given: no fish to pick common depths from")
    median_first = int(np.median([z_first for z_first, _ in depth_ranges]))
    median_last = int(np.median([z_last for _, z_last in depth_ranges]))
    picked_depths = spread_depths(median_first, median_last, n_depths)
    return picked_depths


def downsample_stack(stack, xy_factor):
    """Shrink a stack in y and x by block-averaging, keeping every depth.

    Args:
        stack (numpy.ndarray): (z, y, x) stack.
        xy_factor (int): Block size in y and x (1 keeps the stack as is).

    Returns:
        numpy.ndarray: float32 stack, (z, ceil(y / f), ceil(x / f)).
    """
    small_stack = downscale_local_mean(stack, (1, xy_factor, xy_factor)).astype(np.float32)
    return small_stack


def scale_fish_image(fish_image, low_percentile=1.0, high_percentile=99.5, fill_value=0.0):
    """Scale a warped-fish image to 0-1 using only the pixels where the fish has data.

    The empty (0) area around a warped fish would otherwise set the low
    percentile to 0 and wash the tissue out to mid-grey.

    Args:
        fish_image (numpy.ndarray): 2D warped-fish image.
        low_percentile (float): Percentile of the data pixels mapped to 0.
        high_percentile (float): Percentile of the data pixels mapped to 1.
        fill_value (float): Value given to pixels without data (e.g. 0 or NaN).

    Returns:
        numpy.ndarray: float32 image in [0, 1], `fill_value` outside the data.
    """
    has_data = fish_image > DATA_THRESHOLD
    scaled_image = np.full(fish_image.shape, fill_value, dtype=np.float32)
    if not has_data.any():
        return scaled_image
    low, high = np.percentile(fish_image[has_data], (low_percentile, high_percentile))
    intensity_range = max(high - low, 1e-6)  # guard against a flat image
    scaled_image[has_data] = np.clip((fish_image[has_data] - low) / intensity_range, 0.0, 1.0)
    return scaled_image


def fish_mean_image(fish_slices, low_percentile=1.0, high_percentile=99.5):
    """Average the same reference depth over several fish, each scaled to 0-1 first.

    Each fish is scaled on its own data pixels only, and averaged only where
    it has data, so a fish's empty (0) area doesn't darken the mean. A sharp
    mean means the fish agree; a blurry one means some are misplaced.

    Args:
        fish_slices (list): 2D warped-fish images of the same depth and shape.
        low_percentile (float): Lower percentile for scaling each fish.
        high_percentile (float): Upper percentile for scaling each fish.

    Returns:
        numpy.ndarray: float32 mean image, NaN where no fish has data.
    """
    scaled_slices = [scale_fish_image(fish_slice, low_percentile, high_percentile, fill_value=np.nan) for fish_slice in fish_slices]
    stacked_slices = np.stack(scaled_slices)
    # Sum / count by hand instead of np.nanmean, which warns on pixels no fish covers.
    fish_counts = np.sum(~np.isnan(stacked_slices), axis=0)
    value_sums = np.nansum(stacked_slices, axis=0)
    mean_image = np.full(fish_counts.shape, np.nan, dtype=np.float32)
    np.divide(value_sums, fish_counts, out=mean_image, where=fish_counts > 0, casting="unsafe")
    return mean_image


def read_previous_decisions(table_path):
    """Read the hand-filled decisions of an earlier QC table, if there is one.

    Args:
        table_path (Path): The experiment's QC table CSV.

    Returns:
        pandas.DataFrame or None: `fish_id` + DECISION_COLUMNS, or None if no table yet.
    """
    if not Path(table_path).exists():
        return None
    previous_table = pd.read_csv(table_path, dtype=str, keep_default_na=False)
    previous_decisions = previous_table[["fish_id", *DECISION_COLUMNS]]
    return previous_decisions


def add_decision_columns(qc_table, previous_decisions):
    """Add the hand-filled decision columns, keeping decisions made in an earlier run.

    Args:
        qc_table (pandas.DataFrame): One row per fish, with `fish_id`.
        previous_decisions (pandas.DataFrame or None): From `read_previous_decisions`.

    Returns:
        pandas.DataFrame: New table with DECISION_COLUMNS ("" where not decided yet).
    """
    table_without_decisions = qc_table.drop(columns=list(DECISION_COLUMNS), errors="ignore")
    if previous_decisions is None:
        table_with_decisions = table_without_decisions.assign(**{column: "" for column in DECISION_COLUMNS})
        return table_with_decisions
    table_with_decisions = table_without_decisions.merge(previous_decisions, on="fish_id", how="left")
    table_with_decisions[list(DECISION_COLUMNS)] = table_with_decisions[list(DECISION_COLUMNS)].fillna("")
    return table_with_decisions


def write_qc_table(qc_table, table_path, parameters):
    """Write the QC table and its metadata sidecar.

    Args:
        qc_table (pandas.DataFrame): One row per fish.
        table_path (Path): Output CSV.
        parameters (dict): Settings used (reference, thresholds, ...), stored for provenance.

    Returns:
        Path: The metadata JSON written next to the table.
    """
    table_path = Path(table_path)
    table_path.parent.mkdir(parents=True, exist_ok=True)
    qc_table.to_csv(table_path, index=False)
    metadata = {
        **parameters,
        "data_threshold": DATA_THRESHOLD,
        "min_slice_coverage": MIN_SLICE_COVERAGE,
        "n_fish": int(len(qc_table)),
        "columns": list(qc_table.columns),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    metadata_path = table_path.with_name(f"{table_path.stem}_metadata.json")
    metadata_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    return metadata_path
