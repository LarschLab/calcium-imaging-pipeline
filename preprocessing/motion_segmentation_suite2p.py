"""Run Suite2P motion correction and optional NCC quality gating.

The historical all-in-one Suite2P path remains available.  The newer opt-in
path pauses after motion correction, checks functional planes against anatomy,
and then either continues or stops according to the selected gate mode.
"""

try:
    import suite2p
except ImportError:  # pragma: no cover - allows contract tests without Suite2P installed
    class _MissingSuite2P:
        """Delay the missing-Suite2P error until processing is actually requested."""

        def run_s2p(self, **_kwargs):
            """Explain that Suite2P must be installed before this stage can run.

            Args:
                **_kwargs: Ignored keyword arguments, accepted to match the
                    call signature of ``suite2p.run_s2p``.

            Returns:
                None: This method always raises before returning.
            """
            raise ImportError("Suite2P is required to run registration/segmentation")

    suite2p = _MissingSuite2P()
from pathlib import Path
import numpy as np
import shutil
import time
import copy
import re
import gc
import json
import subprocess
import tifffile as tf

from preprocessing.spatial_preprocessing import (
    canonical_manifest_path,
    record_motion_corrected_output,
    validate_spatial_manifest,
)

NCC_GATE_MODES = {"report_only", "enforce"}


def validate_canonical_plane_input(fish_folder, plane_file):
    """Fail closed if Suite2P input is not declared canonical by the manifest.

    Args:
        fish_folder (Path): Folder of one fish (base directory) containing
            the canonical spatial manifest.
        plane_file (Path): Path to the plane TIFF file to check against the
            manifest's declared functional planes.

    Returns:
        dict: The validated canonical spatial manifest.
    """
    fish = Path(fish_folder)
    plane = Path(plane_file).resolve()
    manifest = validate_spatial_manifest(canonical_manifest_path(fish))
    declared = {
        Path(str(record.get("output_path"))).resolve()
        for record in manifest.get("functional_planes", [])
        if record.get("output_path")
    }
    if plane not in declared:
        raise ValueError(f"Suite2P input is not declared in the canonical spatial manifest: {plane}")
    return manifest

def get_file_index(path):
    """Extract numeric index from filenames like 'file005000_chan0.tif'.

    Args:
        path (Path): File path whose name contains the numeric index.

    Returns:
        int: The extracted index, or -1 if the filename does not match the
        expected pattern.
    """
    match = re.search(r"file(\d+)", path.name)
    if match:
        return int(match.group(1))
    return -1  # fallback if pattern not found

def join_reg_tiffs_to_one(reg_folder, out_tiff):
    """
    Join Suite2p motion-corrected chunks into a single BigTIFF.

    - Read all `file*_chan0.tif` in `reg_folder` (sorted)
    - Append frames to one output stack at `out_tiff`
    - Overwrite existing file if present

    Args:
        reg_folder (Path): Folder with Suite2p `reg_tif` chunks.
        out_tiff (Path): Output path for the merged TIFF stack.

    Returns:
        None: The merged TIFF stack is written to `out_tiff`.
    """
    tiff_files = sorted(reg_folder.glob("file*_chan0.tif"), key=get_file_index)

    # Ensure the destination directory exists (create parents as needed)
    out_tiff.parent.mkdir(parents=True, exist_ok=True)

    # Never overwrite an existing movie (process_fish skips planes that have one).
    if out_tiff.exists():
        raise FileExistsError(f"{out_tiff} already exists; delete it to rerun this plane.")

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

    Args:
        plane_idx (int): Plane index currently processed.
        analysis_s2p_folder (Path): Suite2p output base folder.
        mcorrected_folder (Path): Destination folder for motion-corrected TIFF files.
        fish_id (str): Fish identifier used to prefix moved filenames.

    Returns:
        Path or None: Folder containing the moved segmentation files, or None
        if the expected registered-TIFF folder was not found.
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
        if dest_file.exists():  # never overwrite existing results
            raise FileExistsError(f"{dest_file} already exists; delete it to rerun this plane.")
        shutil.move(str(seg_file), str(dest_file))
        print(f"✅ Moved {seg_file.name} → {dest_file}")

    # Clean up Suite2p's own temporary output folder: its results were moved out
    # above, and nothing else should be stored there.
    shutil.rmtree(analysis_s2p_folder / "suite2p")

    return destination

def run_suite2p(plane_file, global_ops, save_path0, fps, fast_disk=None):
    """
    Prepare and run Suite2p segmentation on a single TIFF file.

    Args:
        plane_file (Path): TIFF file to process.
        global_ops (dict): Suite2p ops loaded from file.
        save_path0 (Path): Destination folder for Suite2p output.
        fps (float): Framerate.
        fast_disk (str or Path or None): Optional fast disk path for Suite2p temporary files.

    Returns:
        None: Suite2p writes its outputs under `save_path0`.
    """
    ops = copy.deepcopy(global_ops)
    ops['input_format'] = 'tif'
    ops['fs'] = fps
    ops['tiff_list'] = [plane_file]
    ops['data_path'] = [str(plane_file.parent)]
    ops['save_path0'] = str(save_path0)
    ops['keep_movie_raw'] = False
    ops['delete_bin'] = True  # Suite2p deletes its temporary binary (data.bin) when done

    if fast_disk is not None:
        ops['fast_disk'] = str(fast_disk)

    ops['batch_size'] = 500 #if n_frames > 500 else n_frames

    suite2p.run_s2p(ops=ops)
    gc.collect()


def run_suite2p_registration_only(plane_file, global_ops, save_path0, fps, fast_disk=None):
    """Run Suite2P registration while retaining outputs for NCC and segmentation.

    This function is used only by the opt-in NCC-gated workflow. The historical
    ``run_suite2p`` path remains unchanged.

    Args:
        plane_file (Path): TIFF file to process.
        global_ops (dict): Suite2p ops loaded from file.
        save_path0 (Path): Destination folder for Suite2p registration output.
        fps (float): Framerate.
        fast_disk (str or Path or None): Optional fast disk path for Suite2p temporary files.

    Returns:
        Path: Folder containing the registered plane's Suite2p outputs
        (``save_path0/suite2p/plane0``).
    """
    ops = copy.deepcopy(global_ops)
    ops['input_format'] = 'tif'
    ops['fs'] = fps
    ops['tiff_list'] = [plane_file]
    ops['data_path'] = [str(plane_file.parent)]
    ops['save_path0'] = str(save_path0)
    ops['keep_movie_raw'] = False
    ops['delete_bin'] = False
    ops['reg_tif'] = True
    ops['roidetect'] = False
    ops['batch_size'] = 500
    if fast_disk is not None:
        ops['fast_disk'] = str(fast_disk)

    suite2p.run_s2p(ops=ops)
    plane_dir = Path(save_path0) / "suite2p" / "plane0"
    ops_path = plane_dir / "ops.npy"
    saved_ops = np.load(ops_path, allow_pickle=True).item() if ops_path.exists() else {}
    registered_binary = Path(saved_ops.get("reg_file", plane_dir / "data.bin"))
    required = (ops_path, registered_binary, plane_dir / "reg_tif")
    missing = [path for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"Suite2P registration-only outputs are incomplete: {missing}")
    gc.collect()
    return plane_dir


def resume_suite2p_segmentation(registered_plane_dir, *, delete_bin=True):
    """Run ROI detection/extraction from an existing Suite2P registration.

    Args:
        registered_plane_dir (Path): Folder containing a previously
            registered plane's Suite2p outputs (ops.npy and registered binary).
        delete_bin (bool): Whether to delete the registered binary file after
            segmentation completes.

    Returns:
        Path: The same `registered_plane_dir`, now also containing
        segmentation outputs (stat.npy, etc.).
    """
    from suite2p.run_s2p import run_plane

    plane_dir = Path(registered_plane_dir)
    ops_path = plane_dir / "ops.npy"
    if not ops_path.exists():
        raise FileNotFoundError(f"Cannot resume Suite2P segmentation from {plane_dir}")
    ops = np.load(ops_path, allow_pickle=True).item()
    binary_path = Path(ops.get("reg_file", plane_dir / "data.bin"))
    if not binary_path.exists():
        raise FileNotFoundError(f"Registered Suite2P binary is missing: {binary_path}")
    ops['do_registration'] = 0
    ops['roidetect'] = True
    ops['delete_bin'] = bool(delete_bin)
    run_plane(ops, ops_path=str(ops_path))
    if not (plane_dir / "stat.npy").exists():
        raise RuntimeError(f"Suite2P segmentation did not write stat.npy under {plane_dir}")
    gc.collect()
    return plane_dir


def move_segmentation_files(plane_idx, suite2p_plane_dir, analysis_s2p_folder, fish_id):
    """Move one registered plane's NPY outputs into the canonical fish folder.

    Args:
        plane_idx (int): Plane index currently processed.
        suite2p_plane_dir (Path): Folder containing the Suite2p plane outputs to move.
        analysis_s2p_folder (Path): Suite2p analysis base folder for this fish.
        fish_id (str): Fish identifier used to prefix moved filenames.

    Returns:
        Path: Destination folder containing the moved segmentation files.
    """
    source = Path(suite2p_plane_dir)
    destination = Path(analysis_s2p_folder) / f"plane{plane_idx}"
    destination.mkdir(parents=True, exist_ok=True)
    for seg_file in sorted(source.glob('*.npy')):
        new_name = f"{fish_id}_plane{plane_idx}_{seg_file.name}"
        dest_file = destination / new_name
        if dest_file.exists():  # never overwrite existing results
            raise FileExistsError(f"{dest_file} already exists; delete it to rerun this plane.")
        shutil.move(str(seg_file), str(dest_file))
        print(f"Moved {seg_file.name} -> {dest_file}")
    return destination


def _existing_plane_outputs(fish_folder, plane_idx):
    """List a plane's Suite2p results that already exist in the fish folder.

    Args:
        fish_folder (Path): Folder of one fish (base directory).
        plane_idx (int): Plane index.

    Returns:
        list: Paths of the plane's motion-corrected movie and ROI `.npy`
        files that already exist (empty if the plane hasn't been processed).
    """
    fish_folder = Path(fish_folder)
    movie = fish_folder / "02_reg/00_preprocessing/2p_functional/02_motionCorrected" / f"{fish_folder.name}_plane{plane_idx}_mcorrected.tif"
    roi_folder = fish_folder / "03_analysis/functional/suite2P" / f"plane{plane_idx}"
    existing_outputs = [movie] if movie.exists() else []
    if roi_folder.is_dir():
        existing_outputs += sorted(roi_folder.glob("*.npy"))
    return existing_outputs


def _report_skipped_plane(plane_idx, existing_outputs):
    """Print why a plane is skipped and how to rerun it.

    Args:
        plane_idx (int): Plane index.
        existing_outputs (list): Its results that already exist.

    Returns:
        None
    """
    listed = "\n    ".join(str(path) for path in existing_outputs)
    print(f"⚠️ Plane {plane_idx}: results already exist, so it is skipped (nothing is overwritten).\n"
          f"  To rerun this plane, delete these files first:\n    {listed}")


def mirror_results_to_storage(results_folder, fish_folder, storage_root):
    """Copy a plane's Suite2p results to the storage drive, never overwriting files there.

    The folder is copied to the same relative location under
    `storage_root/<fish>`. Files already on the drive are kept, with a
    warning, so a rerun can't silently replace stored results.

    Args:
        results_folder (Path): Local folder with the plane's result files.
        fish_folder (Path): Local folder of the fish (base directory).
        storage_root (str or Path): Root of the storage drive.

    Returns:
        None
    """
    results_folder = Path(results_folder)
    storage_folder = Path(storage_root) / Path(fish_folder).name / results_folder.relative_to(fish_folder)
    storage_folder.mkdir(parents=True, exist_ok=True)
    for result_file in results_folder.iterdir():
        if not result_file.is_file():
            continue
        storage_file = storage_folder / result_file.name
        if storage_file.exists():
            print(f"⚠️ Not copied, already on the storage drive (kept as is): {storage_file}\n"
                  f"  To replace it, delete it on the drive first.")
            continue
        shutil.copy2(str(result_file), str(storage_file))
        print(f"📁 Mirrored segmentation file: {result_file} → {storage_file}")


def find_plane_file(pre_dir, plane_idx):
    """
    Find the preprocessed TIFF file for a specific plane index.

    Args:
        pre_dir (Path): Folder containing preprocessed TIFF files.
        plane_idx (int): Plane index to find.

    Returns:
        Path or None: Path to matching TIFF file, or None if not found.
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

    Args:
        fish_folder (Path): Folder of one fish (base directory).
        global_ops (dict): Suite2p ops loaded from disk.
        selected_planes (list[int]): Plane indices to process.
        fps (float): Framerate.
        fast_disk (str or Path or None): Optional fast disk path for Suite2p temporary files.
        storage_root (str or Path or None): Optional root path where final outputs will be copied (mirror).

    Returns:
        None: Motion-corrected TIFFs and segmentation outputs are written
        under `fish_folder`, and optionally mirrored under `storage_root`.
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

    # Only fish from the canonical spatial workflow have a spatial preprocessing
    # manifest; plain (unflipped) fish are processed without the manifest checks.
    has_spatial_manifest = canonical_manifest_path(fish_folder).exists()

    for plane_idx in selected_planes:
        # Look for TIFF file corresponding to current plane
        plane_file = find_plane_file(pre_dir, plane_idx)
        if plane_file is None:
            print(f"⚠️ Plane {plane_idx} not found.")
            continue
        existing_outputs = _existing_plane_outputs(fish_folder, plane_idx)
        if existing_outputs:
            _report_skipped_plane(plane_idx, existing_outputs)
            continue
        if has_spatial_manifest:
            validate_canonical_plane_input(fish_folder, plane_file)
        print(f"Processing plane {plane_idx} → {plane_file.name}")
        run_suite2p(plane_file, global_ops, analysis_s2p_folder, fps, fast_disk)
        src_folder = move_processed_files(plane_idx, analysis_s2p_folder, mcorrected_folder, fish_folder.name)
        if has_spatial_manifest:
            record_motion_corrected_output(
                fish_folder,
                plane_index=plane_idx,
                output_path=mcorrected_folder / f"{fish_folder.name}_plane{plane_idx}_mcorrected.tif",
                suite2p_plane_dir=src_folder,
            )
        
        if storage_root is not None and src_folder:
            mirror_results_to_storage(src_folder, fish_folder, storage_root)
        
        gc.collect()


def process_fish_with_ncc_gate(
    fish_folder,
    global_ops,
    selected_planes,
    fps,
    *,
    fast_disk=None,
    storage_root=None,
    gate_mode="report_only",
    ncc_output_dir=None,
    ncc_workers=1,
    ncc_python=None,
):
    """Run registration, NCC QC, then optionally enforce the gate before segmentation.

    ``report_only`` always continues to segmentation and is intended for parity
    validation. ``enforce`` stops before segmentation unless NCC returns a
    ``pass_candidate``. Registered outputs are preserved when the gate stops.

    Args:
        fish_folder (Path): Folder of one fish (base directory).
        global_ops (dict): Suite2p ops loaded from disk.
        selected_planes (list[int]): Plane indices to process.
        fps (float): Framerate.
        fast_disk (str or Path or None): Optional fast disk path for Suite2p temporary files.
        storage_root (str or Path or None): Optional root path where final
            segmentation outputs will be copied (mirror) once the gate passes.
        gate_mode (str): Either "report_only" (always continue to
            segmentation) or "enforce" (stop before segmentation unless the
            NCC check returns "pass_candidate").
        ncc_output_dir (Path or None): Directory to write NCC validation
            outputs to. Defaults to a timestamped folder under `fish_folder`.
        ncc_workers (int): Number of worker processes to use for the NCC
            drift analysis.
        ncc_python (str or Path or None): Optional path to a Python
            interpreter used to run the NCC analysis as a subprocess. If
            None, the NCC analysis runs in-process.

    Returns:
        dict: Summary of the run, including "ncc_gate_mode", "ncc_manifest",
        "segmentation_ran", and either "registered_plane_dirs" (when the
        gate stopped before segmentation) or "segmentation_destinations"
        (when segmentation ran).
    """
    mode = str(gate_mode).strip().lower()
    if mode not in NCC_GATE_MODES:
        raise ValueError(f"gate_mode must be one of {sorted(NCC_GATE_MODES)}, got {gate_mode!r}")
    fish_folder = Path(fish_folder)
    pre_dir = fish_folder / "02_reg/00_preprocessing/2p_functional/01_individualPlanes"
    mcorrected_folder = fish_folder / "02_reg/00_preprocessing/2p_functional/02_motionCorrected"
    analysis_s2p_folder = fish_folder / "03_analysis/functional/suite2P"
    if not pre_dir.is_dir():
        raise FileNotFoundError(f"Missing preprocessed plane folder: {pre_dir}")
    mcorrected_folder.mkdir(parents=True, exist_ok=True)
    analysis_s2p_folder.mkdir(parents=True, exist_ok=True)
    gate_root = analysis_s2p_folder / "_ncc_gate_registration"
    if gate_root.exists():
        raise FileExistsError(f"NCC gate staging folder already exists: {gate_root}")

    registered_by_plane = {}
    for plane_idx in selected_planes:
        plane_file = find_plane_file(pre_dir, plane_idx)
        if plane_file is None:
            raise FileNotFoundError(f"Preprocessed plane {plane_idx} not found under {pre_dir}")
        existing_outputs = _existing_plane_outputs(fish_folder, plane_idx)
        if existing_outputs:
            _report_skipped_plane(plane_idx, existing_outputs)
            continue
        validate_canonical_plane_input(fish_folder, plane_file)
        stage_root = gate_root / f"plane{plane_idx}"
        plane_fast_disk = None
        if fast_disk is not None:
            plane_fast_disk = Path(fast_disk) / fish_folder.name / f"plane{plane_idx}"
            plane_fast_disk.mkdir(parents=True, exist_ok=True)
        print(f"Registration-only plane {plane_idx} -> {plane_file.name}")
        registered_plane_dir = run_suite2p_registration_only(
            plane_file,
            global_ops,
            stage_root,
            fps,
            plane_fast_disk,
        )
        registered_by_plane[int(plane_idx)] = registered_plane_dir
        join_reg_tiffs_to_one(
            registered_plane_dir / "reg_tif",
            mcorrected_folder / f"{fish_folder.name}_plane{plane_idx}_mcorrected.tif",
        )
        record_motion_corrected_output(
            fish_folder,
            plane_index=plane_idx,
            output_path=mcorrected_folder / f"{fish_folder.name}_plane{plane_idx}_mcorrected.tif",
            suite2p_plane_dir=registered_plane_dir,
        )

    if ncc_output_dir is None:
        ncc_output_dir = (
            fish_folder
            / "03_analysis"
            / "functional"
            / "ncc"
            / "validation"
            / time.strftime("%Y%m%d-%H%M%S")
        )
    ncc_output_dir = Path(ncc_output_dir)
    if ncc_python is None:
        from preprocessing.drift_analysis import FunctionalAnatomyQCConfig, run_drift_analysis

        manifest = run_drift_analysis(
            fish_dir=fish_folder,
            output_dir=ncc_output_dir,
            config=FunctionalAnatomyQCConfig(workers=int(ncc_workers)),
        )
    else:
        command = [
            str(ncc_python),
            "-m",
            "preprocessing.drift_analysis_cli",
            "--fish-dir",
            str(fish_folder),
            "--output-dir",
            str(ncc_output_dir),
            "--workers",
            str(int(ncc_workers)),
        ]
        subprocess.run(
            command,
            cwd=str(Path(__file__).resolve().parent.parent),
            check=True,
        )
        manifest_path = ncc_output_dir / "functional_anatomy_qc_manifest.json"
        manifest = json.loads(manifest_path.read_text())
    print(f"NCC gate result: {manifest['status']}")
    if mode == "enforce" and manifest["status"] != "pass_candidate":
        print("NCC gate stopped before segmentation; registration outputs were preserved for review.")
        return {
            "ncc_gate_mode": mode,
            "ncc_manifest": manifest,
            "segmentation_ran": False,
            "registered_plane_dirs": {str(key): str(value) for key, value in registered_by_plane.items()},
        }

    destinations = {}
    for plane_idx, registered_plane_dir in sorted(registered_by_plane.items()):
        resume_suite2p_segmentation(registered_plane_dir, delete_bin=True)
        destination = move_segmentation_files(
            plane_idx,
            registered_plane_dir,
            analysis_s2p_folder,
            fish_folder.name,
        )
        record_motion_corrected_output(
            fish_folder,
            plane_index=plane_idx,
            output_path=mcorrected_folder / f"{fish_folder.name}_plane{plane_idx}_mcorrected.tif",
            suite2p_plane_dir=destination,
        )
        destinations[str(plane_idx)] = str(destination)
        if storage_root is not None:
            mirror_results_to_storage(destination, fish_folder, storage_root)
    # The staging folder only holds this run's temporary Suite2p files (results
    # were moved out above); nothing else should be stored there.
    if gate_root.exists():
        shutil.rmtree(gate_root)
    return {
        "ncc_gate_mode": mode,
        "ncc_manifest": manifest,
        "segmentation_ran": True,
        "segmentation_destinations": destinations,
    }


def batch_process(data_root, ops_path, fps, fish_ids=None, selected_planes=None, fast_disk=None, storage_root=None):
    """
    Process multiple fish folders.

    Args:
        data_root (Path): Root directory containing all fish folders.
        ops_path (Path): Path to Suite2p ops file (saved as .npy dictionary).
        fps (float): Framerate.
        fish_ids (list[str] or None): List of fish folder names to process (or all if None).
        selected_planes (list[int]): Plane indices to process.
        fast_disk (str or Path or None): Optional fast disk path for Suite2p temporary files.
        storage_root (str or Path or None): Optional root path where final
            outputs will be copied (mirror) for each processed fish.

    Returns:
        None: Each fish's motion-corrected TIFFs and segmentation outputs are
        written to disk, and optionally mirrored under `storage_root`.
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
        fps,
        fish_ids=fish_to_process,
        selected_planes=planes_to_process,
        fast_disk=fast_disk_path,
        storage_root=storage_root)
