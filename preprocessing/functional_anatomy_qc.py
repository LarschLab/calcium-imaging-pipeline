"""NCC-based functional-to-anatomy placement and temporal Z-drift QC.

The stage consumes canonical motion-corrected functional movies and the
canonical registration-ready in-vivo anatomy NRRD. Their shared XY frame is
validated from the spatial preprocessing manifest before NCC is attempted.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import re
import time
from typing import Any, Iterable

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import ndimage as ndi
from skimage.registration import phase_cross_correlation
from skimage.transform import resize
import tifffile

from preprocessing.spatial_preprocessing import (
    CANONICAL_XY_FRAME,
    REGISTRATION_Z_FRAME,
    canonical_manifest_path,
    validate_spatial_manifest,
)


@dataclass(frozen=True)
class FunctionalAnatomyQCConfig:
    windows_per_block: int = 3
    sampled_frames_per_window: int = 80
    top_correlated_frames: int = 20
    top_corr_pre_smooth_sigma: float = 0.5
    sharpen_sigma: float = 1.0
    sharpen_amount: float = 0.6
    scale_coarse: tuple[float, float, float] = (0.45, 1.0, 0.05)
    scale_fine_half_window: float = 0.05
    scale_fine_step: float = 0.01
    scale_xfine_half_window: float = 0.01
    scale_xfine_step: float = 0.002
    local_xy_radius_px: int = 8
    local_xy_fallback_score: float = 0.2
    min_consensus_change_slices: float = 2.0
    min_plane_direction_fraction: float = 0.6
    weak_median_ncc: float = 0.3
    workers: int = 1


@dataclass(frozen=True)
class RawAnatomy:
    data_zyx: np.ndarray
    source_path: Path
    reader: str
    source_dtype: str
    page_count: int
    series_shape: tuple[int, ...]
    used_page_stack_fallback: bool


def norm01(image: np.ndarray) -> np.ndarray:
    arr = np.asarray(image, dtype=np.float32)
    if arr.size == 0:
        return arr
    low, high = np.percentile(arr, (1.0, 99.8))
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        low = float(np.min(arr))
        high = float(np.max(arr))
    if high <= low:
        return np.zeros(arr.shape, dtype=np.float32)
    return np.clip((arr - low) / (high - low), 0.0, 1.0).astype(np.float32)


def local_unsharp(image: np.ndarray, sigma: float, amount: float) -> np.ndarray:
    base = ndi.gaussian_filter(np.asarray(image, dtype=np.float32), sigma)
    return np.clip(base + amount * (np.asarray(image) - base), 0.0, 1.0)


def corrcoef_img(first: np.ndarray, second: np.ndarray) -> float:
    a = np.asarray(first, dtype=np.float32)
    b = np.asarray(second, dtype=np.float32)
    if a.shape != b.shape:
        raise ValueError(f"NCC arrays must have equal shape, got {a.shape} and {b.shape}")
    a = a - float(a.mean())
    b = b - float(b.mean())
    denominator = float(np.sqrt(np.sum(a * a) * np.sum(b * b)))
    if denominator <= 1e-12:
        return 0.0
    return float(np.sum(a * b) / denominator)


def discover_raw_in_vivo_anatomy(fish_dir: str | Path) -> Path:
    raw_dir = Path(fish_dir) / "01_raw" / "2p" / "anatomy"
    candidates = [
        path
        for path in sorted(raw_dir.glob("*.tif*"))
        if "ex_vivo" not in path.stem.lower() and "exvivo" not in path.stem.lower()
    ]
    if len(candidates) != 1:
        listed = ", ".join(path.name for path in candidates) or "<none>"
        raise ValueError(f"Expected exactly one raw in-vivo anatomy TIFF under {raw_dir}; found {listed}")
    return candidates[0]


def read_raw_anatomy(path: str | Path) -> RawAnatomy:
    source = Path(path)
    with tifffile.TiffFile(source) as tif:
        if not tif.pages:
            raise ValueError(f"Raw anatomy TIFF contains no pages: {source}")
        page_count = len(tif.pages)
        series_shape = tuple(int(value) for value in tif.series[0].shape)
        first_shape = tuple(int(value) for value in tif.pages[0].shape)
        if len(first_shape) != 2:
            raise ValueError(f"Expected 2D anatomy pages, got {first_shape}: {source}")
        inconsistent_series = (
            len(series_shape) != 3
            or int(series_shape[0]) != page_count
            or tuple(series_shape[-2:]) != first_shape
        )
        if inconsistent_series:
            pages = [np.asarray(page.asarray()) for page in tif.pages]
            if any(tuple(page.shape) != first_shape for page in pages):
                raise ValueError(f"Raw anatomy TIFF has inconsistent page shapes: {source}")
            data = np.stack(pages, axis=0)
            reader = "tifffile_pages"
        else:
            data = np.asarray(tif.asarray())
            reader = "tifffile_series"
    if data.ndim != 3 or data.shape[0] != page_count:
        raise ValueError(f"Expected anatomy Z,Y,X with {page_count} pages, got {data.shape}: {source}")
    if not np.issubdtype(data.dtype, np.integer):
        raise TypeError(f"Expected integer raw anatomy, got {data.dtype}: {source}")
    return RawAnatomy(
        data_zyx=data,
        source_path=source,
        reader=reader,
        source_dtype=str(data.dtype),
        page_count=page_count,
        series_shape=series_shape,
        used_page_stack_fallback=inconsistent_series,
    )


def read_canonical_anatomy(path: str | Path) -> tuple[RawAnatomy, tuple[float, float, float]]:
    source = Path(path)
    if source.suffix.lower() != ".nrrd":
        raise ValueError(f"Canonical NCC anatomy must be an NRRD, got {source}")
    try:
        import SimpleITK as sitk
    except Exception as exc:  # pragma: no cover - environment dependent
        raise ImportError("SimpleITK is required to read canonical anatomy NRRD") from exc
    image = sitk.ReadImage(str(source))
    data = sitk.GetArrayFromImage(image)
    spacing = tuple(float(value) for value in image.GetSpacing())
    if data.ndim != 3 or data.dtype != np.uint8:
        raise ValueError(f"Expected canonical uint8 Z,Y,X anatomy, got {data.dtype} {data.shape}: {source}")
    return RawAnatomy(
        data_zyx=np.asarray(data),
        source_path=source,
        reader="SimpleITK",
        source_dtype=str(data.dtype),
        page_count=int(data.shape[0]),
        series_shape=tuple(int(value) for value in data.shape),
        used_page_stack_fallback=False,
    ), spacing


def anatomy_z_spacing_um(metadata_dir: str | Path) -> tuple[float, list[Path]]:
    values: list[float] = []
    sources: list[Path] = []
    for path in sorted(Path(metadata_dir).glob("*_metadata.csv")):
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.reader(handle):
                if len(row) >= 2 and row[0].strip() == "step_size_um_anatomy":
                    values.append(float(row[1]))
                    sources.append(path)
    if not values:
        raise ValueError(f"No step_size_um_anatomy found under {metadata_dir}")
    if any(not np.isclose(value, values[0]) for value in values[1:]):
        raise ValueError(f"Conflicting anatomy Z spacing values under {metadata_dir}: {values}")
    if values[0] <= 0:
        raise ValueError(f"Anatomy Z spacing must be positive, got {values[0]}")
    return float(values[0]), sources


def load_preprocessing_sessions(metadata_path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(metadata_path).read_text())
    sessions = payload.get("sessions")
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
    normalized: list[dict[str, Any]] = []
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


def block_third_labels(block_count: int) -> tuple[str, ...]:
    if block_count < 1:
        raise ValueError("block_count must be positive")
    thirds = ("first third", "middle third", "final third")
    return tuple(f"Block {block}\n{third}" for block in range(block_count) for third in thirds)


def block_third_bounds(frame_count: int, block_count: int) -> tuple[tuple[int, int], ...]:
    if frame_count < block_count * 3:
        raise ValueError("Not enough frames to divide every acquisition block into thirds")
    if frame_count % block_count != 0:
        raise ValueError(
            f"Motion-corrected frames ({frame_count}) do not divide evenly across {block_count} blocks"
        )
    frames_per_block = frame_count // block_count
    bounds: list[tuple[int, int]] = []
    for block in range(block_count):
        block_start = block * frames_per_block
        edges = np.linspace(block_start, block_start + frames_per_block, 4, dtype=int)
        bounds.extend((int(edges[idx]), int(edges[idx + 1])) for idx in range(3))
    return tuple(bounds)


def _sample_indices(start: int, stop: int, count: int) -> np.ndarray:
    effective = min(int(count), int(stop - start))
    if effective < 1:
        raise ValueError(f"Empty temporal window {start}:{stop}")
    return np.linspace(start, stop - 1, effective, dtype=int)


def top_correlated_mean(
    stack: np.ndarray,
    *,
    take_k: int,
    pre_smooth_sigma: float,
) -> np.ndarray:
    frames = np.asarray(stack, dtype=np.float32)
    initial = frames.mean(axis=0)
    compare_reference = ndi.gaussian_filter(initial, pre_smooth_sigma) if pre_smooth_sigma > 0 else initial
    correlations = np.empty(frames.shape[0], dtype=np.float32)
    for index, frame in enumerate(frames):
        compare = ndi.gaussian_filter(frame, pre_smooth_sigma) if pre_smooth_sigma > 0 else frame
        correlations[index] = corrcoef_img(compare, compare_reference)
    selected = np.argsort(correlations)[-min(int(take_k), frames.shape[0]) :]
    return frames[selected].mean(axis=0)


def _read_sampled_frames(path: Path, indices: Iterable[int]) -> np.ndarray:
    selected = np.asarray(list(indices), dtype=int)
    try:
        movie = tifffile.memmap(path)
        return np.asarray(movie[selected], dtype=np.float32)
    except Exception:
        with tifffile.TiffFile(path) as tif:
            return np.stack([np.asarray(tif.pages[int(index)].asarray(), dtype=np.float32) for index in selected])


def movie_shape(path: str | Path) -> tuple[int, int, int]:
    target = Path(path)
    with tifffile.TiffFile(target) as tif:
        page_count = len(tif.pages)
        first_shape = tuple(int(value) for value in tif.pages[0].shape)
    if len(first_shape) != 2:
        raise ValueError(f"Expected 2D movie pages, got {first_shape}: {target}")
    return page_count, first_shape[0], first_shape[1]


def build_window_references(
    movie_path: str | Path,
    *,
    block_count: int,
    config: FunctionalAnatomyQCConfig,
) -> tuple[list[np.ndarray], tuple[tuple[int, int], ...], tuple[str, ...]]:
    target = Path(movie_path)
    frame_count, _, _ = movie_shape(target)
    bounds = block_third_bounds(frame_count, block_count)
    labels = block_third_labels(block_count)
    references: list[np.ndarray] = []
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
    movie_path: str | Path,
    *,
    block_count: int,
    config: FunctionalAnatomyQCConfig,
) -> np.ndarray:
    target = Path(movie_path)
    frame_count, _, _ = movie_shape(target)
    if block_count < 2:
        raise ValueError("block_count must be >= 2 so Block 0 can be excluded from pooled-reference analysis")
    if frame_count % block_count != 0:
        raise ValueError(f"Movie frames do not divide evenly across blocks: {target}")
    first_analysis_frame = frame_count // block_count
    indices = _sample_indices(first_analysis_frame, frame_count, config.sampled_frames_per_window * 2)
    sampled = _read_sampled_frames(target, indices)
    reference = top_correlated_mean(
        sampled,
        take_k=config.top_correlated_frames,
        pre_smooth_sigma=config.top_corr_pre_smooth_sigma,
    )
    return local_unsharp(norm01(reference), config.sharpen_sigma, config.sharpen_amount)


def scale_image(image: np.ndarray, scale: float) -> np.ndarray:
    arr = np.asarray(image, dtype=np.float32)
    if np.isclose(scale, 1.0):
        return arr
    shape = tuple(max(1, int(round(value * float(scale)))) for value in arr.shape)
    return resize(arr, shape, order=1, preserve_range=True, anti_aliasing=True).astype(np.float32)


def global_xy_depth_profile(
    template: np.ndarray,
    anatomy_zyx: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    moving = norm01(template)
    scores = np.full(anatomy_zyx.shape[0], -np.inf, dtype=np.float32)
    xs = np.full(anatomy_zyx.shape[0], -1, dtype=np.int32)
    ys = np.full(anatomy_zyx.shape[0], -1, dtype=np.int32)
    for z_index, anatomy_slice in enumerate(anatomy_zyx):
        fixed = norm01(anatomy_slice)
        if moving.shape[0] > fixed.shape[0] or moving.shape[1] > fixed.shape[1]:
            continue
        response = cv2.matchTemplate(fixed, moving, cv2.TM_CCORR_NORMED)
        _, maximum, _, location = cv2.minMaxLoc(response)
        scores[z_index] = float(maximum)
        xs[z_index], ys[z_index] = int(location[0]), int(location[1])
    if not np.isfinite(scores).any():
        raise ValueError(f"Template {moving.shape} does not fit anatomy slices {anatomy_zyx.shape[1:]}")
    return scores, xs, ys


def quadratic_peak_z(scores: np.ndarray) -> float:
    values = np.asarray(scores, dtype=np.float64)
    peak = int(np.nanargmax(values))
    if peak == 0 or peak == values.size - 1:
        return float(peak)
    left, center, right = values[peak - 1 : peak + 2]
    denominator = left - 2.0 * center + right
    if not np.isfinite(denominator) or abs(denominator) < 1e-12:
        return float(peak)
    offset = 0.5 * (left - right) / denominator
    return float(peak + np.clip(offset, -1.0, 1.0))


def _scale_candidates(center: float, half_window: float, step: float) -> np.ndarray:
    return np.arange(max(step, center - half_window), center + half_window + step * 0.25, step)


def search_scale(
    reference: np.ndarray,
    anatomy_zyx: np.ndarray,
    config: FunctionalAnatomyQCConfig,
) -> dict[str, Any]:
    start, stop, step = config.scale_coarse
    candidates = np.arange(start, stop + step * 0.25, step)

    def evaluate(scale: float) -> dict[str, Any] | None:
        scaled = scale_image(reference, float(scale))
        if any(scaled.shape[index] > anatomy_zyx.shape[index + 1] for index in range(2)):
            return None
        scores, xs, ys = global_xy_depth_profile(scaled, anatomy_zyx)
        best_z = int(np.nanargmax(scores))
        return {
            "scale": float(scale),
            "best_z": best_z,
            "score": float(scores[best_z]),
            "x": int(xs[best_z]),
            "y": int(ys[best_z]),
            "scores": scores,
        }

    evaluated = [result for scale in candidates if (result := evaluate(float(scale))) is not None]
    if not evaluated:
        raise RuntimeError("No valid scale candidates fit the anatomy canvas")
    best = max(evaluated, key=lambda result: result["score"])
    for half_window, refine_step in (
        (config.scale_fine_half_window, config.scale_fine_step),
        (config.scale_xfine_half_window, config.scale_xfine_step),
    ):
        if half_window <= 0 or refine_step <= 0:
            continue
        refined = [
            result
            for scale in _scale_candidates(float(best["scale"]), half_window, refine_step)
            if (result := evaluate(float(scale))) is not None
        ]
        if refined:
            best = max(refined, key=lambda result: result["score"])
    return best


def _bounded_xy_depth_profile(
    template: np.ndarray,
    anatomy_zyx: np.ndarray,
    *,
    predicted_x: int,
    predicted_y: int,
    radius: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    moving = norm01(template)
    height, width = moving.shape
    scores = np.full(anatomy_zyx.shape[0], -np.inf, dtype=np.float32)
    xs = np.full(anatomy_zyx.shape[0], -1, dtype=np.int32)
    ys = np.full(anatomy_zyx.shape[0], -1, dtype=np.int32)
    touched = np.zeros(anatomy_zyx.shape[0], dtype=bool)
    for z_index, anatomy_slice in enumerate(anatomy_zyx):
        fixed = norm01(anatomy_slice)
        max_x = fixed.shape[1] - width
        max_y = fixed.shape[0] - height
        x0, x1 = max(0, predicted_x - radius), min(max_x, predicted_x + radius)
        y0, y1 = max(0, predicted_y - radius), min(max_y, predicted_y + radius)
        if x1 < x0 or y1 < y0:
            continue
        search = fixed[y0 : y1 + height, x0 : x1 + width]
        response = cv2.matchTemplate(search, moving, cv2.TM_CCORR_NORMED)
        _, maximum, _, location = cv2.minMaxLoc(response)
        x = x0 + int(location[0])
        y = y0 + int(location[1])
        scores[z_index], xs[z_index], ys[z_index] = float(maximum), x, y
        touched[z_index] = x in {x0, x1} or y in {y0, y1}
    return scores, xs, ys, touched


def tracked_local_depth_profile(
    interval_reference: np.ndarray,
    canonical_reference: np.ndarray,
    anatomy_zyx: np.ndarray,
    *,
    scale: float,
    canonical_x: int,
    canonical_y: int,
    config: FunctionalAnatomyQCConfig,
) -> dict[str, Any]:
    interval_scaled = scale_image(interval_reference, scale)
    canonical_scaled = scale_image(canonical_reference, scale)
    shift_yx, _, _ = phase_cross_correlation(
        norm01(canonical_scaled),
        norm01(interval_scaled),
        upsample_factor=10,
    )
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
    fallback_reason = None
    if float(scores[best_z]) < config.local_xy_fallback_score:
        fallback_reason = "weak_local_ncc"
    elif bool(touched[best_z]):
        fallback_reason = "local_search_boundary"
    if fallback_reason:
        scores, xs, ys = global_xy_depth_profile(interval_scaled, anatomy_zyx)
        best_z = int(np.nanargmax(scores))
    return {
        "scores": scores,
        "best_z": best_z,
        "best_z_subslice": quadratic_peak_z(scores),
        "max_score": float(scores[best_z]),
        "x": int(xs[best_z]),
        "y": int(ys[best_z]),
        "functional_shift_x": float(shift_yx[1]),
        "functional_shift_y": float(shift_yx[0]),
        "predicted_x": predicted_x,
        "predicted_y": predicted_y,
        "fallback_reason": fallback_reason,
    }


def _plane_index(path: Path) -> int:
    match = re.search(r"plane(\d+)", path.name)
    if match is None:
        raise ValueError(f"Could not parse plane index from {path.name}")
    return int(match.group(1))


def discover_motion_corrected_movies(fish_dir: str | Path, fish_id: str) -> dict[int, Path]:
    root = Path(fish_dir) / "02_reg" / "00_preprocessing" / "2p_functional" / "02_motionCorrected"
    movies = {_plane_index(path): path for path in root.glob(f"{fish_id}_plane*_mcorrected.tif")}
    if not movies:
        raise FileNotFoundError(f"No motion-corrected movies found under {root}")
    return dict(sorted(movies.items()))


def _run_plane(
    *,
    fish_id: str,
    session: dict[str, Any],
    plane_index: int,
    movie_path: Path,
    anatomy_filtered: np.ndarray,
    z_spacing_um: float,
    config: FunctionalAnatomyQCConfig,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, Any]],
    np.ndarray,
]:
    block_count = len(session["selected_tiffs"])
    canonical = pooled_analysis_reference(movie_path, block_count=block_count, config=config)
    scale_started = time.perf_counter()
    placement = search_scale(canonical, anatomy_filtered, config)
    scale_seconds = time.perf_counter() - scale_started
    references, bounds, labels = build_window_references(movie_path, block_count=block_count, config=config)

    interval_rows: list[dict[str, Any]] = []
    profile_rows: list[dict[str, Any]] = []
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
        start, stop = bounds_pair
        interval_rows.append(
            {
                "fish_id": fish_id,
                "session": session["session_label"],
                "plane_index": plane_index,
                "interval_index": interval_index,
                "interval_label": label,
                "block_index": interval_index // 3,
                "block_third_index": interval_index % 3,
                "included_in_drift_gate": interval_index // 3 > 0,
                "frame_start": start,
                "frame_stop": stop,
                "scale": float(placement["scale"]),
                "placement_method": "tracked_local_xy_with_global_fallback",
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
        )
        profile_rows.extend(
            {
                "fish_id": fish_id,
                "session": session["session_label"],
                "plane_index": plane_index,
                "interval_index": interval_index,
                "interval_label": label,
                "block_index": interval_index // 3,
                "included_in_drift_gate": interval_index // 3 > 0,
                "placement_method": "tracked_local_xy_with_global_fallback",
                "anatomy_z": z_index,
                "anatomy_z_um": z_index * z_spacing_um,
                "ncc": float(score),
            }
            for z_index, score in enumerate(result["scores"])
        )
    anchor_scores = np.asarray(placement["scores"], dtype=np.float32)
    anchor_metrics = _depth_profile_metrics(anchor_scores)
    plane_summary = {
        "fish_id": fish_id,
        "session": session["session_label"],
        "plane_index": plane_index,
        "plane_label": f"{fish_id}_plane{plane_index}_mcorrected",
        "reference_selection": "pooled_post_block0",
        "scale": float(placement["scale"]),
        "best_z": int(placement["best_z"]),
        "best_z_subslice": quadratic_peak_z(anchor_scores),
        "max_ncc": float(placement["score"]),
        "placement_x": int(placement["x"]),
        "placement_y": int(placement["y"]),
        "peak_delta": anchor_metrics["peak_delta"],
        "peak_zscore": anchor_metrics["peak_zscore"],
        "peak_at_z_boundary": bool(anchor_metrics["peak_at_z_boundary"]),
        "reference_height": int(canonical.shape[0]),
        "reference_width": int(canonical.shape[1]),
        "canonical_best_z": int(placement["best_z"]),
        "canonical_best_z_subslice": quadratic_peak_z(anchor_scores),
        "canonical_ncc": float(placement["score"]),
        "canonical_x": int(placement["x"]),
        "canonical_y": int(placement["y"]),
        "scale_search_seconds": scale_seconds,
        "block_count": block_count,
    }
    anchor_profile_rows = [
        {
            "fish_id": fish_id,
            "session": session["session_label"],
            "plane_index": plane_index,
            "plane_label": plane_summary["plane_label"],
            "reference_selection": "pooled_post_block0",
            "anatomy_z": z_index,
            "anatomy_z_um": z_index * z_spacing_um,
            "ncc": float(score),
        }
        for z_index, score in enumerate(anchor_scores)
    ]
    return interval_rows, profile_rows, plane_summary, anchor_profile_rows, canonical


def _depth_profile_metrics(scores: np.ndarray) -> dict[str, float | bool]:
    values = np.asarray(scores, dtype=np.float64)
    peak = int(np.nanargmax(values))
    maximum = float(values[peak])
    second = float(np.partition(values[np.isfinite(values)], -2)[-2]) if np.isfinite(values).sum() >= 2 else maximum
    mean = float(np.nanmean(values))
    standard_deviation = float(np.nanstd(values))
    return {
        "peak_delta": maximum - second,
        "peak_zscore": (maximum - mean) / (standard_deviation + 1e-6),
        "peak_at_z_boundary": peak in {0, values.size - 1},
    }


def _direction_fraction(changes: np.ndarray, consensus: float) -> float:
    finite = changes[np.isfinite(changes)]
    if finite.size == 0 or np.isclose(consensus, 0.0):
        return 0.0
    return float(np.mean(np.sign(finite) == np.sign(consensus)))


def summarize_sessions(interval_df: pd.DataFrame, config: FunctionalAnatomyQCConfig, z_spacing_um: float) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (fish_id, session), group in interval_df.groupby(["fish_id", "session"]):
        eligible = group[group["included_in_drift_gate"]].copy()
        changes = []
        ranges = []
        for _, plane_group in eligible.groupby("plane_index"):
            ordered = plane_group.sort_values("interval_index")
            values = ordered["best_z_subslice"].to_numpy(dtype=float)
            changes.append(values[-1] - values[0])
            ranges.append(float(np.ptp(values)))
        changes_arr = np.asarray(changes, dtype=float)
        consensus = float(np.median(changes_arr))
        direction = _direction_fraction(changes_arr, consensus)
        material = abs(consensus) >= config.min_consensus_change_slices and direction >= config.min_plane_direction_fraction
        weak = float(eligible["max_score"].median()) < config.weak_median_ncc
        heterogeneous = max(ranges, default=0.0) >= config.min_consensus_change_slices and not material
        if material:
            status = "fail_candidate"
            evidence = "coherent_material_z_drift"
        elif weak or heterogeneous:
            status = "review_required"
            evidence = "weak_or_heterogeneous_profiles"
        else:
            status = "pass_candidate"
            evidence = "stable_below_threshold"

        all_intervals = sorted(group["interval_index"].unique())
        centered_by_interval: list[float] = []
        for interval_index in all_intervals:
            offsets = []
            for _, plane_group in group.groupby("plane_index"):
                ordered = plane_group.sort_values("interval_index")
                final_value = float(ordered.iloc[-1]["best_z_subslice"])
                current = ordered[ordered["interval_index"] == interval_index]
                if not current.empty:
                    offsets.append(float(current.iloc[0]["best_z_subslice"]) - final_value)
            centered_by_interval.append(float(np.median(offsets)))
        settling_index = None
        for index in range(len(centered_by_interval)):
            if max(abs(value) for value in centered_by_interval[index:]) < config.min_consensus_change_slices:
                settling_index = all_intervals[index]
                break
        settling_label = None
        if settling_index is not None:
            settling_label = str(group[group["interval_index"] == settling_index].iloc[0]["interval_label"])

        rows.append(
            {
                "fish_id": fish_id,
                "session": session,
                "placement_method": "tracked_local_xy_with_global_fallback",
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
    return pd.DataFrame(rows)


def _overall_status(summary_df: pd.DataFrame) -> str:
    statuses = set(summary_df["status"])
    if "fail_candidate" in statuses:
        return "fail_candidate"
    if "review_required" in statuses:
        return "review_required"
    return "pass_candidate"


def _render_tracks(interval_df: pd.DataFrame, summary_df: pd.DataFrame, output: Path) -> None:
    sessions = sorted(interval_df["session"].unique())
    fig, axes = plt.subplots(len(sessions), 1, figsize=(11, 4.8 * len(sessions)), squeeze=False)
    for row, session in enumerate(sessions):
        ax = axes[row, 0]
        subset = interval_df[interval_df["session"] == session]
        for plane, group in subset.groupby("plane_index"):
            ordered = group.sort_values("interval_index")
            ax.plot(ordered["interval_index"], ordered["best_z_subslice"], marker="o", label=f"plane {plane}")
        labels = subset.sort_values("interval_index").drop_duplicates("interval_index")["interval_label"].tolist()
        ax.set_xticks(range(len(labels)), labels, rotation=35, ha="right")
        ax.axvspan(-0.5, 2.5, color="0.8", alpha=0.35, label="Initial settling block (excluded from drift calculation)")
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
        "NCC placement in canonical anatomy; each acquisition block is shown in thirds",
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(output, dpi=170, bbox_inches="tight")
    plt.close(fig)


def _render_anchor_profiles(
    anchor_profile_df: pd.DataFrame,
    plane_df: pd.DataFrame,
    output: Path,
) -> None:
    planes = sorted(int(value) for value in anchor_profile_df["plane_index"].unique())
    columns = 2
    rows = max(1, int(np.ceil(len(planes) / columns)))
    fig, axes = plt.subplots(rows, columns, figsize=(12, 3.4 * rows), squeeze=False, sharey=True)
    summary_by_plane = plane_df.set_index("plane_index")
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


def _render_temporal_profiles(profile_df: pd.DataFrame, output: Path) -> None:
    planes = sorted(int(value) for value in profile_df["plane_index"].unique())
    columns = 2
    rows = max(1, int(np.ceil(len(planes) / columns)))
    fig, axes = plt.subplots(rows, columns, figsize=(13, 3.8 * rows), squeeze=False)
    image = None
    for axis, plane_index in zip(axes.flat, planes):
        subset = profile_df[profile_df["plane_index"] == plane_index].copy()
        matrix = subset.pivot(index="interval_index", columns="anatomy_z", values="ncc").sort_index()
        interval_rows = subset.sort_values("interval_index").drop_duplicates("interval_index")
        labels = interval_rows["interval_label"].tolist()
        image = axis.imshow(matrix.to_numpy(), aspect="auto", origin="upper", cmap="viridis")
        best_columns = np.nanargmax(matrix.to_numpy(), axis=1)
        best_z = matrix.columns.to_numpy(dtype=float)[best_columns]
        axis.plot(best_z - float(matrix.columns.min()), np.arange(matrix.shape[0]), color="white", linewidth=1.2)
        axis.scatter(best_z - float(matrix.columns.min()), np.arange(matrix.shape[0]), color="white", s=8)
        axis.axhspan(-0.5, 2.5, color="white", alpha=0.18)
        axis.set_yticks(np.arange(len(labels)), labels, fontsize=7)
        z_values = matrix.columns.to_numpy(dtype=int)
        tick_positions = np.linspace(0, len(z_values) - 1, min(6, len(z_values)), dtype=int)
        axis.set_xticks(tick_positions, z_values[tick_positions])
        axis.set_xlabel("Canonical anatomy Z index")
        axis.set_ylabel("Acquisition block third")
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


def run_functional_anatomy_qc(
    *,
    fish_dir: str | Path,
    output_dir: str | Path,
    anatomy_path: str | Path | None = None,
    preprocessing_metadata_path: str | Path | None = None,
    config: FunctionalAnatomyQCConfig | None = None,
    spatial_manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    cfg = config or FunctionalAnatomyQCConfig()
    root = Path(fish_dir)
    fish_id = root.name
    out = Path(output_dir)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"NCC QC output directory is not empty: {out}")
    out.mkdir(parents=True, exist_ok=True)
    contract_path = Path(spatial_manifest_path) if spatial_manifest_path else canonical_manifest_path(root)
    spatial_manifest = validate_spatial_manifest(contract_path)
    manifest_anatomy = spatial_manifest.get("anatomy", {}).get("output_path")
    anatomy_source = Path(anatomy_path) if anatomy_path else Path(str(manifest_anatomy or ""))
    if not anatomy_source.exists():
        raise FileNotFoundError(f"Canonical anatomy from spatial manifest is missing: {anatomy_source}")
    metadata_path = Path(preprocessing_metadata_path) if preprocessing_metadata_path else (
        root / "02_reg" / "00_preprocessing" / "2p_functional" / "01_individualPlanes" / f"{fish_id}_preprocessing_metadata.json"
    )
    raw_anatomy, anatomy_spacing_xyz_um = read_canonical_anatomy(anatomy_source)
    z_spacing_um = float(anatomy_spacing_xyz_um[2])
    z_metadata_sources = [contract_path]
    anatomy_filtered = np.stack(
        [local_unsharp(norm01(image), cfg.sharpen_sigma, cfg.sharpen_amount) for image in raw_anatomy.data_zyx],
        axis=0,
    )
    sessions = load_preprocessing_sessions(metadata_path)
    movies = discover_motion_corrected_movies(root, fish_id)
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
    requested_planes = {plane for session in sessions for plane in session["output_planes"]}
    missing = sorted(requested_planes - set(movies))
    if missing:
        raise FileNotFoundError(f"Missing motion-corrected movies for planes: {missing}")

    tasks = []
    for session in sessions:
        for plane_index in session["output_planes"]:
            tasks.append((session, plane_index, movies[plane_index]))
    interval_rows: list[dict[str, Any]] = []
    profile_rows: list[dict[str, Any]] = []
    plane_rows: list[dict[str, Any]] = []
    anchor_profile_rows: list[dict[str, Any]] = []
    references_by_plane: dict[int, np.ndarray] = {}
    started = time.perf_counter()

    def execute(task: tuple[dict[str, Any], int, Path]):
        session, plane_index, movie = task
        return _run_plane(
            fish_id=fish_id,
            session=session,
            plane_index=plane_index,
            movie_path=movie,
            anatomy_filtered=anatomy_filtered,
            z_spacing_um=z_spacing_um,
            config=cfg,
        )

    workers = max(1, min(int(cfg.workers), len(tasks)))
    if workers == 1:
        results = [execute(task) for task in tasks]
    else:
        results = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(execute, task): task for task in tasks}
            for future in as_completed(futures):
                results.append(future.result())
    for intervals, profiles, plane, anchor_profiles, reference in results:
        interval_rows.extend(intervals)
        profile_rows.extend(profiles)
        plane_rows.append(plane)
        anchor_profile_rows.extend(anchor_profiles)
        references_by_plane[int(plane["plane_index"])] = np.asarray(reference, dtype=np.float32)
    elapsed = time.perf_counter() - started

    interval_df = pd.DataFrame(interval_rows).sort_values(["session", "plane_index", "interval_index"])
    profile_df = pd.DataFrame(profile_rows).sort_values(["session", "plane_index", "interval_index", "anatomy_z"])
    plane_df = pd.DataFrame(plane_rows).sort_values(["session", "plane_index"])
    anchor_profile_df = pd.DataFrame(anchor_profile_rows).sort_values(["session", "plane_index", "anatomy_z"])
    summary_df = summarize_sessions(interval_df, cfg, z_spacing_um)

    reference_dir = out / "functional_references"
    reference_dir.mkdir(parents=True, exist_ok=True)
    reference_paths: dict[int, Path] = {}
    for plane_index, reference in sorted(references_by_plane.items()):
        reference_path = reference_dir / f"{fish_id}_plane{plane_index}_pooled_post_block0_ref.tif"
        tifffile.imwrite(reference_path, reference)
        reference_paths[plane_index] = reference_path
    plane_df["reference_path"] = plane_df["plane_index"].map(
        lambda plane_index: str(reference_paths[int(plane_index)])
    )

    paths = {
        "intervals": out / "ncc_drift_intervals.csv",
        "profiles": out / "ncc_drift_profiles.csv",
        "profiles_png": out / "ncc_drift_profiles.png",
        "planes": out / "ncc_scale_bestz_by_plane.csv",
        "anchor_profiles": out / "ncc_anchor_profiles.csv",
        "anchor_profiles_png": out / "ncc_best_z_profiles.png",
        "functional_references": reference_dir,
        "summary": out / "ncc_drift_session_summary.csv",
        "tracks_png": out / "ncc_drift_tracks.png",
    }
    interval_df.to_csv(paths["intervals"], index=False)
    profile_df.to_csv(paths["profiles"], index=False)
    plane_df.to_csv(paths["planes"], index=False)
    anchor_profile_df.to_csv(paths["anchor_profiles"], index=False)
    summary_df.to_csv(paths["summary"], index=False)
    _render_tracks(interval_df, summary_df, paths["tracks_png"])
    _render_anchor_profiles(anchor_profile_df, plane_df, paths["anchor_profiles_png"])
    _render_temporal_profiles(profile_df, paths["profiles_png"])

    manifest = {
        "stage": "functional_anatomy_ncc_qc",
        "version": 4,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fish_id": fish_id,
        "status": _overall_status(summary_df),
        "scientific_review_required": True,
        "placement_method": {
            "name": "tracked_local_xy_with_global_fallback",
            "validation": (
                "Promoted after real-data benchmarks reproduced global best Z and maximum NCC without loss "
                "of depth-profile quality while reducing runtime. Full-frame matching remains the safety "
                "fallback when the tracked local optimum is weak or touches the local-search boundary."
            ),
        },
        "inputs": {
            "fish_dir": str(root),
            "canonical_anatomy": str(anatomy_source),
            "spatial_preprocessing_manifest": str(contract_path),
            "preprocessing_metadata": str(metadata_path),
            "motion_corrected_movies": {str(index): str(path) for index, path in movies.items()},
        },
        "canonical_anatomy_validation": {
            "shape_zyx": list(raw_anatomy.data_zyx.shape),
            "source_dtype": raw_anatomy.source_dtype,
            "page_count": raw_anatomy.page_count,
            "series_shape": list(raw_anatomy.series_shape),
            "reader": raw_anatomy.reader,
            "used_page_stack_fallback": raw_anatomy.used_page_stack_fallback,
            "z_spacing_um": z_spacing_um,
            "z_spacing_metadata_sources": [str(path) for path in z_metadata_sources],
            "spacing_xyz_um": list(anatomy_spacing_xyz_um),
            "xy_frame": CANONICAL_XY_FRAME,
            "z_frame": REGISTRATION_Z_FRAME,
        },
        "parameters": asdict(cfg),
        "runtime_seconds": elapsed,
        "parallel_workers": workers,
        "outputs": {key: str(path) for key, path in paths.items()},
        "downstream_handoff": {
            "schema": "functional_anatomy_ncc_handoff_v1",
            "authoritative_placement_table": str(paths["planes"]),
            "authoritative_anchor_profiles": str(paths["anchor_profiles"]),
            "functional_reference_directory": str(reference_dir),
            "functional_reference_selection": "pooled_post_block0",
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
    manifest_path = out / "functional_anatomy_qc_manifest.json"
    manifest["outputs"]["manifest"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
    return manifest


__all__ = [
    "FunctionalAnatomyQCConfig",
    "RawAnatomy",
    "anatomy_z_spacing_um",
    "block_third_bounds",
    "block_third_labels",
    "discover_raw_in_vivo_anatomy",
    "global_xy_depth_profile",
    "quadratic_peak_z",
    "read_canonical_anatomy",
    "read_raw_anatomy",
    "run_functional_anatomy_qc",
    "tracked_local_depth_profile",
]
