import suite2p
from pathlib import Path
import numpy as np
import shutil
import time
import copy
import re
import tifffile as tf


def move_processed_files(plane_idx, segmented_folder, mcorrected_folder):
    """
    Move Suite2p outputs into organized folders:
    - Move registered TIFF chunks into the motion-corrected folder
    - Move segmentation .npy files into a plane-specific subfolder

    Parameters:
    - plane_idx (int): Plane index currently processed
    - segmented_folder (Path): Suite2p output base folder
    - mcorrected_folder (Path): Destination folder for motion-corrected TIFF files
    """

    # Path to the reg folder with TIFF files
    reg_folder = segmented_folder / f"suite2p/plane0/reg_tif"

    if not reg_folder.exists():
        print(f"⚠️ Registered folder not found for plane {plane_idx} in {reg_folder}")
        return

    fish_id = segmented_folder.parent.name

    # Move registered TIFF chunks
    for tiff_file in sorted(reg_folder.glob("file*_chan0.tif")):
        new_name = f"{fish_id}_plane{plane_idx}_mcorrected.tif"
        dest_file = mcorrected_folder / new_name
        if dest_file.exists():
            dest_file.unlink()
        shutil.move(str(tiff_file), str(dest_file))
        print(f"✅ Moved {tiff_file.name} → {dest_file.name}")

    # Move segmentation .npy files
    s2p_folder = segmented_folder / "suite2p/plane0"
    destination = segmented_folder / f"plane{plane_idx}"
    destination.mkdir(exist_ok=True)
    for seg_file in sorted(s2p_folder.glob('*.npy')):
        dest_file = destination / seg_file.name
        if dest_file.exists():
            dest_file.unlink()
        shutil.move(str(seg_file), str(dest_file))
        print(f"✅ Moved {seg_file.name} → {dest_file}")

    # Clean up Suite2p temporary folder
    shutil.rmtree(segmented_folder / "suite2p")

def run_suite2p(plane_file, global_ops, segmented_folder, fps, fast_disk=None):
    """
    Prepare and run Suite2p segmentation on a single TIFF file.

    Parameters:
    - plane_file (Path): TIFF file to process
    - global_ops (dict): Suite2p ops loaded from file
    - segmented_folder (Path): Destination for Suite2p output
    - fps (float) : framerate
    - fast_disk (str or Path or None): Optional fast disk path for Suite2p temporary files
    """
    ops = copy.deepcopy(global_ops)
    ops['input_format'] = 'tif'
    ops['fs'] = fps
    ops['tiff_list'] = [plane_file]
    ops['data_path'] = [str(plane_file.parent)]
    ops['save_path0'] = str(segmented_folder)
    ops['keep_movie_raw'] = False

    if fast_disk is not None:
        ops['fast_disk'] = str(fast_disk)

    # Automatically set batch_size to total number of frames in TIFF
    with tf.TiffFile(plane_file) as tif:
        n_frames = len(tif.pages)
    ops['batch_size'] = n_frames

    suite2p.run_s2p(ops=ops)


def find_plane_file(pre_dir, plane_idx):
    """
    Find the preprocessed TIFF file for a specific plane index.

    Parameters:
    - pre_dir (Path): Folder containing preprocessed TIFF files
    - plane_idx (int): Plane index to find

    Returns:
    - Path or None: Path to matching TIFF file, or None if not found
    """
    candidates = list(pre_dir.glob(f"*plane{plane_idx}.tif"))
    if len(candidates) == 0:
        return None
    elif len(candidates) > 1:
        print(f"⚠️ Multiple files found for plane {plane_idx}")
    return candidates[0]


def process_fish(fish_folder, global_ops, selected_planes, fps, fast_disk=None):
    """
    Process Suite2p registration and segmentation for all selected planes of one fish.

    Parameters:
    - fish_folder (Path): Folder of one fish (base directory)
    - global_ops (dict): Suite2p ops loaded from disk
    - selected_planes (list[int]): Plane indices to process
    - fps (float) : framerate
    - fast_disk (str or Path or None): Optional fast disk path for Suite2p temporary files
    """
    pre_dir = fish_folder / "02_preprocessed"
    if not pre_dir.exists():
        print(f"⚠️ Skipping {fish_folder.name}: no 'preprocessed' folder found.")
        return

    # Create output folders for motion-corrected files and segmentation
    mcorrected_folder = fish_folder / "03_motion_corrected"
    segmented_folder = fish_folder / "04_segmented"
    mcorrected_folder.mkdir(exist_ok=True)
    segmented_folder.mkdir(exist_ok=True)

    print(f"Created folders: {mcorrected_folder}, {segmented_folder}")

    for plane_idx in selected_planes:
        # Look for TIFF file corresponding to current plane
        plane_file = find_plane_file(pre_dir, plane_idx)
        if plane_file is None:
            print(f"⚠️ Plane {plane_idx} not found.")
            continue
        print(f"Processing plane {plane_idx} → {plane_file.name}")
        run_suite2p(plane_file, global_ops, segmented_folder, fps, fast_disk)
        move_processed_files(plane_idx, segmented_folder, mcorrected_folder)


def batch_process(data_root, ops_path, fps, fish_ids=None, selected_planes=None, fast_disk=None):
    """
    Process multiple fish folders.

    Parameters:
    - data_root (Path): Root directory containing all fish folders
    - ops_path (Path): Path to Suite2p ops file (saved as .npy dictionary)
    - fish_ids (list[str] or None): List of fish folder names to process (or all if None)
    - selected_planes (list[int]): Plane indices to process
    - fast_disk (str or Path or None): Optional fast disk path for Suite2p temporary files
    """
    data_root = Path(data_root)
    global_ops = np.load(ops_path, allow_pickle=True).item()

    for fish_folder in data_root.iterdir():
        if not fish_folder.is_dir():
            continue
        if fish_ids is not None and fish_folder.name not in fish_ids:
            continue

        start_time = time.time()
        print(f"\n📂 Processing fish: {fish_folder.name}")
        process_fish(fish_folder, global_ops, selected_planes, fps, fast_disk)
        elapsed = time.time() - start_time
        print(f"⏱️ Finished processing {fish_folder.name} in {elapsed / 60:.2f} min.\n")

if __name__ == "__main__":

    data_root = "D:/Matilde/2p_data/speed_groupsize_thalamus_exp03"
    ops_file_path = data_root + "/suite2p_ops_may2025.npy"    # global Suite2p ops file

    selected_fish = [1]
    fish_to_process = [f"f{fish}" for fish in selected_fish]
    planes_to_process = [0, 1, 2, 3, 4]  # Planes to process
    fps = 2

    fast_disk_path = Path("E:/Matilde")  # Optional fast disk path

    batch_process(
        data_root,
        ops_file_path,
        fps,
        fish_ids=fish_to_process,
        selected_planes=planes_to_process,
        fast_disk=fast_disk_path)
