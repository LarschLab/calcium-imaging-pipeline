"""dF/F extraction: turn the Suite2P fluorescence of each ROI into dF/F traces.

For each plane of a fish, the ROIs that Suite2P classified as cells are kept,
very dim ROIs are dropped, and a slowly varying baseline (F0) is estimated
from a low percentile of each trace in a sliding window. ROIs whose baseline
drops too much are dropped as unstable; for the rest, dF/F = (F - F0) / F0.

- Results are saved next to the Suite2P ROI files (on the storage drive),
  with a metadata file recording the settings used, and the indices of the
  kept ROIs in Suite2P's full ROI list.
- A plane whose dF/F results already exist is skipped, never overwritten.
- Run it from the terminal or fill in the settings at the bottom (see `--help`).

Written by Matilde Perrino (2025).
"""

import argparse
import json
from pathlib import Path
import time

import numpy as np
from scipy.ndimage import uniform_filter1d

SUITE2P_ANALYSIS_SUBFOLDER = Path("03_analysis/functional/suite2P")  # Suite2P ROI files, inside the fish folder
METADATA_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def load_fluorescence_data(path):
    """Load raw fluorescence traces from a Suite2P `F.npy` file.

    Args:
        path (Path): Path to the F.npy file (ROIs x frames).

    Returns:
        np.ndarray: Fluorescence traces (frames x ROIs).
    """
    fluorescence_trace = np.load(path).T
    return fluorescence_trace


def filter_dim_rois(fluorescence_trace, threshold_std=2):
    """Remove dim ROIs: mean fluorescence more than `threshold_std` SDs below the average ROI.

    Args:
        fluorescence_trace (np.ndarray): Fluorescence traces (frames x ROIs).
        threshold_std (float): Threshold in standard deviations of the ROI means.

    Returns:
        tuple: `(filtered_trace, bright_rois_mask)` -- the kept traces
        (frames x kept ROIs) and a boolean mask of the kept ROIs.
    """
    mean_fluo = np.mean(fluorescence_trace, axis=0)
    mean_of_means, std_of_means = np.mean(mean_fluo), np.std(mean_fluo)
    bright_rois_mask = mean_fluo >= mean_of_means - threshold_std * std_of_means
    filtered_trace = fluorescence_trace[:, bright_rois_mask]
    return filtered_trace, bright_rois_mask


def compute_percentile_baseline(fluorescence_trace, fps, tau,
                                percentile=8, instability_ratio=0.1,
                                min_window_s=15, window_tau_multiplier=40):
    """Compute a smooth baseline (F0) per ROI from a sliding-window percentile.

    ROIs whose baseline drops below `instability_ratio` x its maximum are
    marked unstable: their baseline is left as NaN.

    Args:
        fluorescence_trace (np.ndarray): Fluorescence traces (frames x ROIs).
        fps (float): Imaging rate in Hz.
        tau (float): Indicator decay time constant (seconds).
        percentile (int): Percentile used as the baseline.
        instability_ratio (float): If the baseline drops below this fraction
            of its maximum, the ROI is unstable.
        min_window_s (float): Minimum window size (seconds).
        window_tau_multiplier (float): Multiplier of tau to compute the window size.

    Returns:
        np.ndarray: Baseline F0 (frames x ROIs), NaN for unstable ROIs.
    """
    # TODO: discuss with Ale -- `window_frames` is used as a half-width (t ± window_frames),
    # so the percentile window is 2 × window_s (8 min with tau = 6 s), while the smoothing
    # below uses window_frames as its full width. Intended?
    n_frames, n_rois = fluorescence_trace.shape
    window_s = max(min_window_s, window_tau_multiplier * tau)
    window_frames = int(window_s * fps)

    baseline = np.full_like(fluorescence_trace, np.nan)

    for roi_index in range(n_rois):
        trace = fluorescence_trace[:, roi_index]
        local_baseline = np.zeros_like(trace)

        # Sliding-window percentile (the window is cut short at the start and end of the trace)
        for frame_index in range(n_frames):
            start = max(0, frame_index - window_frames)
            end = min(n_frames, frame_index + window_frames + 1)
            local_baseline[frame_index] = np.percentile(trace[start:end], percentile)

        # Stability check: skip ROIs with large baseline drops (their baseline stays NaN)
        if np.min(local_baseline) < instability_ratio * np.max(local_baseline):
            continue

        baseline[:, roi_index] = uniform_filter1d(local_baseline, size=window_frames)  # smooth the baseline

    return baseline


def compute_dff(fluorescence_trace, baseline):
    """Compute dF/F0 = (F - F0) / F0.

    Args:
        fluorescence_trace (np.ndarray): Cleaned fluorescence traces (frames x ROIs).
        baseline (np.ndarray): Baseline F0 (frames x ROIs).

    Returns:
        np.ndarray: dF/F0 traces (frames x ROIs).
    """
    baseline_safe = np.where(baseline == 0, np.finfo(float).eps, baseline)  # avoid dividing by zero
    delta_f_over_f = (fluorescence_trace - baseline) / baseline_safe
    return delta_f_over_f


def process_suite2p_fluorescence(file_prefix, s2p_folder, fps, tau, percentile=8, instability_ratio=0.1, min_window_s=15, window_tau_multiplier=40,
                                 dim_threshold_std=2):
    """Go from one plane's Suite2P output to dF/F traces of its stable, bright cells.

    Args:
        file_prefix (str): Filename prefix for this fish/plane (e.g. "{fish}_plane{i}").
        s2p_folder (Path): Plane folder containing the Suite2P files.
        fps (float): Imaging rate in Hz.
        tau (float): Calcium decay constant (seconds).
        percentile (int): Percentile for baseline estimation.
        instability_ratio (float): Instability rejection threshold.
        min_window_s (float): Minimum baseline window (seconds).
        window_tau_multiplier (float): Baseline window as a multiple of tau, if longer.
        dim_threshold_std (float): Drop ROIs this many SDs dimmer than the average ROI.

    Returns:
        tuple: `(delta_f_over_f, final_indices)` -- dF/F0 traces (frames x
        kept ROIs) and the kept ROIs' indices in Suite2P's full ROI list.
    """
    # TODO: discuss with Ale -- only F.npy is used, no neuropil subtraction (Fneu.npy). Intended?
    fluorescence_trace = load_fluorescence_data(s2p_folder / f"{file_prefix}_F.npy")
    iscell_mask = np.load(s2p_folder / f"{file_prefix}_iscell.npy")[:, 0].astype(bool)  # first column: cell yes/no

    # Keep only ROIs classified as cells
    fluorescence_trace = fluorescence_trace[:, iscell_mask]
    print(f"Excluded {np.sum(~iscell_mask)} non-cell ROIs. Remaining: {fluorescence_trace.shape[1]} cells.")

    filtered_trace, bright_rois_mask = filter_dim_rois(fluorescence_trace, threshold_std=dim_threshold_std)
    print(f"Removed {np.sum(~bright_rois_mask)} dim ROIs.")

    baseline = compute_percentile_baseline(filtered_trace, fps, tau, percentile, instability_ratio, min_window_s,
                                           window_tau_multiplier)

    # Remove ROIs with unstable baselines (NaN baseline = large drops)
    stable_rois_mask = ~np.isnan(baseline).all(axis=0)
    print(f"Removed {np.sum(~stable_rois_mask)} unstable ROIs.")

    clean_trace = filtered_trace[:, stable_rois_mask]
    clean_baseline = baseline[:, stable_rois_mask]
    delta_f_over_f = compute_dff(clean_trace, clean_baseline)
    print(f"ΔF/F0 computed. Final ROIs: {delta_f_over_f.shape[1]}")

    # Map the kept ROIs back to their indices in the full Suite2P ROI list
    original_indices = np.where(iscell_mask)[0]
    retained_indices = original_indices[bright_rois_mask]
    final_indices = retained_indices[stable_rois_mask]

    return delta_f_over_f, final_indices


def existing_dff_outputs(plane_path, file_prefix):
    """List the dF/F outputs of a plane that are already on disk.

    Args:
        plane_path (Path): Suite2P plane folder where the outputs are written.
        file_prefix (str): Filename prefix for this fish/plane (e.g. "{fish}_plane{i}").

    Returns:
        list[Path]: Existing dF/F, ROI-index and metadata files; empty if none.
    """
    output_names = [f"{file_prefix}_dFoF.npy", f"{file_prefix}_filtered_roi_indices.npy", f"{file_prefix}_dFoF_metadata.json"]
    existing_outputs = [plane_path / name for name in output_names if (plane_path / name).exists()]
    return existing_outputs


def save_dff_outputs(plane_path, file_prefix, delta_f_over_f, final_indices, metadata):
    """Save a plane's dF/F traces, kept ROI indices and metadata, never overwriting.

    Args:
        plane_path (Path): Suite2P plane folder where the outputs are written.
        file_prefix (str): Filename prefix for this fish/plane (e.g. "{fish}_plane{i}").
        delta_f_over_f (np.ndarray): dF/F0 traces (frames x kept ROIs).
        final_indices (np.ndarray): Kept ROIs' indices in Suite2P's full ROI list.
        metadata (dict): Settings and shapes, saved as JSON.

    Returns:
        None: Three files are written to `plane_path`.

    Raises:
        FileExistsError: If one of the files already exists (it is left untouched).
    """
    # "xb"/"x" = create only, so an existing file raises instead of being overwritten
    with open(plane_path / f"{file_prefix}_dFoF.npy", "xb") as dff_file:
        np.save(dff_file, delta_f_over_f)  # shape frames x kept ROIs
    with open(plane_path / f"{file_prefix}_filtered_roi_indices.npy", "xb") as indices_file:
        np.save(indices_file, final_indices)
    with (plane_path / f"{file_prefix}_dFoF_metadata.json").open("x", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2)


def extract_dff_for_plane(fish_folder, plane_idx, dff_settings):
    """Compute and save the dF/F traces of one plane, skipping planes already done.

    Args:
        fish_folder (Path): Folder of one fish (with the Suite2P ROI files).
        plane_idx (int): Plane index.
        dff_settings (dict): Keyword settings of `process_suite2p_fluorescence`
            (fps, tau, percentile, ...); also saved in the metadata.

    Returns:
        None: The dF/F outputs are written next to the plane's Suite2P files.
    """
    fish_id = fish_folder.name
    plane_path = fish_folder / SUITE2P_ANALYSIS_SUBFOLDER / f"plane{plane_idx}"
    file_prefix = f"{fish_id}_plane{plane_idx}"
    f_path = plane_path / f"{file_prefix}_F.npy"
    print(f"\n📦 Processing plane {plane_idx}")
    # Never overwrite results (they live on the storage drive, with no backup)
    existing_outputs = existing_dff_outputs(plane_path, file_prefix)
    if existing_outputs:
        existing_names = ", ".join(path.name for path in existing_outputs)
        print(f"  ⚠️ Skipping plane {plane_idx}: dF/F outputs already exist ({existing_names}). Move them to rerun this plane.")
        return
    if not f_path.exists():
        print(f"  ❌ File not found: {f_path}")
        return

    delta_f_over_f, final_indices = process_suite2p_fluorescence(file_prefix, plane_path, **dff_settings)
    metadata = {
        "fish_id": fish_id,
        "plane_index": plane_idx,
        "source_folder": str(f_path),
        "params": dict(dff_settings),
        "shapes": {
            "dFoF_TxN": [int(delta_f_over_f.shape[0]), int(delta_f_over_f.shape[1])],
            "roi_indices_len": int(len(final_indices)),
        },
        "timestamp": time.strftime(METADATA_TIMESTAMP_FORMAT),
    }
    save_dff_outputs(plane_path, file_prefix, delta_f_over_f, final_indices, metadata)
    print(f"Saved to {plane_path}")


def batch_dff_extraction(data_root, fish_ids, planes, dff_settings):
    """Extract dF/F for several fish and planes; missing data is skipped with a warning.

    Args:
        data_root (str or Path): Folder containing the fish folders.
        fish_ids (list[str]): Fish IDs to process (e.g. `["L331_f01"]`).
        planes (list[int]): Plane indices to process.
        dff_settings (dict): Keyword settings of `process_suite2p_fluorescence`.

    Returns:
        None: dF/F outputs are written next to each plane's Suite2P files.
    """
    for fish_id in fish_ids:
        fish_folder = Path(data_root) / fish_id
        print(f"\n🔍 Processing {fish_id} in {fish_folder / SUITE2P_ANALYSIS_SUBFOLDER}")
        if not fish_folder.is_dir():
            print(f"  ⚠️ Fish folder not found, skipping: {fish_folder}")
            continue
        for plane_idx in planes:
            extract_dff_for_plane(fish_folder, plane_idx, dff_settings)


if __name__ == "__main__":
    # ---- Settings: fill in by hand when running this file (terminal options override them) ----
    #DATA_ROOT = "D:/Matilde/2p_data/LR_thalamus_bout_exp01"
    DATA_ROOT = "/Volumes/RECHERCHE/FAC/FBM/CIG/jlarsch/default/D2c/07_Data/Matilde/Microscopy"
    #DATA_ROOT = "F:/Matilde/2p_data"
    FISH_TO_PROCESS = ["L331_f01"]  # Fish IDs to process

    PLANES_TO_PROCESS = [0, 1, 2, 3, 4]  # Planes to process
    FPS = 2.0  # Imaging rate in Hz
    TAU = 6.0  # GCaMP6s decay time (sec)
    PERCENTILE = 8  # Percentile for baseline (e.g. 8th)
    INSTABILITY_RATIO = 0.1  # Baseline instability check (10× drop = 0.1)
    MIN_WINDOW_S = 15  # Shortest baseline window (seconds)
    WINDOW_TAU_MULTIPLIER = 40  # Baseline window = this × tau, if longer
    DIM_THRESHOLD_STD = 2  # Drop ROIs this many SDs dimmer than the average ROI
    # ----------------------------------------------------------------------------------------------

    parser = argparse.ArgumentParser(
        description="dF/F extraction from Suite2P fluorescence, per plane.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,  # show each default in --help
    )
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT, help="folder containing the fish folders")
    parser.add_argument("--fish", nargs="+", default=FISH_TO_PROCESS, help="fish IDs to process")
    parser.add_argument("--planes", type=int, nargs="+", default=PLANES_TO_PROCESS, help="plane indices to process")
    parser.add_argument("--fps", type=float, default=FPS, help="imaging rate (Hz)")
    parser.add_argument("--tau", type=float, default=TAU, help="indicator decay time (s)")
    parser.add_argument("--percentile", type=float, default=PERCENTILE, help="percentile used as the baseline")
    parser.add_argument("--instability-ratio", type=float, default=INSTABILITY_RATIO, help="drop ROIs whose baseline falls below this fraction of its maximum")
    parser.add_argument("--min-window-s", type=float, default=MIN_WINDOW_S, help="shortest baseline window (s)")
    parser.add_argument("--window-tau-multiplier", type=float, default=WINDOW_TAU_MULTIPLIER, help="baseline window = this x tau, if longer")
    parser.add_argument("--dim-threshold-std", type=float, default=DIM_THRESHOLD_STD, help="drop ROIs this many SDs dimmer than the average ROI")
    args = parser.parse_args()

    dff_settings = {
        "fps": args.fps,
        "tau": args.tau,
        "percentile": args.percentile,
        "instability_ratio": args.instability_ratio,
        "min_window_s": args.min_window_s,
        "window_tau_multiplier": args.window_tau_multiplier,
        "dim_threshold_std": args.dim_threshold_std,
    }
    batch_dff_extraction(args.data_root, args.fish, args.planes, dff_settings)
