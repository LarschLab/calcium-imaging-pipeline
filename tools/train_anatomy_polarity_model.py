from __future__ import annotations

import argparse
import json
from pathlib import Path

from preprocessing.anatomy_polarity import save_model, train_from_raw_metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the anatomy polarity model from raw fish_orientation metadata")
    parser.add_argument("--microscopy-root", type=Path, required=True)
    parser.add_argument("--output-model", type=Path, required=True)
    parser.add_argument("--output-validation", type=Path, required=True)
    args = parser.parse_args()
    model, validation = train_from_raw_metadata(args.microscopy_root, exclude_prefixes=("L427",))
    save_model(model, args.output_model)
    args.output_validation.parent.mkdir(parents=True, exist_ok=True)
    args.output_validation.write_text(json.dumps(validation, indent=2), encoding="utf-8")
    print(json.dumps({
        "reference_fish_count": len(model.reference_fish_ids),
        "validation_count": len(validation),
        "validation_correct": sum(bool(row["correct"]) for row in validation),
        "validation_unanimous": sum(bool(row["unanimous"]) for row in validation),
        "calibration_floor": model.calibration_floor,
    }, indent=2))


if __name__ == "__main__":
    main()
