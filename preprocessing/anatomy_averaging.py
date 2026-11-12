"""Inventory raw 2P anatomy z-stacks and average their repeated frames per depth.

ScanImage either averages the repeated frames of each depth while saving
(`logAverageFactor` = frames per depth: one page per depth), or saves every
frame (`logAverageFactor` = 1: frames-per-depth pages per depth). This module
reads each stack's ScanImage header, checks it against the page count, and
classifies the file:

- `already_averaged`: one page per depth -- copy it unchanged.
- `needs_averaging`: N pages per depth -- average each depth's N frames into
  one image (depths are never averaged together).
- `review`: anything that doesn't add up (several channels or volumes, page
  count not matching the header) -- left for a person to decide.

Averaging streams one depth at a time, so multi-GB stacks never have to fit
in memory, and writes the source dtype (int16 for ScanImage) so the result
matches what ScanImage's own averaging would have produced.
"""

import json
import os
import shutil
import time
from pathlib import Path

import numpy as np
import tifffile

from preprocessing.spatial_preprocessing import _metadata_value
from utils import fish_id_from_folder_name

STATUS_ALREADY_AVERAGED = "already_averaged"
STATUS_NEEDS_AVERAGING = "needs_averaging"
STATUS_REVIEW = "review"

# ScanImage header keys (tifffile's `scanimage_metadata["FrameData"]`).
NUM_SLICES_KEY = "SI.hStackManager.actualNumSlices"  # depths actually acquired
NUM_SLICES_FALLBACK_KEY = "SI.hStackManager.numSlices"  # older ScanImage versions
FRAMES_PER_SLICE_KEY = "SI.hStackManager.framesPerSlice"
NUM_VOLUMES_KEY = "SI.hStackManager.actualNumVolumes"
LOG_AVERAGE_FACTOR_KEY = "SI.hScan2D.logAverageFactor"  # frames ScanImage averaged before saving
CHANNEL_SAVE_KEY = "SI.hChannels.channelSave"
Z_STEP_KEY = "SI.hStackManager.actualStackZStepSize"

CSV_FRAMES_PER_SLICE_KEY = "frames_per_slice_anatomy"  # the experimenter's own metadata CSV
EX_VIVO_MARKERS = ("ex_vivo", "exvivo")
AVERAGED_SUFFIX = "_averaged"
PARTIAL_SUFFIX = ".partial"  # files being written; renamed only once complete


def read_stack_header(tiff_path):
    """Read the ScanImage acquisition settings and page layout of an anatomy TIFF.

    Counting pages parses every page index, which takes ~1-2 min for a
    15,000-page file on the network drive.

    Args:
        tiff_path (Path): Anatomy TIFF written by ScanImage.

    Returns:
        dict: `n_pages`, `page_shape`, `dtype`, `num_slices`, `frames_per_slice`,
        `log_average_factor`, `num_volumes`, `n_channels` (None if missing from
        the header), `z_step_um`, `x_resolution` (rational tuple) and
        `resolution_unit` (int).
    """
    with tifffile.TiffFile(tiff_path) as tiff_file:
        frame_data = (tiff_file.scanimage_metadata or {}).get("FrameData", {})
        first_page = tiff_file.pages[0]
        x_resolution = first_page.tags["XResolution"].value if "XResolution" in first_page.tags else None
        resolution_unit = int(first_page.tags["ResolutionUnit"].value) if "ResolutionUnit" in first_page.tags else None
        n_pages = len(tiff_file.pages)
        page_shape = tuple(int(size) for size in first_page.shape)
        dtype = str(first_page.dtype)

    channel_save = frame_data.get(CHANNEL_SAVE_KEY)
    # channelSave is a single channel number, or a list of the saved channels.
    n_channels = len(channel_save) if isinstance(channel_save, list) else (1 if channel_save is not None else None)
    header = {
        "n_pages": n_pages,
        "page_shape": page_shape,
        "dtype": dtype,
        "num_slices": frame_data.get(NUM_SLICES_KEY, frame_data.get(NUM_SLICES_FALLBACK_KEY)),
        "frames_per_slice": frame_data.get(FRAMES_PER_SLICE_KEY),
        "log_average_factor": frame_data.get(LOG_AVERAGE_FACTOR_KEY),
        "num_volumes": frame_data.get(NUM_VOLUMES_KEY, 1),
        "n_channels": n_channels,
        "z_step_um": frame_data.get(Z_STEP_KEY),
        "x_resolution": x_resolution,
        "resolution_unit": resolution_unit,
    }
    return header


def classify_stack(header):
    """Decide whether an anatomy stack is already averaged, needs averaging, or needs review.

    Args:
        header (dict): Result of `read_stack_header`.

    Returns:
        tuple: `(status, frames_per_page_group, note)` -- one of the STATUS_*
        constants, the number of consecutive pages that belong to one depth
        (1 if already averaged, N if it needs averaging, None for review), and
        a short human-readable reason.
    """
    required = ("num_slices", "frames_per_slice", "log_average_factor", "n_channels")
    missing = [key for key in required if header.get(key) is None]
    if missing:
        return STATUS_REVIEW, None, f"ScanImage header lacks {missing}"
    num_slices = int(header["num_slices"])
    frames_per_slice = int(header["frames_per_slice"])
    log_average_factor = int(header["log_average_factor"])
    if header["n_channels"] != 1:
        return STATUS_REVIEW, None, f"{header['n_channels']} channels saved (pages interleaved)"
    if int(header["num_volumes"]) != 1:
        return STATUS_REVIEW, None, f"{header['num_volumes']} volumes saved"
    if log_average_factor < 1 or frames_per_slice % log_average_factor != 0:
        return STATUS_REVIEW, None, f"framesPerSlice {frames_per_slice} not divisible by logAverageFactor {log_average_factor}"

    # Pages ScanImage wrote per depth after its own averaging.
    saved_frames_per_slice = frames_per_slice // log_average_factor
    expected_pages = num_slices * saved_frames_per_slice
    if header["n_pages"] != expected_pages:
        note = (f"{header['n_pages']} pages, header predicts {num_slices} depths x "
                f"{saved_frames_per_slice} frames = {expected_pages} (aborted or edited stack?)")
        return STATUS_REVIEW, None, note
    if saved_frames_per_slice == 1:
        return STATUS_ALREADY_AVERAGED, 1, f"{num_slices} depths, {frames_per_slice} frames averaged by ScanImage"
    note = f"{num_slices} depths x {saved_frames_per_slice} frames, to average"
    return STATUS_NEEDS_AVERAGING, saved_frames_per_slice, note


def average_page_group(pages):
    """Average the repeated frames of one depth into one image of the same dtype.

    Integer inputs are averaged in float64 and rounded back, so the output
    stays in the source dtype (int16 for ScanImage) and can't overflow.

    Args:
        pages (list of numpy.ndarray): Repeated 2D frames of one depth.

    Returns:
        numpy.ndarray: Their pixel-wise mean, same shape and dtype as the pages.
    """
    source_dtype = pages[0].dtype
    mean_image = np.mean(np.stack(pages), axis=0, dtype=np.float64)
    if np.issubdtype(source_dtype, np.integer):
        mean_image = np.rint(mean_image)
    averaged_page = mean_image.astype(source_dtype)
    return averaged_page


def write_averaged_stack(source_path, output_path, frames_per_depth, num_depths, header, num_volumes=1, volume_index=0):
    """Stream an all-frames anatomy TIFF into a one-page-per-depth averaged TIFF.

    Pages are read in file order, `frames_per_depth` at a time. A file holding
    several complete passes through the stack ("volumes", saved one after the
    other) is averaged for one pass only, `volume_index`. The output is
    written as `<output>.partial` and renamed only when complete, so an
    interrupted run never leaves a file that looks finished. An existing
    output is never overwritten.

    Args:
        source_path (Path): All-frames anatomy TIFF (never modified).
        output_path (Path): Averaged TIFF to create.
        frames_per_depth (int): Consecutive pages that belong to one depth.
        num_depths (int): Number of depths in one pass.
        header (dict): Result of `read_stack_header` (for the pixel-size tags).
        num_volumes (int): Complete passes saved in the file.
        volume_index (int): Pass to average (0 = first).

    Raises:
        FileExistsError: If `output_path` already exists.
        ValueError: If the source doesn't hold `frames_per_depth * num_depths * num_volumes`
            pages, or `volume_index` is out of range.
    """
    if not 0 <= volume_index < num_volumes:
        raise ValueError(f"volume_index {volume_index} out of range for {num_volumes} volumes")
    output_path = Path(output_path)
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite {output_path}")
    partial_path = output_path.with_name(output_path.name + PARTIAL_SUFFIX)
    # Keep the source pixel size so `read_pixel_size_um` reads the same value.
    resolution_kwargs = {}
    if header["x_resolution"] is not None:
        resolution_kwargs = {"resolution": (header["x_resolution"], header["x_resolution"]), "resolutionunit": header["resolution_unit"]}

    with tifffile.TiffFile(source_path) as source, tifffile.TiffWriter(partial_path, bigtiff=False) as writer:
        pages_per_volume = frames_per_depth * num_depths
        if len(source.pages) != pages_per_volume * num_volumes:
            raise ValueError(f"{source_path} has {len(source.pages)} pages, expected {frames_per_depth} x {num_depths} x {num_volumes}")
        for depth_index in range(num_depths):
            # Passes follow each other; within a pass, a depth's frames are consecutive pages.
            first_page = volume_index * pages_per_volume + depth_index * frames_per_depth
            pages = [source.pages[first_page + offset].asarray() for offset in range(frames_per_depth)]
            writer.write(average_page_group(pages), contiguous=True, **resolution_kwargs)
    os.replace(partial_path, output_path)


def copy_without_overwrite(source_path, destination_path):
    """Copy a file (with timestamps), refusing to overwrite and never touching the source.

    Args:
        source_path (Path): File to copy.
        destination_path (Path): New file to create.

    Raises:
        FileExistsError: If `destination_path` already exists.
        OSError: If the copied size differs from the source size.
    """
    destination_path = Path(destination_path)
    if destination_path.exists():
        raise FileExistsError(f"Refusing to overwrite {destination_path}")
    partial_path = destination_path.with_name(destination_path.name + PARTIAL_SUFFIX)
    shutil.copy2(source_path, partial_path)
    if partial_path.stat().st_size != Path(source_path).stat().st_size:
        raise OSError(f"Copy of {source_path} is incomplete ({partial_path.stat().st_size} bytes)")
    os.replace(partial_path, destination_path)


def write_averaging_metadata(metadata_path, source_path, output_path, header, frames_per_depth, fish_id, volume_index=0):
    """Write the provenance sidecar of an averaged anatomy stack.

    Args:
        metadata_path (Path): JSON file to write.
        source_path (Path): Original all-frames TIFF.
        output_path (Path): Averaged TIFF.
        header (dict): Result of `read_stack_header` for the source.
        frames_per_depth (int): Frames averaged per depth.
        fish_id (str): Fish identifier.
        volume_index (int): Pass that was averaged, for files with several passes (0 = first).
    """
    metadata = {
        "fish_id": fish_id,
        "source_path": str(source_path),
        "source_size_bytes": Path(source_path).stat().st_size,
        "output_path": str(output_path),
        "method": "mean of each depth's consecutive repeated frames, rounded to the source dtype",
        "frames_averaged_per_depth": int(frames_per_depth),
        "volume_averaged": f"{volume_index + 1} of {header.get('num_volumes', 1)}",
        "source_header": {key: (list(value) if isinstance(value, tuple) else value) for key, value in header.items()},
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with Path(metadata_path).open("w", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2)


def read_file_z_step_um(anatomy_path):
    """Read an anatomy stack's Z step from the file itself, for when the metadata CSV lacks it.

    A ScanImage TIFF carries it in its header. A stack averaged by
    `write_averaged_stack` has no ScanImage header, but its metadata sidecar
    (`<stem>_metadata.json`) kept the source header.

    Args:
        anatomy_path (Path): Anatomy TIFF (raw ScanImage or averaged).

    Returns:
        tuple: `(z_step_um, source)` -- the step rounded to 1e-6 um (ScanImage
        stores e.g. 2.000000000000004) and where it was read; `(None, None)`
        if neither place records it.
    """
    with tifffile.TiffFile(anatomy_path) as tiff_file:
        frame_data = (tiff_file.scanimage_metadata or {}).get("FrameData", {})
    z_step = frame_data.get(Z_STEP_KEY, frame_data.get("SI.hStackManager.stackZStepSize"))
    if z_step is not None:
        return round(float(z_step), 6), f"ScanImage header of {anatomy_path}"
    sidecar_path = Path(anatomy_path).with_name(f"{Path(anatomy_path).stem}_metadata.json")
    if sidecar_path.exists():
        z_step = json.loads(sidecar_path.read_text(encoding="utf-8"))["source_header"].get("z_step_um")
        if z_step is not None:
            return round(float(z_step), 6), f"source ScanImage header, via {sidecar_path}"
    return None, None


def averaged_output_name(source_path):
    """Return the file name of an averaged anatomy stack, derived from its source file.

    Keeping the source name links each output to its original, and two source
    files of one fish can never collide.

    Args:
        source_path (Path): All-frames anatomy TIFF, e.g. ".../L800_f02_anatomy_00001.tif".

    Returns:
        str: e.g. "L800_f02_anatomy_00001_averaged.tif".
    """
    output_name = f"{Path(source_path).stem}{AVERAGED_SUFFIX}.tif"
    return output_name


def index_fish_folders(root):
    """Map fish IDs to the folders under a data root whose names start with them.

    Args:
        root (Path): Folder holding one sub-folder per fish.

    Returns:
        dict: fish_id -> list of folder Paths (normally one).
    """
    folders_by_fish = {}
    for folder in sorted(Path(root).iterdir()):
        if not folder.is_dir():
            continue
        try:
            fish_id = fish_id_from_folder_name(folder.name)
        except ValueError:
            continue  # e.g. "Microscopy", "0 new folder", "L978_test"
        folders_by_fish.setdefault(fish_id, []).append(folder)
    return folders_by_fish


def find_anatomy_files(fish_folder, loose_folder, fish_id):
    """List a fish's in-vivo anatomy TIFFs: in its own folder, plus loose ones named after it.

    Args:
        fish_folder (Path or None): The fish's network folder.
        loose_folder (Path or None): Folder with stray files (e.g. "0 new folder").
        fish_id (str): Fish identifier used to match loose files by name.

    Returns:
        list: `(path, location)` pairs, location being "fish_folder" or "loose".
    """
    found = []
    if fish_folder is not None:
        anatomy_dir = Path(fish_folder) / "01_raw" / "2p" / "anatomy"
        for path in sorted(anatomy_dir.glob("*.tif*")):
            if not any(marker in path.name.lower() for marker in EX_VIVO_MARKERS):
                found.append((path, "fish_folder"))
    if loose_folder is not None and Path(loose_folder).is_dir():
        for path in sorted(Path(loose_folder).glob(f"{fish_id}*anatomy*.tif*")):
            found.append((path, "loose"))
    return found


def read_csv_frames_per_slice(fish_folder):
    """Read `frames_per_slice_anatomy` from a fish's metadata CSV, for cross-checking.

    Args:
        fish_folder (Path): Fish folder with `01_raw/2p/metadata/*_metadata.csv`.

    Returns:
        int or None: The value, or None if absent or unreadable.
    """
    for metadata_path in sorted((Path(fish_folder) / "01_raw" / "2p" / "metadata").glob("*_metadata.csv")):
        value = _metadata_value(metadata_path, CSV_FRAMES_PER_SLICE_KEY)
        try:
            frames_per_slice = int(float(value))
        except (TypeError, ValueError):
            continue
        return frames_per_slice
    return None
