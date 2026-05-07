from pathlib import Path
import tifffile as tf
import numpy as np
import json
import time
import gc
import re
import multiprocessing as mp


class SingleLineProgress:
    """Minimal carriage-return progress display for long TIFF scans."""

    def __init__(self, label, total):
        self.label = label
        self.total = max(int(total), 1)
        self.current = 0
        self.start_time = time.time()
        self.last_text_len = 0

    def update(self, current=None, detail=""):
        if current is None:
            self.current += 1
        else:
            self.current = current

        pct = min(100.0, 100.0 * self.current / self.total)
        elapsed = time.time() - self.start_time
        text = f"{self.label}: {self.current}/{self.total} ({pct:5.1f}%) elapsed {elapsed:6.1f}s"
        if detail:
            text += f" | {detail}"

        padding = " " * max(0, self.last_text_len - len(text))
        print(f"\r{text}{padding}", end="", flush=True)
        self.last_text_len = len(text)

    def finish(self):
        if self.current < self.total:
            self.update(self.total)
        print()


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


def load_tiff_file(filepath, n_planes, n_frames_per_plane):
    """
    Load a multi-page TIFF file into a 3D NumPy array.

    Parameters:
    - filepath (Path): Path to the TIFF file.

    Returns:
    - np.ndarray: 3D array (frames, height, width).
    """

    frames = []
    with tf.TiffFile(filepath) as tif:
        for i, page in enumerate(tif.pages):
            try:
                arr = page.asarray()
                frames.append(arr)
            except Exception as e:
                print(f"⚠️ {filepath.name}: stopped at frame {i} due to error: {e}")
                # frame to remove to make it divisible by n_planes * n_frames_per_plane
                to_remove = len(frames)%(n_planes * n_frames_per_plane)
                frames = frames[:-to_remove]
                break  # stop reading further pages
    if not frames:
        raise ValueError(f"{filepath.name}: no readable frames")

    return np.stack(frames)

    # with tf.TiffFile(filepath) as tif:
    #     return np.stack([page.asarray() for page in tif.pages])


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
    tf.imwrite(output_path / filename, stack, photometric="minisblack")


def clear_resonant_plane_outputs(output_path, fish_id):
    """
    Remove existing stage-2 plane TIFFs for one fish before rewriting them.
    """
    output_path.mkdir(parents=True, exist_ok=True)
    for path in output_path.glob(f"{fish_id}_plane*.tif"):
        path.unlink()


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


def parse_functional_tiff_name(fish_id, tif_file):
    """
    Parse raw functional TIFF names into session label and block number.

    Expected names are either `<fish>_00001.tif` for the first session or
    `<fish>_r2_00001.tif` for later sessions.
    """
    pattern = rf"^{re.escape(fish_id)}(?:_r(?P<session>\d+))?_(?P<block>\d{{5}})\.tif$"
    match = re.match(pattern, tif_file.name)
    if not match:
        return None

    session_number = int(match.group("session") or 1)
    block_number = int(match.group("block"))
    return {
        "session_label": f"r{session_number}",
        "session_number": session_number,
        "block_number": block_number,
    }


def get_functional_tiff_sessions(fish_id, input_base, blocks=None):
    """
    Return selected functional TIFF files grouped by detected imaging session.
    """
    raw_folder = Path(input_base) / fish_id / "01_raw/2p/functional"
    sessions = {}

    for tif_file in sorted(raw_folder.glob("*.tif")):
        if "anatomy" in tif_file.name:
            continue

        parsed = parse_functional_tiff_name(fish_id, tif_file)
        if parsed is None:
            continue
        if blocks is not None and parsed["block_number"] not in blocks:
            continue

        session_label = parsed["session_label"]
        sessions.setdefault(
            session_label,
            {
                "session_label": session_label,
                "session_number": parsed["session_number"],
                "tiff_files": [],
            },
        )
        sessions[session_label]["tiff_files"].append(tif_file)

    if not sessions:
        raise ValueError("No matching TIFF files found for selected blocks.")

    grouped = sorted(sessions.values(), key=lambda session: session["session_number"])
    for session in grouped:
        session["tiff_files"].sort(key=lambda path: parse_functional_tiff_name(fish_id, path)["block_number"])
    return grouped


def get_functional_tiffs(fish_id, input_base, blocks=None):
    """
    Return selected non-anatomy functional TIFF files for one fish.
    """
    sessions = get_functional_tiff_sessions(fish_id, input_base, blocks)
    return [tif_file for session in sessions for tif_file in session["tiff_files"]]


def count_tiff_pages(tiff_files):
    """
    Count pages in selected TIFF files without reading image data.
    """
    total = 0
    for tif_file in tiff_files:
        with tf.TiffFile(tif_file) as tif:
            total += len(tif.pages)
    return total


def corrected_uint16_frame(frame, offset):
    """
    Apply the pipeline's negative-value offset correction to one frame.
    """
    if offset <= 0:
        return frame.astype(np.uint16, copy=False)

    corrected = frame.astype(np.int32)
    corrected += offset
    np.clip(corrected, 0, 65535, out=corrected)
    return corrected.astype(np.uint16)


def correct_stack_with_offset(frames, offset):
    """
    Apply a known negative-value offset to an in-memory stack.
    """
    if offset <= 0:
        return frames.astype(np.uint16)
    corrected = frames.astype(np.int32)
    corrected += offset
    np.clip(corrected, 0, 65535, out=corrected)
    return corrected.astype(np.uint16)


def update_min_max(frame, min_value, max_value):
    """
    Update scalar min/max values from one frame.
    """
    frame_min = int(np.min(frame))
    frame_max = int(np.max(frame))

    if min_value is None or frame_min < min_value:
        min_value = frame_min
    if max_value is None or frame_max > max_value:
        max_value = frame_max

    return min_value, max_value


def scan_resonant_min_max(tiff_files, n_planes, n_frames_per_plane, volume_flyback_frames=1, remove_first_frame=False, progress=True):
    """
    Stream resonant TIFFs once and compute min/max after frame filtering.
    """
    frames_per_volume = n_planes * n_frames_per_plane + volume_flyback_frames
    total_pages = count_tiff_pages(tiff_files)
    progress_line = SingleLineProgress("Pass 1/2 scan", total_pages) if progress else None
    min_value = None
    max_value = None
    raw_pages_seen = 0
    kept_group = []

    try:
        for tif_file in tiff_files:
            with tf.TiffFile(tif_file) as tif:
                for page_idx, page in enumerate(tif.pages):
                    raw_pages_seen += 1
                    if progress_line:
                        progress_line.update(raw_pages_seen, tif_file.name)

                    if volume_flyback_frames > 0 and (page_idx % frames_per_volume) >= (frames_per_volume - volume_flyback_frames):
                        continue

                    kept_group.append(page.asarray())
                    if len(kept_group) != n_frames_per_plane:
                        continue

                    frames_to_scan = kept_group[1:] if remove_first_frame else kept_group
                    if not frames_to_scan:
                        raise ValueError("remove_first_frame=True leaves no frames to average.")

                    for frame in frames_to_scan:
                        min_value, max_value = update_min_max(frame, min_value, max_value)
                    kept_group = []

            if kept_group:
                raise ValueError(f"{tif_file.name}: kept frame count is not divisible by n_frames_per_plane.")
    finally:
        if progress_line:
            progress_line.finish()

    if min_value is None:
        raise ValueError("No frames remained after flyback/first-frame filtering.")

    return min_value, max_value


def write_resonant_streaming(
    tiff_files,
    output_path,
    fish_id,
    n_planes,
    n_frames_per_plane,
    offset,
    volume_flyback_frames=1,
    remove_first_frame=False,
    progress=True,
    plane_offset=0,
):
    """
    Stream resonant TIFFs and append averaged frames directly to per-plane TIFFs.
    """
    frames_per_volume = n_planes * n_frames_per_plane + volume_flyback_frames
    total_pages = count_tiff_pages(tiff_files)
    progress_line = SingleLineProgress(f"Pass 2/2 write planes {plane_offset}-{plane_offset + n_planes - 1}", total_pages) if progress else None
    writers = []
    raw_pages_seen = 0
    group_index = 0
    kept_group = []

    output_path.mkdir(parents=True, exist_ok=True)
    for local_plane_idx in range(n_planes):
        plane_idx = plane_offset + local_plane_idx
        out_file = output_path / f"{fish_id}_plane{plane_idx}.tif"
        if out_file.exists():
            out_file.unlink()
        writers.append(tf.TiffWriter(out_file, bigtiff=True))

    try:
        for tif_file in tiff_files:
            with tf.TiffFile(tif_file) as tif:
                for page_idx, page in enumerate(tif.pages):
                    raw_pages_seen += 1
                    if progress_line:
                        progress_line.update(raw_pages_seen, tif_file.name)

                    if volume_flyback_frames > 0 and (page_idx % frames_per_volume) >= (frames_per_volume - volume_flyback_frames):
                        continue

                    kept_group.append(page.asarray())
                    if len(kept_group) != n_frames_per_plane:
                        continue

                    frames_to_average = kept_group[1:] if remove_first_frame else kept_group
                    if not frames_to_average:
                        raise ValueError("remove_first_frame=True leaves no frames to average.")

                    corrected = [corrected_uint16_frame(frame, offset).astype(np.float64) for frame in frames_to_average]
                    avg_frame = np.round(np.mean(corrected, axis=0)).astype(np.uint16)
                    local_plane_idx = group_index % n_planes
                    writers[local_plane_idx].write(avg_frame, photometric="minisblack", contiguous=True)
                    group_index += 1
                    kept_group = []

            if kept_group:
                raise ValueError(f"{tif_file.name}: kept frame count is not divisible by n_frames_per_plane.")
    finally:
        for writer in writers:
            writer.close()
        if progress_line:
            progress_line.finish()


def scan_linear_min_max(tiff_files, progress=True):
    """
    Stream linear TIFFs once and compute min/max across all selected frames.
    """
    total_pages = count_tiff_pages(tiff_files)
    progress_line = SingleLineProgress("Pass 1/2 scan", total_pages) if progress else None
    min_value = None
    max_value = None
    pages_seen = 0

    try:
        for tif_file in tiff_files:
            with tf.TiffFile(tif_file) as tif:
                for page in tif.pages:
                    pages_seen += 1
                    if progress_line:
                        progress_line.update(pages_seen, tif_file.name)
                    min_value, max_value = update_min_max(page.asarray(), min_value, max_value)
    finally:
        if progress_line:
            progress_line.finish()

    if min_value is None:
        raise ValueError("No readable frames found.")

    return min_value, max_value


def write_linear_streaming(tiff_files, output_path, fish_id, offset, progress=True):
    """
    Stream linear TIFFs and append corrected frames directly to one TIFF stack.
    """
    total_pages = count_tiff_pages(tiff_files)
    progress_line = SingleLineProgress("Pass 2/2 write", total_pages) if progress else None
    output_path.mkdir(parents=True, exist_ok=True)
    out_file = output_path / f"{fish_id}_stack.tif"
    if out_file.exists():
        out_file.unlink()

    pages_seen = 0
    try:
        with tf.TiffWriter(out_file, bigtiff=True) as writer:
            for tif_file in tiff_files:
                with tf.TiffFile(tif_file) as tif:
                    for page in tif.pages:
                        pages_seen += 1
                        if progress_line:
                            progress_line.update(pages_seen, tif_file.name)
                        writer.write(corrected_uint16_frame(page.asarray(), offset), photometric="minisblack", contiguous=True)
    finally:
        if progress_line:
            progress_line.finish()


def resolve_worker_count(workers, task_count):
    """
    Resolve a user worker setting against available independent tasks.
    """
    task_count = max(int(task_count), 1)
    if workers in (None, "", "auto"):
        requested = min(mp.cpu_count(), task_count)
    else:
        requested = int(workers)
    if requested <= 0:
        raise ValueError("workers must be positive or 'auto'.")
    return max(1, min(requested, task_count))


def _scan_resonant_session_worker(args):
    session_label, tiff_files, n_planes, n_frames_per_plane, volume_flyback_frames, remove_first_frame = args
    print(f"[{session_label}] scanning {len(tiff_files)} TIFF file(s)", flush=True)
    min_value, max_value = scan_resonant_min_max(
        tiff_files,
        n_planes,
        n_frames_per_plane,
        volume_flyback_frames=volume_flyback_frames,
        remove_first_frame=remove_first_frame,
        progress=False,
    )
    return session_label, min_value, max_value


def _write_resonant_session_worker(args):
    (
        session_label,
        tiff_files,
        output_path,
        fish_id,
        n_planes,
        n_frames_per_plane,
        offset,
        volume_flyback_frames,
        remove_first_frame,
        plane_offset,
    ) = args
    print(f"[{session_label}] writing output planes {plane_offset}-{plane_offset + n_planes - 1}", flush=True)
    write_resonant_streaming(
        tiff_files,
        output_path,
        fish_id,
        n_planes,
        n_frames_per_plane,
        offset,
        volume_flyback_frames=volume_flyback_frames,
        remove_first_frame=remove_first_frame,
        progress=False,
        plane_offset=plane_offset,
    )


def concatenate_tiff_files(tiff_files, protocol, n_planes=None, n_frames_per_plane=None, volume_flyback_frames=1, remove_first_frame=False):
    """
    Load and concatenate the provided TIFF files.
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

            frames = frames.reshape(-1, n_frames_per_plane, frames.shape[1], frames.shape[2])

            if remove_first_frame:
                frames = frames[:, 1:, :, :]

        all_blocks.append(frames)

    if not all_blocks:
        raise ValueError("No matching TIFF files found for selected blocks.")

    full_stack = np.concatenate(all_blocks, axis=0)
    print(f"  Full concatenated stack shape: {full_stack.shape}")
    return full_stack


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
    tiffs = get_functional_tiffs(fish_id, input_base, blocks)
    return concatenate_tiff_files(tiffs, protocol, n_planes, n_frames_per_plane, volume_flyback_frames, remove_first_frame)

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
    output_path = Path(output_base) / fish_id / "02_reg/00_preprocessing/2p_functional/01_individualPlanes"
    output_path.mkdir(parents=True, exist_ok=True)

    if protocol == "resonant":
        clear_resonant_plane_outputs(output_path, fish_id)
        sessions = get_functional_tiff_sessions(fish_id, input_base, blocks)
        session_stacks = []
        global_min = None
        global_max = None
        for session_index, session in enumerate(sessions):
            full_stack = concatenate_tiff_files(
                session["tiff_files"],
                protocol,
                n_planes,
                n_frames_per_plane,
                volume_flyback_frames,
                remove_first_frame,
            )
            global_min, global_max = update_min_max(full_stack, global_min, global_max)
            session_stacks.append((session_index, session, full_stack))

        offset = abs(global_min) if global_min < 0 else 0
        session_metadata = []
        for session_index, session, full_stack in session_stacks:
            full_stack = correct_stack_with_offset(full_stack, offset)
            plane_offset = session_index * n_planes
            output_planes = []
            for local_plane_idx in range(n_planes):
                plane_idx = plane_offset + local_plane_idx
                avg_plane = np.mean(full_stack, axis=1)[local_plane_idx::n_planes]
                avg_plane = np.round(avg_plane).astype(np.uint16)
                save_stack(output_path, f"{fish_id}_plane{plane_idx}.tif", avg_plane)
                output_planes.append(plane_idx)
                print(f"  Saved plane {plane_idx}")
                del avg_plane
                gc.collect()
            session_metadata.append(
                {
                    "session_label": session["session_label"],
                    "session_number": session["session_number"],
                    "plane_offset": plane_offset,
                    "output_planes": output_planes,
                    "selected_tiffs": [str(path) for path in session["tiff_files"]],
                }
            )
            del full_stack
            gc.collect()

        metadata = {
            "protocol": "resonant",
            "preprocessing_mode": "full_memory",
            "n_planes": n_planes,
            "total_output_planes": n_planes * len(sessions),
            "n_frames_per_plane": n_frames_per_plane,
            "blocks": blocks,
            "volume_flyback_frames": volume_flyback_frames,
            "remove_first_frame": remove_first_frame,
            "fish_id": fish_id,
            "output_path": str(output_path),
            "sessions": session_metadata,
            "global_min": int(global_min),
            "global_max": int(global_max),
            "negative_offset_applied": int(offset),
            "photometric": "minisblack",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    elif protocol == "linear":
        full_stack = concatenate_blocks(fish_id, input_base, protocol, blocks, n_planes, n_frames_per_plane, volume_flyback_frames, remove_first_frame)
        full_stack = correct_negative_values_mp_safe(full_stack)
        save_stack(output_path, f"{fish_id}_stack.tif", full_stack)

        metadata = {
            "protocol": "linear",
            "blocks": blocks,
            "fish_id": fish_id,
            "output_path": str(output_path),
            "photometric": "minisblack",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        del full_stack
        gc.collect()

    else:
        raise ValueError(f"Unknown protocol type: {protocol}")

    with open(output_path / f"{fish_id}_preprocessing_metadata.json", "w") as f:
        json.dump(metadata, f, indent=4)

    print(f"✅ Finished processing {fish_id}")


def process_fish_streaming(
    fish_id,
    input_base,
    output_base,
    protocol="resonant",
    blocks=None,
    n_planes=None,
    n_frames_per_plane=None,
    volume_flyback_frames=1,
    remove_first_frame=False,
    progress=True,
    workers=1,
):
    """
    Process one fish by streaming TIFF pages from disk instead of loading full blocks.

    This writes the same canonical outputs as process_fish while keeping memory
    proportional to a small frame group rather than the selected raw TIFF size.
    """
    output_path = Path(output_base) / fish_id / "02_reg/00_preprocessing/2p_functional/01_individualPlanes"
    output_path.mkdir(parents=True, exist_ok=True)

    if protocol == "resonant":
        if n_planes is None or n_frames_per_plane is None:
            raise ValueError("n_planes and n_frames_per_plane are required for resonant streaming preprocessing.")

        clear_resonant_plane_outputs(output_path, fish_id)
        sessions = get_functional_tiff_sessions(fish_id, input_base, blocks)
        worker_count = resolve_worker_count(workers, len(sessions))
        print(f"Streaming {fish_id}: {sum(len(session['tiff_files']) for session in sessions)} TIFF file(s) across {len(sessions)} session(s)")
        print(f"Using {worker_count} preprocessing worker(s)")

        scan_jobs = [
            (
                session["session_label"],
                session["tiff_files"],
                n_planes,
                n_frames_per_plane,
                volume_flyback_frames,
                remove_first_frame,
            )
            for session in sessions
        ]
        if worker_count > 1:
            with mp.Pool(processes=worker_count) as pool:
                scan_results = pool.map(_scan_resonant_session_worker, scan_jobs)
        else:
            scan_results = []
            for job in scan_jobs:
                scan_results.append(
                    (
                        job[0],
                        *scan_resonant_min_max(
                            job[1],
                            n_planes,
                            n_frames_per_plane,
                            volume_flyback_frames=volume_flyback_frames,
                            remove_first_frame=remove_first_frame,
                            progress=progress,
                        ),
                    )
                )

        min_value = min(result[1] for result in scan_results)
        max_value = max(result[2] for result in scan_results)
        offset = abs(min_value) if min_value < 0 else 0
        print(f"  min: {min_value}, max: {max_value}")
        if offset:
            print(f"  Correcting negative values by adding offset {offset}.")
        else:
            print("  No negative values to correct.")

        write_jobs = []
        session_metadata = []
        for session_index, session in enumerate(sessions):
            plane_offset = session_index * n_planes
            output_planes = list(range(plane_offset, plane_offset + n_planes))
            write_jobs.append(
                (
                    session["session_label"],
                    session["tiff_files"],
                    output_path,
                    fish_id,
                    n_planes,
                    n_frames_per_plane,
                    offset,
                    volume_flyback_frames,
                    remove_first_frame,
                    plane_offset,
                )
            )
            session_metadata.append(
                {
                    "session_label": session["session_label"],
                    "session_number": session["session_number"],
                    "plane_offset": plane_offset,
                    "output_planes": output_planes,
                    "selected_tiffs": [str(path) for path in session["tiff_files"]],
                }
            )

        if worker_count > 1:
            with mp.Pool(processes=worker_count) as pool:
                pool.map(_write_resonant_session_worker, write_jobs)
        else:
            for job in write_jobs:
                write_resonant_streaming(
                    job[1],
                    output_path,
                    fish_id,
                    n_planes,
                    n_frames_per_plane,
                    offset,
                    volume_flyback_frames=volume_flyback_frames,
                    remove_first_frame=remove_first_frame,
                    progress=progress,
                    plane_offset=job[9],
                )

        metadata = {
            "protocol": "resonant",
            "preprocessing_mode": "streaming_two_pass",
            "n_planes": n_planes,
            "total_output_planes": n_planes * len(sessions),
            "n_frames_per_plane": n_frames_per_plane,
            "blocks": blocks,
            "volume_flyback_frames": volume_flyback_frames,
            "remove_first_frame": remove_first_frame,
            "fish_id": fish_id,
            "output_path": str(output_path),
            "sessions": session_metadata,
            "global_min": int(min_value),
            "global_max": int(max_value),
            "negative_offset_applied": int(offset),
            "workers": worker_count,
            "photometric": "minisblack",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    elif protocol == "linear":
        tiff_files = get_functional_tiffs(fish_id, input_base, blocks)
        print(f"Streaming {fish_id}: {len(tiff_files)} TIFF file(s)")
        min_value, max_value = scan_linear_min_max(tiff_files, progress=progress)
        offset = abs(min_value) if min_value < 0 else 0
        print(f"  min: {min_value}, max: {max_value}")
        if offset:
            print(f"  Correcting negative values by adding offset {offset}.")
        else:
            print("  No negative values to correct.")

        write_linear_streaming(tiff_files, output_path, fish_id, offset, progress=progress)

        metadata = {
            "protocol": "linear",
            "preprocessing_mode": "streaming_two_pass",
            "blocks": blocks,
            "fish_id": fish_id,
            "output_path": str(output_path),
            "selected_tiffs": [str(path) for path in tiff_files],
            "global_min": int(min_value),
            "global_max": int(max_value),
            "negative_offset_applied": int(offset),
            "photometric": "minisblack",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    else:
        raise ValueError(f"Unknown protocol type: {protocol}")

    with open(output_path / f"{fish_id}_preprocessing_metadata.json", "w") as f:
        json.dump(metadata, f, indent=4)

    gc.collect()
    print(f"✅ Finished streaming preprocessing for {fish_id}")


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

    input_path = "F:/Matilde/2p_data"
    output_path = "F:/Matilde/2p_data"

    fish_ids = ["L500_f01"]

    protocol = "resonant"  # or "linear"

    n_planes = 5
    n_frames_per_plane = 3
    volume_flyback_frames = 0
    remove_first_frame = True  # Waiting time between frames in resonant protocol

    blocks = [2, 3]  # or None if you want to process all blocks

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
