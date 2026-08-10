from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

import numpy as np
import SimpleITK as sitk
import tifffile

from preprocessing.anatomy_polarity import discover_anatomy, load_model, predict_fish, train_from_raw_metadata
from preprocessing.spatial_preprocessing import (
    apply_canonical_xy,
    preprocess_anatomy,
    read_anatomy_pages,
    read_raw_metadata_polarity,
    resolve_polarity,
)


def _accepted_anatomy(fish: Path) -> Path:
    expected = fish / "02_reg" / "00_preprocessing" / "2p_anatomy" / f"{fish.name}_anatomy_2P_GCaMP.nrrd"
    if not expected.exists():
        raise FileNotFoundError(f"Accepted anatomy NRRD not found: {expected}")
    return expected


def _sample_functional(fish: Path, pages: int = 25) -> tuple[Path, np.ndarray]:
    candidates = sorted(
        path for path in (fish / "01_raw" / "2p" / "functional").glob("*.tif*")
        if "anatomy" not in path.name.lower()
    )
    if not candidates:
        raise FileNotFoundError(f"No raw functional TIFF found for {fish.name}")
    with tifffile.TiffFile(candidates[0]) as tif:
        stack = np.stack([np.asarray(page.asarray()) for page in tif.pages[:pages]])
    return candidates[0], stack


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--microscopy-root", type=Path, required=True)
    parser.add_argument("--fish-id", default="L395_f11")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-npz", type=Path)
    parser.add_argument("--model-validation-json", type=Path)
    args = parser.parse_args()
    output = args.output_dir
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Validation output is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    fish = args.microscopy_root / args.fish_id

    if args.model_npz is not None:
        model = load_model(args.model_npz)
        validation = json.loads(args.model_validation_json.read_text()) if args.model_validation_json else []
    else:
        model, validation = train_from_raw_metadata(args.microscopy_root, exclude_prefixes=("L427",))
    prediction = predict_fish(model, fish)
    resolution = resolve_polarity(fish, classifier_prediction=asdict(prediction))
    raw_metadata_polarity, raw_metadata_source = read_raw_metadata_polarity(fish)

    accepted_path = _accepted_anatomy(fish)
    accepted_image = sitk.ReadImage(str(accepted_path))
    accepted = sitk.GetArrayFromImage(accepted_image)
    accepted_spacing = tuple(float(value) for value in accepted_image.GetSpacing())
    raw_path = discover_anatomy(fish)
    raw, _ = read_anatomy_pages(raw_path)
    source_spacing = (
        accepted_spacing[0] * accepted.shape[2] / raw.shape[2],
        accepted_spacing[1] * accepted.shape[1] / raw.shape[1],
        accepted_spacing[2],
    )
    candidate_path = output / f"{fish.name}_anatomy_2P_GCaMP.nrrd"
    anatomy_record = preprocess_anatomy(
        anatomy_path=raw_path,
        output_path=candidate_path,
        polarity=resolution.polarity,
        source_spacing_xyz_um=source_spacing,
        target_xy_shape=tuple(int(value) for value in accepted.shape[-2:]),
    )
    candidate_image = sitk.ReadImage(str(candidate_path))
    candidate = sitk.GetArrayFromImage(candidate_image)
    candidate_spacing = tuple(float(value) for value in candidate_image.GetSpacing())
    anatomy_comparisons = {}
    for name, transformed in {
        "identity": candidate,
        "flipX": np.flip(candidate, axis=-1),
        "flipY": np.flip(candidate, axis=-2),
        "flipZ": np.flip(candidate, axis=0),
        "flipZX": np.flip(candidate, axis=(0, -1)),
        "flipZY": np.flip(candidate, axis=(0, -2)),
    }.items():
        difference = np.abs(transformed.astype(np.int16) - accepted.astype(np.int16))
        anatomy_comparisons[name] = {
            "exact": bool(np.array_equal(transformed, accepted)),
            "mean_abs_difference": float(difference.mean()),
            "max_abs_difference": int(difference.max()),
        }
    legacy_uint8_tiff = accepted_path.with_name(f"{fish.name}_anatomy_00001_uint8.tif")
    legacy_tiff_comparisons = None
    if legacy_uint8_tiff.exists():
        legacy_array = tifffile.imread(legacy_uint8_tiff)
        legacy_tiff_comparisons = {
            "candidate_equals_legacy_tiff": bool(np.array_equal(candidate, legacy_array)),
            "candidate_equals_legacy_tiff_flipZ": bool(np.array_equal(candidate, np.flip(legacy_array, axis=0))),
            "accepted_nrrd_equals_legacy_tiff": bool(np.array_equal(accepted, legacy_array)),
            "accepted_nrrd_equals_legacy_tiff_flipZ": bool(np.array_equal(accepted, np.flip(legacy_array, axis=0))),
        }

    functional_path, functional_sample = _sample_functional(fish)
    direct = apply_canonical_xy(functional_sample, resolution.polarity)
    if resolution.polarity == "north":
        historical = np.flip(np.flip(functional_sample, axis=-2), axis=-1)
        historical = np.flip(historical, axis=-1)
    else:
        historical = np.flip(functional_sample, axis=-1)

    report = {
        "fish_id": fish.name,
        "excluded_prefixes": ["L427"],
        "raw_metadata_polarity": raw_metadata_polarity,
        "raw_metadata_source": raw_metadata_source,
        "classifier_prediction": asdict(prediction),
        "resolved_polarity": resolution.polarity,
        "resolved_source": resolution.source,
        "reference_fish_ids": list(model.reference_fish_ids),
        "calibration_floor": model.calibration_floor,
        "group_validation": validation,
        "group_validation_all_correct": all(bool(row["correct"]) for row in validation),
        "group_validation_all_unanimous": all(bool(row["unanimous"]) for row in validation),
        "anatomy": {
            "raw_path": str(raw_path),
            "accepted_path": str(accepted_path),
            "candidate_path": str(candidate_path),
            "shape_equal": candidate.shape == accepted.shape,
            "dtype_equal": candidate.dtype == accepted.dtype,
            "spacing_equal": bool(np.allclose(candidate_spacing, accepted_spacing, atol=1e-9, rtol=0)),
            "array_exact_equal": bool(np.array_equal(candidate, accepted)),
            "max_abs_difference": int(np.max(np.abs(candidate.astype(np.int16) - accepted.astype(np.int16)))),
            "candidate_to_accepted_comparisons": anatomy_comparisons,
            "legacy_uint8_tiff_path": str(legacy_uint8_tiff) if legacy_uint8_tiff.exists() else None,
            "legacy_uint8_tiff_comparisons": legacy_tiff_comparisons,
            "candidate_record": anatomy_record,
        },
        "functional_transform": {
            "sample_path": str(functional_path),
            "sample_shape": list(functional_sample.shape),
            "direct_equals_historical_effective_transform": bool(np.array_equal(direct, historical)),
            "reference_mean_parity": bool(np.array_equal(direct.mean(axis=0), historical.mean(axis=0))),
        },
    }
    report["status"] = "pass" if (
        prediction.status == "predicted"
        and resolution.polarity == "south"
        and report["group_validation_all_correct"]
        and report["group_validation_all_unanimous"]
        and report["anatomy"]["shape_equal"]
        and report["anatomy"]["dtype_equal"]
        and report["anatomy"]["spacing_equal"]
        and report["anatomy"]["array_exact_equal"]
        and report["functional_transform"]["direct_equals_historical_effective_transform"]
    ) else "review"
    report_path = output / "validation_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(report_path)}, indent=2))


if __name__ == "__main__":
    main()
