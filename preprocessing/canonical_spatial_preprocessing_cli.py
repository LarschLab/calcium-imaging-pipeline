"""Command-line entry point for canonical functional and anatomy preprocessing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from preprocessing.canonical_spatial_preprocessing import run_canonical_spatial_preprocessing


def main() -> None:
    """Read command-line options, run one fish, and print a short result."""
    parser = argparse.ArgumentParser(description="Create canonical functional planes, anatomy NRRD, and spatial manifest")
    parser.add_argument("--source-fish-dir", type=Path, required=True)
    parser.add_argument("--output-fish-dir", type=Path, required=True)
    model_source = parser.add_mutually_exclusive_group(required=True)
    model_source.add_argument("--reference-microscopy-root", type=Path)
    model_source.add_argument("--classifier-model", type=Path)
    parser.add_argument("--classifier-validation", type=Path)
    parser.add_argument("--protocol", choices=("resonant", "linear"), default="resonant")
    parser.add_argument("--blocks", type=int, nargs="*")
    parser.add_argument("--n-planes", type=int)
    parser.add_argument("--n-frames-per-plane", type=int)
    parser.add_argument("--volume-flyback-frames", type=int, default=1)
    parser.add_argument("--remove-first-frame", action="store_true")
    parser.add_argument("--reviewed-polarity", choices=("north", "south"))
    parser.add_argument("--anatomy-xy-spacing-um", type=float)
    parser.add_argument("--anatomy-z-spacing-um", type=float)
    parser.add_argument("--target-xy", type=int, default=750)
    args = parser.parse_args()
    manifest = run_canonical_spatial_preprocessing(
        source_fish_dir=args.source_fish_dir,
        output_fish_dir=args.output_fish_dir,
        reference_microscopy_root=args.reference_microscopy_root,
        protocol=args.protocol,
        blocks=args.blocks,
        n_planes=args.n_planes,
        n_frames_per_plane=args.n_frames_per_plane,
        volume_flyback_frames=args.volume_flyback_frames,
        remove_first_frame=args.remove_first_frame,
        reviewed_polarity=args.reviewed_polarity,
        anatomy_xy_spacing_um=args.anatomy_xy_spacing_um,
        anatomy_z_spacing_um=args.anatomy_z_spacing_um,
        target_xy_shape=(args.target_xy, args.target_xy),
        classifier_model_path=args.classifier_model,
        classifier_validation_path=args.classifier_validation,
    )
    print(json.dumps({"status": manifest["status"], "fish_id": manifest["fish_id"]}, indent=2))


if __name__ == "__main__":
    main()
