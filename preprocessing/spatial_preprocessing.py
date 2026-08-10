"""Canonical spatial preprocessing for in-vivo two-photon data.

Raw TIFFs remain immutable. Functional movies and anatomy are converted once
from acquisition XY into the codeANTs canonical XY frame. Anatomy is also
reversed in Z for the confocal-registration convention.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
from skimage.transform import resize
import tifffile


SPATIAL_MANIFEST_VERSION = 1
SPATIAL_MANIFEST_NAME = "spatial_preprocessing_manifest.json"
ACQUISITION_XY_FRAME = "two_photon_acquisition_xy"
CANONICAL_XY_FRAME = "codeants_2p_canonical_xy_v1"
ACQUISITION_Z_FRAME = "two_photon_acquisition_z"
REGISTRATION_Z_FRAME = "codeants_confocal_registration_z_v1"


class PolarityResolutionError(RuntimeError):
    """Raised when polarity is absent, invalid, conflicting, or unreviewed."""


@dataclass(frozen=True)
class PolarityPrediction:
    polarity: str | None
    status: str
    model_name: str
    median_margin: float | None = None
    min_abs_margin: float | None = None
    unanimous: bool | None = None
    model_version: str | None = None


@dataclass(frozen=True)
class PolarityResolution:
    polarity: str
    source: str
    status: str
    raw_metadata_source: str | None
    classifier: Mapping[str, Any] | None


def normalize_polarity(value: Any) -> str | None:
    text = "" if value is None else str(value).strip().lower()
    aliases = {
        "n": "north",
        "northward": "north",
        "bottom-left": "north",
        "bottom_left": "north",
        "bottomleft": "north",
        "s": "south",
        "southward": "south",
        "top-right": "south",
        "top_right": "south",
        "topright": "south",
    }
    if text in {"", "none", "nan", "null"}:
        return None
    return aliases.get(text, text)


def _metadata_value(path: Path, parameter: str) -> Any:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return None
    key = parameter.strip().lower()
    for row in rows:
        if len(row) >= 2 and str(row[0]).strip().lower() == key:
            return row[1]
    header = {str(value).strip().lower(): index for index, value in enumerate(rows[0])}
    key_col = next((header[name] for name in ("parameter", "param", "key", "name") if name in header), None)
    value_col = next((header[name] for name in ("value", "val") if name in header), None)
    if key_col is None or value_col is None:
        return None
    for row in rows[1:]:
        if len(row) > max(key_col, value_col) and str(row[key_col]).strip().lower() == key:
            return row[value_col]
    return None


def read_raw_metadata_polarity(fish_dir: str | Path) -> tuple[str | None, str | None]:
    metadata_dir = Path(fish_dir) / "01_raw" / "2p" / "metadata"
    paths = sorted(path for path in metadata_dir.glob("*metadata*.csv") if not path.name.startswith("."))
    found: list[tuple[str, Path]] = []
    invalid: list[str] = []
    for path in paths:
        value = _metadata_value(path, "fish_orientation")
        if value is None:
            continue
        polarity = normalize_polarity(value)
        if polarity not in {"north", "south"}:
            invalid.append(f"{path.name}={value!r}")
        else:
            found.append((polarity, path))
    if invalid:
        raise PolarityResolutionError("Invalid fish_orientation metadata: " + ", ".join(invalid))
    if not found:
        return None, None
    values = {polarity for polarity, _ in found}
    if len(values) != 1:
        details = ", ".join(f"{path.name}={polarity}" for polarity, path in found)
        raise PolarityResolutionError(f"Conflicting fish_orientation metadata: {details}")
    return found[0][0], f"{found[0][1]}:fish_orientation"


def _prediction_dict(prediction: PolarityPrediction | Mapping[str, Any] | None) -> dict[str, Any] | None:
    if prediction is None:
        return None
    return asdict(prediction) if isinstance(prediction, PolarityPrediction) else dict(prediction)


def resolve_polarity(
    fish_dir: str | Path,
    *,
    classifier_prediction: PolarityPrediction | Mapping[str, Any] | None = None,
    reviewed_polarity: str | None = None,
) -> PolarityResolution:
    """Resolve metadata first, classifier second, and fail closed otherwise.

    The classifier is always treated as an independent metadata QC when both
    sources are present. A disagreement requires explicit manual review.
    """
    raw, raw_source = read_raw_metadata_polarity(fish_dir)
    prediction = _prediction_dict(classifier_prediction)
    predicted = normalize_polarity(prediction.get("polarity")) if prediction else None
    predicted_ok = bool(prediction and prediction.get("status") in {"predicted", "accepted"})
    reviewed = normalize_polarity(reviewed_polarity)
    if reviewed_polarity is not None and reviewed not in {"north", "south"}:
        raise PolarityResolutionError(f"Invalid reviewed polarity: {reviewed_polarity!r}")

    if raw in {"north", "south"}:
        if predicted_ok and predicted in {"north", "south"} and predicted != raw:
            if reviewed is None:
                raise PolarityResolutionError(
                    f"Classifier ({predicted}) conflicts with raw metadata ({raw}); manual review is required"
                )
            if reviewed != raw:
                raise PolarityResolutionError(
                    f"Reviewed polarity ({reviewed}) cannot silently override valid raw metadata ({raw})"
                )
        return PolarityResolution(raw, raw_source or "raw_metadata", "resolved", raw_source, prediction)

    if reviewed in {"north", "south"}:
        return PolarityResolution(reviewed, "manual_review", "resolved_after_review", None, prediction)
    if predicted_ok and predicted in {"north", "south"}:
        return PolarityResolution(predicted, "anatomy_classifier", "resolved", None, prediction)
    detail = "no classifier prediction" if prediction is None else f"classifier status={prediction.get('status')!r}"
    raise PolarityResolutionError(f"Missing fish_orientation and {detail}; manual review is required")


def apply_canonical_xy(array: np.ndarray, polarity: str) -> np.ndarray:
    """Apply the direct effective transform to the final Y and X axes."""
    data = np.asarray(array)
    value = normalize_polarity(polarity)
    if data.ndim < 2:
        raise ValueError(f"Expected at least Y,X axes, got shape {data.shape}")
    if value == "north":
        return np.flip(data, axis=-2).copy()
    if value == "south":
        return np.flip(data, axis=-1).copy()
    raise PolarityResolutionError(f"Expected north/south polarity, got {polarity!r}")


def signed_integer_to_uint8(array: np.ndarray) -> tuple[np.ndarray, dict[str, int]]:
    data = np.asarray(array)
    if data.size == 0 or not np.issubdtype(data.dtype, np.integer):
        raise TypeError(f"Expected a non-empty integer stack, got dtype={data.dtype} shape={data.shape}")
    raw_min, raw_max = int(data.min()), int(data.max())
    offset = abs(raw_min) if raw_min < 0 else 0
    corrected = np.clip(data.astype(np.int32) + offset, 0, 65535)
    low, high = int(corrected.min()), int(corrected.max())
    if high <= low:
        output = np.zeros(data.shape, dtype=np.uint8)
    else:
        output = np.clip(np.rint((corrected - low) * (255.0 / (high - low))), 0, 255).astype(np.uint8)
    return output, {
        "raw_min": raw_min,
        "raw_max": raw_max,
        "negative_offset": offset,
        "corrected_min": low,
        "corrected_max": high,
        "output_min": int(output.min()),
        "output_max": int(output.max()),
    }


def read_anatomy_pages(path: str | Path) -> tuple[np.ndarray, dict[str, Any]]:
    source = Path(path)
    with tifffile.TiffFile(source) as tif:
        if not tif.pages:
            raise ValueError(f"Anatomy TIFF contains no pages: {source}")
        shape = tuple(int(value) for value in tif.pages[0].shape)
        pages = [np.asarray(page.asarray()) for page in tif.pages]
    if any(page.ndim != 2 or tuple(page.shape) != shape for page in pages):
        raise ValueError(f"Anatomy TIFF pages are not a consistent 2D stack: {source}")
    stack = np.stack(pages)
    return stack, {"reader": "tifffile_pages", "page_count": len(pages), "shape_zyx": list(stack.shape)}


def write_registration_nrrd(array_zyx: np.ndarray, path: str | Path, spacing_xyz_um: Sequence[float]) -> str:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    spacing = tuple(float(value) for value in spacing_xyz_um)
    if len(spacing) != 3 or any(value <= 0 for value in spacing):
        raise ValueError(f"Expected positive X,Y,Z spacing, got {spacing_xyz_um}")
    try:
        import SimpleITK as sitk
    except Exception as exc:  # pragma: no cover - environment dependent
        raise ImportError("SimpleITK is required to write canonical anatomy NRRD") from exc
    image = sitk.GetImageFromArray(np.asarray(array_zyx, dtype=np.uint8))
    image.SetSpacing(spacing)
    sitk.WriteImage(image, str(output), useCompression=False)
    return "SimpleITK"


def preprocess_anatomy(
    *,
    anatomy_path: str | Path,
    output_path: str | Path,
    polarity: str,
    source_spacing_xyz_um: Sequence[float],
    target_xy_shape: tuple[int, int] = (750, 750),
) -> dict[str, Any]:
    raw, read_info = read_anatomy_pages(anatomy_path)
    converted, range_info = signed_integer_to_uint8(raw)
    oriented = apply_canonical_xy(converted, polarity)
    registration = np.flip(oriented, axis=0).copy()
    target_y, target_x = (int(target_xy_shape[0]), int(target_xy_shape[1]))
    result = np.empty((registration.shape[0], target_y, target_x), dtype=np.uint8)
    for index, plane in enumerate(registration):
        resized = resize(
            plane,
            (target_y, target_x),
            order=1,
            preserve_range=True,
            anti_aliasing=True,
        )
        result[index] = np.clip(np.rint(resized), 0, 255).astype(np.uint8)
    sx, sy, sz = (float(value) for value in source_spacing_xyz_um)
    output_spacing = (sx * raw.shape[2] / target_x, sy * raw.shape[1] / target_y, sz)
    writer = write_registration_nrrd(result, output_path, output_spacing)
    return {
        "source_path": str(Path(anatomy_path)),
        "output_path": str(Path(output_path)),
        "source_shape_zyx": list(raw.shape),
        "output_shape_zyx": list(result.shape),
        "source_dtype": str(raw.dtype),
        "output_dtype": str(result.dtype),
        "source_spacing_xyz_um": [sx, sy, sz],
        "output_spacing_xyz_um": list(output_spacing),
        "spacing_units": "um",
        "reader": read_info,
        "range_conversion": range_info,
        "xy_transform": "flipY" if normalize_polarity(polarity) == "north" else "flipX",
        "z_transform": "flipZ",
        "writer": writer,
    }


def canonical_manifest_path(fish_dir: str | Path) -> Path:
    return Path(fish_dir) / "02_reg" / "00_preprocessing" / SPATIAL_MANIFEST_NAME


def write_spatial_manifest(
    *,
    fish_dir: str | Path,
    polarity: PolarityResolution,
    functional_planes: Sequence[Mapping[str, Any]],
    anatomy: Mapping[str, Any],
    sessions: Sequence[Mapping[str, Any]] = (),
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(fish_dir)
    path = Path(output_path) if output_path else canonical_manifest_path(root)
    if path.exists():
        raise FileExistsError(f"Spatial preprocessing manifest already exists: {path}")
    payload = {
        "stage": "canonical_spatial_preprocessing",
        "version": SPATIAL_MANIFEST_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fish_id": root.name,
        "status": "complete",
        "polarity": {
            "value": polarity.polarity,
            "source": polarity.source,
            "status": polarity.status,
            "raw_metadata_source": polarity.raw_metadata_source,
            "classifier": polarity.classifier,
        },
        "coordinate_frames": {
            "raw_functional_xy": ACQUISITION_XY_FRAME,
            "raw_anatomy_xy": ACQUISITION_XY_FRAME,
            "canonical_functional_xy": CANONICAL_XY_FRAME,
            "canonical_anatomy_xy": CANONICAL_XY_FRAME,
            "raw_anatomy_z": ACQUISITION_Z_FRAME,
            "canonical_anatomy_z": REGISTRATION_Z_FRAME,
        },
        "transforms": {
            "functional_xy": "flipY" if polarity.polarity == "north" else "flipX",
            "anatomy_xy": "flipY" if polarity.polarity == "north" else "flipX",
            "anatomy_z": "flipZ",
        },
        "functional_planes": [dict(value) for value in functional_planes],
        "anatomy": dict(anatomy),
        "sessions": [dict(value) for value in sessions],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def validate_spatial_manifest(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    frames = payload.get("coordinate_frames", {})
    if payload.get("stage") != "canonical_spatial_preprocessing" or payload.get("status") != "complete":
        raise ValueError(f"Incomplete or unknown spatial preprocessing manifest: {target}")
    if frames.get("canonical_functional_xy") != CANONICAL_XY_FRAME:
        raise ValueError(f"Unknown functional coordinate frame in {target}")
    if frames.get("canonical_anatomy_xy") != CANONICAL_XY_FRAME:
        raise ValueError(f"Functional/anatomy XY frames disagree in {target}")
    if frames.get("canonical_anatomy_z") != REGISTRATION_Z_FRAME:
        raise ValueError(f"Unknown anatomy Z frame in {target}")
    return payload


def record_motion_corrected_output(
    fish_dir: str | Path,
    *,
    plane_index: int,
    output_path: str | Path,
    suite2p_plane_dir: str | Path,
) -> dict[str, Any]:
    """Append a Suite2P-derived canonical movie without changing frame semantics."""
    path = canonical_manifest_path(fish_dir)
    payload = validate_spatial_manifest(path)
    records = [
        dict(record)
        for record in payload.get("motion_corrected_movies", [])
        if int(record.get("plane_index", -1)) != int(plane_index)
    ]
    records.append({
        "plane_index": int(plane_index),
        "output_path": str(Path(output_path)),
        "suite2p_plane_dir": str(Path(suite2p_plane_dir)),
        "output_xy_frame": CANONICAL_XY_FRAME,
    })
    payload["motion_corrected_movies"] = sorted(records, key=lambda record: int(record["plane_index"]))
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    return payload


__all__ = [
    "ACQUISITION_XY_FRAME",
    "ACQUISITION_Z_FRAME",
    "CANONICAL_XY_FRAME",
    "PolarityPrediction",
    "PolarityResolution",
    "PolarityResolutionError",
    "REGISTRATION_Z_FRAME",
    "SPATIAL_MANIFEST_NAME",
    "apply_canonical_xy",
    "canonical_manifest_path",
    "normalize_polarity",
    "preprocess_anatomy",
    "read_raw_metadata_polarity",
    "record_motion_corrected_output",
    "resolve_polarity",
    "signed_integer_to_uint8",
    "validate_spatial_manifest",
    "write_spatial_manifest",
]
