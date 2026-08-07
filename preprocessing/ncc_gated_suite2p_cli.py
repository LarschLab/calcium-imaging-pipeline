from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from preprocessing.motion_segmentation_suite2p import process_fish_with_ncc_gate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Suite2P with the opt-in functional-anatomy NCC gate.")
    parser.add_argument("--fish-dir", required=True, type=Path)
    parser.add_argument("--ops-path", required=True, type=Path)
    parser.add_argument("--fps", required=True, type=float)
    parser.add_argument("--planes", required=True, nargs="+", type=int)
    parser.add_argument("--fast-disk", type=Path)
    parser.add_argument("--storage-root", type=Path)
    parser.add_argument("--gate-mode", choices=("report_only", "enforce"), default="report_only")
    parser.add_argument("--ncc-output-dir", type=Path)
    parser.add_argument("--ncc-workers", type=int, default=1)
    parser.add_argument(
        "--ncc-python",
        type=Path,
        help="Scientific Python used for NCC when it differs from the Suite2P runtime.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ops = np.load(args.ops_path, allow_pickle=True).item()
    result = process_fish_with_ncc_gate(
        args.fish_dir,
        ops,
        args.planes,
        args.fps,
        fast_disk=args.fast_disk,
        storage_root=args.storage_root,
        gate_mode=args.gate_mode,
        ncc_output_dir=args.ncc_output_dir,
        ncc_workers=args.ncc_workers,
        ncc_python=args.ncc_python,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
