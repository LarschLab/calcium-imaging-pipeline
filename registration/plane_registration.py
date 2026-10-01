"""Register a functional plane onto its matched anatomy slice with ANTs,
and warp its suite2p ROI masks through the fitted transform.

Ports Danin Dharmaperwira's in-plane registration from `ddharmap-ANTs`
(`src/codeants_2pf_hcr/spatial.py`, `_ants_rigid_affine_in_plane_result`;
`matching.py`, `_resample_labels_ants_nn`). Runs after
`registration.plane_matching`, which supplies each plane's best depth and scale.

Workflow, per plane:
    1. Load the plane's suite2p mean image and ROIs (`load_suite2p_plane`);
       check the functional data weren't pre-flipped (`read_functional_xy_frame`).
    2. Register the plane to the anatomy slice (`register_plane_to_anatomy`):
       resize it by its matched scale onto the anatomy pixel grid, place it
       at its NCC position on an anatomy-sized canvas, then refine with ANTs
       Rigid -> Affine inside a square around that position, and score the fit.
    3. Warp the ROIs through the same placement and transform
       (`warp_roi_masks_to_anatomy`).
    4. Write the registration metadata (`write_registration_metadata`).

Terms used below:
    NCC: normalized cross-correlation, a similarity score between two
        images (1 = identical); used to place the plane and to score the
        registration.
    Label image: one image where each pixel holds the number of the ROI it
        belongs to (ROI index + 1, 0 = background). All ROIs are warped
        through the registration in one go this way, then read back per
        ROI number.
"""
import json
import pathlib
import tempfile
import time

import ants
import cv2
import numpy as np
from skimage.transform import resize

from preprocessing.spatial_preprocessing import (
    ACQUISITION_XY_FRAME,
    CANONICAL_XY_FRAME,
    canonical_manifest_path,
    validate_spatial_manifest,
)
from registration.image_utils import local_unsharp, norm01, normalized_cross_correlation
from registration.plane_matching import scale_image

# Where preprocessing_tiff.process_fish writes its metadata, relative to the fish folder.
PREPROCESSING_METADATA_DIR = "02_reg/00_preprocessing/2p_functional/01_individualPlanes"


def load_suite2p_plane(suite2p_plane_folder, file_prefix):
    """Load one suite2p plane's mean image and ROI masks.

    Args:
        suite2p_plane_folder (Path): Folder with this plane's suite2p
            outputs (`{file_prefix}_ops.npy`, `{file_prefix}_stat.npy`).
        file_prefix (str): Filename prefix, e.g. `"{fish_id}_plane{i}"`.

    Returns:
        tuple: `(reference_image, stat_array)` -- suite2p's mean image
        (`ops["meanImg"]`) and the array of per-ROI stat dicts.
    """
    # ops.npy (from Windows Suite2P) can pickle WindowsPath objects, which
    # crash on macOS/Linux -- alias to PosixPath just for this load.
    original_windows_path = pathlib.WindowsPath
    pathlib.WindowsPath = pathlib.PosixPath
    try:
        ops = np.load(suite2p_plane_folder / f"{file_prefix}_ops.npy", allow_pickle=True).item()
        stat_array = np.load(suite2p_plane_folder / f"{file_prefix}_stat.npy", allow_pickle=True)
    finally:
        pathlib.WindowsPath = original_windows_path
    reference_image = ops["meanImg"]
    return reference_image, stat_array


def read_functional_xy_frame(fish_dir):
    """Find which X/Y orientation a fish's preprocessed functional data is in.

    Checks, in order: the canonical spatial-preprocessing manifest (it only
    exists when the functional movies were flipped into the canonical XY
    frame), then `preprocessing_tiff`'s metadata (`output_xy_frame`). Fish
    preprocessed before either record existed have neither and were never
    flipped, so they're reported in the acquisition frame.

    Args:
        fish_dir (Path): Fish folder (named after the fish ID).

    Returns:
        tuple: `(xy_frame, source)` -- the frame ID (`ACQUISITION_XY_FRAME`
        or `CANONICAL_XY_FRAME`) and the file it was read from (or a note
        that it was assumed).
    """
    fish_dir = pathlib.Path(fish_dir)
    manifest_path = canonical_manifest_path(fish_dir)
    if manifest_path.exists():
        # Raises on an incomplete or unknown manifest rather than guessing.
        validate_spatial_manifest(manifest_path)
        return CANONICAL_XY_FRAME, str(manifest_path)
    metadata_path = fish_dir / PREPROCESSING_METADATA_DIR / f"{fish_dir.name}_preprocessing_metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        # Metadata written before the orientation option existed has no
        # output_xy_frame; that workflow never flipped.
        xy_frame = metadata.get("output_xy_frame", ACQUISITION_XY_FRAME)
        return xy_frame, str(metadata_path)
    return ACQUISITION_XY_FRAME, "no preprocessing record found (assumed unflipped)"


def ncc_xy(template, image, low_percentile=1.0, high_percentile=99.0):
    """Find where `template` best matches inside `image`, by NCC.

    Both images are rescaled to uint8 with `norm01`, 
    then matched with `TM_CCORR_NORMED`.

    Args:
        template (numpy.ndarray): Image to place (the resized functional
            plane). Must fit inside `image`.
        image (numpy.ndarray): Image to search (the anatomy slice).
        low_percentile (float): Percentile mapped to 0 before the uint8
            conversion.
        high_percentile (float): Percentile mapped to 255.

    Returns:
        tuple: `(x0, y0, score)` -- top-left column and row of the best
        match, in `image` pixels, and its NCC score.

    Raises:
        ValueError: If `template` is larger than `image` in either
            dimension.
    """
    if template.shape[0] > image.shape[0] or template.shape[1] > image.shape[1]:
        raise ValueError(f"Resized functional plane {template.shape} is larger than the anatomy slice {image.shape}")
    uint8_max = np.iinfo(np.uint8).max
    template_uint8 = (norm01(template, low_percentile, high_percentile) * uint8_max).astype(np.uint8)
    image_uint8 = (norm01(image, low_percentile, high_percentile) * uint8_max).astype(np.uint8)
    response = cv2.matchTemplate(image_uint8, template_uint8, cv2.TM_CCORR_NORMED)
    best_row, best_col = np.unravel_index(np.argmax(response), response.shape)
    best_score = float(response[best_row, best_col])
    return int(best_col), int(best_row), best_score


def _place_on_canvas(image, canvas_shape, x0, y0):
    """Paste an image onto a zero canvas with its top-left corner at (x0, y0).
    Parts of `image` that fall outside the canvas (including for negative offsets) are cropped.

    Args:
        image (numpy.ndarray): 2D image to paste.
        canvas_shape (tuple): `(height, width)` of the canvas.
        x0 (int): Canvas column of the image's top-left corner.
        y0 (int): Canvas row of the image's top-left corner.

    Returns:
        numpy.ndarray or None: Canvas with `image` pasted in (same dtype as
        `image`), or None if `image` doesn't overlap the canvas at all.
    """
    canvas = np.zeros(canvas_shape, dtype=image.dtype)
    image_height, image_width = image.shape
    # Destination window on the canvas, clipped to the canvas edges.
    canvas_row_start, canvas_col_start = max(0, y0), max(0, x0)
    canvas_row_stop = min(canvas_shape[0], y0 + image_height)
    canvas_col_stop = min(canvas_shape[1], x0 + image_width)
    if canvas_row_stop <= canvas_row_start or canvas_col_stop <= canvas_col_start:
        return None
    # Matching source window: skips the image rows/cols that a negative
    # offset pushes off the canvas.
    image_row_start, image_col_start = max(0, -y0), max(0, -x0)
    image_row_stop = image_row_start + (canvas_row_stop - canvas_row_start)
    image_col_stop = image_col_start + (canvas_col_stop - canvas_col_start)
    canvas[canvas_row_start:canvas_row_stop, canvas_col_start:canvas_col_stop] = image[image_row_start:image_row_stop, image_col_start:image_col_stop]
    return canvas


def _square_around_placement(x0, y0, source_shape, canvas_shape, margin_fraction, min_size_px=4):
    """Build the square ANTs is restricted to, around the NCC-placed plane.
    Centred on the placed plane, with a side `margin_fraction` longer than 
    the plane's longer side, and shifted (not cropped) to stay inside the canvas.

    Args:
        x0 (int): Canvas column of the placed plane's top-left corner.
        y0 (int): Canvas row of the placed plane's top-left corner.
        source_shape (tuple): `(height, width)` of the resized plane.
        canvas_shape (tuple): `(height, width)` of the anatomy canvas.
        margin_fraction (float): Extra side length, as a fraction of the
            plane's longer side (0.10 = 10% larger).
        min_size_px (int): Smallest allowed side, in pixels.

    Returns:
        tuple: `(x0, y0, x1, y1)` square in canvas pixels (`x1`/`y1` exclusive).
    """
    plane_height, plane_width = source_shape
    canvas_height, canvas_width = canvas_shape
    center_x = round(x0 + (plane_width - 1) / 2)
    center_y = round(y0 + (plane_height - 1) / 2)
    requested_size = int(np.ceil(max(plane_height, plane_width) * (1 + margin_fraction)))
    # Never smaller than min_size_px, never larger than the canvas.
    size = max(min_size_px, min(requested_size, canvas_height, canvas_width))
    # Clamp the corner so the whole square stays on the canvas.
    square_x0 = min(max(0, round(center_x - size / 2)), canvas_width - size)
    square_y0 = min(max(0, round(center_y - size / 2)), canvas_height - size)
    square_xyxy = (square_x0, square_y0, square_x0 + size, square_y0 + size)
    return square_xyxy


def apply_square_region_mask(image, region_xyxy):
    """Zero an image outside a rectangular region.

    Args:
        image (numpy.ndarray): 2D anatomy image.
        region_xyxy (tuple): `(x0, y0, x1, y1)` region in `image` pixels;
            `x1`/`y1` are exclusive.

    Returns:
        tuple: `(masked_image, region_mask)` -- float32 image zeroed outside
        the region, and the boolean mask of the region.
    """
    x0, y0, x1, y1 = region_xyxy
    region_mask = np.zeros(image.shape, dtype=bool)
    region_mask[y0:y1, x0:x1] = True
    masked_image = np.where(region_mask, image, 0.0).astype(np.float32)
    return masked_image, region_mask


def _ants_image_from_array(array, pixel_size_um):
    """Wrap a 2D array as an ANTs image with isotropic pixel spacing.

    Args:
        array (numpy.ndarray): 2D image array.
        pixel_size_um (float): Isotropic pixel size, in micrometers.

    Returns:
        ants.ANTsImage: `array` wrapped as an ANTs image.
    """
    ants_image = ants.from_numpy(np.asarray(array, dtype=np.float32))
    ants_image.set_spacing((pixel_size_um, pixel_size_um))
    ants_image.set_origin((0.0, 0.0))
    ants_image.set_direction(np.eye(2))
    return ants_image


def _run_rigid_then_affine(fixed_image_ants, moving_image_ants, transform_output_prefix, fixed_mask_ants, aff_iterations, aff_shrink_factors, aff_smoothing_sigmas):
    """Run ANTs Rigid, then Affine starting from the Rigid result.
    The Rigid file is written to a temporary folder and deleted afterwards.

    Args:
        fixed_image_ants (ants.ANTsImage): Anatomy target.
        moving_image_ants (ants.ANTsImage): Functional plane, already
            placed on the anatomy canvas.
        transform_output_prefix (Path or str): Path prefix for the saved
            (Affine) transform file.
        fixed_mask_ants (ants.ANTsImage): Square ANTs scores the match in,
            at every stage.
        aff_iterations (tuple of int): Iterations per resolution level.
        aff_shrink_factors (tuple of int): Downsampling per level.
        aff_smoothing_sigmas (tuple of int): Gaussian smoothing per level.

    Returns:
        tuple: `(affine_registration, transformlist)` -- ANTs' result for
        the Affine stage (includes the warped plane, `warpedmovout`) and the
        list of transform files to apply later (just the Affine file).
    """
    registration_kwargs = {
        "aff_iterations": tuple(aff_iterations),
        "aff_shrink_factors": tuple(aff_shrink_factors),
        "aff_smoothing_sigmas": tuple(aff_smoothing_sigmas),
        "mask": fixed_mask_ants,
        "mask_all_stages": True,
    }

    # Rigid: small rotation/shift correction around the NCC placement. 
    # ANTsPy's default start first lines up the two images'
    # brightness centres; the square mask leaves only the plane's region of
    # the anatomy, so that shift is small.
    with tempfile.TemporaryDirectory() as rigid_directory:
        rigid_registration = ants.registration(
            fixed=fixed_image_ants,
            moving=moving_image_ants,
            type_of_transform="Rigid",
            outprefix=str(pathlib.Path(rigid_directory) / "rigid_"),
            **registration_kwargs,
        )
        # Affine: adds the residual scale/shear correction on top of the rigid fit.
        affine_registration = ants.registration(
            fixed=fixed_image_ants,
            moving=moving_image_ants,
            type_of_transform="Affine",
            initial_transform=rigid_registration["fwdtransforms"][0],
            outprefix=str(transform_output_prefix),
            **registration_kwargs,
        )
    # Named explicitly rather than taken from ANTsPy's `fwdtransforms`: ANTsPy
    # builds that list from every file matching the output prefix, which can
    # pick up unrelated leftovers (e.g. an older run's Rigid file).
    transformlist = [f"{transform_output_prefix}0GenericAffine.mat"]
    return affine_registration, transformlist


def _post_transform_ncc(warped_image, fixed_image, zero_tolerance=1e-8, min_overlap_pixels=4, low_percentile=1.0, high_percentile=99.0):
    """Correlate a warped image with the anatomy where the warped image has data,
    used as a registration-quality score: pixels that are zero in `warped_image` 
    (outside the warped functional plane) are ignored.

    Args:
        warped_image (numpy.ndarray): Registered functional plane, zero
            outside its valid region.
        fixed_image (numpy.ndarray): Anatomy image, same shape.
        zero_tolerance (float): Warped pixels at or below this absolute
            value count as outside the plane.
        min_overlap_pixels (int): Fewer overlapping pixels than this can't
            give a meaningful correlation.
        low_percentile (float): Lower percentile both pixel sets are
            rescaled from (default: Danin's `norm01`).
        high_percentile (float): Upper percentile both pixel sets are
            rescaled from (default: Danin's `norm01`).

    Returns:
        float: Correlation in [-1, 1], or NaN if the shapes differ or fewer
        than `min_overlap_pixels` pixels overlap.
    """
    if warped_image.shape != fixed_image.shape:
        return float("nan")
    overlap = np.isfinite(warped_image) & np.isfinite(fixed_image) & (np.abs(warped_image) > zero_tolerance)
    if int(overlap.sum()) < min_overlap_pixels:
        return float("nan")
    warped_values = norm01(warped_image[overlap], low_percentile, high_percentile)
    fixed_values = norm01(fixed_image[overlap], low_percentile, high_percentile)
    correlation = normalized_cross_correlation(warped_values, fixed_values)
    return correlation


def register_plane_to_anatomy(
    reference_image,
    anatomy_slice,
    anatomy_pixel_size_um,
    functional_scale,
    transform_output_prefix,
    fixed_region_margin_fraction=0.10,
    aff_iterations=(2000, 1000, 500, 250, 100),
    aff_shrink_factors=(12, 8, 4, 2, 1),
    aff_smoothing_sigmas=(4, 3, 2, 1, 0),
    random_seed=123,
    clip_percentiles=(5, 95),
    sharpen_sigma=1.0,
    sharpen_amount=0.6,
    support_threshold=0.5,
    ncc_drop_tolerance=0.005,
):
    """Register one functional plane onto its matched anatomy slice.

    1. Resize the plane by `functional_scale`, so it shares the anatomy's
       pixel grid, and clip-normalize it.
    2. Sharpen and clip-normalize the anatomy slice.
    3. Find the plane's position on the anatomy by NCC and paste it onto a
       zero canvas of the anatomy's shape there -- ANTs starts from that
       placement instead of the (0, 0) corner.
    4. Restrict ANTs to a square around the placed plane (Danin's
       NCC-guided region): the anatomy is zeroed outside it, and ANTs only
       scores the match inside it.
    5. Run ANTs Rigid, then Affine.
    6. Zero the warped plane outside its valid footprint and score the fit.

    The defaults of the tuning arguments are Danin's values
    (`InPlaneRegistrationComparisonConfig`, `_clip_norm01`,
    `local_unsharp`, the region selector's `margin_fraction`), except
    `random_seed`; the values actually used are
    returned under `params`.

    Args:
        reference_image (numpy.ndarray): Functional plane image (e.g. a
            suite2p mean image), at its native resolution.
        anatomy_slice (numpy.ndarray): Matched anatomy Z-slice (raw, not
            sharpened; see `registration.plane_matching`).
        anatomy_pixel_size_um (float): Anatomy's isotropic pixel size, in
            micrometers.
        functional_scale (float): `scale` field from
            `registration.plane_matching.match_plane_to_anatomy` -- resizes
            the plane onto the anatomy's pixel grid.
        transform_output_prefix (Path or str): Path prefix ANTs writes
            transform files under.
        fixed_region_margin_fraction (float): How much longer the square's
            side is than the plane's longer side (0.10 = 10%).
        aff_iterations (tuple of int): Rigid/Affine iterations per
            resolution level, coarse-to-fine (most-downsampled first).
        aff_shrink_factors (tuple of int): Downsampling factor per level.
        aff_smoothing_sigmas (tuple of int): Gaussian smoothing per level.
        random_seed (int): Seed for ANTs' random choice of which pixels to
            sample for the metric, so reruns give identical transforms.
            Non-zero on purpose: ANTsPy passes it to `antsRegistration
            --random-seed`, and ANTs may treat 0 as "unset" and seed from
            the clock (Danin's code uses 0 here).
        clip_percentiles (tuple): `(low, high)` percentile clip applied to
            both images before NCC placement and ANTs.
        sharpen_sigma (float): Gaussian sigma of the anatomy unsharp mask.
        sharpen_amount (float): Blend amount of the anatomy unsharp mask.
        support_threshold (float): The warped "support" image (1 inside
            the plane, 0 outside) counts as inside above this value.
        ncc_drop_tolerance (float): ANTs counts as having lowered the fit
            only if the NCC drops by more than this; smaller drops are
            resampling noise (ANTs improves real planes by ~0.02-0.04).

    Returns:
        dict: Registration result:
            `transformlist` (list of str), `warped_image` (numpy.ndarray,
            zero outside the valid region), `fixed_image` (numpy.ndarray,
            the normalized anatomy target), `ncc_placement` (dict with
            `x0`, `y0`, `score`, `source_shape`, `canvas_shape`),
            `pixel_size_um` (float), `fixed_region_xyxy` (tuple, the square
            used, in anatomy pixels),
            `pre_ants_ncc` and `post_ncc` (float, the same masked
            correlation before and after ANTs), `ants_lowered_fit` (bool),
            `valid_fraction` (float), and `params` (dict of the tuning
            arguments used).

    Raises:
        ValueError: If the resized plane is larger than the anatomy slice.
        RuntimeError: If the NCC placement leaves no overlap with the
            anatomy canvas.
    """
    set_ants_deterministic = getattr(getattr(ants, "config", None), "set_ants_deterministic", None)
    if callable(set_ants_deterministic):
        set_ants_deterministic(True, seed_value=random_seed)

    # 1. Plane resized onto the anatomy pixel grid, then clip-normalized.
    resized_reference = scale_image(reference_image, functional_scale)
    moving_source = norm01(resized_reference, *clip_percentiles)
    # 2. Sharpened anatomy. norm01's defaults (1-99.8, as in drift_analysis.py)
    sharpened_anatomy = local_unsharp(norm01(anatomy_slice), sigma=sharpen_sigma, amount=sharpen_amount)
    fixed_array = norm01(sharpened_anatomy, *clip_percentiles)

    # 3. NCC placement of the plane on the anatomy canvas, plus a ones
    # "support" image marking which canvas pixels hold real plane data.
    x0, y0, ncc_score = ncc_xy(moving_source, fixed_array)
    moving_array = _place_on_canvas(moving_source, fixed_array.shape, x0, y0)
    moving_support = _place_on_canvas(np.ones(moving_source.shape, dtype=np.float32), fixed_array.shape, x0, y0)
    if moving_array is None or moving_support is None:
        raise RuntimeError("NCC placement produced no overlap with the anatomy canvas")

    # 4. Square around the placed plane; ANTs only sees the anatomy inside it.
    fixed_region_xyxy = _square_around_placement(x0, y0, moving_source.shape, fixed_array.shape, fixed_region_margin_fraction)
    fixed_array, region_mask = apply_square_region_mask(fixed_array, fixed_region_xyxy)
    fixed_mask_ants = _ants_image_from_array(region_mask.astype(np.float32), anatomy_pixel_size_um)

    anatomy_fov_um = np.array(anatomy_slice.shape) * anatomy_pixel_size_um
    functional_fov_um = np.array(moving_source.shape) * anatomy_pixel_size_um
    print(f"Anatomy slice FOV:                {anatomy_fov_um} um")
    print(f"Functional FOV (scale-corrected): {functional_fov_um} um")
    # Same score as post_ncc below, on the placed plane before ANTs, so the
    # two can be compared directly (ncc_score uses a different formula).
    pre_ants_ncc = _post_transform_ncc(moving_array, fixed_array)
    print(f"NCC placement: x0={x0}, y0={y0} (anatomy px), score={ncc_score:.3f}")

    # 5. Rigid -> Affine, both images on the anatomy grid.
    fixed_image_ants = _ants_image_from_array(fixed_array, anatomy_pixel_size_um)
    moving_image_ants = _ants_image_from_array(moving_array, anatomy_pixel_size_um)
    affine_registration, transformlist = _run_rigid_then_affine(
        fixed_image_ants, moving_image_ants, transform_output_prefix, fixed_mask_ants,
        aff_iterations, aff_shrink_factors, aff_smoothing_sigmas,
    )

    # 6. Warp the support image to find where the registered plane has
    # data, and zero everything else.
    warped_support = ants.apply_transforms(
        fixed=fixed_image_ants,
        moving=_ants_image_from_array(moving_support, anatomy_pixel_size_um),
        transformlist=transformlist,
        interpolator="nearestNeighbor",
    )
    valid_mask = warped_support.numpy() > support_threshold
    warped_image = np.where(valid_mask, affine_registration["warpedmovout"].numpy(), 0.0).astype(np.float32)
    post_ncc = _post_transform_ncc(warped_image, fixed_array)
    valid_fraction = float(valid_mask.mean())
    print(f"Transform files written: {transformlist}")
    print(f"NCC before ANTs: {pre_ants_ncc:.3f}, after: {post_ncc:.3f}, valid fraction: {valid_fraction:.3f}")
    # Same score before and after, so a real drop means ANTs moved the plane
    # away from a better starting fit; kept but flagged for review.
    ants_lowered_fit = bool(pre_ants_ncc - post_ncc > ncc_drop_tolerance)
    if ants_lowered_fit:
        print(f"WARNING: ANTs lowered the fit (NCC {pre_ants_ncc:.3f} -> {post_ncc:.3f}); check this plane's overlay.")

    # Return a dict with all the relevant outputs, including the transform list for later warping of the ROIs.
    registration = {
        "transformlist": transformlist,
        "warped_image": warped_image,
        "fixed_image": fixed_array,
        "ncc_placement": {
            "x0": x0,
            "y0": y0,
            "score": ncc_score,
            "source_shape": tuple(int(size) for size in moving_source.shape),
            "canvas_shape": tuple(int(size) for size in fixed_array.shape),
        },
        "pixel_size_um": float(anatomy_pixel_size_um),
        "fixed_region_xyxy": fixed_region_xyxy,
        "pre_ants_ncc": pre_ants_ncc,
        "post_ncc": post_ncc,
        "ants_lowered_fit": ants_lowered_fit,
        "valid_fraction": valid_fraction,
        "params": {
            "aff_iterations": list(aff_iterations),
            "aff_shrink_factors": list(aff_shrink_factors),
            "aff_smoothing_sigmas": list(aff_smoothing_sigmas),
            "fixed_region_margin_fraction": fixed_region_margin_fraction,
            "random_seed": random_seed,
            "clip_percentiles": list(clip_percentiles),
            "sharpen_sigma": sharpen_sigma,
            "sharpen_amount": sharpen_amount,
            "support_threshold": support_threshold,
            "ncc_drop_tolerance": ncc_drop_tolerance,
        },
    }
    return registration

def _build_roi_label_image(stat_array, native_shape):
    """Rasterize suite2p ROIs into one label image (ROI index + 1).

    Pixels flagged in a ROI's `overlap` field (shared with another ROI) are left out. 
    ROIs with empty or out-of-bounds pixels are skipped with a warning rather than
    raising, since one bad ROI shouldn't stop the batch.

    Args:
        stat_array (numpy.ndarray): Suite2p `stat.npy` array of per-ROI
            dicts with native-resolution `xpix`/`ypix`.
        native_shape (tuple): `(height, width)` of the functional plane.

    Returns:
        tuple: `(label_image, kept_roi_indices)` -- uint32 label image
        (0 = background) and the indices of the ROIs that were rasterized.
    """
    label_image = np.zeros(native_shape, dtype=np.uint32)
    kept_roi_indices = []
    for roi_index, roi in enumerate(stat_array):
        xpix = np.asarray(roi["xpix"])
        ypix = np.asarray(roi["ypix"])
        in_bounds = (
            xpix.size > 0
            and ypix.size > 0
            and xpix.min() >= 0
            and ypix.min() >= 0
            and xpix.max() < native_shape[1]
            and ypix.max() < native_shape[0]
        )
        if not in_bounds:
            print(f"Skipping ROI {roi_index} with empty/out-of-bounds pixels: xpix={xpix}, ypix={ypix}")
            continue
        if "overlap" in roi:
            not_shared = ~np.asarray(roi["overlap"], dtype=bool)
            xpix, ypix = xpix[not_shared], ypix[not_shared]
        label_image[ypix, xpix] = roi_index + 1
        kept_roi_indices.append(roi_index)
    return label_image, kept_roi_indices


def _resample_labels_ants_nn(label_image, registration):
    """Warp a label image onto the anatomy with a fitted registration.

    The labels get the same resize and NCC placement as the functional plane, then the same ANTs
    transform, all with nearest neighbour so ROI numbers stay intact.

    Args:
        label_image (numpy.ndarray): Label image at the functional plane's
            native resolution (ROI index + 1, 0 = background).
        registration (dict): Result of `register_plane_to_anatomy`.

    Returns:
        numpy.ndarray: Warped int64 label image, shaped like the anatomy slice.

    Raises:
        RuntimeError: If the placement puts the labels outside the anatomy canvas.
    """
    placement = registration["ncc_placement"]
    pixel_size_um = registration["pixel_size_um"]
    # Same resize + placement as the functional plane in
    # `register_plane_to_anatomy` (order=0 keeps labels intact).
    resized_labels = resize(label_image, placement["source_shape"], order=0, preserve_range=True, anti_aliasing=False).astype(np.uint32)
    placed_labels = _place_on_canvas(resized_labels, placement["canvas_shape"], placement["x0"], placement["y0"])
    if placed_labels is None:
        raise RuntimeError("NCC placement puts the functional labels outside the anatomy canvas")

    # Output grid for apply_transforms -- only shape/spacing matter.
    anatomy_domain = _ants_image_from_array(np.zeros(placement["canvas_shape"], dtype=np.float32), pixel_size_um)
    warped_labels_image = ants.apply_transforms(
        fixed=anatomy_domain,
        moving=_ants_image_from_array(placed_labels.astype(np.float32), pixel_size_um),
        transformlist=registration["transformlist"],
        interpolator="nearestNeighbor",
    )
    warped_labels = np.rint(warped_labels_image.numpy()).astype(np.int64)
    return warped_labels


def warp_roi_masks_to_anatomy(stat_array, registration, native_shape, best_depth):
    """Warp suite2p ROI masks into anatomy space using a fitted registration.

    All ROIs go into one label image, which is warped once
    (`_resample_labels_ants_nn`); each ROI's aligned pixels are then read
    back from the warped labels.

    Args:
        stat_array (numpy.ndarray): Suite2p `stat.npy` array of per-ROI
            dicts with native-resolution `xpix`/`ypix`.
        registration (dict): Result of `register_plane_to_anatomy`.
        native_shape (tuple): `(height, width)` of the functional plane.
        best_depth (int): Matched anatomy Z-slice index, stored as `z_pix`.

    Returns:
        list: Copies of `stat_array`'s dicts (skipped ROIs left out) with
        `xpix_aligned`/`ypix_aligned` (numpy.ndarray of int) added,
        `med_aligned` ([row, col] median, `[nan, nan]` if empty), and
        `z_pix` (numpy.ndarray of int, `best_depth` repeated once per
        pixel).
    """
    label_image, kept_roi_indices = _build_roi_label_image(stat_array, native_shape)
    warped_labels = _resample_labels_ants_nn(label_image, registration)

    warped_rois = []
    for roi_index in kept_roi_indices:
        ypix_aligned, xpix_aligned = np.where(warped_labels == roi_index + 1)
        new_roi = dict(stat_array[roi_index])
        new_roi["xpix_aligned"] = xpix_aligned.astype(int)
        new_roi["ypix_aligned"] = ypix_aligned.astype(int)
        if xpix_aligned.size > 0:
            # Suite2p's own [row, col] convention for a "med" field.
            new_roi["med_aligned"] = [float(np.median(ypix_aligned)), float(np.median(xpix_aligned))]
        else:
            new_roi["med_aligned"] = [np.nan, np.nan]
        new_roi["z_pix"] = np.full(xpix_aligned.shape, best_depth)
        warped_rois.append(new_roi)

    empty_roi_count = sum(1 for roi in warped_rois if roi["xpix_aligned"].size == 0)
    print(f"Warped {len(warped_rois)} of {len(stat_array)} ROIs "
          f"({len(stat_array) - len(warped_rois)} skipped as empty/out-of-bounds, "
          f"{empty_roi_count} with no pixels left after warping).")
    return warped_rois


def write_registration_metadata(registration, match, stat_array, warped_rois, sources, fish_id, metadata_path):
    """Write the parameters and results records for one plane's matching + registration as JSON.

    Stores what's needed to reproduce or reuse the result: the depth/scale
    match and its search settings, the source files, the transform chain and
    placement, the QC numbers, and how many ROIs were warped.

    Args:
        registration (dict): Result of `register_plane_to_anatomy`.
        match (dict): Result of
            `registration.plane_matching.match_plane_to_anatomy`.
        stat_array (numpy.ndarray): The plane's suite2p ROIs (for counts).
        warped_rois (list): Result of `warp_roi_masks_to_anatomy`.
        sources (dict): Where the inputs came from (e.g. suite2p folder,
            anatomy path/shape/Z step, functional XY frame); written as-is.
        fish_id (str): Fish identifier, e.g. `"L331_f01"`.
        metadata_path (Path): Output `..._registration_metadata.json` path.
    """
    metadata = {
        "fish_id": fish_id,
        "sources": sources,
        "match": {
            "best_z": int(match["best_z"]),
            "best_z_subslice": float(match["best_z_subslice"]),
            "scale": float(match["scale"]),
            "score": float(match["score"]),
            "scores": [float(score) for score in match["scores"]],
            "params": match["params"],
        },
        "method": "ncc_placement_then_ants_rigid_affine",
        # Apply all files, in this order (ANTs' transform chain).
        "transformlist": [str(path) for path in registration["transformlist"]],
        "ncc_placement": registration["ncc_placement"],
        "pixel_size_um": registration["pixel_size_um"],
        "fixed_region_xyxy": registration["fixed_region_xyxy"],
        "pre_ants_ncc": registration["pre_ants_ncc"],
        "post_ncc": registration["post_ncc"],
        "ants_lowered_fit": registration["ants_lowered_fit"],
        "valid_fraction": registration["valid_fraction"],
        "params": registration["params"],
        "rois": {
            "in_suite2p": len(stat_array),
            "warped": len(warped_rois),
            "skipped_out_of_bounds": len(stat_array) - len(warped_rois),
            "empty_after_warp": sum(1 for roi in warped_rois if roi["xpix_aligned"].size == 0),
        },
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with pathlib.Path(metadata_path).open("w", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2)
