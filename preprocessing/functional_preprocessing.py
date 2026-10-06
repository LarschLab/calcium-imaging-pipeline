"""Functional preprocessing: turn the raw two-photon functional recordings of a
fish into one functional plane recording per plane.

For each fish, the raw functional TIFFs of the selected blocks are loaded and
joined, negative pixel values are shifted up so the data fit in 16 bits, and
the repeated frames of each plane are averaged. The result is one functional
plane recording per plane, plus a metadata file with the settings used.

- Recordings keep the microscope's X/Y orientation. Optionally they can be
  flipped into the shared orientation (used by Danin's canonical workflow).
- A fish whose outputs already exist is skipped, never overwritten.
- Run it from the terminal or fill in the settings at the bottom (see `--help`).

Written by Matilde Perrino (2025); orientation option added by Danin
Dharmaperwira (2026). Was `preprocessing_tiff.py`.
"""

# TODO: remove the linear protocol and the volume flyback removal (no longer
# used; keep them only in the repo history), once checked:
# - with Danin: canonical_preprocessing passes `protocol` and
#   `volume_flyback_frames` through, and its terminal command defaults to
#   1 flyback frame (our recordings have 0) -- do his fish have one?
# - whether `'mode': 'linear'` in visual_stimulation/dots_continous_session.py
#   is still used for acquisition.

import argparse
import gc
import json
import multiprocessing as mp
from pathlib import Path
import re
import time

import numpy as np
import tifffile as tf

from preprocessing.spatial_preprocessing import (
    ACQUISITION_XY_FRAME,
    CANONICAL_XY_FRAME,
    apply_canonical_xy,
    normalize_polarity,
)

RAW_FUNCTIONAL_SUBFOLDER = Path("01_raw/2p/functional")  # raw functional TIFFs, inside the fish folder
PLANES_SUBFOLDER = Path("02_reg/00_preprocessing/2p_functional/01_individualPlanes")  # outputs, inside the fish folder
PROTOCOLS = ("resonant", "linear")
UINT16_MAX = int(np.iinfo(np.uint16).max)
BLOCK_NUMBER_PATTERN = re.compile(r"_(\d{5})\.tif$")  # raw TIFFs end in _000XX.tif, XX = block number
METADATA_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def correct_chunk_int16_to_uint16(chunk, offset):
    """Shift one chunk of frames up by `offset` and store it as uint16.

    Args:
        chunk (np.ndarray): 3D array chunk (int16).
        offset (int): Value added so the most negative pixel becomes 0.

    Returns:
        np.ndarray: Corrected uint16 chunk.
    """
    chunk_int32 = chunk.astype(np.int32)  # int32 so adding the offset can't overflow
    chunk_int32 += offset
    np.clip(chunk_int32, 0, UINT16_MAX, out=chunk_int32)
    corrected_chunk = chunk_int32.astype(np.uint16)
    return corrected_chunk


def load_tiff_file(filepath, n_planes, n_frames_per_plane):
    """Load a multi-page TIFF file into a 3D array.

    If a page can't be read (e.g. a truncated file), reading stops there and
    the frames are trimmed back to a whole number of volumes.

    Args:
        filepath (Path): Path to the TIFF file.
        n_planes (int): Number of planes acquired per volume.
        n_frames_per_plane (int): Number of frames acquired per plane.

    Returns:
        np.ndarray: 3D array (frames, height, width).

    Raises:
        ValueError: If no page of the file can be read.
    """
    frames = []
    with tf.TiffFile(filepath) as tif:
        for frame_index, page in enumerate(tif.pages):
            try:
                frames.append(page.asarray())
            except Exception as error:
                print(f"⚠️ {filepath.name}: stopped at frame {frame_index} due to error: {error}")
                # Drop the incomplete last volume, so frames divide by n_planes * n_frames_per_plane
                extra_frames = len(frames) % (n_planes * n_frames_per_plane)
                if extra_frames:
                    frames = frames[:-extra_frames]
                break  # stop reading further pages
    if not frames:
        raise ValueError(f"{filepath.name}: no readable frames")

    stack = np.stack(frames)
    return stack


def remove_vflyback_frames(frames, frames_per_volume, vflyback_frames=1):
    """Remove the volume flyback frames (black frames) at the end of each volume.

    Args:
        frames (np.ndarray): 3D array (frames, height, width).
        frames_per_volume (int): Total frames in one volume (including flyback).
        vflyback_frames (int): Number of flyback frames per volume.

    Returns:
        np.ndarray: 3D array without the flyback frames.
    """
    total_frames = len(frames)
    if total_frames % frames_per_volume != 0:
        print(f"⚠️ Warning: {total_frames} frames not divisible by {frames_per_volume}. Some frames may be dropped.")

    # Keep a frame unless it is one of the last `vflyback_frames` of its volume
    keep_indices = np.array([
        frame_index for frame_index in range(total_frames)
        if (frame_index % frames_per_volume) < (frames_per_volume - vflyback_frames)])

    kept_frames = frames[keep_indices]
    return kept_frames


def correct_negative_values(frames, num_chunks=5):
    """Shift the whole stack up so no pixel is negative, and store it as uint16.

    The same offset (the most negative value) is added to every pixel; the
    stack is processed in chunks to limit memory use.

    Args:
        frames (np.ndarray): Image stack, int16 (may contain negative values).
        num_chunks (int): Number of chunks the stack is split into.

    Returns:
        np.ndarray: Corrected image stack, uint16.
    """
    min_value = np.min(frames)
    print(f"  min: {min_value}, max: {np.max(frames)}")

    if min_value >= 0:
        print("  No negative values to correct.")
        uint16_frames = frames.astype(np.uint16)
        return uint16_frames

    offset = abs(min_value)
    corrected = np.empty(frames.shape, dtype=np.uint16)
    chunk_size = int(np.ceil(frames.shape[0] / num_chunks))

    for chunk_index in range(num_chunks):
        start = chunk_index * chunk_size
        end = min((chunk_index + 1) * chunk_size, frames.shape[0])
        corrected[start:end] = correct_chunk_int16_to_uint16(frames[start:end], offset)
        print(f"    Processed chunk {chunk_index + 1}/{num_chunks} ({end - start} volumes)")

    print(f"  Corrected negative values by adding offset {offset}.")
    print(f"  New min: {np.min(corrected)}, max: {np.max(corrected)}")
    return corrected


def save_stack(output_path, filename, stack):
    """Save an image stack as TIFF.

    Args:
        output_path (Path): Directory to save the file in.
        filename (str): Output TIFF filename.
        stack (np.ndarray): Image stack to save.

    Returns:
        None: The stack is written to `output_path / filename`.
    """
    output_path.mkdir(parents=True, exist_ok=True)
    tf.imwrite(output_path / filename, stack, photometric="minisblack")


def extract_block_number(tif_file):
    """Read the block number from a raw TIFF name ending in `_000XX.tif`.

    Args:
        tif_file (Path): TIFF file.

    Returns:
        int or None: Block number, or None if the name doesn't match.
    """
    match = BLOCK_NUMBER_PATTERN.search(tif_file.name)
    if not match:
        return None
    block_number = int(match.group(1))
    return block_number


def select_functional_tiffs(fish_id, input_base, blocks=None):
    """Pick the raw functional TIFFs of a fish, in block order.

    Args:
        fish_id (str): Fish ID.
        input_base (Path): Folder containing the fish folders.
        blocks (list[int] or None): Blocks to include; None = all blocks.

    Returns:
        list[Path]: Selected functional TIFFs (anatomy TIFFs excluded).
    """
    raw_folder = Path(input_base) / fish_id / RAW_FUNCTIONAL_SUBFOLDER
    selected_tiffs = []
    for tif_file in sorted(raw_folder.glob("*.tif")):
        if "anatomy" in tif_file.name.lower():  # the anatomy stack sits in the same folder
            continue
        if blocks is not None and extract_block_number(tif_file) not in blocks:
            continue
        selected_tiffs.append(tif_file)
    return selected_tiffs


def concatenate_blocks(tiff_files, protocol, n_planes=None, n_frames_per_plane=None, volume_flyback_frames=1, remove_first_frame=False):
    """Load and join the selected blocks. For the resonant protocol, also remove flyback and reshape.

    Args:
        tiff_files (list[Path]): Functional TIFFs to load, in block order
            (from `select_functional_tiffs`).
        protocol (str): 'resonant' or 'linear'.
        n_planes (int): Number of planes (only for resonant).
        n_frames_per_plane (int): Frames per plane (only for resonant).
        volume_flyback_frames (int): Volume flyback frames (only for resonant).
        remove_first_frame (bool): If True, drop the first frame of each
            plane within each volume (only for resonant).

    Returns:
        np.ndarray: Full joined image stack; for resonant, shaped
        (volumes x planes, frames_per_plane, height, width).

    Raises:
        ValueError: If no TIFF file was given.
    """
    all_blocks = []
    for tif_file in tiff_files:
        print(f"  Loading {tif_file.name}")
        frames = load_tiff_file(tif_file, n_planes, n_frames_per_plane)

        if protocol == "resonant":
            frames_per_volume = n_planes * n_frames_per_plane + volume_flyback_frames
            if volume_flyback_frames > 0:
                print(f"  Removing {volume_flyback_frames} flyback frames per volume.")
                frames = remove_vflyback_frames(frames, frames_per_volume, volume_flyback_frames)

            # One row per plane acquisition: (volumes x planes, frames_per_plane, H, W)
            frames = frames.reshape(-1, n_frames_per_plane, frames.shape[1], frames.shape[2])

            if remove_first_frame:
                frames = frames[:, 1:, :, :]

        all_blocks.append(frames)

    if not all_blocks:
        raise ValueError("No matching TIFF files found for selected blocks.")

    full_stack = np.concatenate(all_blocks, axis=0)
    print(f"  Full concatenated stack shape: {full_stack.shape}")
    return full_stack


def existing_preprocessing_outputs(output_path, fish_id):
    """List the preprocessing outputs of a fish that are already on disk.

    Args:
        output_path (Path): Folder where the fish's plane TIFFs and metadata are written.
        fish_id (str): Fish ID.

    Returns:
        list[Path]: Existing plane TIFFs, stack TIFF and metadata JSON of
        this fish; empty if none exist yet.
    """
    output_patterns = [f"{fish_id}_plane*.tif", f"{fish_id}_stack.tif", f"{fish_id}_preprocessing_metadata.json"]
    existing_outputs = [path for pattern in output_patterns for path in sorted(Path(output_path).glob(pattern))]
    return existing_outputs


def orientation_record(apply_polarity_orientation, polarity, polarity_source):
    """Describe how the X/Y orientation of the recordings is handled.

    Args:
        apply_polarity_orientation (bool): If True, flip into the shared
            orientation using `polarity`; if False, keep the microscope's.
        polarity (str or None): North/south direction (needed only when flipping).
        polarity_source (str or None): Where `polarity` came from.

    Returns:
        dict: Orientation fields saved in the metadata (polarity and its
        source are None when no flip is applied).

    Raises:
        ValueError: If flipping is requested without a north/south polarity.
    """
    if not apply_polarity_orientation:
        orientation = {
            "apply_polarity_orientation": False,
            "polarity": None,
            "polarity_source": None,
            "input_xy_frame": ACQUISITION_XY_FRAME,
            "output_xy_frame": ACQUISITION_XY_FRAME,
            "xy_transform": "none",
        }
        return orientation
    polarity = normalize_polarity(polarity)
    if polarity not in {"north", "south"}:
        raise ValueError("apply_polarity_orientation=True requires a resolved north/south polarity")
    orientation = {
        "apply_polarity_orientation": True,
        "polarity": polarity,
        "polarity_source": polarity_source,
        "input_xy_frame": ACQUISITION_XY_FRAME,
        "output_xy_frame": CANONICAL_XY_FRAME,
        "xy_transform": "flipY" if polarity == "north" else "flipX",
    }
    return orientation


def save_plane_recordings(full_stack, output_path, fish_id, n_planes, polarity=None):
    """Average each plane's repeated frames and save one recording per plane.

    Args:
        full_stack (np.ndarray): Resonant stack from `concatenate_blocks`
            (rows cycle through the planes, volume after volume).
        output_path (Path): Folder for the plane TIFFs.
        fish_id (str): Fish ID.
        n_planes (int): Number of planes.
        polarity (str or None): North/south direction to flip into the
            shared orientation; None keeps the microscope's orientation.

    Returns:
        None: `{fish_id}_plane{i}.tif` files are written to `output_path`.
    """
    for plane_idx in range(n_planes):
        # Extract one plane across all volumes (every n_planes-th row), then average its repeated frames
        avg_plane = np.mean(full_stack[plane_idx::n_planes], axis=1)
        avg_plane = np.round(avg_plane).astype(np.uint16)
        if polarity is not None:
            avg_plane = apply_canonical_xy(avg_plane, polarity)
        save_stack(output_path, f"{fish_id}_plane{plane_idx}.tif", avg_plane)
        print(f"  Saved plane {plane_idx}")
        del avg_plane
        gc.collect()


def preprocess_functional_fish(
    fish_id,
    input_base,
    output_base,
    protocol="resonant",
    blocks=None,
    n_planes=None,
    n_frames_per_plane=None,
    volume_flyback_frames=1,
    remove_first_frame=False,
    *,
    apply_polarity_orientation=False,
    polarity=None,
    polarity_source=None,
):
    """Preprocess the functional recordings of one fish (resonant or linear protocol).

    Args:
        fish_id (str): Fish ID.
        input_base (Path): Folder containing the raw fish folders.
        output_base (Path): Folder where the fish's output folder is written.
        protocol (str): 'resonant' or 'linear'.
        blocks (list[int] or None): Blocks to include; None = all blocks.
        n_planes (int): Number of planes (only resonant).
        n_frames_per_plane (int): Frames per plane (only resonant).
        volume_flyback_frames (int): Volume flyback frames (only resonant).
        remove_first_frame (bool): Whether to remove the first frame in resonant protocol.
        apply_polarity_orientation (bool): If True, use north/south polarity to
            place the recordings in the shared X/Y orientation. If False, do
            not use polarity and leave X/Y unchanged.
        polarity (str or None): Reviewed or predicted north/south direction. It
            is required only when apply_polarity_orientation is True.
        polarity_source (str or None): Plain description of where polarity came
            from, saved in the metadata when orientation is applied.

    Returns:
        None: Plane TIFFs and a JSON metadata file are written to output_base.
        If any of them already exist, the fish is skipped with a warning and
        nothing is overwritten.

    Raises:
        ValueError: If the protocol is unknown or the polarity is missing when flipping.
    """
    output_path = Path(output_base) / fish_id / PLANES_SUBFOLDER
    # Never overwrite earlier results: checked before loading, so a skipped fish costs nothing.
    existing_outputs = existing_preprocessing_outputs(output_path, fish_id)
    if existing_outputs:
        existing_names = ", ".join(path.name for path in existing_outputs)
        print(f"⚠️ Skipping {fish_id}: preprocessing outputs already exist in {output_path} ({existing_names}). "
              f"Delete or move them to rerun this fish.")
        return
    if protocol not in PROTOCOLS:
        raise ValueError(f"Unknown protocol type: {protocol}")
    orientation = orientation_record(apply_polarity_orientation, polarity, polarity_source)

    selected_tiffs = select_functional_tiffs(fish_id, input_base, blocks)
    full_stack = concatenate_blocks(selected_tiffs, protocol, n_planes, n_frames_per_plane, volume_flyback_frames, remove_first_frame)
    full_stack = correct_negative_values(full_stack)
    output_path.mkdir(parents=True, exist_ok=True)

    if protocol == "resonant":
        save_plane_recordings(full_stack, output_path, fish_id, n_planes, orientation["polarity"])
        protocol_settings = {
            "n_planes": n_planes,
            "n_frames_per_plane": n_frames_per_plane,
            "blocks": blocks,
            "volume_flyback_frames": volume_flyback_frames,
            "remove_first_frame": remove_first_frame,
        }
        output_planes = list(range(int(n_planes)))
    else:  # linear: the whole stack is saved as one recording
        if apply_polarity_orientation:
            full_stack = apply_canonical_xy(full_stack, orientation["polarity"])
        save_stack(output_path, f"{fish_id}_stack.tif", full_stack)
        protocol_settings = {"blocks": blocks}
        output_planes = [0]

    del full_stack
    gc.collect()

    metadata = {
        "protocol": protocol,
        **protocol_settings,
        "fish_id": fish_id,
        "output_path": str(output_path),
        **orientation,
        "sessions": [{
            "session_label": "r1",  # one session per preprocessing run
            "session_number": 1,
            "output_planes": output_planes,
            "selected_tiffs": [str(path) for path in selected_tiffs],
        }],
        "timestamp": time.strftime(METADATA_TIMESTAMP_FORMAT),
    }
    with open(output_path / f"{fish_id}_preprocessing_metadata.json", "w") as metadata_file:
        json.dump(metadata, metadata_file, indent=4)

    print(f"✅ Finished processing {fish_id}")


def parallel_preprocess(
    fish_ids,
    input_base,
    output_base,
    protocol="resonant",
    blocks=None,
    n_planes=None,
    n_frames_per_plane=None,
    volume_flyback_frames=1,
    remove_first_frame=False,
    *,
    apply_polarity_orientation=False,
    polarity_by_fish=None,
    polarity_source_by_fish=None,
):
    """Preprocess several fish in parallel, one process per fish.

    Args:
        fish_ids (list[str]): List of fish IDs.
        input_base (Path): Folder containing the raw fish folders.
        output_base (Path): Folder where the fish output folders are written.
        protocol (str): 'resonant' or 'linear'.
        blocks (list[int] or None): Blocks to include; None = all blocks.
        n_planes (int): Number of planes (only resonant).
        n_frames_per_plane (int): Frames per plane (only resonant).
        volume_flyback_frames (int): Volume flyback frames (only resonant).
        remove_first_frame (bool): Whether to remove the first frame in resonant protocol.
        apply_polarity_orientation (bool): Apply both polarity interpretation and
            the matching X/Y reorientation when True; do neither when False.
        polarity_by_fish (dict[str, str] or None): North/south value for each fish
            when polarity orientation is enabled.
        polarity_source_by_fish (dict[str, str] or None): Where each saved
            polarity value came from.

    Returns:
        None: Waits for every fish-processing job to finish.
    """
    with mp.Pool(processes=mp.cpu_count()) as pool:
        jobs = []
        for fish_id in fish_ids:
            jobs.append(pool.apply_async(
                preprocess_functional_fish,
                args=(
                    fish_id, input_base, output_base, protocol, blocks,
                    n_planes, n_frames_per_plane, volume_flyback_frames, remove_first_frame,
                ),
                kwds={
                    "apply_polarity_orientation": apply_polarity_orientation,
                    "polarity": (polarity_by_fish or {}).get(fish_id),
                    "polarity_source": (polarity_source_by_fish or {}).get(fish_id),
                },
            ))
        for job in jobs:
            job.get()


if __name__ == "__main__":
    # ---- Settings: fill in by hand when running this file (terminal options override them) ----
    INPUT_PATH = "F:/Matilde/2p_data"
    OUTPUT_PATH = "F:/Matilde/2p_data"

    FISH_TO_PROCESS = ["L500_f01"]  # Fish IDs to process

    PROTOCOL = "resonant"  # or "linear"

    N_PLANES = 5
    N_FRAMES_PER_PLANE = 3
    VOLUME_FLYBACK_FRAMES = 0
    REMOVE_FIRST_FRAME = True  # Waiting time between frames in resonant protocol

    BLOCKS = [2, 3]  # or None if you want to process all blocks
    # ----------------------------------------------------------------------------------------------

    parser = argparse.ArgumentParser(
        description="Split raw functional recordings into one functional plane recording per plane.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,  # show each default in --help
    )
    parser.add_argument("--input-path", type=Path, default=INPUT_PATH, help="folder containing the raw fish folders")
    parser.add_argument("--output-path", type=Path, default=OUTPUT_PATH, help="folder where the fish output folders are written")
    parser.add_argument("--fish", nargs="+", default=FISH_TO_PROCESS, help="fish IDs to process")
    parser.add_argument("--protocol", choices=PROTOCOLS, default=PROTOCOL, help="acquisition protocol")
    parser.add_argument("--n-planes", type=int, default=N_PLANES, help="planes per volume")
    parser.add_argument("--n-frames-per-plane", type=int, default=N_FRAMES_PER_PLANE, help="frames acquired per plane")
    parser.add_argument("--volume-flyback-frames", type=int, default=VOLUME_FLYBACK_FRAMES, help="flyback frames per volume")
    parser.add_argument("--remove-first-frame", action=argparse.BooleanOptionalAction, default=REMOVE_FIRST_FRAME, help="drop the first frame of each plane")
    parser.add_argument("--blocks", type=int, nargs="+", default=BLOCKS, help="blocks to process")
    parser.add_argument("--all-blocks", action="store_true", help="process all blocks (ignores --blocks)")
    args = parser.parse_args()

    start_time = time.time()

    parallel_preprocess(
        args.fish,
        input_base=args.input_path,
        output_base=args.output_path,
        protocol=args.protocol,
        blocks=None if args.all_blocks else args.blocks,
        n_planes=args.n_planes,
        n_frames_per_plane=args.n_frames_per_plane,
        volume_flyback_frames=args.volume_flyback_frames,
        remove_first_frame=args.remove_first_frame,
    )

    elapsed = time.time() - start_time
    print(f"⏱️ Finished full processing in {elapsed/60:.2f} min.\n")
