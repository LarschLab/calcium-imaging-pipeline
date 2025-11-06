import numpy as np
from pathlib import Path
from scipy.ndimage import uniform_filter1d
import time


def load_fluorescence_data(path):
    """
    Load raw fluorescence time-series data from Suite2p output.

    Parameters:
    - path (Path): Path to F.npy file.

    Returns:
    - np.ndarray: Fluorescence trace data (T x N).
    """
    fluorescence_trace = np.load(path).T
    return fluorescence_trace

def filter_dim_rois(fluorescence_trace, threshold_std=2):
    """
    Remove low-intensity (dim) ROIs based on mean fluorescence level.

    Parameters:
    - fluorescence_trace (np.ndarray): Fluorescence trace (T x N).
    - threshold_std (float): Threshold in standard deviations.

    Returns:
    - np.ndarray: Filtered fluorescence trace (T x N_filtered).
    - np.ndarray: Boolean mask indicating retained ROIs.
    """
    mean_fluo = np.mean(fluorescence_trace, axis=0)
    mu, sigma = np.mean(mean_fluo), np.std(mean_fluo)
    bright_rois_mask = mean_fluo >= mu - threshold_std * sigma
    return fluorescence_trace[:, bright_rois_mask], bright_rois_mask

def compute_percentile_baseline(fluorescence_trace, fps, tau,
                                        percentile=8, instability_ratio=0.1,
                                        min_window_s=15, window_tau_multiplier=40):
    """
    Compute smooth F0_baseline (F0) using sliding percentile window and stability filtering.

    Parameters:
    - fluorescence_trace (np.ndarray): Fluorescence data (T x N)
    - fps (float): Imaging rate in Hz.
    - tau (float): Indicator decay time constant (seconds).
    - percentile (int): Percentile for F0_baseline estimation.
    - instability_ratio (float): If F0 drops more than this ratio, ROI is unstable.
    - min_window_s (float): Minimum window size (seconds).
    - window_tau_multiplier (float): Multiplier of tau to compute window size.

    Returns:
    - np.ndarray: Baseline matrix F0 (T x N), NaN for unstable ROIs.
    """
    T, N = fluorescence_trace.shape
    window_s = max(min_window_s, window_tau_multiplier * tau)
    window_frames = int(window_s * fps)

    F0_baseline = np.full_like(fluorescence_trace, np.nan)

    for n in range(N):
        trace = fluorescence_trace[:, n]
        local_baseline  = np.zeros_like(trace)

        # Sliding window percentile calculation
        for t in range(T):
            start = max(0, t - window_frames)
            end = min(T, t + window_frames + 1)
            local_baseline [t] = np.percentile(trace[start:end], percentile)

        # Stability check: discard ROIs with large F0_baseline fluctuations
        if np.min(local_baseline ) < instability_ratio * np.max(local_baseline ):
            continue

        # Smooth F0_baseline
        F0_baseline[:, n] = uniform_filter1d(local_baseline , size=window_frames)

    return F0_baseline

def compute_dff(fluorescence_trace, F0_baseline):
    """
    Compute delta F over F0 (ΔF/F0).

    Parameters:
    - fluorescence_trace (np.ndarray): Cleaned fluorescence trace (T x N).
    - baseline (np.ndarray): Baseline F0 estimate (T x N).

    Returns:
    - np.ndarray: ΔF/F0 traces (T x N).
    """
    baseline_safe = np.where(F0_baseline == 0, np.finfo(float).eps, F0_baseline)
    return (fluorescence_trace - F0_baseline) / baseline_safe


def process_suite2p_fluorescence(fish, s2p_folder, fps, tau, percentile=8, instability_ratio=0.1, min_window_s=15, window_tau_multiplier=40):
    """
    Complete extraction pipeline: from Suite2p raw output to ΔF/F traces.

    Parameters:
    - fish (str): Fish ID for logging.
    - s2p_folder (Path): Path to plane folder containing Suite2p files.
    - fps (float): Imaging rate in Hz.
    - tau (float): Calcium decay constant (seconds).
    - percentile (int): Percentile for baseline estimation.
    - instability_ratio (float): Instability rejection threshold.

    Returns:
    - np.ndarray: ΔF/F0 traces (T x N_final).
    - np.ndarray: Retained ROI indices relative to full Suite2p ROI list.
    """
    fluorescence_trace = load_fluorescence_data(s2p_folder / f"{fish}_F.npy")
    iscell_mask = np.load(s2p_folder / f"{fish}_iscell.npy")[:, 0].astype(bool)

    # Keep only ROIs classified as cells
    fluorescence_trace = fluorescence_trace[:, iscell_mask]
    print(f"Excluded {np.sum(~iscell_mask)} non-cell ROIs. Remaining: {fluorescence_trace.shape[1]} cells.")

    # Remove dim (low-intensity) ROIs
    filtered_trace, bright_rois_mask = filter_dim_rois(fluorescence_trace)
    print(f"Removed {np.sum(~bright_rois_mask)} dim ROIs.")

    # Compute percentile baseline (F0)
    F0_baseline = compute_percentile_baseline(filtered_trace, fps, tau, percentile, instability_ratio, min_window_s,
                                           window_tau_multiplier)

    # Create mask to remove rois with unstable baselines (baseline with large drops)
    stable_rois_mask = ~np.isnan(F0_baseline).all(axis=0)
    print(f"Removed {np.sum(~stable_rois_mask)} unstable ROIs.")

    clean_trace = filtered_trace[:, stable_rois_mask]
    clean_baseline = F0_baseline[:, stable_rois_mask]
    deltaF_F = compute_dff(clean_trace, clean_baseline)
    print(f"ΔF/F0 computed. Final ROIs: {deltaF_F.shape[1]}")

    # Reconstruct final ROI indices relative to full Suite2p list
    original_indices = np.where(iscell_mask)[0]
    retained_indices = original_indices[bright_rois_mask]
    final_indices = retained_indices[stable_rois_mask] # filtered list of Suite2p ROI indices

    return deltaF_F, final_indices

if __name__ == "__main__":

    # Parameters
    #base_data_path = Path("D:/Matilde/2p_data/LR_thalamus_bout_exp01")
    #base_data_path = Path("/Volumes/LAB-MATI/Lausanne/2p/speed_groupsize_thalamus_exp03")
    base_data_path = Path("F:/Matilde/2p_data")
    fish_selected = ['L500_f01']  # List of fish numbers to process

    n_planes = 5
    fps = 2.0 # Imaging rate in Hz
    tau = 6.0 # GCaMP6s decay time (sec)
    percentile = 8 # Percentile for baseline (e.g. 8th)
    instability_ratio = 0.1 # Baseline instability check (10× drop = 0.1)


    for fish in fish_selected:
        fish_folder = base_data_path / fish
        s2p_folder = fish_folder / "03_analysis/functional/suite2P"
        print(f"\n🔍 Processing {fish} in {s2p_folder}")

        for i in range(n_planes):
            print(f"\n📦 Processing plane {i}")
            plane_path = s2p_folder / f"plane{i}"
            if (plane_path / f"{fish}_F.npy").exists():
                deltaF_F, final_indices = process_suite2p_fluorescence(
                    fish,
                    plane_path,
                    fps,
                    tau,
                    percentile=percentile,
                    instability_ratio=instability_ratio
                )

                # ---- Save outputs to 05_dff/plane{i} ----
                out_dir = s2p_folder.parent / "dFoF" / f"plane{i}"
                out_dir.mkdir(parents=True, exist_ok=True)

                # Save arrays
                np.save(out_dir / f"{fish}_dFoF.npy", deltaF_F)  # shape T x N_final
                np.save(out_dir / f"{fish}_filtered_roi_indices.npy", final_indices)

                # Save minimal metadata
                meta = {
                    "fish_id": fish,
                    "plane_index": i,
                    "source_folder": str(f_path),
                    "params": {
                        "fps": fps,
                        "tau": tau,
                        "percentile": percentile,
                        "instability_ratio": instability_ratio
                    },
                    "shapes": {
                        "dFoF_TxN": [int(deltaF_F.shape[0]), int(deltaF_F.shape[1])],
                        "roi_indices_len": int(len(final_indices))
                    },
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                with (out_dir / "meta.json").open("w", encoding="utf-8") as f:
                    import json

                    json.dump(meta, f, indent=2)

                print(f"Saved to {out_dir}")
                # -----------------------------------------

            else:
                print(f"  ❌ File not found: {f_path}")