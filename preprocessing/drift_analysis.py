"""Z-drift QC: track how each functional plane's best-matching anatomy depth
changes across time (recording blocks).

During an experiment the imaged plane can slowly move in depth (Z drift), e.g.
from laser power/heating or fish movement, so later blocks may record a
different part of the brain than earlier ones. For every motion-corrected
plane of a fish (`run_drift_analysis`):
1. Build a pooled reference image (after block 0) and find its scale, best
   anatomy depth and X/Y position on the canonical anatomy NRRD (NCC search;
   the matching functions come from `registration/`).
2. Split every block into windows (thirds by default) and find the best-matching anatomy depth for
   each, near the reference position; the change in depth over time is the
   Z drift. Block 0 is shown for settling but excluded from the decision.
3. Summarize per session whether the drift is acceptable (pass / review /
   fail candidate), and write CSV tables, QC plots and a JSON manifest.

Inputs: the canonical anatomy NRRD, the preprocessing metadata (sessions) and
the motion-corrected plane TIFFs declared in the spatial manifest -- so it
runs only on fish from the canonical spatial workflow.

Call order in `run_drift_analysis`: read inputs -> `_run_plane` per plane
(`pooled_analysis_reference`, `search_scale`, `build_window_references`,
`tracked_local_depth_profile`) -> `summarize_sessions` -> CSVs, `_render_*`
plots and manifest.

Used by:
- `drift_analysis_cli.py`: retrospective run on an already processed fish.
- `motion_segmentation_suite2p.py`: the NCC-gated Suite2P run, after motion
  correction and before ROI segmentation (report only, or stop on a bad result).
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time

import cv2
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import ndimage as ndi
from skimage.registration import phase_cross_correlation
import tifffile

from preprocessing.spatial_preprocessing import (
    CANONICAL_XY_FRAME,
    REGISTRATION_Z_FRAME,
    canonical_manifest_path,
    validate_spatial_manifest,
)
from registration.image_utils import local_unsharp, norm01, normalized_cross_correlation
from registration.plane_matching import find_best_xy_at_each_depth, refine_peak_depth, scale_image, search_scale


# How each block window is placed: tracked near the anchor position, full-slice search as fallback.
PLACEMENT_METHOD = "tracked_local_xy_with_global_fallback"
# The anchor reference: frames pooled from all blocks after block 0 (settling).
REFERENCE_SELECTION = "pooled_post_block0"
MANIFEST_VERSION = 4  # layout version of the output manifest
PHASE_CORRELATION_UPSAMPLING = 10  # sub-pixel precision of the X/Y shift: 1/10 pixel


# All sampling, search and decision settings of the drift analysis (recorded in the output manifest).
@dataclass(frozen=True)
class FunctionalAnatomyQCConfig:
    windows_per_block: int = 3  # time windows each block is split into (thirds)
    sampled_frames_per_window: int = 80  # frames read per window
    top_correlated_frames: int = 20  # most typical frames averaged into each reference
    top_corr_pre_smooth_sigma: float = 0.5
    sharpen_sigma: float = 1.0
    sharpen_amount: float = 0.6
    scale_coarse: tuple[float, float, float] = (0.45, 1.0, 0.05)  # (start, stop, step) of the coarse scale search
    scale_fine_half_window: float = 0.05
    scale_fine_step: float = 0.01
    scale_xfine_half_window: float = 0.01
    scale_xfine_step: float = 0.002
    local_xy_radius_px: int = 8  # half-width of the X/Y search around the predicted position
    local_xy_fallback_score: float = 0.2  # below this NCC, redo the search over the whole slice
    min_consensus_change_slices: float = 2.0  # depth change (slices) counted as real drift
    min_plane_direction_fraction: float = 0.6  # share of planes that must drift the same way
    weak_median_ncc: float = 0.3  # below this median NCC, matches are too weak to trust
    workers: int = 1


def read_canonical_anatomy(path):
    """Read prepared anatomy together with its X/Y/Z physical spacing.

    Args:
        path (str or Path): Path to the canonical anatomy NRRD file.

    Returns:
        tuple: `(anatomy_zyx, spacing)` -- the uint8 (Z, Y, X) volume, and a
        tuple of three floats giving the X, Y, Z physical spacing in the units
        stored in the NRRD.

    Raises:
        ValueError: If the file isn't an NRRD, or isn't a uint8 (Z, Y, X) volume.
        ImportError: If SimpleITK isn't installed.
    """
    source = Path(path)
    if source.suffix.lower() != ".nrrd":
        raise ValueError(f"Canonical NCC anatomy must be an NRRD, got {source}")
    try:
        import SimpleITK as sitk
    except Exception as exc:  # pragma: no cover - environment dependent
        raise ImportError("SimpleITK is required to read canonical anatomy NRRD") from exc
    image = sitk.ReadImage(str(source))
    anatomy_array = sitk.GetArrayFromImage(image)
    spacing = tuple(float(value) for value in image.GetSpacing())  # SimpleITK gives X, Y, Z
    if anatomy_array.ndim != 3 or anatomy_array.dtype != np.uint8:
        raise ValueError(f"Expected canonical uint8 Z,Y,X anatomy, got {anatomy_array.dtype} {anatomy_array.shape}: {source}")
    anatomy_zyx = np.asarray(anatomy_array)
    return anatomy_zyx, spacing


def load_preprocessing_sessions(metadata_path):
    """Load recording sessions and the source blocks belonging to each one.

    Reads a preprocessing metadata JSON file and returns its `sessions`
    list in a normalized form. If the file has no `sessions` list, it
    falls back to building a single legacy session from top-level
    `n_planes` and `blocks` fields.

    Args:
        metadata_path (str or Path): Path to the preprocessing metadata
            JSON file.

    Returns:
        list: List of dicts, one per session, each with `session_label`
        (str), `session_number` (int), `output_planes` (list of int), and
        `selected_tiffs` (list of str).

    Raises:
        ValueError: If the metadata has no sessions (nor `n_planes` and `blocks`),
            or a session lacks `output_planes` or `selected_tiffs`.
    """
    payload = json.loads(Path(metadata_path).read_text())
    sessions = payload.get("sessions")
    # Older metadata has no `sessions` list: build one session from `n_planes` and `blocks`.
    if not isinstance(sessions, list) or not sessions:
        n_planes = int(payload.get("n_planes", 0) or 0)
        if n_planes <= 0:
            raise ValueError(f"Preprocessing metadata has no sessions or n_planes: {metadata_path}")
        blocks = payload.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            raise ValueError(
                "Legacy preprocessing metadata must list selected blocks so temporal block boundaries are explicit"
            )
        sessions = [
            {
                "session_label": "r1",
                "session_number": 1,
                "output_planes": list(range(n_planes)),
                "selected_tiffs": [str(value) for value in blocks],
            }
        ]
    # Each entry of `selected_tiffs` is one acquisition block.
    normalized = []
    for index, session in enumerate(sessions):
        if not isinstance(session, dict):
            continue
        planes = [int(value) for value in session.get("output_planes", [])]
        selected = [str(value) for value in session.get("selected_tiffs", [])]
        if not planes or not selected:
            raise ValueError(f"Session {index + 1} lacks output_planes or selected_tiffs: {metadata_path}")
        normalized.append(
            {
                "session_label": str(session.get("session_label") or f"r{index + 1}"),
                "session_number": int(session.get("session_number", index + 1)),
                "output_planes": planes,
                "selected_tiffs": selected,
            }
        )
    return normalized


def block_window_labels(block_count, windows_per_block=3):
    """Create one label per time window of every recording block.

    Args:
        block_count (int): Number of acquisition blocks.
        windows_per_block (int): Windows each block is split into.

    Returns:
        tuple: `windows_per_block` labels per block, "Block {block}\\n{window}",
        where the window is "first/middle/final third" for 3 windows and
        "window {i} of {N}" otherwise.

    Raises:
        ValueError: If `block_count` isn't positive.
    """
    if block_count < 1:
        raise ValueError("block_count must be positive")
    # Thirds keep their historical names, so default outputs are unchanged.
    if windows_per_block == 3:
        window_names = ("first third", "middle third", "final third")
    else:
        window_names = tuple(f"window {index + 1} of {windows_per_block}" for index in range(windows_per_block))
    labels = tuple(f"Block {block}\n{window_name}" for block in range(block_count) for window_name in window_names)
    return labels


def block_window_bounds(frame_count, block_count, windows_per_block=3):
    """Divide equal recording blocks into `windows_per_block` frame ranges each.

    Args:
        frame_count (int): Total number of frames in the movie.
        block_count (int): Number of equally sized acquisition blocks the
            frames are divided into.
        windows_per_block (int): Windows each block is split into.

    Returns:
        tuple: Tuple of `(start, stop)` int pairs, `windows_per_block` per
        block, giving the frame range of each window.

    Raises:
        ValueError: If there are too few frames, or they don't divide evenly into blocks.
    """
    if frame_count < block_count * windows_per_block:
        raise ValueError(f"Not enough frames to divide every acquisition block into {windows_per_block} windows")
    if frame_count % block_count != 0:
        raise ValueError(
            f"Motion-corrected frames ({frame_count}) do not divide evenly across {block_count} blocks"
        )
    frames_per_block = frame_count // block_count
    bounds = []
    for block in range(block_count):
        block_start = block * frames_per_block
        # N + 1 edges -> N equal windows of this block.
        edges = np.linspace(block_start, block_start + frames_per_block, windows_per_block + 1, dtype=int)
        bounds.extend((int(edges[window_index]), int(edges[window_index + 1])) for window_index in range(windows_per_block))
    window_bounds = tuple(bounds)
    return window_bounds


def _sample_indices(start, stop, count):
    """Choose evenly spaced frame numbers from one time window.

    Args:
        start (int): First frame index of the window (inclusive).
        stop (int): One past the last frame index of the window
            (exclusive).
        count (int): Desired number of samples; capped at the number of
            frames actually available in the window.

    Returns:
        numpy.ndarray: Integer array of evenly spaced frame indices within
        `[start, stop)`.

    Raises:
        ValueError: If the window `[start, stop)` is empty.
    """
    effective = min(int(count), int(stop - start))  # can't sample more frames than the window has
    if effective < 1:
        raise ValueError(f"Empty temporal window {start}:{stop}")
    frame_indices = np.linspace(start, stop - 1, effective, dtype=int)
    return frame_indices


def top_correlated_mean(
    stack,
    *,
    take_k,
    pre_smooth_sigma,
):
    """Average the sampled frames that best resemble the window's typical image.

    Computes each frame's correlation to the (optionally smoothed) mean of
    the stack, then averages the `take_k` frames with the highest
    correlation.

    Args:
        stack (numpy.ndarray): Frames array, shaped (n_frames, height,
            width).
        take_k (int): Number of top-correlated frames to average; clamped
            to the number of frames available.
        pre_smooth_sigma (float): Gaussian smoothing sigma applied before
            computing correlations; 0 disables smoothing.

    Returns:
        numpy.ndarray: Mean image of the top-correlated frames.
    """
    frames = np.asarray(stack, dtype=np.float32)
    initial = frames.mean(axis=0)
    compare_reference = ndi.gaussian_filter(initial, pre_smooth_sigma) if pre_smooth_sigma > 0 else initial
    # Score every frame against the window's mean image (optionally smoothed first).
    correlations = np.empty(frames.shape[0], dtype=np.float32)
    for index, frame in enumerate(frames):
        compare = ndi.gaussian_filter(frame, pre_smooth_sigma) if pre_smooth_sigma > 0 else frame
        correlations[index] = normalized_cross_correlation(compare, compare_reference)
    selected = np.argsort(correlations)[-min(int(take_k), frames.shape[0]) :]  # keep the most typical frames, dropping e.g. motion artefacts
    mean_image = frames[selected].mean(axis=0)
    return mean_image


def _read_sampled_frames(path, indices):
    """Read requested TIFF pages without loading the full movie when possible.

    Tries to memory-map the movie and index directly into it; falls back to
    reading individual pages via `tifffile.TiffFile` if memory-mapping
    fails.

    Args:
        path (Path): Path to the movie TIFF.
        indices (Iterable[int]): Frame indices to read.

    Returns:
        numpy.ndarray: Float32 array of the requested frames, shaped
        (len(indices), height, width).
    """
    selected = np.asarray(list(indices), dtype=int)
    # Memory-mapping reads only the requested frames; TIFFs that can't be mapped are read page by page.
    try:
        movie = tifffile.memmap(path)
        sampled_frames = np.asarray(movie[selected], dtype=np.float32)
        return sampled_frames
    except ValueError:  # tifffile: "image data are not memory-mappable" (e.g. compressed TIFF)
        with tifffile.TiffFile(path) as movie_tiff:
            sampled_frames = np.stack([np.asarray(movie_tiff.pages[int(index)].asarray(), dtype=np.float32) for index in selected])
            return sampled_frames


def movie_shape(path):
    """Return movie length, height, and width without reading every frame.

    Args:
        path (str or Path): Path to the movie TIFF.

    Returns:
        tuple: `(page_count, height, width)` as ints.

    Raises:
        ValueError: If the movie's pages aren't 2-D images.
    """
    target = Path(path)
    with tifffile.TiffFile(target) as movie_tiff:
        page_count = len(movie_tiff.pages)  # one page per frame
        first_shape = tuple(int(value) for value in movie_tiff.pages[0].shape)
    if len(first_shape) != 2:
        raise ValueError(f"Expected 2D movie pages, got {first_shape}: {target}")
    height, width = first_shape
    return page_count, height, width


def build_window_references(
    movie_path,
    *,
    block_count,
    config,
):
    """Build one representative functional image for every block third.

    For each first/middle/final third of every acquisition block, samples
    frames, averages the top-correlated ones, normalizes, and sharpens the
    result into a reference image.

    Args:
        movie_path (str or Path): Path to the motion-corrected movie TIFF.
        block_count (int): Number of acquisition blocks in the movie.
        config (FunctionalAnatomyQCConfig): Sampling and sharpening
            settings.

    Returns:
        tuple: `(references, bounds, labels)`, where `references` is a list
        of sharpened, normalized reference images (one per block third),
        `bounds` is the matching tuple of `(start, stop)` frame ranges, and
        `labels` is the matching tuple of block-third label strings.
    """
    target = Path(movie_path)
    frame_count, _, _ = movie_shape(target)
    bounds = block_window_bounds(frame_count, block_count, config.windows_per_block)
    labels = block_window_labels(block_count, config.windows_per_block)
    references = []
    # For each window: sample frames, average the most typical ones, normalize and sharpen.
    for start, stop in bounds:
        indices = _sample_indices(start, stop, config.sampled_frames_per_window)
        sampled = _read_sampled_frames(target, indices)
        reference = top_correlated_mean(
            sampled,
            take_k=config.top_correlated_frames,
            pre_smooth_sigma=config.top_corr_pre_smooth_sigma,
        )
        references.append(
            local_unsharp(norm01(reference), config.sharpen_sigma, config.sharpen_amount)
        )
    return references, bounds, labels


def pooled_analysis_reference(
    movie_path,
    *,
    block_count,
    config,
):
    """Combine post-settling frames into one stable plane-placement reference.

    Excludes the first block (assumed to be an initial settling period),
    samples frames from the remaining recording, averages the
    top-correlated ones, and normalizes and sharpens the result.

    Args:
        movie_path (str or Path): Path to the motion-corrected movie TIFF.
        block_count (int): Number of acquisition blocks in the movie; must
            be at least 2 so Block 0 can be excluded.
        config (FunctionalAnatomyQCConfig): Sampling and sharpening
            settings.

    Returns:
        numpy.ndarray: Sharpened, normalized pooled reference image.

    Raises:
        ValueError: If there are fewer than 2 blocks, or the frames don't divide
            evenly into blocks.
    """
    target = Path(movie_path)
    frame_count, _, _ = movie_shape(target)
    if block_count < 2:
        raise ValueError("block_count must be >= 2 so Block 0 can be excluded from pooled-reference analysis")
    if frame_count % block_count != 0:
        raise ValueError(f"Movie frames do not divide evenly across blocks: {target}")
    # Skip block 0 (settling) and sample from the rest of the recording.
    first_analysis_frame = frame_count // block_count
    indices = _sample_indices(first_analysis_frame, frame_count, config.sampled_frames_per_window * 2)
    sampled = _read_sampled_frames(target, indices)
    reference = top_correlated_mean(
        sampled,
        take_k=config.top_correlated_frames,
        pre_smooth_sigma=config.top_corr_pre_smooth_sigma,
    )
    pooled_reference = local_unsharp(norm01(reference), config.sharpen_sigma, config.sharpen_amount)
    return pooled_reference


def _bounded_xy_depth_profile(
    template,
    anatomy_zyx,
    *,
    predicted_x,
    predicted_y,
    radius,
):
    """Search near expected X/Y positions while moving through anatomy depth.

    At every anatomy depth, restricts the normalized cross-correlation
    template match to a square window around `(predicted_x, predicted_y)`
    and records whether the match landed on the window's boundary.

    Args:
        template (numpy.ndarray): Functional reference image to place
            within the anatomy volume.
        anatomy_zyx (numpy.ndarray): Anatomy volume, shaped (Z, Y, X).
        predicted_x (int): Expected top-left X coordinate of the match.
        predicted_y (int): Expected top-left Y coordinate of the match.
        radius (int): Half-width, in pixels, of the search window around
            the predicted position.

    Returns:
        tuple: `(scores, xs, ys, touched)`, four arrays of length equal to
        the number of anatomy slices: best-match NCC score, top-left X and
        Y coordinates of that match, and a bool flag marking depths where
        the match touched the search window's edge. Depths with an empty
        search window keep a score of `-inf`, coordinates of `-1`, and
        `touched` False.
    """
    moving = norm01(template)
    height, width = moving.shape
    scores = np.full(anatomy_zyx.shape[0], -np.inf, dtype=np.float32)
    xs = np.full(anatomy_zyx.shape[0], -1, dtype=np.int32)
    ys = np.full(anatomy_zyx.shape[0], -1, dtype=np.int32)
    touched = np.zeros(anatomy_zyx.shape[0], dtype=bool)
    for z_index, anatomy_slice in enumerate(anatomy_zyx):
        fixed = norm01(anatomy_slice)
        # Valid top-left positions keep the template inside the slice.
        max_x = fixed.shape[1] - width
        max_y = fixed.shape[0] - height
        x0, x1 = max(0, predicted_x - radius), min(max_x, predicted_x + radius)
        y0, y1 = max(0, predicted_y - radius), min(max_y, predicted_y + radius)
        if x1 < x0 or y1 < y0:
            continue
        search = fixed[y0 : y1 + height, x0 : x1 + width]  # window padded by the template size
        response = cv2.matchTemplate(search, moving, cv2.TM_CCORR_NORMED)
        _, maximum, _, location = cv2.minMaxLoc(response)
        x = x0 + int(location[0])
        y = y0 + int(location[1])
        scores[z_index], xs[z_index], ys[z_index] = float(maximum), x, y
        touched[z_index] = x in {x0, x1} or y in {y0, y1}  # a match on the window edge may have a better optimum outside it
    return scores, xs, ys, touched


def tracked_local_depth_profile(
    interval_reference,
    canonical_reference,
    anatomy_zyx,
    *,
    scale,
    canonical_x,
    canonical_y,
    config,
):
    """Track a local depth profile, using a full search when confidence is weak.

    Predicts the interval's X/Y position from the phase-correlation shift
    between the interval and canonical references, then searches near that
    position at every anatomy depth. Falls back to a full-canvas search
    when the local match is weak or touches the local-search boundary.

    Args:
        interval_reference (numpy.ndarray): Functional reference image for
            this time interval.
        canonical_reference (numpy.ndarray): Pooled functional reference
            used as the tracking anchor.
        anatomy_zyx (numpy.ndarray): Anatomy volume, shaped (Z, Y, X).
        scale (float): Image scale factor applied to both references before
            matching.
        canonical_x (int): Anchor X coordinate of the canonical reference's
            best match in the anatomy volume.
        canonical_y (int): Anchor Y coordinate of the canonical reference's
            best match in the anatomy volume.
        config (FunctionalAnatomyQCConfig): Local search radius and
            fallback-score threshold settings.

    Returns:
        dict: Placement result with keys `scores` (numpy.ndarray of
        per-depth NCC scores), `best_z` (int), `best_z_subslice` (float),
        `max_score` (float), `x` (int), `y` (int), `functional_shift_x`
        (float), `functional_shift_y` (float), `predicted_x` (int),
        `predicted_y` (int), and `fallback_reason` (str or None).
    """
    interval_scaled = scale_image(interval_reference, scale)
    canonical_scaled = scale_image(canonical_reference, scale)
    # How far this interval's image moved in X/Y relative to the pooled reference.
    shift_yx, _, _ = phase_cross_correlation(
        norm01(canonical_scaled),
        norm01(interval_scaled),
        upsample_factor=PHASE_CORRELATION_UPSAMPLING,
    )
    # Expected position on the anatomy: the pooled reference's position plus that shift.
    predicted_x = int(round(canonical_x + float(shift_yx[1])))
    predicted_y = int(round(canonical_y + float(shift_yx[0])))
    scores, xs, ys, touched = _bounded_xy_depth_profile(
        interval_scaled,
        anatomy_zyx,
        predicted_x=predicted_x,
        predicted_y=predicted_y,
        radius=config.local_xy_radius_px,
    )
    best_z = int(np.nanargmax(scores))
    # Redo the search over the whole slice when the local result is unreliable.
    fallback_reason = None
    if float(scores[best_z]) < config.local_xy_fallback_score:
        fallback_reason = "weak_local_ncc"
    elif bool(touched[best_z]):
        fallback_reason = "local_search_boundary"
    if fallback_reason:
        scores, xs, ys = find_best_xy_at_each_depth(interval_scaled, anatomy_zyx)
        best_z = int(np.nanargmax(scores))
    tracked_placement = {
        "scores": scores,
        "best_z": best_z,
        "best_z_subslice": refine_peak_depth(scores),
        "max_score": float(scores[best_z]),
        "x": int(xs[best_z]),
        "y": int(ys[best_z]),
        "functional_shift_x": float(shift_yx[1]),
        "functional_shift_y": float(shift_yx[0]),
        "predicted_x": predicted_x,
        "predicted_y": predicted_y,
        "fallback_reason": fallback_reason,
    }
    return tracked_placement


def _plane_index(path):
    """Extract the plane number from a motion-corrected TIFF filename.

    Args:
        path (Path): Motion-corrected movie TIFF path, expected to contain
            "plane<N>" in its filename.

    Returns:
        int: The parsed plane index.

    Raises:
        ValueError: If the filename has no "plane<N>".
    """
    match = re.search(r"plane(\d+)", path.name)
    if match is None:
        raise ValueError(f"Could not parse plane index from {path.name}")
    plane_index = int(match.group(1))
    return plane_index


def discover_motion_corrected_movies(fish_dir, fish_id):
    """Find one motion-corrected TIFF for each functional plane.

    Args:
        fish_dir (str or Path): Fish root directory.
        fish_id (str): Fish identifier used in the movie filenames.

    Returns:
        dict: Mapping of plane index (int) to motion-corrected movie path
        (Path), sorted by plane index.

    Raises:
        FileNotFoundError: If no motion-corrected movie is found.
    """
    movie_folder = Path(fish_dir) / "02_reg" / "00_preprocessing" / "2p_functional" / "02_motionCorrected"
    movies = {_plane_index(path): path for path in movie_folder.glob(f"{fish_id}_plane*_mcorrected.tif")}  # plane index -> movie file
    if not movies:
        raise FileNotFoundError(f"No motion-corrected movies found under {movie_folder}")
    movies_by_plane = dict(sorted(movies.items()))
    return movies_by_plane


def _interval_row(fish_id, session_label, plane_index, interval_index, label, frame_bounds, scale, result, z_spacing_um, runtime_seconds, windows_per_block):
    """Build the output row for one tracked block third.

    Args:
        fish_id (str): Fish identifier.
        session_label (str): Session the plane belongs to.
        plane_index (int): Functional plane index.
        interval_index (int): Position of this block third in the recording.
        label (str): Block-third label, e.g. "Block 1\nfirst third".
        frame_bounds (tuple): `(start, stop)` frame range of the third.
        scale (float): Scale of the plane's anchor placement.
        result (dict): Output of `tracked_local_depth_profile` for this third.
        z_spacing_um (float): Anatomy Z-slice spacing, in micrometers.
        runtime_seconds (float): Time the tracking took.
        windows_per_block (int): Windows each block is split into.

    Returns:
        dict: One row of `ncc_drift_intervals.csv`.
    """
    start, stop = frame_bounds
    interval_row = {
        "fish_id": fish_id,
        "session": session_label,
        "plane_index": plane_index,
        "interval_index": interval_index,
        "interval_label": label,
        "block_index": interval_index // windows_per_block,
        # TODO: renamed from "block_third_index" now that the number of windows is
        # configurable; check with Danin that no script reads the old column name.
        "block_window_index": interval_index % windows_per_block,
        "included_in_drift_gate": interval_index // windows_per_block > 0,  # block 0 (settling) is excluded
        "frame_start": start,
        "frame_stop": stop,
        "scale": scale,
        "placement_method": PLACEMENT_METHOD,
        "best_z": result["best_z"],
        "best_z_subslice": result["best_z_subslice"],
        "best_z_um": result["best_z_subslice"] * z_spacing_um,
        "max_score": result["max_score"],
        "x": result["x"],
        "y": result["y"],
        "functional_shift_x": result["functional_shift_x"],
        "functional_shift_y": result["functional_shift_y"],
        "predicted_x": result["predicted_x"],
        "predicted_y": result["predicted_y"],
        "fallback_reason": result["fallback_reason"],
        "runtime_seconds": runtime_seconds,
    }
    return interval_row


def _interval_profile_rows(fish_id, session_label, plane_index, interval_index, label, scores, z_spacing_um, windows_per_block):
    """Build one row per anatomy depth with a block third's NCC score (for the heatmaps).

    Args:
        fish_id (str): Fish identifier.
        session_label (str): Session the plane belongs to.
        plane_index (int): Functional plane index.
        interval_index (int): Position of this block third in the recording.
        label (str): Block-third label.
        scores (numpy.ndarray): Per-depth NCC scores of this third.
        z_spacing_um (float): Anatomy Z-slice spacing, in micrometers.
        windows_per_block (int): Windows each block is split into.

    Returns:
        list: Rows of `ncc_drift_profiles.csv`, one per anatomy depth.
    """
    profile_rows = [
        {
            "fish_id": fish_id,
            "session": session_label,
            "plane_index": plane_index,
            "interval_index": interval_index,
            "interval_label": label,
            "block_index": interval_index // windows_per_block,
            "included_in_drift_gate": interval_index // windows_per_block > 0,
            "placement_method": PLACEMENT_METHOD,
            "anatomy_z": z_index,
            "anatomy_z_um": z_index * z_spacing_um,
            "ncc": float(score),
        }
        for z_index, score in enumerate(scores)
    ]
    return profile_rows


def _plane_summary(fish_id, session_label, plane_index, placement, anchor_scores, reference_shape, scale_seconds, block_count):
    """Summarize a plane's anchor placement and how distinct its depth peak is.

    Args:
        fish_id (str): Fish identifier.
        session_label (str): Session the plane belongs to.
        plane_index (int): Functional plane index.
        placement (dict): `search_scale` result for the pooled reference.
        anchor_scores (numpy.ndarray): Its per-depth NCC scores (float32).
        reference_shape (tuple): `(height, width)` of the pooled reference.
        scale_seconds (float): Time the scale search took.
        block_count (int): Number of acquisition blocks.

    Returns:
        dict: One row of `ncc_scale_bestz_by_plane.csv`.
    """
    anchor_metrics = _depth_profile_metrics(anchor_scores)
    best_z_subslice = refine_peak_depth(anchor_scores)
    plane_summary = {
        "fish_id": fish_id,
        "session": session_label,
        "plane_index": plane_index,
        "plane_label": f"{fish_id}_plane{plane_index}_mcorrected",
        "reference_selection": REFERENCE_SELECTION,
        "scale": float(placement["scale"]),
        "best_z": int(placement["best_z"]),
        "best_z_subslice": best_z_subslice,
        "max_ncc": float(placement["score"]),
        "placement_x": int(placement["x"]),
        "placement_y": int(placement["y"]),
        "peak_delta": anchor_metrics["peak_delta"],
        "peak_zscore": anchor_metrics["peak_zscore"],
        "peak_at_z_boundary": bool(anchor_metrics["peak_at_z_boundary"]),
        "reference_height": int(reference_shape[0]),
        "reference_width": int(reference_shape[1]),
        # TODO: the canonical_* columns below repeat best_z, best_z_subslice, max_ncc
        # and placement_x/y. Decide with Danin which set to delete (this table is the
        # manifest's `authoritative_placement_table`, so his tools may read either).
        "canonical_best_z": int(placement["best_z"]),
        "canonical_best_z_subslice": best_z_subslice,
        "canonical_ncc": float(placement["score"]),
        "canonical_x": int(placement["x"]),
        "canonical_y": int(placement["y"]),
        "scale_search_seconds": scale_seconds,
        "block_count": block_count,
    }
    return plane_summary


def _anchor_profile_rows(fish_id, session_label, plane_index, plane_label, anchor_scores, z_spacing_um):
    """Build one row per anatomy depth with the pooled reference's NCC score.

    Args:
        fish_id (str): Fish identifier.
        session_label (str): Session the plane belongs to.
        plane_index (int): Functional plane index.
        plane_label (str): Plane label from `_plane_summary`.
        anchor_scores (numpy.ndarray): Per-depth NCC scores of the pooled reference.
        z_spacing_um (float): Anatomy Z-slice spacing, in micrometers.

    Returns:
        list: Rows of `ncc_anchor_profiles.csv`, one per anatomy depth.
    """
    anchor_profile_rows = [
        {
            "fish_id": fish_id,
            "session": session_label,
            "plane_index": plane_index,
            "plane_label": plane_label,
            "reference_selection": REFERENCE_SELECTION,
            "anatomy_z": z_index,
            "anatomy_z_um": z_index * z_spacing_um,
            "ncc": float(score),
        }
        for z_index, score in enumerate(anchor_scores)
    ]
    return anchor_profile_rows


def _run_plane(
    *,
    fish_id,
    session,
    plane_index,
    movie_path,
    anatomy_filtered,
    z_spacing_um,
    config,
):
    """Measure best anatomy depth and its change over time for one plane.

    Builds a pooled reference to anchor the plane's scale and X/Y/Z
    placement in the anatomy volume, then builds per-block-third references
    and tracks their local depth profile over the recording to produce
    interval-level and profile-level rows plus a plane-level summary.

    Args:
        fish_id (str): Fish identifier.
        session (dict): Session record with `session_label` and
            `selected_tiffs` used to determine the block count.
        plane_index (int): Functional plane index being processed.
        movie_path (Path): Path to this plane's motion-corrected movie
            TIFF.
        anatomy_filtered (numpy.ndarray): Normalized and sharpened anatomy
            volume, shaped (Z, Y, X).
        z_spacing_um (float): Anatomy Z-slice spacing in micrometers.
        config (FunctionalAnatomyQCConfig): Sampling, scale-search, and
            local-tracking settings.

    Returns:
        tuple: `(interval_rows, profile_rows, plane_summary,
        anchor_profile_rows, canonical)`, where `interval_rows` (list of
        dict) holds one row per block third with placement and drift
        fields, `profile_rows` (list of dict) holds one row per
        block-third/anatomy-depth combination, `plane_summary` (dict) holds
        the plane-level anchor placement and peak-quality metrics,
        `anchor_profile_rows` (list of dict) holds one row per anatomy
        depth for the pooled anchor reference, and `canonical`
        (numpy.ndarray) is the pooled reference image used for this plane.
    """
    block_count = len(session["selected_tiffs"])
    # 1. Anchor: scale, best depth and X/Y of the pooled (post-block-0) reference.
    canonical = pooled_analysis_reference(movie_path, block_count=block_count, config=config)
    scale_started = time.perf_counter()
    placement = search_scale(
        canonical, anatomy_filtered, *config.scale_coarse,
        refine_windows=((config.scale_fine_half_window, config.scale_fine_step),
                        (config.scale_xfine_half_window, config.scale_xfine_step)),
    )
    scale_seconds = time.perf_counter() - scale_started
    # 2. One reference image per block third.
    references, bounds, labels = build_window_references(movie_path, block_count=block_count, config=config)

    interval_rows = []
    profile_rows = []
    # 3. Track each third near the anchor position; its best depth over time is the drift.
    for interval_index, (reference, bounds_pair, label) in enumerate(zip(references, bounds, labels)):
        started = time.perf_counter()
        result = tracked_local_depth_profile(
            reference,
            canonical,
            anatomy_filtered,
            scale=float(placement["scale"]),
            canonical_x=int(placement["x"]),
            canonical_y=int(placement["y"]),
            config=config,
        )
        runtime_seconds = time.perf_counter() - started
        interval_rows.append(_interval_row(
            fish_id, session["session_label"], plane_index, interval_index, label, bounds_pair,
            float(placement["scale"]), result, z_spacing_um, runtime_seconds, config.windows_per_block,
        ))
        profile_rows.extend(_interval_profile_rows(
            fish_id, session["session_label"], plane_index, interval_index, label, result["scores"], z_spacing_um,
            config.windows_per_block,
        ))
    # Plane summary: anchor placement and how distinct its depth peak is.
    anchor_scores = np.asarray(placement["scores"], dtype=np.float32)
    plane_summary = _plane_summary(
        fish_id, session["session_label"], plane_index, placement, anchor_scores, canonical.shape, scale_seconds, block_count,
    )
    anchor_profile_rows = _anchor_profile_rows(
        fish_id, session["session_label"], plane_index, plane_summary["plane_label"], anchor_scores, z_spacing_um,
    )
    return interval_rows, profile_rows, plane_summary, anchor_profile_rows, canonical


def _depth_profile_metrics(scores):
    """Describe how strong and isolated the best depth-profile peak is.

    Args:
        scores (numpy.ndarray): Per-depth similarity scores.

    Returns:
        dict: Metrics with keys `peak_delta` (float, gap between the top
        two scores), `peak_zscore` (float, how many standard deviations the
        peak is above the mean), and `peak_at_z_boundary` (bool, whether
        the peak sits at the first or last depth index).
    """
    values = np.asarray(scores, dtype=np.float64)
    peak = int(np.nanargmax(values))
    maximum = float(values[peak])
    second = float(np.partition(values[np.isfinite(values)], -2)[-2]) if np.isfinite(values).sum() >= 2 else maximum  # second-highest finite score
    mean = float(np.nanmean(values))
    standard_deviation = float(np.nanstd(values))
    # A clear peak: well above the second-best depth (delta) and above the
    # mean of all depths (z-score); a peak at the first or last slice may be cut off.
    peak_metrics = {
        "peak_delta": maximum - second,
        "peak_zscore": (maximum - mean) / (standard_deviation + 1e-6),
        "peak_at_z_boundary": peak in {0, values.size - 1},
    }
    return peak_metrics


def _direction_fraction(changes, consensus):
    """Measure how many planes move in the same direction as the group.

    Args:
        changes (numpy.ndarray): Per-plane depth change values.
        consensus (float): Group-level reference change (e.g. median)
            whose sign defines the expected direction.

    Returns:
        float: Fraction of finite `changes` values sharing the sign of
        `consensus`, or 0.0 if there are no finite values or `consensus` is
        zero.
    """
    finite = changes[np.isfinite(changes)]
    if finite.size == 0 or np.isclose(consensus, 0.0):
        return 0.0  # no direction to agree with
    same_direction_fraction = float(np.mean(np.sign(finite) == np.sign(consensus)))
    return same_direction_fraction


def _settling_interval(session_df, threshold_slices):
    """Find when a session's planes stop moving in depth.

    For every interval (block 0 included), takes the median across planes of
    how far each plane's best depth is from its final depth. The settling
    interval is the first one after which that median stays below
    `threshold_slices` until the end.

    Args:
        session_df (pandas.DataFrame): Interval rows of one fish/session,
            all planes.
        threshold_slices (float): Largest offset from the final depth, in
            anatomy slices, still counted as settled.

    Returns:
        tuple: `(settling_index, settling_label)` -- the interval index and
        label, or `(None, None)` if the session never settles.
    """
    all_intervals = sorted(session_df["interval_index"].unique())
    centered_by_interval = []  # median offset from the final depth, per interval
    for interval_index in all_intervals:
        offsets = []
        for _, plane_group in session_df.groupby("plane_index"):
            ordered = plane_group.sort_values("interval_index")
            final_value = float(ordered.iloc[-1]["best_z_subslice"])
            current = ordered[ordered["interval_index"] == interval_index]
            if not current.empty:
                offsets.append(float(current.iloc[0]["best_z_subslice"]) - final_value)
        centered_by_interval.append(float(np.median(offsets)))
    settling_index = None
    for index in range(len(centered_by_interval)):
        # Settled from here on if every later interval stays within the threshold.
        if max(abs(value) for value in centered_by_interval[index:]) < threshold_slices:
            settling_index = all_intervals[index]
            break
    settling_label = None
    if settling_index is not None:
        settling_label = str(session_df[session_df["interval_index"] == settling_index].iloc[0]["interval_label"])
    return settling_index, settling_label


def summarize_sessions(interval_df, config, z_spacing_um):
    """Summarize plane changes and decide whether meaningful drift is plausible.

    For each fish/session group, computes the consensus depth change across
    planes (excluding the initial settling block), classifies the session
    as `fail_candidate`, `review_required`, or `pass_candidate` based on
    magnitude, direction consistency, and match confidence, and estimates
    the interval at which the depth profile settles.

    Args:
        interval_df (pandas.DataFrame): Interval-level rows produced by
            `_run_plane`, across all planes and sessions.
        config (FunctionalAnatomyQCConfig): Thresholds for material drift,
            direction consensus, and weak-match detection.
        z_spacing_um (float): Anatomy Z-slice spacing in micrometers.

    Returns:
        pandas.DataFrame: One row per fish/session with drift magnitude,
        direction consensus, match-quality, settling, and status columns.
    """
    rows = []
    for (fish_id, session), group in interval_df.groupby(["fish_id", "session"]):
        eligible = group[group["included_in_drift_gate"]].copy()  # block 0 excluded
        changes = []
        ranges = []
        # Per plane: depth change from the first to the last analysed third, and its total range.
        for _, plane_group in eligible.groupby("plane_index"):
            ordered = plane_group.sort_values("interval_index")
            values = ordered["best_z_subslice"].to_numpy(dtype=float)
            changes.append(values[-1] - values[0])
            ranges.append(float(np.ptp(values)))
        changes_arr = np.asarray(changes, dtype=float)
        # Real drift: the median change across planes is large, and most planes move the same way.
        consensus = float(np.median(changes_arr))
        direction = _direction_fraction(changes_arr, consensus)
        material = abs(consensus) >= config.min_consensus_change_slices and direction >= config.min_plane_direction_fraction
        weak = float(eligible["max_score"].median()) < config.weak_median_ncc  # matches too weak to trust
        heterogeneous = max(ranges, default=0.0) >= config.min_consensus_change_slices and not material  # some plane moves a lot, but planes disagree
        # Decision: real drift -> fail; weak or inconsistent -> review; otherwise pass.
        if material:
            status = "fail_candidate"
            evidence = "coherent_material_z_drift"
        elif weak or heterogeneous:
            status = "review_required"
            evidence = "weak_or_heterogeneous_profiles"
        else:
            status = "pass_candidate"
            evidence = "stable_below_threshold"

        settling_index, settling_label = _settling_interval(group, config.min_consensus_change_slices)

        rows.append(
            {
                "fish_id": fish_id,
                "session": session,
                "placement_method": PLACEMENT_METHOD,
                "plane_count": int(eligible["plane_index"].nunique()),
                "analysis_interval_count": int(eligible["interval_index"].nunique()),
                "block0_included_in_figures": True,
                "block0_included_in_drift_gate": False,
                "consensus_change_slices": consensus,
                "consensus_change_um": consensus * z_spacing_um,
                "same_direction_plane_fraction": direction,
                "max_plane_range_slices": max(ranges, default=0.0),
                "median_max_ncc": float(eligible["max_score"].median()),
                "fallback_count": int(eligible["fallback_reason"].notna().sum()),
                "settling_interval_index": settling_index,
                "settling_interval_label": settling_label,
                "status": status,
                "evidence_tier": evidence,
            }
        )
    session_summary = pd.DataFrame(rows)
    return session_summary


def _overall_status(summary_df):
    """Combine session decisions into one fish-level QC status.

    Args:
        summary_df (pandas.DataFrame): Session-level summary rows produced
            by `summarize_sessions`, containing a `status` column.

    Returns:
        str: `"fail_candidate"` if any session failed, else
        `"review_required"` if any session needs review, else
        `"pass_candidate"`.
    """
    statuses = set(summary_df["status"])
    # The worst session status decides for the whole fish.
    if "fail_candidate" in statuses:
        return "fail_candidate"
    if "review_required" in statuses:
        return "review_required"
    return "pass_candidate"


def _windows_description(interval_df):
    """Describe how blocks are split, for plot titles ("thirds" or "N windows").

    Args:
        interval_df (pandas.DataFrame): Rows with `block_index` and `interval_index`.

    Returns:
        str: "thirds" for 3 windows per block, otherwise "N windows".
    """
    windows_per_block = interval_df.loc[interval_df["block_index"] == 0, "interval_index"].nunique()
    description = "thirds" if windows_per_block == 3 else f"{windows_per_block} windows"
    return description


def _render_tracks(interval_df, summary_df, output):
    """Plot the matched anatomy depth of every functional plane over time.

    Writes one subplot per session showing each plane's tracked sub-slice
    depth across intervals, annotated with the session's drift-gate status
    and consensus depth change.

    Args:
        interval_df (pandas.DataFrame): Interval-level rows across all
            planes and sessions.
        summary_df (pandas.DataFrame): Session-level summary rows produced
            by `summarize_sessions`.
        output (Path): File path the figure is saved to.

    Returns:
        None
    """
    sessions = sorted(interval_df["session"].unique())
    fig, axes = plt.subplots(len(sessions), 1, figsize=(11, 4.8 * len(sessions)), squeeze=False)
    # One subplot per session: each plane's best depth over the block windows.
    for row, session in enumerate(sessions):
        ax = axes[row, 0]
        subset = interval_df[interval_df["session"] == session]
        for plane, group in subset.groupby("plane_index"):
            ordered = group.sort_values("interval_index")
            ax.plot(ordered["interval_index"], ordered["best_z_subslice"], marker="o", label=f"plane {plane}")
        labels = subset.sort_values("interval_index").drop_duplicates("interval_index")["interval_label"].tolist()
        ax.set_xticks(range(len(labels)), labels, rotation=35, ha="right")
        block0_window_count = subset.loc[subset["block_index"] == 0, "interval_index"].nunique()
        # Shade block 0's windows (the first intervals).
        ax.axvspan(-0.5, block0_window_count - 0.5, color="0.8", alpha=0.35, label="Initial settling block (excluded from drift calculation)")
        summary = summary_df[summary_df["session"] == session].iloc[0]
        status = str(summary["status"]).replace("_", " ").upper()
        planes = sorted(int(value) for value in subset["plane_index"].unique())
        ax.set_title(
            f"Session {session}: functional planes {planes[0]}–{planes[-1]}\n"
            f"Drift gate: {status} | median ΔZ = {summary['consensus_change_slices']:+.2f} slices "
            f"({summary['consensus_change_um']:+.2f} µm)"
        )
        ax.set_ylabel("Matched canonical-anatomy depth\n(sub-slice Z index)")
        ax.grid(alpha=0.2)
        ax.legend(fontsize=8, ncol=3)
    fig.suptitle(
        "Functional-plane depth stability over time\n"
        f"NCC placement in canonical anatomy; each acquisition block is shown in {_windows_description(interval_df)}",
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(output, dpi=170, bbox_inches="tight")
    plt.close(fig)


def _render_anchor_profiles(
    anchor_profile_df,
    plane_df,
    output,
):
    """Plot pooled NCC-versus-depth curves and mark each best-Z estimate.

    Writes one subplot per plane showing the pooled-reference NCC score
    against anatomy depth, with the best sub-slice depth and peak
    confidence metrics annotated.

    Args:
        anchor_profile_df (pandas.DataFrame): Per-plane, per-depth NCC rows
            for the pooled anchor reference.
        plane_df (pandas.DataFrame): Plane-level summary rows produced by
            `_run_plane`, indexed by `plane_index`.
        output (Path): File path the figure is saved to.

    Returns:
        None
    """
    planes = sorted(int(value) for value in anchor_profile_df["plane_index"].unique())
    columns = 2
    rows = max(1, int(np.ceil(len(planes) / columns)))
    fig, axes = plt.subplots(rows, columns, figsize=(12, 3.4 * rows), squeeze=False, sharey=True)
    summary_by_plane = plane_df.set_index("plane_index")
    # One subplot per plane: NCC versus anatomy depth, best depth marked in red.
    for axis, plane_index in zip(axes.flat, planes):
        profile = anchor_profile_df[anchor_profile_df["plane_index"] == plane_index].sort_values("anatomy_z")
        summary = summary_by_plane.loc[plane_index]
        best_z = int(summary["best_z"])
        best_subslice = float(summary["best_z_subslice"])
        maximum = float(summary["max_ncc"])
        axis.plot(profile["anatomy_z"], profile["ncc"], color="#27628d", linewidth=1.8)
        axis.axvline(best_subslice, color="#cf2436", linestyle="--", linewidth=1.2)
        axis.scatter([best_z], [maximum], color="#cf2436", s=24, zorder=3)
        boundary = " | boundary peak" if bool(summary["peak_at_z_boundary"]) else ""
        axis.set_title(
            f"Plane {plane_index}: best anatomy Z = {best_subslice:.2f}\n"
            f"peak NCC = {maximum:.3f}, peak z-score = {float(summary['peak_zscore']):.2f}{boundary}"
        )
        axis.set_xlabel("Canonical anatomy Z index")
        axis.set_ylabel("Normalized cross-correlation (NCC)")
        axis.grid(alpha=0.2)
    for axis in axes.flat[len(planes) :]:
        axis.axis("off")
    fig.suptitle(
        "Confidence of pooled functional-plane placement across anatomical depth\n"
        "Sharper, isolated NCC peaks support a more specific best-Z assignment",
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(output, dpi=170, bbox_inches="tight")
    plt.close(fig)


def _render_temporal_profiles(profile_df, output):
    """Plot NCC-versus-depth heatmaps for successive recording windows.

    Writes one heatmap subplot per plane with acquisition block third on
    the Y axis and anatomy Z index on the X axis, overlaying the
    best-matching depth at each interval and shading the excluded
    settling block.

    Args:
        profile_df (pandas.DataFrame): Interval-level, per-depth NCC rows
            across all planes.
        output (Path): File path the figure is saved to.

    Returns:
        None
    """
    planes = sorted(int(value) for value in profile_df["plane_index"].unique())
    columns = 2
    rows = max(1, int(np.ceil(len(planes) / columns)))
    fig, axes = plt.subplots(rows, columns, figsize=(13, 3.8 * rows), squeeze=False)
    image = None
    for axis, plane_index in zip(axes.flat, planes):
        subset = profile_df[profile_df["plane_index"] == plane_index].copy()
        matrix = subset.pivot(index="interval_index", columns="anatomy_z", values="ncc").sort_index()  # rows = intervals, columns = anatomy depth
        interval_rows = subset.sort_values("interval_index").drop_duplicates("interval_index")
        labels = interval_rows["interval_label"].tolist()
        image = axis.imshow(matrix.to_numpy(), aspect="auto", origin="upper", cmap="viridis")
        best_columns = np.nanargmax(matrix.to_numpy(), axis=1)
        best_z = matrix.columns.to_numpy(dtype=float)[best_columns]
        axis.plot(best_z - float(matrix.columns.min()), np.arange(matrix.shape[0]), color="white", linewidth=1.2)
        axis.scatter(best_z - float(matrix.columns.min()), np.arange(matrix.shape[0]), color="white", s=8)
        block0_window_count = subset.loc[subset["block_index"] == 0, "interval_index"].nunique()
        axis.axhspan(-0.5, block0_window_count - 0.5, color="white", alpha=0.18)  # shade block 0
        axis.set_yticks(np.arange(len(labels)), labels, fontsize=7)
        z_values = matrix.columns.to_numpy(dtype=int)
        tick_positions = np.linspace(0, len(z_values) - 1, min(6, len(z_values)), dtype=int)
        axis.set_xticks(tick_positions, z_values[tick_positions])
        axis.set_xlabel("Canonical anatomy Z index")
        axis.set_ylabel("Acquisition block third" if _windows_description(profile_df) == "thirds" else "Acquisition block window")
        axis.set_title(f"Plane {plane_index}: temporal NCC-versus-depth profiles", pad=8)
    for axis in axes.flat[len(planes) :]:
        axis.axis("off")
    if image is not None:
        colorbar_axis = fig.add_axes([0.92, 0.15, 0.015, 0.66])
        fig.colorbar(image, cax=colorbar_axis, label="NCC")
    fig.suptitle(
        "Anatomical-depth match quality over time\n"
        "Block 0 is shaded and shown for settling context but excluded from the drift decision",
        fontweight="bold",
    )
    fig.subplots_adjust(top=0.78, right=0.90, hspace=0.55, wspace=0.38)
    fig.savefig(output, dpi=170, bbox_inches="tight")
    plt.close(fig)


def run_drift_analysis(
    *,
    fish_dir,
    output_dir,
    anatomy_path=None,
    preprocessing_metadata_path=None,
    config=None,
    spatial_manifest_path=None,
):
    """Run functional-to-anatomy depth placement and temporal drift QC.

    For every motion-corrected plane, this builds representative images, finds
    the most similar anatomy depth, tracks the match through recording time,
    and writes CSV tables, QC PNGs, and a machine-readable manifest.

    Args:
        fish_dir (str or Path): Canonically preprocessed fish folder.
        output_dir (str or Path): New empty directory for QC outputs.
        anatomy_path (str or Path or None): Optional anatomy override.
        preprocessing_metadata_path (str or Path or None): Optional session
            metadata override.
        config (FunctionalAnatomyQCConfig or None): Sampling and decision
            settings.
        spatial_manifest_path (str or Path or None): Optional spatial
            manifest override.

    Returns:
        dict: QC status, inputs, settings, runtime, and output paths.

    Raises:
        FileExistsError: If `output_dir` already contains files.
        FileNotFoundError: If the canonical anatomy or a plane's motion-corrected movie is missing.
        ValueError: If the spatial manifest is invalid, or the movies aren't declared in it.
    """
    config = config or FunctionalAnatomyQCConfig()
    fish_folder = Path(fish_dir)
    fish_id = fish_folder.name
    output_folder = Path(output_dir)
    if output_folder.exists() and any(output_folder.iterdir()):  # never write into a non-empty folder
        raise FileExistsError(f"NCC QC output directory is not empty: {output_folder}")
    output_folder.mkdir(parents=True, exist_ok=True)
    # Inputs come from the spatial manifest, so only canonical-workflow fish can run.
    spatial_manifest_file = Path(spatial_manifest_path) if spatial_manifest_path else canonical_manifest_path(fish_folder)
    spatial_manifest = validate_spatial_manifest(spatial_manifest_file)
    manifest_anatomy = spatial_manifest.get("anatomy", {}).get("output_path")
    anatomy_source = Path(anatomy_path) if anatomy_path else Path(str(manifest_anatomy or ""))
    if not anatomy_source.exists():
        raise FileNotFoundError(f"Canonical anatomy from spatial manifest is missing: {anatomy_source}")
    # Session/block layout written by the functional preprocessing.
    metadata_path = Path(preprocessing_metadata_path) if preprocessing_metadata_path else (
        fish_folder / "02_reg" / "00_preprocessing" / "2p_functional" / "01_individualPlanes" / f"{fish_id}_preprocessing_metadata.json"
    )
    anatomy_zyx, anatomy_spacing_xyz_um = read_canonical_anatomy(anatomy_source)
    z_spacing_um = float(anatomy_spacing_xyz_um[2])  # Z spacing from the NRRD header
    z_metadata_sources = [spatial_manifest_file]
    # Sharpen the anatomy once; every plane is matched against it.
    anatomy_filtered = np.stack(
        [local_unsharp(norm01(image), config.sharpen_sigma, config.sharpen_amount) for image in anatomy_zyx],
        axis=0,
    )
    sessions = load_preprocessing_sessions(metadata_path)
    movies = discover_motion_corrected_movies(fish_folder, fish_id)
    # Every motion-corrected movie must be declared canonical in the manifest.
    declared_movies = {
        Path(str(record["output_path"])).resolve()
        for record in spatial_manifest.get("motion_corrected_movies", [])
        if isinstance(record, dict) and record.get("output_path")
    }
    observed_movies = {path.resolve() for path in movies.values()}
    if not observed_movies or not observed_movies.issubset(declared_movies):
        raise ValueError(
            "NCC motion-corrected inputs are not declared canonical in the spatial manifest: "
            f"observed={sorted(str(path) for path in observed_movies)}, "
            f"declared={sorted(str(path) for path in declared_movies)}"
        )
    # Every plane listed in the sessions needs its movie.
    requested_planes = {plane for session in sessions for plane in session["output_planes"]}
    missing = sorted(requested_planes - set(movies))
    if missing:
        raise FileNotFoundError(f"Missing motion-corrected movies for planes: {missing}")

    # One task per (session, plane); run in parallel threads when workers > 1.
    tasks = []
    for session in sessions:
        for plane_index in session["output_planes"]:
            tasks.append((session, plane_index, movies[plane_index]))
    interval_rows = []
    profile_rows = []
    plane_rows = []
    anchor_profile_rows = []
    references_by_plane = {}
    started = time.perf_counter()

    # Arguments that are the same for every plane.
    shared_arguments = {"fish_id": fish_id, "anatomy_filtered": anatomy_filtered, "z_spacing_um": z_spacing_um, "config": config}
    workers = max(1, min(int(config.workers), len(tasks)))
    if workers == 1:
        results = [
            _run_plane(session=session, plane_index=plane_index, movie_path=movie, **shared_arguments)
            for session, plane_index, movie in tasks
        ]
    else:
        results = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(_run_plane, session=session, plane_index=plane_index, movie_path=movie, **shared_arguments)
                for session, plane_index, movie in tasks
            ]
            for future in as_completed(futures):
                results.append(future.result())
    # Collect every plane's rows into fish-level tables.
    for intervals, profiles, plane, anchor_profiles, reference in results:
        interval_rows.extend(intervals)
        profile_rows.extend(profiles)
        plane_rows.append(plane)
        anchor_profile_rows.extend(anchor_profiles)
        references_by_plane[int(plane["plane_index"])] = np.asarray(reference, dtype=np.float32)
    elapsed = time.perf_counter() - started

    # Tables sorted by session and plane, then the per-session drift decision.
    interval_df = pd.DataFrame(interval_rows).sort_values(["session", "plane_index", "interval_index"])
    profile_df = pd.DataFrame(profile_rows).sort_values(["session", "plane_index", "interval_index", "anatomy_z"])
    plane_df = pd.DataFrame(plane_rows).sort_values(["session", "plane_index"])
    anchor_profile_df = pd.DataFrame(anchor_profile_rows).sort_values(["session", "plane_index", "anatomy_z"])
    summary_df = summarize_sessions(interval_df, config, z_spacing_um)

    # Save each plane's pooled reference image, then the tables and plots.
    reference_dir = output_folder / "functional_references"
    reference_dir.mkdir(parents=True, exist_ok=True)
    reference_paths = {}
    for plane_index, reference in sorted(references_by_plane.items()):
        reference_path = reference_dir / f"{fish_id}_plane{plane_index}_{REFERENCE_SELECTION}_ref.tif"
        tifffile.imwrite(reference_path, reference)
        reference_paths[plane_index] = str(reference_path)
    plane_df["reference_path"] = plane_df["plane_index"].map(reference_paths)  # plane index -> its reference file

    paths = {
        "intervals": output_folder / "ncc_drift_intervals.csv",
        "profiles": output_folder / "ncc_drift_profiles.csv",
        "profiles_png": output_folder / "ncc_drift_profiles.png",
        "planes": output_folder / "ncc_scale_bestz_by_plane.csv",
        "anchor_profiles": output_folder / "ncc_anchor_profiles.csv",
        "anchor_profiles_png": output_folder / "ncc_best_z_profiles.png",
        "functional_references": reference_dir,
        "summary": output_folder / "ncc_drift_session_summary.csv",
        "tracks_png": output_folder / "ncc_drift_tracks.png",
    }
    interval_df.to_csv(paths["intervals"], index=False)
    profile_df.to_csv(paths["profiles"], index=False)
    plane_df.to_csv(paths["planes"], index=False)
    anchor_profile_df.to_csv(paths["anchor_profiles"], index=False)
    summary_df.to_csv(paths["summary"], index=False)
    _render_tracks(interval_df, summary_df, paths["tracks_png"])
    _render_anchor_profiles(anchor_profile_df, plane_df, paths["anchor_profiles_png"])
    _render_temporal_profiles(profile_df, paths["profiles_png"])

    # Manifest: status, inputs, settings, outputs, and what later steps can reuse.
    manifest = {
        "stage": "functional_anatomy_ncc_qc",
        "version": MANIFEST_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fish_id": fish_id,
        "status": _overall_status(summary_df),
        "scientific_review_required": True,
        "placement_method": {
            "name": PLACEMENT_METHOD,
            "validation": (
                "Promoted after real-data benchmarks reproduced global best Z and maximum NCC without loss "
                "of depth-profile quality while reducing runtime. Full-frame matching remains the safety "
                "fallback when the tracked local optimum is weak or touches the local-search boundary."
            ),
        },
        "inputs": {
            "fish_dir": str(fish_folder),
            "canonical_anatomy": str(anatomy_source),
            "spatial_preprocessing_manifest": str(spatial_manifest_file),
            "preprocessing_metadata": str(metadata_path),
            "motion_corrected_movies": {str(index): str(path) for index, path in movies.items()},
        },
        "canonical_anatomy_validation": {
            "shape_zyx": list(anatomy_zyx.shape),
            # TODO: the next five keys are fixed for an NRRD (left over from a deleted
            # raw-TIFF reader); decide with Danin whether to drop them from the manifest.
            "source_dtype": str(anatomy_zyx.dtype),
            "page_count": int(anatomy_zyx.shape[0]),
            "series_shape": [int(size) for size in anatomy_zyx.shape],
            "reader": "SimpleITK",
            "used_page_stack_fallback": False,
            "z_spacing_um": z_spacing_um,
            "z_spacing_metadata_sources": [str(path) for path in z_metadata_sources],
            "spacing_xyz_um": list(anatomy_spacing_xyz_um),
            "xy_frame": CANONICAL_XY_FRAME,
            "z_frame": REGISTRATION_Z_FRAME,
        },
        "parameters": asdict(config),
        "runtime_seconds": elapsed,
        "parallel_workers": workers,
        "outputs": {key: str(path) for key, path in paths.items()},
        "downstream_handoff": {
            "schema": "functional_anatomy_ncc_handoff_v1",
            "authoritative_placement_table": str(paths["planes"]),
            "authoritative_anchor_profiles": str(paths["anchor_profiles"]),
            "functional_reference_directory": str(reference_dir),
            "functional_reference_selection": REFERENCE_SELECTION,
            "xy_frame": CANONICAL_XY_FRAME,
            "z_frame": REGISTRATION_Z_FRAME,
            "reusable_components": ["functional_reference", "scale", "best_z", "ncc_depth_profile", "xy_placement"],
            "downstream_residual_step": "ants_rigid_affine",
        },
        "session_summary": summary_df.to_dict(orient="records"),
        "deferred": [
            "Optional segmentation restricted to stable intervals is intentionally deferred until the NCC gate is validated."
        ],
    }
    manifest_path = output_folder / "functional_anatomy_qc_manifest.json"
    manifest["outputs"]["manifest"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
    return manifest



__all__ = [
    "FunctionalAnatomyQCConfig",
    "block_window_bounds",
    "block_window_labels",
    "read_canonical_anatomy",
    "run_drift_analysis",
    "tracked_local_depth_profile",
]
