from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import tifffile as tf


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "preprocessing"))

import preprocessing_tiff  # noqa: E402


def write_raw_tiff(base: Path, fish_id: str, filename: str, stack: np.ndarray) -> None:
    raw_dir = base / fish_id / "01_raw/2p/functional"
    raw_dir.mkdir(parents=True, exist_ok=True)
    tf.imwrite(raw_dir / filename, stack, photometric="minisblack")


def read_tiff(path: Path) -> np.ndarray:
    data = tf.imread(path)
    if data.ndim == 2:
        return data[np.newaxis, ...]
    return data


class StreamingPreprocessingTests(unittest.TestCase):
    def test_functional_tiff_sessions_detect_r2_and_block_filter(self) -> None:
        fish_id = "fish01"
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_base = tmp_path / "input"
            stack = np.ones((2, 2, 2), dtype=np.uint16)
            write_raw_tiff(input_base, fish_id, "fish01_00001.tif", stack)
            write_raw_tiff(input_base, fish_id, "fish01_00002.tif", stack)
            write_raw_tiff(input_base, fish_id, "fish01_r2_00001.tif", stack)
            write_raw_tiff(input_base, fish_id, "fish01_r2_00002.tif", stack)

            sessions = preprocessing_tiff.get_functional_tiff_sessions(fish_id, input_base, blocks=[1])

            self.assertEqual([session["session_label"] for session in sessions], ["r1", "r2"])
            self.assertEqual([path.name for path in sessions[0]["tiff_files"]], ["fish01_00001.tif"])
            self.assertEqual([path.name for path in sessions[1]["tiff_files"]], ["fish01_r2_00001.tif"])

    def test_r2_streaming_writes_next_plane_indices_and_grayscale(self) -> None:
        fish_id = "fish01"
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_base = tmp_path / "input"
            output_base = tmp_path / "output"

            r1 = np.array(
                [
                    [[10, 10], [10, 10]],
                    [[20, 20], [20, 20]],
                    [[30, 30], [30, 30]],
                    [[40, 40], [40, 40]],
                ],
                dtype=np.uint16,
            )
            r2 = np.array(
                [
                    [[100, 100], [100, 100]],
                    [[200, 200], [200, 200]],
                    [[300, 300], [300, 300]],
                    [[400, 400], [400, 400]],
                ],
                dtype=np.uint16,
            )
            write_raw_tiff(input_base, fish_id, "fish01_00001.tif", r1)
            write_raw_tiff(input_base, fish_id, "fish01_r2_00001.tif", r2)

            with redirect_stdout(io.StringIO()):
                preprocessing_tiff.process_fish_streaming(
                    fish_id,
                    input_base,
                    output_base,
                    protocol="resonant",
                    n_planes=2,
                    n_frames_per_plane=1,
                    volume_flyback_frames=0,
                    remove_first_frame=False,
                    progress=False,
                    workers=1,
                )

            stream_dir = output_base / fish_id / "02_reg/00_preprocessing/2p_functional/01_individualPlanes"
            np.testing.assert_array_equal(read_tiff(stream_dir / "fish01_plane0.tif"), r1[[0, 2]])
            np.testing.assert_array_equal(read_tiff(stream_dir / "fish01_plane1.tif"), r1[[1, 3]])
            np.testing.assert_array_equal(read_tiff(stream_dir / "fish01_plane2.tif"), r2[[0, 2]])
            np.testing.assert_array_equal(read_tiff(stream_dir / "fish01_plane3.tif"), r2[[1, 3]])

            metadata = json.loads((stream_dir / f"{fish_id}_preprocessing_metadata.json").read_text())
            self.assertEqual(metadata["total_output_planes"], 4)
            self.assertEqual(metadata["sessions"][0]["output_planes"], [0, 1])
            self.assertEqual(metadata["sessions"][1]["output_planes"], [2, 3])
            self.assertEqual(metadata["photometric"], "minisblack")

            with tf.TiffFile(stream_dir / "fish01_plane2.tif") as tif:
                self.assertEqual(tif.pages[0].photometric.name.lower(), "minisblack")

    def test_resonant_streaming_removes_stale_plane_outputs(self) -> None:
        fish_id = "fish01"
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_base = tmp_path / "input"
            output_base = tmp_path / "output"

            stack = np.ones((2, 2, 2), dtype=np.uint16)
            write_raw_tiff(input_base, fish_id, "fish01_00001.tif", stack)
            stream_dir = output_base / fish_id / "02_reg/00_preprocessing/2p_functional/01_individualPlanes"
            stream_dir.mkdir(parents=True)
            (stream_dir / "fish01_plane9.tif").write_bytes(b"stale")

            with redirect_stdout(io.StringIO()):
                preprocessing_tiff.process_fish_streaming(
                    fish_id,
                    input_base,
                    output_base,
                    protocol="resonant",
                    n_planes=2,
                    n_frames_per_plane=1,
                    volume_flyback_frames=0,
                    remove_first_frame=False,
                    progress=False,
                    workers=1,
                )

            self.assertFalse((stream_dir / "fish01_plane9.tif").exists())

    def test_resonant_streaming_matches_full_memory_with_negative_values(self) -> None:
        fish_id = "fish01"
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_base = tmp_path / "input"
            full_base = tmp_path / "full"
            stream_base = tmp_path / "stream"

            block_1 = (np.arange(10 * 3 * 4).reshape(10, 3, 4) - 40).astype(np.int16)
            block_2 = (np.arange(10 * 3 * 4).reshape(10, 3, 4) + 80).astype(np.int16)
            write_raw_tiff(input_base, fish_id, "fish01_00001.tif", block_1)
            write_raw_tiff(input_base, fish_id, "fish01_00002.tif", block_2)

            with redirect_stdout(io.StringIO()):
                preprocessing_tiff.process_fish(
                    fish_id,
                    input_base,
                    full_base,
                    protocol="resonant",
                    blocks=[1, 2],
                    n_planes=2,
                    n_frames_per_plane=2,
                    volume_flyback_frames=1,
                    remove_first_frame=True,
                )
                preprocessing_tiff.process_fish_streaming(
                    fish_id,
                    input_base,
                    stream_base,
                    protocol="resonant",
                    blocks=[1, 2],
                    n_planes=2,
                    n_frames_per_plane=2,
                    volume_flyback_frames=1,
                    remove_first_frame=True,
                    progress=False,
                )

            full_dir = full_base / fish_id / "02_reg/00_preprocessing/2p_functional/01_individualPlanes"
            stream_dir = stream_base / fish_id / "02_reg/00_preprocessing/2p_functional/01_individualPlanes"
            for plane_idx in range(2):
                full_stack = read_tiff(full_dir / f"{fish_id}_plane{plane_idx}.tif")
                stream_stack = read_tiff(stream_dir / f"{fish_id}_plane{plane_idx}.tif")
                np.testing.assert_array_equal(stream_stack, full_stack)

            metadata = json.loads((stream_dir / f"{fish_id}_preprocessing_metadata.json").read_text())
            self.assertEqual(metadata["preprocessing_mode"], "streaming_two_pass")
            self.assertEqual(metadata["negative_offset_applied"], 28)

    def test_linear_streaming_matches_full_memory(self) -> None:
        fish_id = "fish02"
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_base = tmp_path / "input"
            full_base = tmp_path / "full"
            stream_base = tmp_path / "stream"

            block_1 = (np.arange(4 * 3 * 3).reshape(4, 3, 3) - 5).astype(np.int16)
            block_2 = (np.arange(4 * 3 * 3).reshape(4, 3, 3) + 20).astype(np.int16)
            write_raw_tiff(input_base, fish_id, "fish02_00001.tif", block_1)
            write_raw_tiff(input_base, fish_id, "fish02_00002.tif", block_2)

            with redirect_stdout(io.StringIO()):
                preprocessing_tiff.process_fish(
                    fish_id,
                    input_base,
                    full_base,
                    protocol="linear",
                    blocks=[1, 2],
                )
                preprocessing_tiff.process_fish_streaming(
                    fish_id,
                    input_base,
                    stream_base,
                    protocol="linear",
                    blocks=[1, 2],
                    progress=False,
                )

            full_file = full_base / fish_id / "02_reg/00_preprocessing/2p_functional/01_individualPlanes" / f"{fish_id}_stack.tif"
            stream_file = stream_base / fish_id / "02_reg/00_preprocessing/2p_functional/01_individualPlanes" / f"{fish_id}_stack.tif"
            np.testing.assert_array_equal(read_tiff(stream_file), read_tiff(full_file))

    def test_progress_updates_single_terminal_line(self) -> None:
        fish_id = "fish03"
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_base = tmp_path / "input"
            stack = np.arange(5 * 2 * 2).reshape(5, 2, 2).astype(np.uint16)
            write_raw_tiff(input_base, fish_id, "fish03_00001.tif", stack)
            tiffs = preprocessing_tiff.get_functional_tiffs(fish_id, input_base)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                preprocessing_tiff.scan_linear_min_max(tiffs, progress=True)

            output = stdout.getvalue()
            self.assertGreater(output.count("\r"), 1)
            self.assertEqual(output.count("\n"), 1)


if __name__ == "__main__":
    unittest.main()
