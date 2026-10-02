"""Command-line entry point for Suite2P with optional NCC review gating."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from preprocessing.motion_segmentation_suite2p import run_suite2p_for_fish


def build_parser():
    """Describe Suite2P, plane-selection, and NCC gate command-line options.

    Returns:
        argparse.ArgumentParser: Parser configured with the Suite2P run
        options (fish directory, ops file, FPS, planes, storage paths) and
        the NCC gate options (gate mode, output directory, worker count,
        Python runtime).
    """
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


def main(argv=None):
    """Run the gated Suite2P workflow and print a machine-readable result.

    Args:
        argv (list[str] | None): Command-line arguments to parse, excluding
            the program name. Defaults to None, which makes argparse read
            from ``sys.argv``.

    Returns:
        int: Process exit code; always 0 on success.
    """
    args = build_parser().parse_args(argv)
    ops = np.load(args.ops_path, allow_pickle=True).item()
    result = run_suite2p_for_fish(
        args.fish_dir,
        ops,
        args.planes,
        args.fps,
        fast_disk=args.fast_disk,
        storage_root=args.storage_root,
        drift_check=args.gate_mode,
        drift_output_dir=args.ncc_output_dir,
        drift_workers=args.ncc_workers,
        drift_python=args.ncc_python,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
