from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "preprocessing"))

import preprocessing_tiff  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark preprocessing worker counts on representative real data.")
    parser.add_argument("--data-root", default="/Users/ddharmap/dataProcessing/2p_processing")
    parser.add_argument("--fish-id", default="L758_f02")
    parser.add_argument("--blocks", default="1", help="Comma-separated block numbers to benchmark, or empty for all blocks.")
    parser.add_argument("--workers", default="1,2", help="Comma-separated worker counts to compare.")
    parser.add_argument("--n-planes", type=int, default=5)
    parser.add_argument("--n-frames-per-plane", type=int, default=3)
    parser.add_argument("--volume-flyback-frames", type=int, default=0)
    parser.add_argument("--keep-output", action="store_true")
    return parser.parse_args()


def parse_int_csv(value: str) -> list[int] | None:
    if not value.strip():
        return None
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def main() -> int:
    args = parse_args()
    data_root = Path(args.data_root)
    blocks = parse_int_csv(args.blocks)
    workers_to_test = parse_int_csv(args.workers)
    if not workers_to_test:
        raise ValueError("At least one worker count is required.")

    timings = []
    with tempfile.TemporaryDirectory(prefix="preprocessing_benchmark_") as tmpdir:
        tmp_root = Path(tmpdir)
        for workers in workers_to_test:
            output_root = tmp_root / f"workers_{workers}"
            start = time.perf_counter()
            preprocessing_tiff.process_fish_streaming(
                args.fish_id,
                data_root,
                output_root,
                protocol="resonant",
                blocks=blocks,
                n_planes=args.n_planes,
                n_frames_per_plane=args.n_frames_per_plane,
                volume_flyback_frames=args.volume_flyback_frames,
                remove_first_frame=True,
                progress=False,
                workers=workers,
            )
            elapsed = time.perf_counter() - start
            timings.append((workers, elapsed, output_root))
            print(f"workers={workers}: {elapsed:.2f}s ({elapsed / 60:.2f} min)")

        baseline = timings[0][1]
        for workers, elapsed, _output_root in timings[1:]:
            speedup = baseline / elapsed if elapsed else float("inf")
            pct = (1 - elapsed / baseline) * 100 if baseline else 0
            print(f"workers={workers}: {speedup:.2f}x speedup, {pct:.1f}% faster than workers={timings[0][0]}")

        if args.keep_output:
            kept_root = Path.cwd() / "preprocessing_benchmark_outputs"
            if kept_root.exists():
                shutil.rmtree(kept_root)
            shutil.copytree(tmp_root, kept_root)
            print(f"Kept benchmark outputs at {kept_root}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
