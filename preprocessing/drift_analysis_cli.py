"""Standalone command for retroactive functional-plane drift analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from preprocessing.drift_analysis import FunctionalAnatomyQCConfig, run_drift_analysis


def build_parser() -> argparse.ArgumentParser:
    """Describe the user-facing command-line options for NCC QC."""
    parser = argparse.ArgumentParser(description="Run NCC scaling, best-Z, and temporal Z-drift QC.")
    parser.add_argument("--fish-dir", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--anatomy-path", type=Path)
    parser.add_argument("--preprocessing-metadata-path", type=Path)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--sampled-frames-per-third", type=int, default=80)
    parser.add_argument("--top-correlated-frames", type=int, default=20)
    parser.add_argument("--local-xy-radius", type=int, default=8)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run NCC QC from command-line arguments and print its manifest."""
    args = build_parser().parse_args(argv)
    fish_dir = args.fish_dir.resolve()
    output_dir = args.output_dir or (
        fish_dir / "03_analysis" / "functional" / "ncc" / "validation" / "current"
    )
    manifest = run_drift_analysis(
        fish_dir=fish_dir,
        output_dir=output_dir,
        anatomy_path=args.anatomy_path,
        preprocessing_metadata_path=args.preprocessing_metadata_path,
        config=FunctionalAnatomyQCConfig(
            workers=args.workers,
            sampled_frames_per_window=args.sampled_frames_per_third,
            top_correlated_frames=args.top_correlated_frames,
            local_xy_radius_px=args.local_xy_radius,
        ),
    )
    print(json.dumps(manifest, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
