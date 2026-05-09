from __future__ import annotations

import argparse
import csv
import math
import pathlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import tifffile as tf

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from preprocessing.dFoF_extraction import compute_dff, compute_percentile_baseline


pathlib.WindowsPath = pathlib.PosixPath

DEFAULT_BASELINE_ROOT = Path("/Users/ddharmap/dataProcessing/2p_processing/L395_f11")
DEFAULT_COMPARISON_ROOT = Path("/Users/ddharmap/dataProcessing/2p_processing_suite2p_legacy_mps/L395_f11")
DEFAULT_OUTPUT_ROOT = Path(
    "/Users/ddharmap/dataProcessing/2p_processing_suite2p_legacy_mps/comparison_vs_baseline/L395_f11"
)
DEFAULT_FISH_ID = "L395_f11"
DEFAULT_PLANES = [0, 1, 2, 3, 4]


@dataclass(frozen=True)
class RoiMatch:
    reference_index: int
    comparison_index: int
    iou: float
    centroid_distance: float


@dataclass(frozen=True)
class TracePanel:
    group: str
    plane: int
    roi_id: int
    category: str
    sort_metric: float
    trace: np.ndarray


def parse_int_csv(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def plane_dir(run_root: Path, plane: int) -> Path:
    return run_root / "03_analysis/functional/suite2P" / f"plane{plane}"


def first_match(folder: Path, suffix: str) -> Path:
    matches = sorted(folder.glob(f"*_{suffix}.npy"))
    if not matches:
        raise FileNotFoundError(f"No *_{suffix}.npy file found in {folder}")
    return sorted(matches, key=lambda path: (len(path.name), path.name))[0]


def load_plane_outputs(run_root: Path, plane: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    folder = plane_dir(run_root, plane)
    stat = np.load(first_match(folder, "stat"), allow_pickle=True)
    iscell = np.load(first_match(folder, "iscell"), allow_pickle=True)
    fluorescence = np.load(first_match(folder, "F"), allow_pickle=True)
    return stat, iscell, fluorescence


def roi_centroid(stat_entry: dict) -> np.ndarray:
    return np.asarray(stat_entry["med"], dtype=float)


def roi_pixels(stat_entry: dict) -> set[tuple[int, int]]:
    ypix = np.asarray(stat_entry["ypix"], dtype=int)
    xpix = np.asarray(stat_entry["xpix"], dtype=int)
    return set(zip(ypix.tolist(), xpix.tolist()))


def roi_iou(reference_pixels: set[tuple[int, int]], comparison_pixels: set[tuple[int, int]]) -> float:
    union = len(reference_pixels | comparison_pixels)
    if union == 0:
        return 0.0
    return len(reference_pixels & comparison_pixels) / union


def match_rois(
    reference_stat: np.ndarray,
    comparison_stat: np.ndarray,
    reference_indices: Iterable[int],
    comparison_indices: Iterable[int],
    max_centroid_distance: float = 5.0,
    min_iou: float = 0.05,
) -> list[RoiMatch]:
    reference_indices = list(reference_indices)
    comparison_indices = list(comparison_indices)
    comparison_pixels = {idx: roi_pixels(comparison_stat[idx]) for idx in comparison_indices}
    comparison_centroids = {idx: roi_centroid(comparison_stat[idx]) for idx in comparison_indices}

    candidates: list[tuple[float, float, int, int]] = []
    for ref_idx in reference_indices:
        ref_pixels = roi_pixels(reference_stat[ref_idx])
        ref_centroid = roi_centroid(reference_stat[ref_idx])
        for cmp_idx in comparison_indices:
            distance = float(np.linalg.norm(ref_centroid - comparison_centroids[cmp_idx]))
            if distance > max_centroid_distance:
                continue
            iou = roi_iou(ref_pixels, comparison_pixels[cmp_idx])
            if iou >= min_iou:
                candidates.append((-iou, distance, ref_idx, cmp_idx))

    candidates.sort()
    used_reference: set[int] = set()
    used_comparison: set[int] = set()
    matches: list[RoiMatch] = []
    for neg_iou, distance, ref_idx, cmp_idx in candidates:
        if ref_idx in used_reference or cmp_idx in used_comparison:
            continue
        used_reference.add(ref_idx)
        used_comparison.add(cmp_idx)
        matches.append(RoiMatch(ref_idx, cmp_idx, -neg_iou, distance))
    return matches


def trace_quality_metrics(trace: np.ndarray) -> dict[str, float | int]:
    trace = np.asarray(trace, dtype=float)
    mean = float(np.mean(trace))
    std = float(np.std(trace))
    cv = float(std / mean) if mean else math.nan
    centered = trace - mean
    skew = float(np.mean(centered**3) / (std**3)) if std else math.nan
    p5, p95 = np.percentile(trace, [5, 95])
    median = float(np.median(trace))
    mad = float(np.median(np.abs(trace - median)))
    robust_scale = 1.4826 * mad if mad else std
    if robust_scale:
        robust_z = (trace - median) / robust_scale
        max_robust_z = float(np.max(robust_z))
        transient_count = int(np.sum(robust_z > 3.0))
    else:
        max_robust_z = math.nan
        transient_count = 0
    return {
        "mean_f": mean,
        "std_f": std,
        "cv_f": cv,
        "skew_f": skew,
        "p95_minus_p5": float(p95 - p5),
        "robust_transient_count": transient_count,
        "max_robust_z": max_robust_z,
    }


def weighted_trace_from_tiff(tiff_path: Path, stat_entry: dict) -> np.ndarray:
    ypix = np.asarray(stat_entry["ypix"], dtype=int)
    xpix = np.asarray(stat_entry["xpix"], dtype=int)
    lam = np.asarray(stat_entry["lam"], dtype=float)
    if lam.size == 0:
        return np.array([], dtype=float)
    lam_sum = np.sum(lam)
    weights = lam / lam_sum if lam_sum else np.full_like(lam, 1.0 / len(lam))

    values = []
    with tf.TiffFile(tiff_path) as tif:
        for page in tif.pages:
            frame = page.asarray()
            values.append(float(np.dot(frame[ypix, xpix], weights)))
    return np.asarray(values, dtype=float)


def motion_corrected_tiff(run_root: Path, fish_id: str, plane: int) -> Path:
    return (
        run_root
        / "02_reg/00_preprocessing/2p_functional/02_motionCorrected"
        / f"{fish_id}_plane{plane}_mcorrected.tif"
    )


def metric_columns(prefix: str) -> list[str]:
    return [
        f"{prefix}_mean_f",
        f"{prefix}_std_f",
        f"{prefix}_cv_f",
        f"{prefix}_skew_f",
        f"{prefix}_p95_minus_p5",
        f"{prefix}_robust_transient_count",
        f"{prefix}_max_robust_z",
    ]


def prefixed_metrics(prefix: str, metrics: dict[str, float | int] | None) -> dict[str, float | int | str]:
    if metrics is None:
        return {column: "" for column in metric_columns(prefix)}
    return {f"{prefix}_{key}": value for key, value in metrics.items()}


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def safe_float(value: float | int | str) -> float:
    if value == "" or value is None:
        return math.nan
    return float(value)


def zscore_trace(trace: np.ndarray) -> np.ndarray | None:
    trace = np.asarray(trace, dtype=float)
    if trace.size == 0 or not np.all(np.isfinite(trace)):
        return None
    std = float(np.std(trace))
    if std == 0.0:
        return None
    return (trace - float(np.mean(trace))) / std


def zscored_dff_trace_items(
    fluorescence: np.ndarray,
    roi_indices: Iterable[int],
    fps: float,
    tau: float,
) -> list[tuple[int, np.ndarray]]:
    roi_indices = list(roi_indices)
    if not roi_indices:
        return []

    traces_t_by_n = np.asarray(fluorescence[roi_indices], dtype=float).T
    baseline = compute_percentile_baseline(traces_t_by_n, fps=fps, tau=tau)
    dff = compute_dff(traces_t_by_n, baseline)
    zscored: list[tuple[int, np.ndarray]] = []
    for roi_id, roi_trace in zip(roi_indices, dff.T):
        trace = zscore_trace(roi_trace)
        if trace is not None:
            zscored.append((int(roi_id), trace))
    return zscored


def zscored_dff_traces(fluorescence: np.ndarray, roi_indices: Iterable[int], fps: float, tau: float) -> list[np.ndarray]:
    return [trace for _roi_id, trace in zscored_dff_trace_items(fluorescence, roi_indices, fps, tau)]


def baseline_remainder_roi_ids(rows: list[dict], plane: int) -> list[int]:
    remainder_categories = {"matched_rejected", "unmatched"}
    return [
        int(row["baseline_roi_id"])
        for row in rows
        if int(row["plane"]) == plane and row["category"] in remainder_categories
    ]


def new_accepted_comparison_roi_ids(rows: list[dict], plane: int) -> list[int]:
    return [int(row["comparison_roi_id"]) for row in rows if int(row["plane"]) == plane]


def plane_trace_params(run_root: Path, plane: int) -> tuple[float, float]:
    ops_path = first_match(plane_dir(run_root, plane), "ops")
    ops = np.load(ops_path, allow_pickle=True).item()
    return float(ops.get("fs", 2.0)), float(ops.get("tau", 3.0))


def trace_panel_row_count(trace_count: int, traces_per_panel: int = 5) -> int:
    if trace_count <= 0:
        return 0
    return int(math.ceil(trace_count / traces_per_panel))


def analyze_plane(
    baseline_root: Path,
    comparison_root: Path,
    fish_id: str,
    plane: int,
    max_centroid_distance: float,
    min_iou: float,
) -> tuple[list[dict], list[dict], dict]:
    baseline_stat, baseline_iscell, baseline_f = load_plane_outputs(baseline_root, plane)
    comparison_stat, comparison_iscell, comparison_f = load_plane_outputs(comparison_root, plane)
    baseline_accepted = np.flatnonzero(baseline_iscell[:, 0].astype(bool))
    comparison_accepted = np.flatnonzero(comparison_iscell[:, 0].astype(bool))
    comparison_all = np.arange(len(comparison_stat))

    matches = match_rois(
        baseline_stat,
        comparison_stat,
        baseline_accepted,
        comparison_all,
        max_centroid_distance=max_centroid_distance,
        min_iou=min_iou,
    )
    matches_by_ref = {match.reference_index: match for match in matches}
    matched_comparison = {match.comparison_index for match in matches}

    comparison_tiff = motion_corrected_tiff(comparison_root, fish_id, plane)
    baseline_rows: list[dict] = []
    for ref_idx in baseline_accepted:
        ref_entry = baseline_stat[ref_idx]
        ref_centroid = roi_centroid(ref_entry)
        baseline_metrics = trace_quality_metrics(baseline_f[ref_idx])
        match = matches_by_ref.get(ref_idx)
        comparison_metrics = None
        comparison_mask_metrics = None
        if match is None:
            category = "unmatched"
            comparison_idx = ""
            comparison_score = ""
            centroid_distance = ""
            iou = ""
            if comparison_tiff.exists():
                comparison_mask_metrics = trace_quality_metrics(weighted_trace_from_tiff(comparison_tiff, ref_entry))
        else:
            comparison_idx = match.comparison_index
            comparison_score = float(comparison_iscell[comparison_idx, 1])
            centroid_distance = match.centroid_distance
            iou = match.iou
            category = "matched_accepted" if bool(comparison_iscell[comparison_idx, 0]) else "matched_rejected"
            comparison_metrics = trace_quality_metrics(comparison_f[comparison_idx])

        row = {
            "plane": plane,
            "baseline_roi_id": int(ref_idx),
            "category": category,
            "comparison_roi_id": comparison_idx,
            "comparison_iscell_score": comparison_score,
            "centroid_distance_px": centroid_distance,
            "iou": iou,
            "baseline_med_y": float(ref_centroid[0]),
            "baseline_med_x": float(ref_centroid[1]),
            "baseline_npix": int(ref_entry["npix"]),
        }
        row.update(prefixed_metrics("baseline", baseline_metrics))
        row.update(prefixed_metrics("comparison", comparison_metrics))
        row.update(prefixed_metrics("comparison_baseline_mask", comparison_mask_metrics))
        baseline_rows.append(row)

    new_accepted_rows: list[dict] = []
    for cmp_idx in comparison_accepted:
        if int(cmp_idx) in matched_comparison:
            continue
        cmp_entry = comparison_stat[cmp_idx]
        cmp_centroid = roi_centroid(cmp_entry)
        metrics = trace_quality_metrics(comparison_f[cmp_idx])
        row = {
            "plane": plane,
            "comparison_roi_id": int(cmp_idx),
            "comparison_iscell_score": float(comparison_iscell[cmp_idx, 1]),
            "comparison_med_y": float(cmp_centroid[0]),
            "comparison_med_x": float(cmp_centroid[1]),
            "comparison_npix": int(cmp_entry["npix"]),
        }
        row.update(prefixed_metrics("comparison", metrics))
        new_accepted_rows.append(row)

    category_counts = {category: 0 for category in ["matched_accepted", "matched_rejected", "unmatched"]}
    for row in baseline_rows:
        category_counts[row["category"]] += 1
    summary = {
        "plane": plane,
        "baseline_accepted_count": int(len(baseline_accepted)),
        "comparison_total_roi_count": int(len(comparison_stat)),
        "comparison_accepted_count": int(len(comparison_accepted)),
        "matched_accepted": category_counts["matched_accepted"],
        "matched_rejected": category_counts["matched_rejected"],
        "unmatched": category_counts["unmatched"],
        "new_accepted": int(len(new_accepted_rows)),
        "median_matched_iou": float(np.nanmedian([safe_float(row["iou"]) for row in baseline_rows if row["iou"] != ""]))
        if any(row["iou"] != "" for row in baseline_rows)
        else math.nan,
        "median_matched_centroid_distance_px": float(
            np.nanmedian([safe_float(row["centroid_distance_px"]) for row in baseline_rows if row["centroid_distance_px"] != ""])
        )
        if any(row["centroid_distance_px"] != "" for row in baseline_rows)
        else math.nan,
    }
    return baseline_rows, new_accepted_rows, summary


def plot_remainder_traces(
    output_root: Path,
    baseline_rows: list[dict],
    new_accepted_rows: list[dict],
    summary_rows: list[dict],
    baseline_root: Path,
    comparison_root: Path,
) -> None:
    import matplotlib.pyplot as plt

    planes = [int(row["plane"]) for row in summary_rows]
    if not planes:
        return

    panels: list[TracePanel] = []
    for plane in planes:
        plane_rows = [
            row for row in baseline_rows if int(row["plane"]) == plane and row["category"] in {"matched_rejected", "unmatched"}
        ]
        if plane_rows:
            roi_ids = [int(row["baseline_roi_id"]) for row in plane_rows]
            _stat, _iscell, fluorescence = load_plane_outputs(baseline_root, plane)
            fps, tau = plane_trace_params(baseline_root, plane)
            traces_by_roi = dict(zscored_dff_trace_items(fluorescence, roi_ids, fps=fps, tau=tau))
            for row in plane_rows:
                roi_id = int(row["baseline_roi_id"])
                trace = traces_by_roi.get(roi_id)
                if trace is None:
                    continue
                panels.append(
                    TracePanel(
                        group="Baseline accepted only",
                        plane=plane,
                        roi_id=roi_id,
                        category=str(row["category"]),
                        sort_metric=safe_float(row["baseline_max_robust_z"]),
                        trace=trace,
                    )
                )

        plane_new_rows = [row for row in new_accepted_rows if int(row["plane"]) == plane]
        if plane_new_rows:
            roi_ids = [int(row["comparison_roi_id"]) for row in plane_new_rows]
            _stat, _iscell, fluorescence = load_plane_outputs(comparison_root, plane)
            fps, tau = plane_trace_params(comparison_root, plane)
            traces_by_roi = dict(zscored_dff_trace_items(fluorescence, roi_ids, fps=fps, tau=tau))
            for row in plane_new_rows:
                roi_id = int(row["comparison_roi_id"])
                trace = traces_by_roi.get(roi_id)
                if trace is None:
                    continue
                panels.append(
                    TracePanel(
                        group="Legacy MPS accepted only",
                        plane=plane,
                        roi_id=roi_id,
                        category="new_accepted",
                        sort_metric=safe_float(row["comparison_max_robust_z"]),
                        trace=trace,
                    )
                )

    if not panels:
        return

    group_order = {"Baseline accepted only": 0, "Legacy MPS accepted only": 1}
    panels.sort(key=lambda panel: (group_order[panel.group], -panel.sort_metric, panel.plane, panel.roi_id))
    traces_per_panel = 5
    grouped_panels: list[tuple[str, int, int, list[TracePanel]]] = []
    for group in group_order:
        group_panels = [panel for panel in panels if panel.group == group]
        for start in range(0, len(group_panels), traces_per_panel):
            grouped_panels.append((group, start + 1, len(group_panels), group_panels[start : start + traces_per_panel]))

    rows = len(grouped_panels)
    fig, axes = plt.subplots(
        rows,
        1,
        figsize=(18, max(2.4, 1.85 * rows)),
        sharex=True,
        sharey=True,
        squeeze=False,
    )
    colors = plt.get_cmap("tab10")
    for row_idx, (group, start, group_total, trace_group) in enumerate(grouped_panels):
        ax = axes[row_idx, 0]
        ax.axhline(0.0, color="0.75", linewidth=0.45)
        for color_idx, panel in enumerate(trace_group):
            prefix = "baseline" if panel.group.startswith("Baseline") else "legacy"
            label = f"{prefix} p{panel.plane} r{panel.roi_id}, {panel.category}, z={panel.sort_metric:.1f}"
            ax.plot(panel.trace, color=colors(color_idx), linewidth=0.8, label=label)
        end = start + len(trace_group) - 1
        ax.set_title(f"{group}: traces {start}-{end} of {group_total}", fontsize=9)
        ax.set_ylabel("z-scored dF/F", fontsize=8)
        if row_idx == rows - 1:
            ax.set_xlabel("Frame", fontsize=8)
        ax.legend(loc="upper right", ncol=min(traces_per_panel, len(trace_group)), fontsize=6, frameon=False)
        ax.tick_params(axis="both", labelsize=7)

    fig.suptitle(
        "Remainder ROI activity traces: one wide panel per five traces",
        fontsize=13,
        y=0.998,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.988), h_pad=1.0, w_pad=0.6)
    fig.savefig(output_root / "remainder_zscored_dff_traces_by_plane.png", dpi=160)
    plt.close(fig)


def plot_outputs(
    output_root: Path,
    baseline_rows: list[dict],
    new_accepted_rows: list[dict],
    summary_rows: list[dict],
    baseline_root: Path,
    comparison_root: Path,
) -> None:
    import matplotlib.pyplot as plt

    output_root.mkdir(parents=True, exist_ok=True)
    planes = [row["plane"] for row in summary_rows]
    categories = ["matched_accepted", "matched_rejected", "unmatched"]
    bottoms = np.zeros(len(planes))
    fig, ax = plt.subplots(figsize=(8, 4))
    for category in categories:
        values = np.asarray([row[category] for row in summary_rows])
        ax.bar(planes, values, bottom=bottoms, label=category)
        bottoms += values
    ax.set_xlabel("Plane")
    ax.set_ylabel("Baseline accepted ROIs")
    ax.legend()
    ax.set_title("Baseline accepted ROI match categories")
    fig.tight_layout()
    fig.savefig(output_root / "roi_match_counts_by_plane.png", dpi=160)
    plt.close(fig)

    metric = "baseline_max_robust_z"
    fig, ax = plt.subplots(figsize=(8, 4))
    for category in categories:
        values = [safe_float(row[metric]) for row in baseline_rows if row["category"] == category]
        if values:
            ax.hist(values, bins=30, alpha=0.45, label=category)
    ax.set_xlabel(metric)
    ax.set_ylabel("ROI count")
    ax.legend()
    ax.set_title("Baseline trace signal metric by match category")
    fig.tight_layout()
    fig.savefig(output_root / "baseline_max_robust_z_by_category.png", dpi=160)
    plt.close(fig)

    for plane in planes:
        plane_rows = [row for row in baseline_rows if row["plane"] == plane]
        ops_path = first_match(plane_dir(baseline_root, plane), "ops")
        ops = np.load(ops_path, allow_pickle=True).item()
        image = ops.get("meanImg")
        if image is None:
            continue
        fig, ax = plt.subplots(figsize=(7, 7))
        ax.imshow(image, cmap="gray")
        colors = {"matched_accepted": "lime", "matched_rejected": "orange", "unmatched": "red"}
        for category, color in colors.items():
            xs = [row["baseline_med_x"] for row in plane_rows if row["category"] == category]
            ys = [row["baseline_med_y"] for row in plane_rows if row["category"] == category]
            ax.scatter(xs, ys, s=8, c=color, label=category, alpha=0.8)
        ax.set_title(f"Plane {plane} baseline ROI match overlay")
        ax.set_axis_off()
        ax.legend(loc="upper right", markerscale=2)
        fig.tight_layout()
        fig.savefig(output_root / f"plane{plane}_match_overlay.png", dpi=160)
        plt.close(fig)

    strongest = sorted(
        [row for row in baseline_rows if row["category"] == "unmatched"],
        key=lambda row: safe_float(row["baseline_max_robust_z"]),
        reverse=True,
    )[:12]
    if strongest:
        fig, axes = plt.subplots(len(strongest), 1, figsize=(10, max(3, 1.5 * len(strongest))), sharex=True)
        if len(strongest) == 1:
            axes = [axes]
        for ax, row in zip(axes, strongest):
            plane = int(row["plane"])
            roi_id = int(row["baseline_roi_id"])
            _stat, _iscell, baseline_f = load_plane_outputs(baseline_root, plane)
            trace = baseline_f[roi_id]
            ax.plot(trace, linewidth=0.8)
            ax.set_ylabel(f"p{plane} r{roi_id}")
        axes[-1].set_xlabel("Frame")
        fig.suptitle("Strongest unmatched baseline traces")
        fig.tight_layout()
        fig.savefig(output_root / "strongest_unmatched_baseline_traces.png", dpi=160)
        plt.close(fig)

    plot_remainder_traces(output_root, baseline_rows, new_accepted_rows, summary_rows, baseline_root, comparison_root)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Suite2P ROI sets across two runs.")
    parser.add_argument("--baseline-root", default=str(DEFAULT_BASELINE_ROOT))
    parser.add_argument("--comparison-root", default=str(DEFAULT_COMPARISON_ROOT))
    parser.add_argument("--fish-id", default=DEFAULT_FISH_ID)
    parser.add_argument("--planes", default="0,1,2,3,4")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--max-centroid-distance", type=float, default=5.0)
    parser.add_argument("--min-iou", type=float, default=0.05)
    parser.add_argument("--skip-plots", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    baseline_root = Path(args.baseline_root)
    comparison_root = Path(args.comparison_root)
    output_root = Path(args.output_root)
    planes = parse_int_csv(args.planes)

    all_baseline_rows: list[dict] = []
    all_new_accepted_rows: list[dict] = []
    summary_rows: list[dict] = []
    for plane in planes:
        baseline_rows, new_accepted_rows, summary = analyze_plane(
            baseline_root,
            comparison_root,
            args.fish_id,
            plane,
            max_centroid_distance=args.max_centroid_distance,
            min_iou=args.min_iou,
        )
        all_baseline_rows.extend(baseline_rows)
        all_new_accepted_rows.extend(new_accepted_rows)
        summary_rows.append(summary)

    baseline_fields = [
        "plane",
        "baseline_roi_id",
        "category",
        "comparison_roi_id",
        "comparison_iscell_score",
        "centroid_distance_px",
        "iou",
        "baseline_med_y",
        "baseline_med_x",
        "baseline_npix",
        *metric_columns("baseline"),
        *metric_columns("comparison"),
        *metric_columns("comparison_baseline_mask"),
    ]
    new_fields = [
        "plane",
        "comparison_roi_id",
        "comparison_iscell_score",
        "comparison_med_y",
        "comparison_med_x",
        "comparison_npix",
        *metric_columns("comparison"),
    ]
    summary_fields = [
        "plane",
        "baseline_accepted_count",
        "comparison_total_roi_count",
        "comparison_accepted_count",
        "matched_accepted",
        "matched_rejected",
        "unmatched",
        "new_accepted",
        "median_matched_iou",
        "median_matched_centroid_distance_px",
    ]
    write_csv(output_root / "baseline_cell_match_table.csv", all_baseline_rows, baseline_fields)
    write_csv(output_root / "legacy_new_accepted_table.csv", all_new_accepted_rows, new_fields)
    write_csv(output_root / "roi_match_summary.csv", summary_rows, summary_fields)

    if not args.skip_plots:
        plot_outputs(output_root, all_baseline_rows, all_new_accepted_rows, summary_rows, baseline_root, comparison_root)

    print(f"Wrote ROI comparison outputs to {output_root}")
    for row in summary_rows:
        print(
            f"plane {row['plane']}: matched_accepted={row['matched_accepted']}, "
            f"matched_rejected={row['matched_rejected']}, unmatched={row['unmatched']}, "
            f"new_accepted={row['new_accepted']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
