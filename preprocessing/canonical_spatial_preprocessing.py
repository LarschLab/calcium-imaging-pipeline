"""Orchestration for one-pass canonical functional and anatomy preprocessing."""

from __future__ import annotations

from dataclasses import asdict
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import tifffile

from preprocessing.anatomy_polarity import discover_anatomy, load_model, predict_fish, train_from_raw_metadata
from preprocessing.preprocessing_tiff import process_fish
from preprocessing.spatial_preprocessing import (
    canonical_manifest_path,
    preprocess_anatomy,
    resolve_polarity,
    write_spatial_manifest,
)


def _metadata_float(fish_dir: Path, keys: Sequence[str]) -> float | None:
    """Read the first positive numeric value matching any requested metadata key."""
    wanted = {str(value).strip().lower() for value in keys}
    for path in sorted((fish_dir / "01_raw" / "2p" / "metadata").glob("*metadata*.csv")):
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.reader(handle):
                if len(row) >= 2 and str(row[0]).strip().lower() in wanted:
                    try:
                        value = float(row[1])
                    except ValueError:
                        continue
                    if value > 0:
                        return value
    return None


def _functional_plane_records(output_fish_dir: Path) -> list[dict[str, Any]]:
    """Describe the functional plane TIFFs created for the spatial manifest."""
    directory = output_fish_dir / "02_reg" / "00_preprocessing" / "2p_functional" / "01_individualPlanes"
    records = []
    for path in sorted(directory.glob(f"{output_fish_dir.name}_plane*.tif")):
        with tifffile.TiffFile(path) as tif:
            shape = [len(tif.pages), *[int(value) for value in tif.pages[0].shape]]
            dtype = str(tif.pages[0].dtype)
        records.append({
            "plane_index": int(path.stem.rsplit("plane", 1)[1]),
            "output_path": str(path),
            "output_shape_tyx": shape,
            "output_dtype": dtype,
            "output_spacing_xy_um": [None, None],
            "spacing_units": "um",
            "input_xy_frame": "two_photon_acquisition_xy",
            "output_xy_frame": "codeants_2p_canonical_xy_v1",
        })
    return records


def run_canonical_spatial_preprocessing(
    *,
    source_fish_dir: str | Path,
    output_fish_dir: str | Path,
    reference_microscopy_root: str | Path | None,
    protocol: str,
    blocks: Sequence[int] | None,
    n_planes: int | None,
    n_frames_per_plane: int | None,
    volume_flyback_frames: int = 1,
    remove_first_frame: bool = False,
    reviewed_polarity: str | None = None,
    anatomy_xy_spacing_um: float | None = None,
    anatomy_z_spacing_um: float | None = None,
    target_xy_shape: tuple[int, int] = (750, 750),
    classifier_model_path: str | Path | None = None,
    classifier_validation_path: str | Path | None = None,
) -> dict[str, Any]:
    """Create consistently oriented functional planes and anatomy for one fish.

    This end-to-end entry point predicts or reviews fish polarity, preprocesses
    raw functional TIFFs, prepares the anatomy NRRD, and writes a manifest that
    records every coordinate change.

    Parameters:
    - source_fish_dir (str or Path): Existing fish folder containing raw data.
    - output_fish_dir (str or Path): New isolated output folder for the same fish ID.
    - reference_microscopy_root (str or Path or None): Reference fish used when
      a saved classifier is not supplied.
    - protocol (str): Functional acquisition type, ``resonant`` or ``linear``.
    - blocks (Sequence[int] or None): Recording blocks to include.
    - n_planes (int or None): Number of acquired functional planes.
    - n_frames_per_plane (int or None): Frames averaged for each plane and volume.
    - volume_flyback_frames (int): Unusable return frames in each volume.
    - remove_first_frame (bool): Drop the first repeated resonant frame when requested.
    - reviewed_polarity (str or None): Manually reviewed north/south value.
    - anatomy_xy_spacing_um (float or None): Raw anatomy pixel size in X and Y.
    - anatomy_z_spacing_um (float or None): Distance between anatomy slices.
    - target_xy_shape (tuple[int, int]): Output anatomy height and width.
    - classifier_model_path (str or Path or None): Saved polarity model.
    - classifier_validation_path (str or Path or None): Validation report for that model.

    Returns:
    - dict: Completed spatial manifest describing inputs, outputs, and transforms.
    """
    source = Path(source_fish_dir)
    output = Path(output_fish_dir)
    if source.name.startswith("L427"):
        raise ValueError("L427 interleaved two-channel fish are excluded from this workflow")
    if output.name != source.name:
        raise ValueError("Output fish directory must retain the source fish ID")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Isolated output fish directory is not empty: {output}")

    if classifier_model_path is not None:
        model = load_model(classifier_model_path)
        validation = (
            json.loads(Path(classifier_validation_path).read_text(encoding="utf-8"))
            if classifier_validation_path is not None
            else []
        )
    else:
        if reference_microscopy_root is None:
            raise ValueError("reference_microscopy_root or classifier_model_path is required")
        model, validation = train_from_raw_metadata(reference_microscopy_root, exclude_prefixes=("L427",))
    prediction = predict_fish(model, source)
    prediction_payload = {
        **asdict(prediction),
        "calibration_floor": model.calibration_floor,
        "reference_fish_count": len(model.reference_fish_ids),
        "reference_fish_ids": list(model.reference_fish_ids),
        "group_held_out_correct": sum(bool(row["correct"]) for row in validation),
        "group_held_out_count": len(validation),
    }
    if classifier_model_path is not None:
        model_path = Path(classifier_model_path)
        prediction_payload["model_path"] = str(model_path)
        prediction_payload["model_sha256"] = hashlib.sha256(model_path.read_bytes()).hexdigest()
    resolution = resolve_polarity(
        source,
        classifier_prediction=prediction_payload,
        reviewed_polarity=reviewed_polarity,
    )

    anatomy_source = discover_anatomy(source)
    xy_spacing = anatomy_xy_spacing_um or _metadata_float(
        source,
        ("pixel_size_um_anatomy", "pixel_size_anatomy_um", "anatomy_pixel_size_um"),
    )
    z_spacing = anatomy_z_spacing_um or _metadata_float(source, ("step_size_um_anatomy",))
    if xy_spacing is None or z_spacing is None:
        raise ValueError(
            "Anatomy X/Y and Z spacing are required; provide explicit spacing when raw metadata lacks it"
        )

    process_fish(
        source.name,
        source.parent,
        output.parent,
        protocol=protocol,
        blocks=list(blocks) if blocks is not None else None,
        n_planes=n_planes,
        n_frames_per_plane=n_frames_per_plane,
        volume_flyback_frames=volume_flyback_frames,
        remove_first_frame=remove_first_frame,
        apply_polarity_orientation=True,
        polarity=resolution.polarity,
        polarity_source=resolution.source,
    )

    anatomy_output = (
        output / "02_reg" / "00_preprocessing" / "2p_anatomy" /
        f"{source.name}_anatomy_2P_GCaMP.nrrd"
    )
    anatomy_record = preprocess_anatomy(
        anatomy_path=anatomy_source,
        output_path=anatomy_output,
        polarity=resolution.polarity,
        source_spacing_xyz_um=(xy_spacing, xy_spacing, z_spacing),
        target_xy_shape=target_xy_shape,
    )

    functional_records = _functional_plane_records(output)
    metadata_path = (
        output / "02_reg" / "00_preprocessing" / "2p_functional" / "01_individualPlanes" /
        f"{source.name}_preprocessing_metadata.json"
    )
    functional_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    sessions = functional_metadata.get("sessions", [])
    selected_sources = [
        str(path)
        for session in sessions
        for path in session.get("selected_tiffs", [])
    ]
    for record in functional_records:
        record["source_paths"] = selected_sources
        record["xy_transform"] = "flipY" if resolution.polarity == "north" else "flipX"
    manifest = write_spatial_manifest(
        fish_dir=output,
        polarity=resolution,
        functional_planes=functional_records,
        anatomy=anatomy_record,
        sessions=sessions,
    )
    validation_path = canonical_manifest_path(output).with_name("anatomy_polarity_group_validation.json")
    validation_path.write_text(json.dumps(validation, indent=2), encoding="utf-8")
    manifest["polarity"]["classifier"]["group_validation_path"] = str(validation_path)
    canonical_manifest_path(output).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


__all__ = ["run_canonical_spatial_preprocessing"]
