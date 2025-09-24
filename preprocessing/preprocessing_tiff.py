from pathlib import Path
import tifffile as tf
import numpy as np
import json
import time
import gc
import re
import multiprocessing as mp

def correct_chunk_int16_to_uint16(chunk, offset):
    """
    Correct one chunk of frames by shifting negative values to positive.

    Parameters:
    - chunk (np.ndarray): 3D array chunk.
    - offset (int): Value to add to make data positive.

    Returns:
    - np.ndarray: Corrected uint16 chunk.
    """
    chunk_int32 = chunk.astype(np.int32)
    chunk_int32 += offset
    np.clip(chunk_int32, 0, 65535, out=chunk_int32)
    return chunk_int32.astype(np.uint16)


def load_tiff_file(filepath):
    """
    Load a multi-page TIFF file into a 3D NumPy array.

    Parameters:
    - filepath (Path): Path to the TIFF file.

    Returns:
    - np.ndarray: 3D array (frames, height, width).
    """
    with tf.TiffFile(filepath) as tif:
        return np.stack([page.asarray() for page in tif.pages])


def remove_vflyback_frames(frames, frames_per_volume, vflyback_frames=1):
    """
    Remove volume flyback frame (black frame) from each volume.

    Parameters:
    - frames (np.ndarray): 3D array (frames, H, W)
    - frames_per_volume (int): Total frames in one volume (including flyback)
    - flyback_frames (int): Number of flyback frames per volume

    Returns:
    - np.ndarray: Cleaned 3D array
    """
    total_frames = len(frames)
    if total_frames % frames_per_volume != 0:
        print(f"⚠️ Warning: {total_frames} frames not divisible by {frames_per_volume}. Some frames may be dropped.")

    # Build index to keep frames except flyback frames
    keep_idx = np.array([
        i for i in range(total_frames)
        if (i % frames_per_volume) < (frames_per_volume - vflyback_frames)])



    return frames[keep_idx]


def correct_negative_values_mp_safe(frames, num_chunks=5):
    """
   Correct negative pixel values using multiprocessing.

   Parameters:
   - frames (np.ndarray): Original image stack, uint16.
   - num_chunks (int): Number of chunks to split data into for processing.

   Returns:
   - np.ndarray: Corrected image stack, uint16.
    """

    min_value = np.min(frames)
    print(f"  min: {min_value}, max: {np.max(frames)}")

    if min_value >= 0:
        print("  No negative values to correct.")
        return frames.astype(np.uint16)

    offset = abs(min_value)
    corrected = np.empty(frames.shape, dtype=np.uint16)
    chunk_size = int(np.ceil(frames.shape[0] / num_chunks))

    for i in range(num_chunks):
        start = i * chunk_size
        end = min((i + 1) * chunk_size, frames.shape[0])
        chunk = frames[start:end]
        corrected_chunk = correct_chunk_int16_to_uint16(chunk, offset)
        corrected[start:end] = corrected_chunk
        print(f"    Processed chunk {i + 1}/{num_chunks} ({end - start} volumes)")

    print(f"  Corrected negative values by adding offset {offset}.")
    print(f"  New min: {np.min(corrected)}, max: {np.max(corrected)}")
    return corrected

def save_stack(output_path, filename, stack):
    """
    Save image stack as TIFF.

    Parameters:
    - output_path (Path): Directory to save file.
    - filename (str): Output TIFF filename.
    - stack (np.ndarray): Image stack to save.
    """
    output_path.mkdir(parents=True, exist_ok=True)
    tf.imwrite(output_path / filename, stack, photometric='minisblack')


def extract_block_number(tif_file):
    """
    Extract block number from TIFF filename assuming format *_000XX.tif.

    Parameters:
    - tif_file (Path): TIFF file.

    Returns:
    - int or None: Block number.
    """
    match = re.search(r"_(\d{5})\.tif$", tif_file.name)
    if match:
        return int(match.group(1))
    else:
        return None


def concatenate_blocks(fish_id, input_base, protocol, blocks=None, n_planes=None, n_frames_per_plane=None, volume_flyback_frames=1, remove_first_frame=False):
    """
    Load and concatenate selected blocks. For resonant protocol, also remove flyback and reshape.

    Parameters:
    - fish_id (str): Fish ID.
    - input_base (Path): Root input directory.
    - protocol (str): 'resonant' or 'linear'.
    - blocks (list[int] or None): Blocks to include.
    - n_planes (int): Number of planes (only for resonant).
    - n_frames_per_plane (int): Frames per plane (only for resonant).
    - volume flyback_frames (int): Volume Flyback frames (only for resonant).

    Returns:
    - np.ndarray: Full concatenated image stack.
    """
    raw_folder = Path(input_base) / fish_id / "00_raw"
    tiffs = sorted(raw_folder.glob("*.tif"))

    all_blocks = []
    for tif_file in tiffs:
        if 'anatomy' not in tif_file.name:
            block_number = extract_block_number(tif_file)
            if blocks is not None and block_number not in blocks:
                continue

            print(f"  Loading {tif_file.name}")
            frames = load_tiff_file(tif_file)

            if protocol == "resonant":
                frames_per_volume = n_planes * n_frames_per_plane + volume_flyback_frames
                if volume_flyback_frames > 0:
                    print(f"  Removing {volume_flyback_frames} flyback frames per volume.")
                    # Remove flyback frames and reshape for plane extraction
                    frames = remove_vflyback_frames(frames, frames_per_volume, volume_flyback_frames)

                frames = frames.reshape(-1, n_frames_per_plane, frames.shape[1], frames.shape[2]) # Reshape to (volumes, frames_per_plane, H, W)

                if remove_first_frame:
                    frames = frames[:, 1:, :, :]

            all_blocks.append(frames)

    if not all_blocks:
        raise ValueError("No matching TIFF files found for selected blocks.")

    # Concatenate all loaded blocks into single array
    full_stack = np.concatenate(all_blocks, axis=0)
    print(f"  Full concatenated stack shape: {full_stack.shape}")
    return full_stack

def process_fish(fish_id, input_base, output_base, protocol="resonant", blocks=None, n_planes=None, n_frames_per_plane=None, volume_flyback_frames=1, remove_first_frame=False):
    """
    Process one fish for either resonant or linear protocols.

    Parameters:
    - fish_id (str): Fish ID.
    - input_base (Path): Root input directory.
    - output_base (Path): Output directory.
    - protocol (str): 'resonant' or 'linear'.
    - blocks (list[int] or None): Blocks to include.
    - n_planes (int): Number of planes (only resonant).
    - n_frames_per_plane (int): Frames per plane (only resonant).
    - volume_flyback_frames (int): Volume flyback frames (only resonant).
    - remove_first_frame (bool): Whether to remove the first frame in resonant protocol.
    """
    full_stack = concatenate_blocks(fish_id, input_base, protocol, blocks, n_planes, n_frames_per_plane, volume_flyback_frames, remove_first_frame)
    full_stack = correct_negative_values_mp_safe(full_stack)
    output_path = Path(output_base) / fish_id / "02_preprocessed"

    if protocol == "resonant":
        for plane_idx in range(n_planes):
            # Extract one plane across all volumes
            avg_plane = np.mean(full_stack, axis=1)[plane_idx::n_planes]
            avg_plane = np.round(avg_plane).astype(np.uint16)
            save_stack(output_path, f"{fish_id}_plane{plane_idx}.tif", avg_plane)
            print(f"  Saved plane {plane_idx}")
            del avg_plane
            gc.collect()

        metadata = {
            "protocol": "resonant",
            "n_planes": n_planes,
            "n_frames_per_plane": n_frames_per_plane,
            "blocks": blocks,
            "volume_flyback_frames": volume_flyback_frames,
            "remove_first_frame": remove_first_frame,
            "fish_id": fish_id,
            "output_path": str(output_path),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    elif protocol == "linear":
        save_stack(output_path, f"{fish_id}_stack.tif", full_stack)

        metadata = {
            "protocol": "linear",
            "blocks": blocks,
            "fish_id": fish_id,
            "output_path": str(output_path),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    else:
        raise ValueError(f"Unknown protocol type: {protocol}")

    del full_stack
    gc.collect()

    with open(output_path / f"{fish_id}_preprocessing_metadata.json", "w") as f:
        json.dump(metadata, f, indent=4)

    print(f"✅ Finished processing {fish_id}")

def parallel_preprocess(fish_ids, input_base, output_base, protocol="resonant", blocks=None, n_planes=None, n_frames_per_plane=None, volume_flyback_frames=1, remove_first_frame=False):
    """
    Run preprocessing across multiple fish using multiprocessing.

    Parameters:
    - fish_ids (list[str]): List of fish IDs.
    - input_base (Path): Root input directory.
    - output_base (Path): Output directory.
    - protocol (str): 'resonant' or 'linear'.
    - blocks (list[int] or None): Blocks to include.
    - n_planes (int): Number of planes (only resonant).
    - n_frames_per_plane (int): Frames per plane (only resonant).
    - vflyback_frames (int): Flyback frames (only resonant).
    - remove_first_frame (bool): Whether to remove the first frame in resonant protocol.

    """
    jobs = []
    for fish_id in fish_ids:
        # Prepare arguments for each fish to be processed in parallel
        jobs.append((fish_id, input_base, output_base, protocol, blocks, n_planes, n_frames_per_plane, volume_flyback_frames, remove_first_frame))

    with mp.Pool(processes=mp.cpu_count()) as pool:
        pool.starmap(process_fish, jobs)


if __name__ == "__main__":

    input_path = "E:/Matilde/2p_data/speed_groupsize_thalamus_exp03"
    output_path = "D:/Matilde/2p_data/speed_groupsize_thalamus_exp03"

    selected_fish = [2]
    fish_ids = [f"f{fish}" for fish in selected_fish]

    protocol = "resonant"  # or "linear"

    n_planes = 5
    n_frames_per_plane = 3
    volume_flyback_frames = 0
    remove_first_frame = True  # Waiting time between frames in resonant protocol

    blocks = [2, 3, 4]  # or None if you want to process all blocks

    start_time = time.time()

    parallel_preprocess(
        fish_ids,
        input_base=input_path,
        output_base=output_path,
        protocol=protocol,
        blocks=blocks,
        n_planes=n_planes,
        n_frames_per_plane=n_frames_per_plane,
        volume_flyback_frames=volume_flyback_frames,
        remove_first_frame=remove_first_frame
    )

    elapsed = time.time() - start_time
    print(f"⏱️ Finished full processing in {elapsed/60:.2f} min.\n")
