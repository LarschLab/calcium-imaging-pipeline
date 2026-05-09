import suite2p
from pathlib import Path, PureWindowsPath
import numpy as np
import shutil
import time
import copy
import re
import gc
import inspect
import os
import tifffile as tf

FORCE_CPU_ENV_VAR = "CALCIUM_SUITE2P_FORCE_CPU"
DEFAULT_CELLPOSE_MODEL = r"D:\cellpose\models\2pf_cpsam_20250915_134652"
DEFAULT_CELLPOSE_MODEL_NAME = PureWindowsPath(DEFAULT_CELLPOSE_MODEL).name
DEFAULT_CELLPOSE_MODEL_LOCAL_CANDIDATES = (
    Path.home() / "dataProcessing/2p_processing/cellpose/models" / DEFAULT_CELLPOSE_MODEL_NAME,
)
DEFAULT_CELLPOSE_ANATOMICAL_ONLY = 2

def force_cpu_requested():
    """
    Return whether Suite2P/Cellpose should be forced onto CPU.
    """
    return os.environ.get(FORCE_CPU_ENV_VAR, "").strip().lower() in {"1", "true", "yes", "on"}

def best_available_torch_device():
    """
    Return the best torch device available to Suite2P on this machine.
    """
    try:
        import torch
    except Exception:
        return "cpu"

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"

def patch_cellpose_cpu_only():
    """
    Patch Cellpose GPU detection for legacy Suite2P CPU replay.
    """
    from cellpose import core

    core.use_gpu = lambda *args, **kwargs: False

def patch_suite2p_mps_float64_ops():
    """
    Patch Suite2P's MPS-incompatible float64 taper mask construction.
    """
    import torch
    from suite2p.registration import rigid, utils

    def spatial_taper_float32(sig, Ly, Lx):
        y = torch.arange(0, Ly, dtype=torch.float32)
        x = torch.arange(0, Lx, dtype=torch.float32)
        x = (x - x.mean()).abs()
        y = (y - y.mean()).abs()
        mY = ((Ly - 1) / 2) - 2 * sig
        mX = ((Lx - 1) / 2) - 2 * sig
        maskY = 1.0 / (1.0 + torch.exp((y - mY) / sig))
        maskX = 1.0 / (1.0 + torch.exp((x - mX) / sig))
        return maskY[:, None] * maskX

    utils.spatial_taper = spatial_taper_float32
    rigid.spatial_taper = spatial_taper_float32

def patch_suite2p_no_neuropil_extract():
    """
    Preserve legacy Suite2P behavior when neuropil extraction is disabled.
    """
    import torch
    import suite2p.extraction as extraction_package
    from suite2p.extraction import extract

    if getattr(extract.extraction_wrapper, "_calcium_no_neuropil_patch", False):
        return

    original_extraction_wrapper = extract.extraction_wrapper

    def extract_cell_traces(f_in, cell_masks, batch_size=500, device=torch.device("cuda")):
        n_frames, Ly, Lx = f_in.shape
        if device.type == "mps":
            device = torch.device("cpu")

        ccol_indices = [m for cm in cell_masks for m in cm[0]]
        row_indices = [k for k in range(len(cell_masks)) for _m in cell_masks[k][0]]
        cell_lam = torch.Tensor([l for cm in cell_masks for l in cm[1]]).to(device)
        inds = torch.Tensor([ccol_indices, row_indices]).to(device)
        cmasks = torch.sparse_coo_tensor(inds, cell_lam, size=(Ly * Lx, len(cell_masks)))
        cmasks = cmasks.to_sparse_csc()

        F = np.zeros((len(cell_masks), n_frames), np.float32)
        batch_size = min(int(batch_size), 1000)
        for start in range(0, n_frames, batch_size):
            end = min(start + batch_size, n_frames)
            data = torch.from_numpy(f_in[start:end]).to(device)
            data = data.reshape(-1, Ly * Lx).float()
            F[:, start:end] = (data @ cmasks).T.cpu().numpy()
        return F

    def extraction_wrapper_no_neuropil(
        stat,
        f_reg,
        f_reg_chan2=None,
        cell_masks=None,
        neuropil_masks=None,
        settings=None,
        device=torch.device("cuda"),
    ):
        if settings is None or settings.get("neuropil_extract", True):
            return original_extraction_wrapper(
                stat,
                f_reg,
                f_reg_chan2=f_reg_chan2,
                cell_masks=cell_masks,
                neuropil_masks=neuropil_masks,
                settings=settings,
                device=device,
            )

        n_frames, Ly, Lx = f_reg.shape
        if cell_masks is None:
            cell_masks, _unused = extract.create_masks(
                stat,
                Ly,
                Lx,
                lam_percentile=settings["lam_percentile"],
                allow_overlap=settings["allow_overlap"],
                neuropil_extract=False,
                inner_neuropil_radius=settings["inner_neuropil_radius"],
                min_neuropil_pixels=settings["min_neuropil_pixels"],
                circular_neuropil=settings["circular_neuropil"],
            )

        F = extract_cell_traces(f_reg, cell_masks, batch_size=settings["batch_size"], device=device)
        Fneu = np.zeros((len(cell_masks), n_frames), np.float32)
        if f_reg_chan2 is not None:
            F_chan2 = extract_cell_traces(f_reg_chan2, cell_masks, batch_size=settings["batch_size"], device=device)
            Fneu_chan2 = np.zeros((len(cell_masks), f_reg_chan2.shape[0]), np.float32)
        else:
            F_chan2, Fneu_chan2 = None, None
        return F, Fneu, F_chan2, Fneu_chan2

    extraction_wrapper_no_neuropil._calcium_no_neuropil_patch = True
    extract.extraction_wrapper = extraction_wrapper_no_neuropil
    extraction_package.extraction_wrapper = extraction_wrapper_no_neuropil

def suite2p_uses_legacy_ops_api():
    signature = inspect.signature(suite2p.run_s2p)
    return "ops" in signature.parameters

def apply_legacy_cellpose_settings_to_current(settings, ops):
    """
    Map legacy Suite2P Cellpose ops into current Suite2P nested settings.
    """
    detection = settings.get("detection")
    if not isinstance(detection, dict):
        return settings

    cellpose_settings = detection.setdefault("cellpose_settings", {})
    anatomical_only = int(ops.get("anatomical_only", 0) or 0)
    if anatomical_only > 0:
        detection["algorithm"] = "cellpose"
        cellpose_settings["img"] = {
            1: "max_proj / meanImg",
            2: "meanImg",
            3: "meanImg",
            4: "max_proj",
        }.get(anatomical_only, cellpose_settings.get("img", "max_proj / meanImg"))

    if ops.get("pretrained_model"):
        cellpose_settings["cellpose_model"] = str(ops["pretrained_model"])
    if "flow_threshold" in ops:
        cellpose_settings["flow_threshold"] = ops["flow_threshold"]
    if "cellprob_threshold" in ops:
        cellpose_settings["cellprob_threshold"] = ops["cellprob_threshold"]
    if "spatial_hp_cp" in ops:
        cellpose_settings["highpass_spatial"] = ops["spatial_hp_cp"]
    return settings

def resolve_default_cellpose_model(plane_file=None):
    """
    Resolve the historical default model name to a local Cellpose model file.
    """
    candidates = []
    if plane_file is not None:
        for parent in Path(plane_file).resolve().parents:
            candidates.append(parent / "cellpose/models" / DEFAULT_CELLPOSE_MODEL_NAME)
    candidates.extend(DEFAULT_CELLPOSE_MODEL_LOCAL_CANDIDATES)

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return DEFAULT_CELLPOSE_MODEL


def apply_default_cellpose_model(ops, plane_file=None):
    """
    Force the pipeline's default Cellpose model before Suite2P receives ops.
    """
    ops["pretrained_model"] = resolve_default_cellpose_model(plane_file)
    ops["anatomical_only"] = DEFAULT_CELLPOSE_ANATOMICAL_ONLY
    return ops

def get_file_index(path: Path) -> int:
    """Extract numeric index from filenames like 'file005000_chan0.tif'."""
    match = re.search(r"file\s*(\d+)", path.name)
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
    tiff_files = sorted(reg_folder.glob("file*.tif"), key=get_file_index)
    if not tiff_files:
        raise FileNotFoundError(f"No registered TIFF chunks found in {reg_folder}")

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

def _run_s2p_with_runtime_ops(ops):
    if suite2p_uses_legacy_ops_api():
        if force_cpu_requested():
            patch_cellpose_cpu_only()
        suite2p.run_s2p(ops=ops)
        return

    from suite2p.parameters import convert_settings_orig

    db, settings, _unused = convert_settings_orig(
        copy.deepcopy(ops),
        db=suite2p.default_db(),
        settings=suite2p.default_settings(),
    )
    apply_legacy_cellpose_settings_to_current(settings, ops)
    settings["io"]["delete_bin"] = True
    settings["registration"]["reg_tif"] = True
    settings["registration"]["batch_size"] = 500
    settings["extraction"]["batch_size"] = 500
    if force_cpu_requested():
        settings["torch_device"] = "cpu"
        patch_cellpose_cpu_only()
    if settings.get("torch_device") == "mps":
        patch_suite2p_mps_float64_ops()
    if not settings["extraction"].get("neuropil_extract", True):
        patch_suite2p_no_neuropil_extract()
    suite2p.run_s2p(db=db, settings=settings)

def normalize_runtime_ops(ops):
    """
    Normalize runtime Suite2P ops values that are invalid for current Suite2P.
    """
    requested_device = str(ops.get("torch_device", "cuda")).lower()
    if requested_device != "cpu":
        ops["torch_device"] = best_available_torch_device()
    if ops.get("do_bidiphase") and int(ops.get("bidiphase", 0)) == 0:
        ops["do_bidiphase"] = False
    if "two_step_registration" in ops:
        ops["two_step_registration"] = bool(ops["two_step_registration"])
    if np.isscalar(ops.get("diameter")) and float(ops["diameter"]) <= 0:
        ops["diameter"] = [12.0, 12.0]
    return ops

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
    plane_file = Path(plane_file)
    ops = copy.deepcopy(global_ops)
    ops['input_format'] = 'tif'
    ops['fs'] = fps
    ops['tiff_list'] = [str(plane_file)]
    ops['data_path'] = [str(plane_file.parent)]
    ops['filelist'] = [str(plane_file)]
    ops['file_list'] = [plane_file.name]
    ops['save_path0'] = str(save_path0)
    ops['save_folder'] = "suite2p"
    ops['keep_movie_raw'] = False
    ops['delete_bin'] = True
    apply_default_cellpose_model(ops, plane_file)
    print(f"[Suite2P] Cellpose model: {ops['pretrained_model']}", flush=True)

    if fast_disk is not None:
        ops['fast_disk'] = str(fast_disk)

    ops['batch_size'] = 500 #if n_frames > 500 else n_frames
    if force_cpu_requested() and not suite2p_uses_legacy_ops_api():
        ops["torch_device"] = "cpu"
    if not suite2p_uses_legacy_ops_api():
        normalize_runtime_ops(ops)

    _run_s2p_with_runtime_ops(ops)
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


def batch_process(data_root, ops_path, fps, fish_ids=None, selected_planes=None, fast_disk=None, storage_root=None, selected_planes_by_fish=None):
    """
    Process multiple fish folders.

    Parameters:
    - data_root (Path): Root directory containing all fish folders
    - ops_path (Path): Path to Suite2p ops file (saved as .npy dictionary)
    - storage_root (Path): Root folder where outputs will be mirrored/copied
    - fish_ids (list[str] or None): List of fish folder names to process (or all if None)
    - selected_planes (list[int]): Plane indices to process
    - fast_disk (str or Path or None): Optional fast disk path for Suite2p temporary files
    - storage_root (str or Path or None): Optional root folder where outputs will be mirrored/copied
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
        planes_for_fish = selected_planes
        if selected_planes_by_fish is not None:
            planes_for_fish = selected_planes_by_fish.get(fish_folder.name, selected_planes)
        process_fish(fish_folder, global_ops, planes_for_fish, fps, fast_disk, storage_root=storage_root)
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
        fps,
        fish_ids=fish_to_process,
        selected_planes=planes_to_process,
        fast_disk=fast_disk_path,
        storage_root=storage_root)
