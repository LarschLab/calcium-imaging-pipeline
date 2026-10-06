"""Canonical spatial preprocessing: rebuild a fish in a new folder, in the
shared X/Y orientation, with everything the drift analysis needs.

For each fish:
1. Decide the fish's direction (north/south) from the raw metadata,
   cross-checked by the anatomy classifier.
2. Make the functional plane recordings (with `functional_preprocessing`),
   flipped into the shared orientation.
3. Prepare the anatomy for registration (flip, Z reversal, 8 bit, resize).
4. Write the spatial manifest, which records every change and where each
   file is; the drift analysis reads its inputs from it.

- Results go to a new, empty folder, so a fish can be rebuilt next to its
  existing outputs and compared (written to validate the move to the shared
  orientation).
- If the direction can't be decided (no orientation in the metadata and an
  unsure classifier, or the two disagree), the fish is skipped until it is
  reviewed by hand (`REVIEWED_POLARITY` in the settings).
- L427 fish (two interleaved channels) are excluded.
- Run it from the terminal or fill in the settings at the bottom (see `--help`).

Written by Danin Dharmaperwira (2026); the terminal entry point was merged
in from `canonical_spatial_preprocessing_cli.py`.
"""

import argparse
from dataclasses import asdict
import csv
import hashlib
import json
from pathlib import Path

import tifffile

from preprocessing.anatomy_polarity import discover_anatomy, load_model, predict_fish, train_from_raw_metadata
from preprocessing.functional_preprocessing import PLANES_SUBFOLDER, preprocess_functional_fish
from preprocessing.spatial_preprocessing import (
    ACQUISITION_XY_FRAME,
    CANONICAL_XY_FRAME,
    XY_TRANSFORM_BY_POLARITY,
    PolarityResolutionError,
    spatial_manifest_path,
    preprocess_anatomy,
    resolve_polarity,
    write_spatial_manifest,
)

EXCLUDED_FISH_PREFIX = "L427"  # interleaved two-channel fish: not supported by this workflow
RAW_METADATA_SUBFOLDER = Path("01_raw/2p/metadata")  # raw metadata CSVs, inside the fish folder
ANATOMY_OUTPUT_SUBFOLDER = Path("02_reg/00_preprocessing/2p_anatomy")  # prepared anatomy, inside the fish folder
# Metadata row names accepted for the anatomy pixel size and Z-step
ANATOMY_XY_SPACING_KEYS = ("pixel_size_um_anatomy", "pixel_size_anatomy_um", "anatomy_pixel_size_um")
ANATOMY_Z_SPACING_KEYS = ("step_size_um_anatomy",)
CLASSIFIER_VALIDATION_NAME = "anatomy_polarity_group_validation.json"  # saved next to the spatial manifest


def _metadata_float(fish_dir, keys):
    """Read the first positive numeric value matching any requested metadata key.

    Args:
        fish_dir (Path): Root folder for one fish.
        keys (Sequence[str]): Metadata row names to accept, matched
            case-insensitively.

    Returns:
        float or None: The first matching positive value found, or None
            if no metadata CSV contains a matching, positive value.
    """
    wanted = {str(value).strip().lower() for value in keys}
    for path in sorted((fish_dir / RAW_METADATA_SUBFOLDER).glob("*metadata*.csv")):
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.reader(handle):
                if len(row) < 2 or str(row[0]).strip().lower() not in wanted:  # rows are "name, value"
                    continue
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
    # TODO: ask Danin -- only `*_plane*.tif` files are recorded, so a linear
    # recording (saved as `*_stack.tif`) gives a manifest without planes; see
    # the "remove the linear protocol" TODO in functional_preprocessing.py.
    directory = output_fish_dir / PLANES_SUBFOLDER
    records = []
    for path in sorted(directory.glob(f"{output_fish_dir.name}_plane*.tif")):
        with tifffile.TiffFile(path) as tif:
            shape = [len(tif.pages), *[int(value) for value in tif.pages[0].shape]]  # (frames, Y, X)
            dtype = str(tif.pages[0].dtype)
        records.append({
            "plane_index": int(path.stem.rsplit("plane", 1)[1]),  # "<fish>_plane3" -> 3
            "output_path": str(path),
            "output_shape_tyx": shape,
            "output_dtype": dtype,
            "output_spacing_xy_um": [None, None],
            "spacing_units": "um",
            "input_xy_frame": ACQUISITION_XY_FRAME,
            "output_xy_frame": CANONICAL_XY_FRAME,
        })
    return records


def _check_fish_folders(source, output):
    """Check that a fish can run: supported fish, same fish ID, and a new output folder.

    Args:
        source (Path): Existing fish folder containing the raw data.
        output (Path): Output folder for the same fish ID.

    Returns:
        None: Returns only if all checks pass.

    Raises:
        ValueError: If the fish is excluded or the fish IDs differ.
        FileExistsError: If the output folder already contains files.
    """
    if source.name.startswith(EXCLUDED_FISH_PREFIX):
        raise ValueError(f"{EXCLUDED_FISH_PREFIX} interleaved two-channel fish are excluded from this workflow")
    if output.name != source.name:
        raise ValueError("Output fish directory must retain the source fish ID")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Isolated output fish directory is not empty: {output}")


def _classifier_prediction(source, classifier_model_path, classifier_validation_path, reference_microscopy_root):
    """Predict the fish's polarity with a saved or freshly trained classifier.

    Args:
        source (Path): Fish folder containing the raw anatomy.
        classifier_model_path (str or Path or None): Saved polarity model.
        classifier_validation_path (str or Path or None): Validation report for that model.
        reference_microscopy_root (str or Path or None): Reference fish to train
            the classifier from, when no saved model is given.

    Returns:
        tuple: `(prediction_payload, validation)` -- the prediction with its
        model details (dict, recorded in the manifest), and the classifier's
        held-out validation rows (list).

    Raises:
        ValueError: If neither a saved model nor a reference folder is given.
    """
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
        model, validation = train_from_raw_metadata(reference_microscopy_root, exclude_prefixes=(EXCLUDED_FISH_PREFIX,))
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
        prediction_payload["model_sha256"] = hashlib.sha256(model_path.read_bytes()).hexdigest()  # identifies the exact model file
    return prediction_payload, validation


def _anatomy_spacing(source, anatomy_xy_spacing_um, anatomy_z_spacing_um):
    """Return the anatomy pixel size and Z-step: given values, else from the raw metadata.

    Args:
        source (Path): Fish folder containing the raw metadata.
        anatomy_xy_spacing_um (float or None): Pixel size override.
        anatomy_z_spacing_um (float or None): Z-step override.

    Returns:
        tuple: `(xy_spacing, z_spacing)` in micrometres.

    Raises:
        ValueError: If either value is neither given nor in the metadata.
    """
    xy_spacing = anatomy_xy_spacing_um or _metadata_float(source, ANATOMY_XY_SPACING_KEYS)
    z_spacing = anatomy_z_spacing_um or _metadata_float(source, ANATOMY_Z_SPACING_KEYS)
    if xy_spacing is None or z_spacing is None:
        raise ValueError(
            "Anatomy X/Y and Z spacing are required; provide explicit spacing when raw metadata lacks it"
        )
    return xy_spacing, z_spacing


def _write_canonical_manifest(output, fish_id, resolution, anatomy_record, validation):
    """Write the spatial manifest and the classifier validation report.

    Args:
        output (Path): Output fish folder.
        fish_id (str): Fish ID.
        resolution (PolarityResolution): The resolved polarity and its evidence.
        anatomy_record (dict): Record of the prepared anatomy (from `preprocess_anatomy`).
        validation (list): Classifier held-out validation rows.

    Returns:
        dict: The completed spatial manifest.
    """
    functional_records = _functional_plane_records(output)
    metadata_path = output / PLANES_SUBFOLDER / f"{fish_id}_preprocessing_metadata.json"
    functional_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    sessions = functional_metadata.get("sessions", [])
    selected_sources = [
        str(path)
        for session in sessions
        for path in session.get("selected_tiffs", [])
    ]
    for record in functional_records:
        record["source_paths"] = selected_sources
        record["xy_transform"] = XY_TRANSFORM_BY_POLARITY[resolution.polarity]
    manifest = write_spatial_manifest(
        fish_dir=output,
        polarity=resolution,
        functional_planes=functional_records,
        anatomy=anatomy_record,
        sessions=sessions,
    )
    validation_path = spatial_manifest_path(output).with_name(CLASSIFIER_VALIDATION_NAME)
    validation_path.write_text(json.dumps(validation, indent=2), encoding="utf-8")
    # Rewrite the manifest so it also points to the validation report
    manifest["polarity"]["classifier"]["group_validation_path"] = str(validation_path)
    spatial_manifest_path(output).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


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
        protocol (str): Functional acquisition type, `resonant` or `linear`.
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

    Raises:
        ValueError: If the fish is excluded, inputs are missing, or no classifier is given.
        FileExistsError: If the output folder already contains files.
        PolarityResolutionError: If the polarity needs a manual review.
    """
    source = Path(source_fish_dir)
    output = Path(output_fish_dir)
    _check_fish_folders(source, output)

    # 1. Polarity: raw metadata first, classifier as cross-check (or fallback)
    prediction_payload, validation = _classifier_prediction(
        source, classifier_model_path, classifier_validation_path, reference_microscopy_root,
    )
    resolution = resolve_polarity(
        source,
        classifier_prediction=prediction_payload,
        reviewed_polarity=reviewed_polarity,
    )

    anatomy_source = discover_anatomy(source)
    xy_spacing, z_spacing = _anatomy_spacing(source, anatomy_xy_spacing_um, anatomy_z_spacing_um)

    # 2. Functional plane recordings, flipped into the shared orientation
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

    # 3. Anatomy prepared for registration
    anatomy_output = output / ANATOMY_OUTPUT_SUBFOLDER / f"{source.name}_anatomy_2P_GCaMP.nrrd"
    anatomy_record = preprocess_anatomy(
        anatomy_path=anatomy_source,
        output_path=anatomy_output,
        polarity=resolution.polarity,
        source_spacing_xyz_um=(xy_spacing, xy_spacing, z_spacing),
        target_xy_shape=target_xy_shape,
    )

    # 4. Spatial manifest
    manifest = _write_canonical_manifest(output, source.name, resolution, anatomy_record, validation)
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
