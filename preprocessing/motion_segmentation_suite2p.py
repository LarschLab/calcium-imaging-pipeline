import suite2p
from pathlib import Path
import numpy as np
import shutil
import time
import copy
import re
import gc
import tifffile as tf

def get_file_index(path: Path) -> int:
    """Extract numeric index from filenames like 'file005000_chan0.tif'."""
    match = re.search(r"file(\d+)", path.name)
    if match:
        return int(match.group(1))
    return -1  # fallback if pattern not found

def join_reg_tiffs_to_one(reg_folder: Path, out_tiff: Path):
    """
    Join Suite2p motion-corrected chunks into a single BigTIFF.

    - Read all `file*_chan0.tif` in `reg_folder` (sorted)
    - Append frames to one output stack at `out_tiff`
    - Overwrite existing file if present

    Parameters:
    - reg_folder (Path): Folder with Suite2p `reg_tif` chunks
    - out_tiff (Path): Output path for the merged TIFF stack
    """
    tiff_files = sorted(reg_folder.glob("file*_chan0.tif"), key=get_file_index)

    # Ensure the destination directory exists (create parents as needed)
    out_tiff.parent.mkdir(parents=True, exist_ok=True)

    # If an output file already exists, remove it so we overwrite cleanly
    if out_tiff.exists():
        out_tiff.unlink()

    # Open a writer for the output stack; BigTIFF handles >4 GB files safely
    with tf.TiffWriter(out_tiff, bigtiff=True) as tw:
        for f in tiff_files:
            with tf.TiffFile(f) as tif:
                for page in tif.pages:
                    tw.write(page.asarray(), contiguous=True)

    print(f"✅ Wrote joined stack: {out_tiff}")

def move_processed_files(plane_idx, analysis_s2p_folder, mcorrected_folder, fish_id):
    """
    Move Suite2p outputs into organized folders:
    - Move registered TIFF chunks into the motion-corrected folder
    - Move segmentation .npy files into a plane-specific subfolder

    Parameters:
    - plane_idx (int): Plane index currently processed
    - analysis_s2p_folder (Path): Suite2p output base folder
    - mcorrected_folder (Path): Destination folder for motion-corrected TIFF files
    """

    # Path to the reg folder with TIFF files
    reg_folder = analysis_s2p_folder / f"suite2p/plane0/reg_tif"

    if not reg_folder.exists():
        print(f"⚠️ Registered folder not found for plane {plane_idx} in {reg_folder}")
        return

    out_tiff = mcorrected_folder / f"{fish_id}_plane{plane_idx}_mcorrected.tif"

    join_reg_tiffs_to_one(reg_folder, out_tiff)

    # Move segmentation .npy files
    s2p_folder = analysis_s2p_folder / "suite2p/plane0"
    destination = analysis_s2p_folder / f"plane{plane_idx}"
    destination.mkdir(exist_ok=True)

    for seg_file in sorted(s2p_folder.glob('*.npy')):
        new_name = f"{fish_id}_plane{plane_idx}_{seg_file.name}"
        dest_file = destination / new_name
        if dest_file.exists():
            dest_file.unlink()
        shutil.move(str(seg_file), str(dest_file))
        print(f"✅ Moved {seg_file.name} → {dest_file}")

    # Clean up Suite2p temporary folder
    shutil.rmtree(analysis_s2p_folder / "suite2p")

    return destination

def run_suite2p(plane_file, global_ops, save_path0, fps, fast_disk=None):
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
    ops['save_path0'] = str(save_path0)
    ops['keep_movie_raw'] = False
    ops['delete_bin'] = True

    if fast_disk is not None:
        ops['fast_disk'] = str(fast_disk)

    ops['batch_size'] = 500 #if n_frames > 500 else n_frames

    suite2p.run_s2p(ops=ops)
    gc.collect()


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


def process_fish(fish_folder, global_ops, selected_planes, fps, fast_disk=None, storage_root=None):
    """
    Process Suite2p registration and segmentation for all selected planes of one fish.

    Parameters:
    - fish_folder (Path): Folder of one fish (base directory)
    - global_ops (dict): Suite2p ops loaded from disk
    - selected_planes (list[int]): Plane indices to process
    - fps (float) : framerate
    - fast_disk (str or Path or None): Optional fast disk path for Suite2p temporary files
    - storage_root (str or Path or None): Optional root path where final outputs will be copied (mirror)
    """
    pre_dir = fish_folder / "02_reg/00_preprocessing/2p_functional/01_individualPlanes"
    if not pre_dir.exists():
        print(f"⚠️ Skipping {fish_folder.name}: no 'preprocessed' folder found.")
        return

    # Create output folders for motion-corrected files and segmentation
    mcorrected_folder = fish_folder / "02_reg/00_preprocessing/2p_functional/02_motionCorrected"
    analysis_s2p_folder = fish_folder / "03_analysis/functional/suite2P"

    mcorrected_folder.mkdir(parents=True, exist_ok=True)
    analysis_s2p_folder.mkdir(parents=True, exist_ok=True)

    print(f"Created folders: {mcorrected_folder}, {analysis_s2p_folder}")

    for plane_idx in selected_planes:
        # Look for TIFF file corresponding to current plane
        plane_file = find_plane_file(pre_dir, plane_idx)
        if plane_file is None:
            print(f"⚠️ Plane {plane_idx} not found.")
            continue
        print(f"Processing plane {plane_idx} → {plane_file.name}")
        run_suite2p(plane_file, global_ops, analysis_s2p_folder, fps, fast_disk)
        src_folder = move_processed_files(plane_idx, analysis_s2p_folder, mcorrected_folder, fish_folder.name)
        
        if storage_root is not None and src_folder:
            storage_root_p = Path(storage_root)
            storage_fish_base = storage_root_p / fish_folder.name

            rel_folder = src_folder.relative_to(fish_folder)
            dst_folder = storage_fish_base / rel_folder
            dst_folder.mkdir(parents=True, exist_ok=True)
            for f in src_folder.iterdir():
                if f.is_file():
                    dst_file = dst_folder / f.name
                    shutil.copy2(str(f), str(dst_file))
                    print(f"📁 Mirrored segmentation file: {f} → {dst_file}")
        
        gc.collect()


def batch_process(data_root, ops_path, fps, fish_ids=None, selected_planes=None, fast_disk=None):
    """
    Process multiple fish folders.

    Parameters:
    - data_root (Path): Root directory containing all fish folders
    - ops_path (Path): Path to Suite2p ops file (saved as .npy dictionary)
    - storage_root (Path): Root folder where outputs will be mirrored/copied
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
        process_fish(fish_folder, global_ops, selected_planes, fps, fast_disk, storage_root=storage_root)
        elapsed = time.time() - start_time
        print(f"⏱️ Finished processing {fish_folder.name} in {elapsed / 60:.2f} min.\n")

if __name__ == "__main__":

    data_root = "F:/Matilde/2p_data"
    storage_root = "Z:/D2c/07_Data/Matilde/Microscopy"  # Root folder for data storage

    ops_file_path = data_root + "/suite2p_ops_sep_2025_cp.npy"    # global Suite2p ops file

    #selected_fish = np.arange(11,12)  # Fish IDs to process
    fish_to_process = ["L500_f01"]  # Fish IDs to process
    planes_to_process = [0, 1, 2, 3, 4]  # Planes to process
    fps = 2

    fast_disk_path = Path("F:/Matilde")  # Optional fast disk path

    batch_process(
        data_root,
        ops_file_path,
        storage_root,
        fps,
        fish_ids=fish_to_process,
        selected_planes=planes_to_process,
        fast_disk=fast_disk_path)
