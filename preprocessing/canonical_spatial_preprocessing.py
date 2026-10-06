"""Orchestration for one-pass canonical functional and anatomy preprocessing.

Run it from the terminal or fill in the settings at the bottom (see `--help`).
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import tifffile

from preprocessing.anatomy_polarity import discover_anatomy, load_model, predict_fish, train_from_raw_metadata
from preprocessing.functional_preprocessing import preprocess_functional_fish
from preprocessing.spatial_preprocessing import (
    PolarityResolutionError,
    spatial_manifest_path,
    preprocess_anatomy,
    resolve_polarity,
    write_spatial_manifest,
)


def _metadata_float(fish_dir, keys):
    """Read the first positive numeric value matching any requested metadata key.

    Args:
        fish_dir (Path): Root folder for one fish.
        keys (Sequence[str]): Metadata row names to accept, matched
            case-insensitively.

    Returns:
        float or None: The first matching positive value found, or ``None``
            if no metadata CSV contains a matching, positive value.
    """
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


def _functional_plane_records(output_fish_dir):
    """Describe the functional plane TIFFs created for the spatial manifest.

    Args:
        output_fish_dir (Path): Isolated output folder for the fish being
            preprocessed.

    Returns:
        list[dict]: One record per functional plane TIFF, describing its
            output path, shape, dtype, and coordinate frame.
    """
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
    source_fish_dir,
    output_fish_dir,
    reference_microscopy_root,
    protocol,
    blocks,
    n_planes,
    n_frames_per_plane,
    volume_flyback_frames=1,
    remove_first_frame=False,
    reviewed_polarity=None,
    anatomy_xy_spacing_um=None,
    anatomy_z_spacing_um=None,
    target_xy_shape=(750, 750),
    classifier_model_path=None,
    classifier_validation_path=None,
):
    """Create consistently oriented functional planes and anatomy for one fish.

    This end-to-end entry point predicts or reviews fish polarity, preprocesses
    raw functional TIFFs, prepares the anatomy NRRD, and writes a manifest that
    records every coordinate change.

    Args:
        source_fish_dir (str or Path): Existing fish folder containing raw data.
        output_fish_dir (str or Path): New isolated output folder for the same fish ID.
        reference_microscopy_root (str or Path or None): Reference fish used when
            a saved classifier is not supplied.
        protocol (str): Functional acquisition type, ``resonant`` or ``linear``.
        blocks (Sequence[int] or None): Recording blocks to include.
        n_planes (int or None): Number of acquired functional planes.
        n_frames_per_plane (int or None): Frames averaged for each plane and volume.
        volume_flyback_frames (int): Unusable return frames in each volume.
        remove_first_frame (bool): Drop the first repeated resonant frame when requested.
        reviewed_polarity (str or None): Manually reviewed north/south value.
        anatomy_xy_spacing_um (float or None): Raw anatomy pixel size in X and Y.
        anatomy_z_spacing_um (float or None): Distance between anatomy slices.
        target_xy_shape (tuple[int, int]): Output anatomy height and width.
        classifier_model_path (str or Path or None): Saved polarity model.
        classifier_validation_path (str or Path or None): Validation report for that model.

    Returns:
        dict: Completed spatial manifest describing inputs, outputs, and transforms.
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

    preprocess_functional_fish(
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
    validation_path = spatial_manifest_path(output).with_name("anatomy_polarity_group_validation.json")
    validation_path.write_text(json.dumps(validation, indent=2), encoding="utf-8")
    manifest["polarity"]["classifier"]["group_validation_path"] = str(validation_path)
    spatial_manifest_path(output).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def batch_canonical_spatial_preprocessing(data_root, fish_ids, output_root, *, classifier_model_path=None,
                                          reference_microscopy_root=None, reviewed_polarity=None,
                                          anatomy_xy_spacing_um=None, anatomy_z_spacing_um=None, **settings):
    """Run the canonical preprocessing on several fish, skipping fish that fail.

    A fish whose inputs are missing or invalid, or whose polarity needs a
    manual review, gets a warning and is skipped, so one bad fish doesn't
    stop the others.

    Args:
        data_root (str or Path): Folder containing the raw fish folders.
        fish_ids (list[str]): Fish IDs to process (e.g. `["L500_f01"]`).
        output_root (str or Path): Results go to `output_root/<fish_id>`,
            which must not exist yet or be empty.
        classifier_model_path (str or Path or None): Saved polarity model.
        reference_microscopy_root (str or Path or None): Reference fish to
            train the classifier from instead (slow: retrained for every fish).
        reviewed_polarity (str or None): Manually reviewed north/south; single fish only.
        anatomy_xy_spacing_um (float or None): Anatomy pixel size override; single fish only.
        anatomy_z_spacing_um (float or None): Anatomy Z-step override; single fish only.
        **settings: Other keyword settings of `run_canonical_spatial_preprocessing`
            (protocol, blocks, n_planes, ...).

    Returns:
        dict: Spatial manifest of each fish that ran, keyed by fish ID.

    Raises:
        ValueError: If not exactly one of the model and the reference folder is
            given, or a single-fish option is given with several fish.
    """
    if (classifier_model_path is None) == (reference_microscopy_root is None):
        raise ValueError("Give exactly one of classifier_model_path and reference_microscopy_root")
    single_fish_options = [reviewed_polarity, anatomy_xy_spacing_um, anatomy_z_spacing_um]
    if len(fish_ids) != 1 and any(option is not None for option in single_fish_options):
        raise ValueError("reviewed_polarity and the anatomy spacing overrides need exactly one fish")
    manifests = {}
    for fish_id in fish_ids:
        print(f"\n📂 Canonical preprocessing of {fish_id}")
        try:
            manifest = run_canonical_spatial_preprocessing(
                source_fish_dir=Path(data_root) / fish_id,
                output_fish_dir=Path(output_root) / fish_id,
                reference_microscopy_root=reference_microscopy_root,
                classifier_model_path=classifier_model_path,
                reviewed_polarity=reviewed_polarity,
                anatomy_xy_spacing_um=anatomy_xy_spacing_um,
                anatomy_z_spacing_um=anatomy_z_spacing_um,
                **settings,
            )
        except (FileExistsError, FileNotFoundError, ValueError, PolarityResolutionError) as error:  # bad inputs of this fish
            print(f"⚠️ Skipping {fish_id}: {error}")
            continue
        print(f"✅ {fish_id}: {manifest['status']}")
        manifests[fish_id] = manifest
    return manifests


__all__ = ["batch_canonical_spatial_preprocessing", "run_canonical_spatial_preprocessing"]


if __name__ == "__main__":
    # ---- Settings: fill in by hand when running this file (terminal options override them) ----
    DATA_ROOT = "F:/Matilde/2p_data"  # folder containing the raw fish folders
    FISH_TO_PROCESS = ["L500_f01"]  # Fish IDs to process
    OUTPUT_ROOT = "F:/Matilde/canonical"  # results go to OUTPUT_ROOT/<fish_id> (must not exist yet or be empty)

    CLASSIFIER_MODEL = None  # saved polarity model; or set REFERENCE_MICROSCOPY_ROOT instead
    CLASSIFIER_VALIDATION = None  # validation report of that model
    REFERENCE_MICROSCOPY_ROOT = None  # reference fish to train the classifier from (slow: retrained per fish)

    PROTOCOL = "resonant"  # or "linear"
    BLOCKS = None  # blocks to process; None = all blocks
    N_PLANES = 5
    N_FRAMES_PER_PLANE = 3
    # TODO: ask Danin -- default 1 flyback frame, but Matilde's recordings have 0;
    # with 1, every (n_planes * n_frames_per_plane + 1)-th frame is dropped by mistake.
    VOLUME_FLYBACK_FRAMES = 1
    REMOVE_FIRST_FRAME = False
    TARGET_XY = 750  # anatomy output height and width (pixels)

    # Single-fish values (only with one fish in FISH_TO_PROCESS):
    REVIEWED_POLARITY = None  # "north" or "south" after a manual review
    ANATOMY_XY_SPACING_UM = None  # anatomy pixel size, if missing from the metadata
    ANATOMY_Z_SPACING_UM = None  # anatomy Z-step, if missing from the metadata
    # ----------------------------------------------------------------------------------------------

    parser = argparse.ArgumentParser(
        description="Canonical functional plane recordings, anatomy NRRD and spatial manifest, per fish.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,  # show each default in --help
    )
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT, help="folder containing the raw fish folders")
    parser.add_argument("--fish", nargs="+", default=FISH_TO_PROCESS, help="fish IDs to process")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT, help="results go to OUTPUT_ROOT/<fish_id>")
    parser.add_argument("--classifier-model", type=Path, default=CLASSIFIER_MODEL, help="saved polarity model")
    parser.add_argument("--classifier-validation", type=Path, default=CLASSIFIER_VALIDATION, help="validation report of that model")
    parser.add_argument("--reference-microscopy-root", type=Path, default=REFERENCE_MICROSCOPY_ROOT, help="reference fish to train the classifier from")
    parser.add_argument("--protocol", choices=("resonant", "linear"), default=PROTOCOL, help="acquisition protocol")
    parser.add_argument("--blocks", type=int, nargs="+", default=BLOCKS, help="blocks to process (default: all)")
    parser.add_argument("--n-planes", type=int, default=N_PLANES, help="planes per volume")
    parser.add_argument("--n-frames-per-plane", type=int, default=N_FRAMES_PER_PLANE, help="frames acquired per plane")
    parser.add_argument("--volume-flyback-frames", type=int, default=VOLUME_FLYBACK_FRAMES, help="flyback frames per volume")
    parser.add_argument("--remove-first-frame", action=argparse.BooleanOptionalAction, default=REMOVE_FIRST_FRAME, help="drop the first frame of each plane")
    parser.add_argument("--target-xy", type=int, default=TARGET_XY, help="anatomy output height and width (pixels)")
    parser.add_argument("--reviewed-polarity", choices=("north", "south"), default=REVIEWED_POLARITY, help="manually reviewed polarity (one fish only)")
    parser.add_argument("--anatomy-xy-spacing-um", type=float, default=ANATOMY_XY_SPACING_UM, help="anatomy pixel size, if missing from the metadata (one fish only)")
    parser.add_argument("--anatomy-z-spacing-um", type=float, default=ANATOMY_Z_SPACING_UM, help="anatomy Z-step, if missing from the metadata (one fish only)")
    args = parser.parse_args()

    batch_canonical_spatial_preprocessing(
        args.data_root,
        args.fish,
        args.output_root,
        classifier_model_path=args.classifier_model,
        classifier_validation_path=args.classifier_validation,
        reference_microscopy_root=args.reference_microscopy_root,
        reviewed_polarity=args.reviewed_polarity,
        anatomy_xy_spacing_um=args.anatomy_xy_spacing_um,
        anatomy_z_spacing_um=args.anatomy_z_spacing_um,
        protocol=args.protocol,
        blocks=args.blocks,
        n_planes=args.n_planes,
        n_frames_per_plane=args.n_frames_per_plane,
        volume_flyback_frames=args.volume_flyback_frames,
        remove_first_frame=args.remove_first_frame,
        target_xy_shape=(args.target_xy, args.target_xy),
    )
