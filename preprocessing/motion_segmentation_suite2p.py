"""Run the Suite2P step of the functional preprocessing: motion correction, then ROI segmentation, plane by plane.

For each functional plane recording of a fish, Suite2P first corrects the
motion, then finds the ROIs (cells) and extracts their fluorescence traces.
An optional Z-drift check can run in between: it compares the motion-corrected
recordings with the anatomy to see whether the imaged planes slowly moved in
depth during the experiment, and can stop before segmentation if they did.

Details:
- Works for fish preprocessed as recorded and for fish flipped into the
  canonical orientation. For flipped fish, it also confirms each recording is
  the flipped one listed in their spatial preprocessing manifest, and adds the
  motion-corrected recording to it. The Z-drift check needs a flipped fish.
- Outputs per plane: the motion-corrected recording and the Suite2P ROI files
  (stat, F, iscell, ...). Only the ROI files are copied to the storage drive.
- Planes that already have results are skipped, never overwritten.

Original workflow by Matilde Perrino; Danin Dharmaperwira added the Z-drift
check and the manifest checks (Aug 2026); both merged in this version (Oct 2026).
"""

import argparse
import copy
import gc
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
import tifffile as tf

# Suite2P is a heavy package, often installed only in its own environment. If it
# is missing, a stand-in is used, so this file can still be imported and its code checked
try:
    import suite2p
except ImportError:  # pragma: no cover
    class _MissingSuite2P:
        """Stand-in for `suite2p` when it isn't installed."""

        def run_s2p(self, **_kwargs):
            """Raise: Suite2P is needed to actually run registration/segmentation."""
            raise ImportError("Suite2P is required to run registration/segmentation")

    suite2p = _MissingSuite2P()

from preprocessing.spatial_preprocessing import (
    spatial_manifest_path,
    add_suite2p_record_to_manifest,
    validate_spatial_manifest,
)

DRIFT_CHECK_MODES = {"report_only", "enforce"}
MCORRECTED_MOVIE_NAME = "{fish_id}_plane{plane_idx}_mcorrected.tif"  # how motion-corrected recordings are named
SUITE2P_OUTPUT_FOLDER = "suite2p"  # the folder Suite2P writes into, inside its save path
SUITE2P_PLANE_SUBFOLDER = Path(SUITE2P_OUTPUT_FOLDER) / "plane0"  # Suite2P's outputs for the single plane it is given
REGISTERED_TIFF_FOLDER = "reg_tif"  # Suite2P's motion-corrected TIFF chunks, inside the plane subfolder
DRIFT_RESULTS_SUBFOLDER = Path("03_analysis/functional/ncc/validation")  # default drift results folder, inside the fish folder
# (used when the drift check runs from this step; drift_analysis.py has its own default for its own runs)


def check_plane_in_manifest(fish_folder, plane_file):
    """Fail closed if Suite2P input is not declared canonical by the manifest.

    Args:
        fish_folder (Path): Folder of one fish (base directory) containing
            the canonical spatial manifest.
        plane_file (Path): Path to the plane TIFF file to check against the
            manifest's declared functional planes.

    Returns:
        dict: The validated canonical spatial manifest.

    Raises:
        ValueError: If the plane recording isn't declared in the manifest.
    """
    fish = Path(fish_folder)
    plane = Path(plane_file).resolve()
    manifest = validate_spatial_manifest(spatial_manifest_path(fish))
    # The plane recordings the canonical workflow wrote (and flipped).
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
        file_index = int(match.group(1))
        return file_index
    return -1  # fallback if pattern not found

def join_registered_tiffs(reg_folder, out_tiff):
    """Join Suite2p's motion-corrected chunks into one BigTIFF recording.

    Reads every `file*_chan0.tif` in `reg_folder`, in file order, and appends
    their frames to `out_tiff`.

    Args:
        reg_folder (Path): Folder with Suite2p `reg_tif` chunks.
        out_tiff (Path): Output path for the merged TIFF stack.

    Returns:
        None: The merged TIFF stack is written to `out_tiff`.

    Raises:
        FileExistsError: If `out_tiff` already exists (never overwritten).
    """
    tiff_files = sorted(reg_folder.glob("file*_chan0.tif"), key=get_file_index)

    # Ensure the destination directory exists (create parents as needed)
    out_tiff.parent.mkdir(parents=True, exist_ok=True)

    # Never overwrite an existing movie (run_suite2p_for_fish skips planes that have one).
    if out_tiff.exists():
        raise FileExistsError(f"{out_tiff} already exists; delete it to rerun this plane.")

    # Open a writer for the output stack; BigTIFF handles >4 GB files safely
    with tf.TiffWriter(out_tiff, bigtiff=True) as tw:
        for f in tiff_files:
            with tf.TiffFile(f) as tif:
                for page in tif.pages:
                    tw.write(page.asarray(), contiguous=True)

    print(f"✅ Wrote joined stack: {out_tiff}")

def collect_suite2p_results(plane_idx, analysis_s2p_folder, mcorrected_folder, fish_id):
    """Collect a plane's Suite2p results into the standard folders, then clean up.

    Joins the motion-corrected TIFF chunks into one recording in
    `mcorrected_folder`, moves the ROI `.npy` files into `plane<i>/`, and
    removes Suite2p's temporary output folder.

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
    reg_folder = analysis_s2p_folder / SUITE2P_PLANE_SUBFOLDER / REGISTERED_TIFF_FOLDER

    if not reg_folder.exists():
        print(f"⚠️ Registered folder not found for plane {plane_idx} in {reg_folder}")
        return

    out_tiff = mcorrected_folder / MCORRECTED_MOVIE_NAME.format(fish_id=fish_id, plane_idx=plane_idx)

    join_registered_tiffs(reg_folder, out_tiff)
    # Move the segmentation .npy files into the plane's results folder.
    destination = move_segmented_rois(plane_idx, analysis_s2p_folder / SUITE2P_PLANE_SUBFOLDER, analysis_s2p_folder, fish_id)

    # Clean up Suite2p's own temporary output folder: its results were moved out
    # above, and nothing else should be stored there.
    shutil.rmtree(analysis_s2p_folder / SUITE2P_OUTPUT_FOLDER)

    return destination

def _suite2p_ops(global_ops, plane_file, save_path0, fps, fast_disk, **overrides):
    """Build the Suite2p settings for one plane TIFF: the shared ones plus the caller's own.

    Args:
        global_ops (dict): Suite2p ops loaded from file (not modified).
        plane_file (Path): TIFF file to process.
        save_path0 (Path): Destination folder for Suite2p output.
        fps (float): Framerate.
        fast_disk (str or Path or None): Optional fast disk path for Suite2p temporary files.
        **overrides: Settings specific to the caller (e.g. `delete_bin`, `reg_tif`).

    Returns:
        dict: The Suite2p ops for this plane.
    """
    ops = copy.deepcopy(global_ops)
    ops['input_format'] = 'tif'
    ops['fs'] = fps
    ops['tiff_list'] = [plane_file]
    ops['data_path'] = [str(plane_file.parent)]
    ops['save_path0'] = str(save_path0)
    ops['keep_movie_raw'] = False
    ops['batch_size'] = 500
    if fast_disk is not None:
        ops['fast_disk'] = str(fast_disk)
    ops.update(overrides)  # the caller's own settings
    return ops


def run_suite2p(plane_file, global_ops, save_path0, fps, fast_disk=None):
    """Run Suite2p (motion correction + ROI segmentation) on one plane TIFF.

    Args:
        plane_file (Path): TIFF file to process.
        global_ops (dict): Suite2p ops loaded from file.
        save_path0 (Path): Destination folder for Suite2p output.
        fps (float): Framerate.
        fast_disk (str or Path or None): Optional fast disk path for Suite2p temporary files.

    Returns:
        None: Suite2p writes its outputs under `save_path0`.
    """
    ops = _suite2p_ops(
        global_ops, plane_file, save_path0, fps, fast_disk,
        delete_bin=True,  # Suite2p deletes its temporary binary (data.bin) when done
    )
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

    Raises:
        RuntimeError: If Suite2P didn't write the ops, the registered binary or the TIFF chunks.
    """
    ops = _suite2p_ops(
        global_ops, plane_file, save_path0, fps, fast_disk,
        delete_bin=False,  # keep the registered binary for the later segmentation
        reg_tif=True,  # write the registered movie as TIFF chunks
        roidetect=False,  # registration only
    )
    suite2p.run_s2p(ops=ops)
    plane_dir = Path(save_path0) / SUITE2P_PLANE_SUBFOLDER
    ops_path = plane_dir / "ops.npy"
    saved_ops = np.load(ops_path, allow_pickle=True).item() if ops_path.exists() else {}
    registered_binary = Path(saved_ops.get("reg_file", plane_dir / "data.bin"))
    required = (ops_path, registered_binary, plane_dir / REGISTERED_TIFF_FOLDER)
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

    Raises:
        FileNotFoundError: If the saved ops or the registered binary are missing.
        RuntimeError: If Suite2P didn't write `stat.npy`.
    """
    # Imported here, not at the top, so the file still imports without Suite2P (see the top of the file).
    from suite2p.run_s2p import run_plane

    plane_dir = Path(registered_plane_dir)
    ops_path = plane_dir / "ops.npy"
    if not ops_path.exists():
        raise FileNotFoundError(f"Cannot resume Suite2P segmentation from {plane_dir}")
    ops = np.load(ops_path, allow_pickle=True).item()
    binary_path = Path(ops.get("reg_file", plane_dir / "data.bin"))
    if not binary_path.exists():
        raise FileNotFoundError(f"Registered Suite2P binary is missing: {binary_path}")
    # Reuse the saved registration: skip motion correction, run ROI detection only.
    ops['do_registration'] = 0
    ops['roidetect'] = True
    ops['delete_bin'] = bool(delete_bin)
    run_plane(ops, ops_path=str(ops_path))
    if not (plane_dir / "stat.npy").exists():
        raise RuntimeError(f"Suite2P segmentation did not write stat.npy under {plane_dir}")
    gc.collect()
    return plane_dir


def move_segmented_rois(plane_idx, suite2p_plane_dir, analysis_s2p_folder, fish_id):
    """Move one registered plane's NPY outputs into the canonical fish folder.

    Args:
        plane_idx (int): Plane index currently processed.
        suite2p_plane_dir (Path): Folder containing the Suite2p plane outputs to move.
        analysis_s2p_folder (Path): Suite2p analysis base folder for this fish.
        fish_id (str): Fish identifier used to prefix moved filenames.

    Returns:
        Path: Destination folder containing the moved segmentation files.

    Raises:
        FileExistsError: If a file already exists at the destination (never overwritten).
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
    _, mcorrected_folder, suite2p_folder = _fish_folders(fish_folder)
    movie = mcorrected_folder / MCORRECTED_MOVIE_NAME.format(fish_id=Path(fish_folder).name, plane_idx=plane_idx)
    roi_folder = suite2p_folder / f"plane{plane_idx}"
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
    # Same place relative to the fish folder, under storage_root/<fish>.
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
    """Find the preprocessed TIFF file for a specific plane index.

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
    plane_file = candidates[0]
    return plane_file


def _fish_folders(fish_folder):
    """Return a fish's standard Suite2P input and output folders.

    Args:
        fish_folder (Path): Folder of one fish (base directory).

    Returns:
        tuple: `(planes_folder, mcorrected_folder, suite2p_folder)` -- the
        preprocessed plane TIFFs, the motion-corrected movies, and the
        Suite2P results.
    """
    fish_folder = Path(fish_folder)
    planes_folder = fish_folder / "02_reg/00_preprocessing/2p_functional/01_individualPlanes"
    mcorrected_folder = fish_folder / "02_reg/00_preprocessing/2p_functional/02_motionCorrected"
    suite2p_folder = fish_folder / "03_analysis/functional/suite2P"
    return planes_folder, mcorrected_folder, suite2p_folder


def _planes_to_run(fish_folder, selected_planes, require_spatial_manifest):
    """Select the planes to process, skipping missing planes and planes with results.

    Missing folders or planes are skipped with a warning, so one bad item
    doesn't stop a batch. Planes are checked against the spatial
    preprocessing manifest when the fish has one, or always when required.

    Args:
        fish_folder (Path): Folder of one fish (base directory).
        selected_planes (list[int]): Plane indices requested.
        require_spatial_manifest (bool): Check every plane against the manifest
            (the drift check needs it); otherwise only if the fish has one.

    Returns:
        list: `(plane_idx, plane_file)` pairs to process.

    Raises:
        FileNotFoundError: If the manifest is required but missing.
        ValueError: If a plane isn't declared in the manifest.
    """
    planes_folder, mcorrected_folder, suite2p_folder = _fish_folders(fish_folder)
    if not planes_folder.is_dir():
        print(f"⚠️ Skipping {Path(fish_folder).name}: no preprocessed planes folder ({planes_folder}).")
        return []
    mcorrected_folder.mkdir(parents=True, exist_ok=True)
    suite2p_folder.mkdir(parents=True, exist_ok=True)
    # Only fish from the canonical spatial workflow have a spatial preprocessing manifest.
    check_manifest = require_spatial_manifest or spatial_manifest_path(fish_folder).exists()
    planes = []
    for plane_idx in selected_planes:
        plane_file = find_plane_file(planes_folder, plane_idx)
        if plane_file is None:
            print(f"⚠️ Plane {plane_idx} not found in {planes_folder}; skipping it.")
            continue
        existing_outputs = _existing_plane_outputs(fish_folder, plane_idx)
        if existing_outputs:
            _report_skipped_plane(plane_idx, existing_outputs)
            continue
        if check_manifest:
            check_plane_in_manifest(fish_folder, plane_file)
        planes.append((plane_idx, plane_file))
    return planes


def _finish_plane(fish_folder, plane_idx, results_folder, storage_root):
    """Record a finished plane in the spatial manifest (if any) and copy its results to storage.

    Args:
        fish_folder (Path): Folder of one fish (base directory).
        plane_idx (int): Plane index.
        results_folder (Path or None): Folder with the plane's ROI files; None
            if Suite2P produced none (nothing to record or copy).
        storage_root (str or Path or None): Storage drive root, or None.

    Returns:
        None
    """
    if results_folder is None:  # Suite2P produced no ROI files for this plane
        return
    if spatial_manifest_path(fish_folder).exists():  # canonical fish only
        add_suite2p_record_to_manifest(
            fish_folder,
            plane_index=plane_idx,
            output_path=_fish_folders(fish_folder)[1] / MCORRECTED_MOVIE_NAME.format(fish_id=Path(fish_folder).name, plane_idx=plane_idx),
            suite2p_plane_dir=results_folder,
        )
    if storage_root is not None:
        mirror_results_to_storage(results_folder, fish_folder, storage_root)


def run_suite2p_for_fish(
    fish_folder,
    global_ops,
    selected_planes,
    fps,
    *,
    fast_disk=None,
    storage_root=None,
    drift_check=None,
    drift_output_dir=None,
    drift_workers=1,
    drift_python=None,
):
    """Run Suite2P on a fish's planes, optionally checking Z drift before segmentation.

    Without `drift_check`, Suite2P runs once per plane (registration +
    segmentation). With it, every plane is registered first, the Z-drift
    check runs on the motion-corrected movies, and segmentation then resumes
    from the saved registration -- or, in "enforce" mode, stops unless the
    check returns "pass_candidate" (the registration is kept for review).

    Args:
        fish_folder (Path): Folder of one fish (base directory).
        global_ops (dict): Suite2P ops loaded from disk.
        selected_planes (list[int]): Plane indices to process.
        fps (float): Framerate.
        fast_disk (str or Path or None): Optional fast disk for Suite2P temporary
            files; each plane gets its own subfolder.
        storage_root (str or Path or None): Optional storage drive root where
            the ROI results are copied (existing files there are kept).
        drift_check (str or None): None (no drift check), "report_only" (check,
            always segment) or "enforce" (segment only after a passing check).
        drift_output_dir (str or Path or None): Folder for the drift outputs.
        drift_workers (int): Parallel workers for the drift check.
        drift_python (str or Path or None): Separate Python for the drift check.

    Returns:
        dict: `drift_check`, `drift_manifest` (drift result, or None),
        `segmentation_ran`, and `segmentation_destinations` (or
        `registered_plane_dirs` when the gate stopped).

    Raises:
        ValueError: If `drift_check` isn't None, "report_only" or "enforce".
        FileExistsError: If a previous gated run left its staging folder.
    """
    fish_folder = Path(fish_folder)
    mode = None if drift_check is None else str(drift_check).strip().lower()
    if mode is not None and mode not in DRIFT_CHECK_MODES:
        raise ValueError(f"drift_check must be None or one of {sorted(DRIFT_CHECK_MODES)}, got {drift_check!r}")
    _, mcorrected_folder, suite2p_folder = _fish_folders(fish_folder)
    gate_root = suite2p_folder / "_ncc_gate_registration"  # staging of the gated run's registrations
    if mode is not None and gate_root.exists():
        raise FileExistsError(f"NCC gate staging folder already exists: {gate_root}")
    planes = _planes_to_run(fish_folder, selected_planes, require_spatial_manifest=mode is not None)
    destinations = {}
    # TODO: the summary keys were renamed from "ncc_gate_mode" / "ncc_manifest" to
    # "drift_check" / "drift_manifest"; tell Danin in case his scripts read them.

    if mode is None:
        # One Suite2P run per plane: registration + segmentation.
        for plane_idx, plane_file in planes:
            print(f"Processing plane {plane_idx} → {plane_file.name}")
            # Each plane gets its own fast-disk folder, so planes never share Suite2P temporary files.
            plane_fast_disk = None if fast_disk is None else Path(fast_disk) / fish_folder.name / f"plane{plane_idx}"
            if plane_fast_disk is not None:
                plane_fast_disk.mkdir(parents=True, exist_ok=True)
            run_suite2p(plane_file, global_ops, suite2p_folder, fps, plane_fast_disk)
            results_folder = collect_suite2p_results(plane_idx, suite2p_folder, mcorrected_folder, fish_folder.name)
            _finish_plane(fish_folder, plane_idx, results_folder, storage_root)
            if results_folder is not None:
                destinations[str(plane_idx)] = str(results_folder)
            gc.collect()
        summary = {"drift_check": None, "drift_manifest": None, "segmentation_ran": True, "segmentation_destinations": destinations}
        return summary

    # 1. Register every plane and write its motion-corrected movie.
    registered_by_plane = {}
    for plane_idx, plane_file in planes:
        print(f"Registration-only plane {plane_idx} -> {plane_file.name}")
        # Each plane gets its own fast-disk folder, so planes never share Suite2P temporary files.
        plane_fast_disk = None if fast_disk is None else Path(fast_disk) / fish_folder.name / f"plane{plane_idx}"
        if plane_fast_disk is not None:
            plane_fast_disk.mkdir(parents=True, exist_ok=True)
        registered_plane_dir = run_suite2p_registration_only(
            plane_file, global_ops, gate_root / f"plane{plane_idx}", fps, plane_fast_disk,
        )
        registered_by_plane[int(plane_idx)] = registered_plane_dir
        movie_path = mcorrected_folder / MCORRECTED_MOVIE_NAME.format(fish_id=fish_folder.name, plane_idx=plane_idx)
        join_registered_tiffs(registered_plane_dir / REGISTERED_TIFF_FOLDER, movie_path)
        # The drift check only accepts movies declared in the manifest.
        add_suite2p_record_to_manifest(
            fish_folder,
            plane_index=plane_idx,
            output_path=movie_path,
            suite2p_plane_dir=registered_plane_dir,
        )
    # 2. Z-drift check on the motion-corrected movies, then the gate.
    manifest = _run_drift_check(fish_folder, drift_output_dir, drift_workers, drift_python)
    print(f"NCC gate result: {manifest['status']}")
    if mode == "enforce" and manifest["status"] != "pass_candidate":
        print("NCC gate stopped before segmentation; registration outputs were preserved for review.")
        summary = {
            "drift_check": mode,
            "drift_manifest": manifest,
            "segmentation_ran": False,
            "registered_plane_dirs": {str(key): str(value) for key, value in registered_by_plane.items()},
        }
        return summary
    # 3. Segment each plane from its saved registration.
    for plane_idx, registered_plane_dir in sorted(registered_by_plane.items()):
        resume_suite2p_segmentation(registered_plane_dir, delete_bin=True)
        results_folder = move_segmented_rois(plane_idx, registered_plane_dir, suite2p_folder, fish_folder.name)
        _finish_plane(fish_folder, plane_idx, results_folder, storage_root)
        destinations[str(plane_idx)] = str(results_folder)
    # The staging folder only holds this run's temporary Suite2P files (results
    # were moved out above); nothing else should be stored there.
    if gate_root.exists():
        shutil.rmtree(gate_root)
    summary = {"drift_check": mode, "drift_manifest": manifest, "segmentation_ran": True, "segmentation_destinations": destinations}
    return summary


def _run_drift_check(fish_folder, drift_output_dir, drift_workers, drift_python):
    """Run the Z-drift analysis on a fish's motion-corrected movies and return its result.

    Args:
        fish_folder (Path): Folder of one fish (base directory).
        drift_output_dir (str or Path or None): Folder for the drift outputs; None
            uses a new timestamped folder under `03_analysis/functional/ncc/validation`.
        drift_workers (int): Parallel workers for the drift analysis.
        drift_python (str or Path or None): Python to run the drift analysis with,
            when it differs from the Suite2P environment; None runs it here.

    Returns:
        dict: The drift-analysis manifest (its `status` drives the gate).
    """
    if drift_output_dir is None:
        drift_output_dir = fish_folder / DRIFT_RESULTS_SUBFOLDER / time.strftime("%Y%m%d-%H%M%S")
    drift_output_dir = Path(drift_output_dir)
    if drift_python is None:
        # Imported here, not at the top: the drift analysis may live in a
        # different Python environment from Suite2P (see `drift_python`).
        from preprocessing.drift_analysis import FunctionalAnatomyQCConfig, run_drift_analysis

        manifest = run_drift_analysis(
            fish_dir=fish_folder,
            output_dir=drift_output_dir,
            config=FunctionalAnatomyQCConfig(workers=int(drift_workers)),
        )
        return manifest
    # Separate Python: run the drift module from the terminal, then read its manifest.
    command = [
        str(drift_python),
        "-m",
        "preprocessing.drift_analysis",
        "--data-root",
        str(fish_folder.parent),
        "--fish",
        fish_folder.name,
        "--output-dir",
        str(drift_output_dir),
        "--workers",
        str(int(drift_workers)),
    ]
    subprocess.run(
        command,
        cwd=str(Path(__file__).resolve().parent.parent),
        check=True,
    )
    manifest_path = drift_output_dir / "functional_anatomy_qc_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    return manifest


def batch_process(data_root, ops_path, fps, fish_ids=None, selected_planes=None, fast_disk=None, storage_root=None,
                  drift_check=None, drift_workers=1, drift_python=None, drift_output_root=None):
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
        drift_check (str or None): Z-drift check before segmentation: None (off),
            "report_only" or "enforce" (see `run_suite2p_for_fish`).
        drift_workers (int): Parallel workers for the drift check.
        drift_python (str or Path or None): Separate Python for the drift check.
        drift_output_root (str or Path or None): Folder for the drift results,
            one `<fish>/<date-time>` subfolder per fish; None keeps them inside
            each fish folder (`03_analysis/functional/ncc/validation/<date-time>`).

    Returns:
        None: Each fish's motion-corrected TIFFs and segmentation outputs are
        written to disk, and optionally mirrored under `storage_root`.
    """
    data_root = Path(data_root)
    global_ops = np.load(ops_path, allow_pickle=True).item()

    for fish_folder in data_root.iterdir():
        if not fish_folder.is_dir():
            continue
        if fish_ids is not None and fish_folder.name not in fish_ids:  # only the requested fish
            continue

        start_time = time.time()
        print(f"\n📂 Processing fish: {fish_folder.name}")
        drift_output_dir = None if drift_output_root is None else Path(drift_output_root) / fish_folder.name / time.strftime("%Y%m%d-%H%M%S")
        run_suite2p_for_fish(
            fish_folder, global_ops, selected_planes, fps, fast_disk=fast_disk, storage_root=storage_root,
            drift_check=drift_check, drift_workers=drift_workers, drift_python=drift_python, drift_output_dir=drift_output_dir,
        )
        elapsed = time.time() - start_time
        print(f"⏱️ Finished processing {fish_folder.name} in {elapsed / 60:.2f} min.\n")

if __name__ == "__main__":
    # ---- Settings: fill in by hand when running this file (terminal options override them) ----
    DATA_ROOT = "F:/Matilde/2p_data"
    STORAGE_ROOT = "Z:/D2c/07_Data/Matilde/Microscopy"  # Root folder for data storage

    OPS_FILE_PATH = DATA_ROOT + "/suite2p_ops_sep_2025_cp.npy"    # global Suite2p ops file

    #SELECTED_FISH = np.arange(11,12)  # Fish IDs to process
    FISH_TO_PROCESS = ["L500_f01"]  # Fish IDs to process
    PLANES_TO_PROCESS = [0, 1, 2, 3, 4]  # Planes to process
    FPS = 2

    FAST_DISK_PATH = Path("F:/Matilde")  # Optional fast disk path

    DRIFT_CHECK = None  # Z-drift check before segmentation: None, "report_only" or "enforce"
    DRIFT_WORKERS = 1  # parallel workers for the drift check
    DRIFT_PYTHON = None  # separate Python for the drift check, if it lives in another environment
    DRIFT_OUTPUT_ROOT = None  # folder for the drift results; None = inside each fish folder
    # ----------------------------------------------------------------------------------------------

    parser = argparse.ArgumentParser(
        description="Suite2P motion correction (+ optional Z-drift check) and ROI segmentation.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,  # show each default in --help
    )
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT, help="folder containing the fish folders")
    parser.add_argument("--storage-root", type=Path, default=STORAGE_ROOT, help="storage drive where the ROI results are copied")
    parser.add_argument("--no-storage", action="store_true", help="don't copy the ROI results to the storage drive")
    parser.add_argument("--ops-path", type=Path, default=OPS_FILE_PATH, help="Suite2P settings file (.npy)")
    parser.add_argument("--fish", nargs="+", default=FISH_TO_PROCESS, help="fish IDs to process")
    parser.add_argument("--planes", type=int, nargs="+", default=PLANES_TO_PROCESS, help="list with plane indices to process")
    parser.add_argument("--fps", type=float, default=FPS, help="frame rate of the plane recordings)")
    parser.add_argument("--fast-disk", type=Path, default=FAST_DISK_PATH, help="local folder for Suite2P temporary files")
    parser.add_argument("--no-fast-disk", action="store_true", help="keep Suite2P temporary files in the fish folder")
    parser.add_argument("--drift-check", choices=sorted(DRIFT_CHECK_MODES), default=DRIFT_CHECK, help="Z-drift check before segmentation (off if not given)")
    parser.add_argument("--drift-workers", type=int, default=DRIFT_WORKERS, help="parallel workers for the drift check")
    parser.add_argument("--drift-python", type=Path, default=DRIFT_PYTHON, help="separate Python for the drift check")
    parser.add_argument("--drift-output-root", type=Path, default=DRIFT_OUTPUT_ROOT, help="folder for the drift results (one subfolder per fish); default: inside each fish folder")
    args = parser.parse_args()

    batch_process(
        args.data_root,
        args.ops_path,
        args.fps,
        fish_ids=args.fish,
        selected_planes=args.planes,
        fast_disk=None if args.no_fast_disk else args.fast_disk,
        storage_root=None if args.no_storage else args.storage_root,
        drift_check=args.drift_check,
        drift_workers=args.drift_workers,
        drift_python=args.drift_python,
        drift_output_root=args.drift_output_root,
    )
