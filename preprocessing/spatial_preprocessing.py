"""Spatial transformations for in-vivo two-photon data, and anatomy preprocessing.

Raw TIFFs are never modified. Covers:
1. Fish polarity: north/south from raw metadata (or a manual value, or the
   anatomy classifier) -- `resolve_polarity`.
2. Canonical X/Y flip by polarity, so every fish shares one orientation
   (codeANTs convention). Applied to the anatomy, and to the functional
   movies only when `functional_preprocessing` runs with
   `apply_polarity_orientation=True`.
3. Anatomy preprocessing for reference registration (anatomy only): 8-bit
   conversion, X/Y flip, Z reversal, 750x750 resize, NRRD -- `preprocess_anatomy`.
4. Spatial manifest: the JSON record of the canonical workflow's frames and files.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import csv
import json
from pathlib import Path

import numpy as np
from skimage.transform import resize
import tifffile


SPATIAL_MANIFEST_VERSION = 1  # layout version written into each manifest, to detect future format changes
SPATIAL_MANIFEST_NAME = "spatial_preprocessing_manifest.json"  # the canonical workflow's record of what it did to a fish

# Labels naming each coordinate frame. They're written into metadata and
# compared when read back, so every step agrees on an image's orientation.
ACQUISITION_XY_FRAME = "two_photon_acquisition_xy"  # X/Y as the microscope saved it
CANONICAL_XY_FRAME = "codeants_2p_canonical_xy_v1"  # X/Y after the polarity flip #TODO check whether same as Lukas reference brain
ACQUISITION_Z_FRAME = "two_photon_acquisition_z"  # slices in acquisition order
REGISTRATION_Z_FRAME = "codeants_confocal_registration_z_v1"  # slices reversed, as reference registration expects

VALID_POLARITIES = {"north", "south"}
XY_TRANSFORM_BY_POLARITY = {"north": "flipY", "south": "flipX"}  # canonical X/Y flip, as recorded in metadata
Z_TRANSFORM = "flipZ"  # anatomy slice reversal, as recorded in metadata
UINT8_MAX = int(np.iinfo(np.uint8).max)  # 255
UINT16_MAX = int(np.iinfo(np.uint16).max)  # 65535

# The exception raised when polarity is missing, invalid, or conflicting. 
class PolarityResolutionError(RuntimeError):
    """Raised when polarity is absent, invalid, conflicting, or unreviewed."""

# Classes for the polarity resolution workflow.
# The classifier is treated as a metadata source, so its prediction is recorded in the manifest for later review.
# TODO: classifier-only parts (PolarityPrediction, _prediction_dict, the
# classifier_prediction branch of resolve_polarity, PolarityResolution.classifier):
# keep or delete together with anatomy_polarity.py -- see the TODO there.
@dataclass(frozen=True)
class PolarityPrediction:
    """Classifier result and simple confidence measurements for one fish."""
    polarity: str | None  # None when the classifier abstains
    status: str  # "predicted" or "review"
    model_name: str
    median_margin: float | None = None
    min_abs_margin: float | None = None
    unanimous: bool | None = None
    model_version: str | None = None


@dataclass(frozen=True)
class PolarityResolution:
    """Final reviewed polarity together with evidence showing where it came from."""
    polarity: str
    source: str  # a metadata file, "manual_review" or "anatomy_classifier"
    status: str
    raw_metadata_source: str | None
    classifier: dict | None


def normalize_polarity(value):
    """Convert accepted shorthand labels into `north` or `south`.

    Empty values become None; unknown non-empty text is returned unchanged so
    the caller can give a useful validation error.

    Args:
        value (Any): Raw polarity value to normalize, such as a string read
            from metadata or user input. May be None.

    Returns:
        str | None: The normalized `"north"` or `"south"` label, the
        unrecognized text unchanged, or None if the value was empty.
    """
    text = "" if value is None else str(value).strip().lower()
    # "bottom-left" / "top-right" are what the stimulus scripts save as fish_orientation.
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
    # Blank cells, and how CSVs/pandas write missing values, mean no polarity.
    if text in {"", "none", "nan", "null"}:
        return None
    normalized_polarity = aliases.get(text, text)
    return normalized_polarity


def _metadata_value(path, parameter):
    """Read one named value from either supported metadata CSV layout.

    Args:
        path (Path): Path to the metadata CSV file.
        parameter (str): Name of the parameter to look up, matched
            case-insensitively.

    Returns:
        Any: The matching value as read from the CSV, or None if the file is
        empty or the parameter is not found.
    """
    with path.open(newline="", encoding="utf-8-sig") as metadata_file:  # utf-8-sig drops the byte-order mark Excel adds
        rows = list(csv.reader(metadata_file))
    if not rows:
        return None
    parameter_key = parameter.strip().lower()
    # Layout 1: one `parameter,value` pair per row.
    for row in rows:
        if len(row) >= 2 and str(row[0]).strip().lower() == parameter_key:
            return row[1]
    # Layout 2: a header row naming the key and value columns.
    header = {str(column_name).strip().lower(): index for index, column_name in enumerate(rows[0])}
    key_column = next((header[name] for name in ("parameter", "param", "key", "name") if name in header), None)
    value_column = next((header[name] for name in ("value", "val") if name in header), None)
    if key_column is None or value_column is None:
        return None
    for row in rows[1:]:
        if len(row) > max(key_column, value_column) and str(row[key_column]).strip().lower() == parameter_key:
            return row[value_column]
    return None


def read_raw_metadata_polarity(fish_dir):
    """Read and cross-check north/south orientation from raw metadata files.

    Conflicting or unrecognized values stop processing instead of being
    guessed.

    Args:
        fish_dir (str | Path): Root directory for one fish, containing the
            `01_raw/2p/metadata` folder to search for orientation CSVs.

    Returns:
        tuple[str | None, str | None]: The normalized polarity value and a
        description of the metadata file/field it came from, or
        `(None, None)` if no metadata file specifies an orientation.

    Raises:
        PolarityResolutionError: If a value is unrecognized, or files disagree.
    """
    metadata_dir = Path(fish_dir) / "01_raw" / "2p" / "metadata"
    paths = sorted(path for path in metadata_dir.glob("*metadata*.csv") if not path.name.startswith("."))  # skips hidden files (e.g. macOS ._ copies)
    found = []  # (polarity, path) for every file that records one
    invalid = []  # "file=value" for every unrecognized value
    for path in paths:
        value = _metadata_value(path, "fish_orientation")
        if value is None:
            continue
        polarity = normalize_polarity(value)
        if polarity not in VALID_POLARITIES:
            invalid.append(f"{path.name}={value!r}")
        else:
            found.append((polarity, path))
    if invalid:
        raise PolarityResolutionError("Invalid fish_orientation metadata: " + ", ".join(invalid))
    if not found:
        return None, None
    # All files that record a polarity must agree.
    values = {polarity for polarity, _ in found}
    if len(values) != 1:
        details = ", ".join(f"{path.name}={polarity}" for polarity, path in found)
        raise PolarityResolutionError(f"Conflicting fish_orientation metadata: {details}")
    polarity, path = found[0]
    polarity_source = f"{path}:fish_orientation"
    return polarity, polarity_source


# The anatomy Z step always comes from the raw metadata CSV (`step_size_um_anatomy`):
# ScanImage doesn't record it. Used by the registration notebook.
# TODO: the canonical workflow reads the same row with its own `_metadata_float`;
# use this function there too, so there is one metadata reader.
def anatomy_z_spacing_um(metadata_dir):
    """Read anatomy slice spacing and ensure all metadata files agree.

    Args:
        metadata_dir (str or Path): Directory searched (via
            `*_metadata.csv`) for a `step_size_um_anatomy` row.

    Returns:
        tuple: A `(spacing_um, sources)` pair, where `spacing_um` (float) is
        the agreed anatomy Z spacing in micrometers and `sources` (list of
        Path) lists the metadata files it was read from.

    Raises:
        ValueError: If no file records the spacing, files disagree, or it isn't positive.
    """
    values = []  # every step_size_um_anatomy value found
    sources = []  # the file each value came from
    for path in sorted(Path(metadata_dir).glob("*_metadata.csv")):
        with path.open(newline="", encoding="utf-8-sig") as metadata_file:
            for row in csv.reader(metadata_file):
                if len(row) >= 2 and row[0].strip() == "step_size_um_anatomy":
                    values.append(float(row[1]))
                    sources.append(path)
    if not values:
        raise ValueError(f"No step_size_um_anatomy found under {metadata_dir}")
    if any(not np.isclose(value, values[0]) for value in values[1:]):
        raise ValueError(f"Conflicting anatomy Z spacing values under {metadata_dir}: {values}")
    if values[0] <= 0:
        raise ValueError(f"Anatomy Z spacing must be positive, got {values[0]}")
    spacing_um = float(values[0])
    return spacing_um, sources


def _prediction_dict(prediction):
    """Convert an optional prediction record to an ordinary dictionary.

    Args:
        prediction (PolarityPrediction | dict | None): The classifier
            prediction to convert, either already a dict or a
            `PolarityPrediction` instance. May be None.

    Returns:
        dict | None: The prediction as a plain dictionary, or None
        if `prediction` was None.
    """
    if prediction is None:
        return None
    prediction_dict = asdict(prediction) if isinstance(prediction, PolarityPrediction) else dict(prediction)
    return prediction_dict


def resolve_polarity(
    fish_dir,
    *,
    classifier_prediction=None,
    reviewed_polarity=None,
):
    """Resolve metadata first, classifier second, and fail closed otherwise.

    The classifier is always treated as an independent metadata QC when both
    sources are present. A disagreement requires explicit manual review.

    Args:
        fish_dir (str | Path): Root directory for one fish, used to look up
            raw metadata orientation.
        classifier_prediction (PolarityPrediction | dict | None):
            Optional anatomy-classifier prediction to cross-check against raw
            metadata. Defaults to None.
        reviewed_polarity (str | None): Optional manually reviewed polarity
            used to resolve conflicts or to stand in when no raw metadata or
            accepted classifier prediction is available. Defaults to None.

    Returns:
        PolarityResolution: The resolved polarity together with its source,
        status, and supporting evidence.

    Raises:
        PolarityResolutionError: If the sources conflict without a matching
            review, the reviewed value is invalid, or no source gives a polarity.
    """
    raw, raw_source = read_raw_metadata_polarity(fish_dir)
    # TODO: classifier inputs below depend on the anatomy_polarity.py decision.
    prediction = _prediction_dict(classifier_prediction)
    predicted = normalize_polarity(prediction.get("polarity")) if prediction else None
    predicted_ok = bool(prediction and prediction.get("status") in {"predicted", "accepted"})  # only a confident classifier result counts
    reviewed = normalize_polarity(reviewed_polarity)
    if reviewed_polarity is not None and reviewed not in VALID_POLARITIES:
        raise PolarityResolutionError(f"Invalid reviewed polarity: {reviewed_polarity!r}")

    # 1. Raw metadata wins; the classifier only cross-checks it.
    if raw in VALID_POLARITIES:
        if predicted_ok and predicted in VALID_POLARITIES and predicted != raw:
            if reviewed is None:
                raise PolarityResolutionError(
                    f"Classifier ({predicted}) conflicts with raw metadata ({raw}); manual review is required"
                )
            if reviewed != raw:
                raise PolarityResolutionError(
                    f"Reviewed polarity ({reviewed}) cannot silently override valid raw metadata ({raw})"
                )
        resolution = PolarityResolution(raw, raw_source or "raw_metadata", "resolved", raw_source, prediction)
        return resolution

    # 2. No metadata: a manual review, then the classifier.
    if reviewed in VALID_POLARITIES:
        resolution = PolarityResolution(reviewed, "manual_review", "resolved_after_review", None, prediction)
        return resolution
    if predicted_ok and predicted in VALID_POLARITIES:
        resolution = PolarityResolution(predicted, "anatomy_classifier", "resolved", None, prediction)
        return resolution
    # 3. Nothing usable: stop for manual review.
    detail = "no classifier prediction" if prediction is None else f"classifier status={prediction.get('status')!r}"
    raise PolarityResolutionError(f"Missing fish_orientation and {detail}; manual review is required")


def apply_canonical_xy(array, polarity):
    """Apply the direct effective transform to the final Y and X axes.

    Args:
        array (numpy.ndarray): Array with at least two trailing Y, X axes to
            reorient.
        polarity (str): Polarity label (`"north"` or `"south"`, or an
            accepted alias) determining which axis is flipped.

    Returns:
        numpy.ndarray: A new array with the Y axis flipped for `"north"` or
        the X axis flipped for `"south"`.

    Raises:
        ValueError: If `array` has fewer than two axes.
        PolarityResolutionError: If `polarity` isn't north or south.
    """
    data = np.asarray(array)
    value = normalize_polarity(polarity)
    if data.ndim < 2:
        raise ValueError(f"Expected at least Y,X axes, got shape {data.shape}")
    if value == "north":
        flipped = np.flip(data, axis=-2).copy()  # flip Y; copy so the result is independent of the input
        return flipped
    if value == "south":
        flipped = np.flip(data, axis=-1).copy()  # flip X
        return flipped
    raise PolarityResolutionError(f"Expected north/south polarity, got {polarity!r}")


def signed_integer_to_uint8(array):
    """Convert a signed anatomy stack to display-safe 8-bit intensities.

    Negative values are shifted above zero before the full observed range is
    mapped to 0-255. The returned dictionary records that conversion.

    Args:
        array (numpy.ndarray): Non-empty integer-dtype anatomy stack to convert.

    Returns:
        tuple[numpy.ndarray, dict]: The converted `uint8` array, and a record
        of the raw min/max, the negative offset applied, and the corrected and
        output intensity ranges.

    Raises:
        TypeError: If `array` is empty or not of an integer dtype.
    """
    stack = np.asarray(array)
    if stack.size == 0 or not np.issubdtype(stack.dtype, np.integer):
        raise TypeError(f"Expected a non-empty integer stack, got dtype={stack.dtype} shape={stack.shape}")
    raw_min, raw_max = int(stack.min()), int(stack.max())
    # Shift negative values (ScanImage int16) up so the darkest pixel is 0,
    # keeping the result within the uint16 range.
    negative_offset = abs(raw_min) if raw_min < 0 else 0
    corrected = np.clip(stack.astype(np.int32) + negative_offset, 0, UINT16_MAX)
    corrected_min, corrected_max = int(corrected.min()), int(corrected.max())
    if corrected_max <= corrected_min:
        # Flat stack: no range to stretch.
        output = np.zeros(stack.shape, dtype=np.uint8)
    else:
        # Stretch the corrected range linearly onto 0-255.
        output = np.clip(np.rint((corrected - corrected_min) * (UINT8_MAX / (corrected_max - corrected_min))), 0, UINT8_MAX).astype(np.uint8)
    conversion_record = {
        "raw_min": raw_min,
        "raw_max": raw_max,
        "negative_offset": negative_offset,
        "corrected_min": corrected_min,
        "corrected_max": corrected_max,
        "output_min": int(output.min()),
        "output_max": int(output.max()),
    }
    return output, conversion_record


# Single-channel anatomy is assumed: every page is read as one Z slice. A stack
# saved with several ScanImage channels (interleaved pages, e.g. L427) would
# become a wrong, double-depth stack; the registration notebook checks for this.
def read_anatomy_pages(path):
    """Read TIFF pages in file order and verify that they form one 3-D stack.

    Args:
        path (str | Path): Path to the anatomy TIFF file to read.

    Returns:
        tuple[numpy.ndarray, dict]: The stacked pages as a 3-D array
        and a dictionary describing the read (reader name, page count, and
        Z/Y/X shape).

    Raises:
        ValueError: If the TIFF has no pages, or its pages differ in shape.
    """
    source = Path(path)
    with tifffile.TiffFile(source) as anatomy_tiff:
        if not anatomy_tiff.pages:
            raise ValueError(f"Anatomy TIFF contains no pages: {source}")
        page_shape = tuple(int(size) for size in anatomy_tiff.pages[0].shape)
        pages = [np.asarray(page.asarray()) for page in anatomy_tiff.pages]
    # Every page must be one 2-D slice of the same size.
    if any(page.ndim != 2 or tuple(page.shape) != page_shape for page in pages):
        raise ValueError(f"Anatomy TIFF pages are not a consistent 2D stack: {source}")
    stack = np.stack(pages)
    read_record = {"reader": "tifffile_pages", "page_count": len(pages), "shape_zyx": list(stack.shape)}
    return stack, read_record


def write_registration_nrrd(array_zyx, path, spacing_xyz_um):
    """Write an anatomy stack as an uncompressed NRRD with physical spacing.

    Args:
        array_zyx (numpy.ndarray): Anatomy stack in Z, Y, X order to write.
        path (str | Path): Output NRRD file path; parent directories are
            created if missing.
        spacing_xyz_um (Sequence[float]): Positive physical voxel spacing in
            micrometers, ordered X, Y, Z.

    Returns:
        str: Name of the library used to write the file (`"SimpleITK"`).

    Raises:
        ValueError: If the spacing isn't three positive numbers.
        ImportError: If SimpleITK isn't installed.
    """
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    spacing = tuple(float(value) for value in spacing_xyz_um)
    if len(spacing) != 3 or any(value <= 0 for value in spacing):
        raise ValueError(f"Expected positive X,Y,Z spacing, got {spacing_xyz_um}")
    # Imported here: only NRRD writing needs SimpleITK.
    try:
        import SimpleITK as sitk
    except Exception as exc:  # pragma: no cover - environment dependent
        raise ImportError("SimpleITK is required to write canonical anatomy NRRD") from exc
    image = sitk.GetImageFromArray(np.asarray(array_zyx, dtype=np.uint8))  # numpy (Z, Y, X) -> image with X, Y, Z axes
    image.SetSpacing(spacing)  # SimpleITK takes spacing in X, Y, Z order
    sitk.WriteImage(image, str(output), useCompression=False)
    return "SimpleITK"


def preprocess_anatomy(
    *,
    anatomy_path,
    output_path,
    polarity,
    source_spacing_xyz_um,
    target_xy_shape=(750, 750),
):
    """Prepare raw anatomy for same-frame registration with functional data.

    The function converts intensity, applies the polarity-dependent X/Y flip,
    reverses Z for the registration convention, resizes X/Y, and writes NRRD.

    Args:
        anatomy_path (str | Path): Path to the raw anatomy TIFF to read.
        output_path (str | Path): Path where the canonical registration NRRD
            is written.
        polarity (str): Polarity label (`"north"` or `"south"`, or an
            accepted alias) determining the X/Y flip applied.
        source_spacing_xyz_um (Sequence[float]): Positive physical voxel
            spacing of the raw anatomy in micrometers, ordered X, Y, Z.
        target_xy_shape (tuple[int, int]): Target (Y, X) pixel shape to
            resize each plane to. Defaults to (750, 750).

    Returns:
        dict: Source, output, spacing, intensity, and orientation
        details describing the conversion.
    """
    raw_stack, read_record = read_anatomy_pages(anatomy_path)
    converted, conversion_record = signed_integer_to_uint8(raw_stack)
    oriented = apply_canonical_xy(converted, polarity)
    reversed_stack = np.flip(oriented, axis=0).copy()  # reverse the slice order (registration Z convention)
    target_y, target_x = (int(target_xy_shape[0]), int(target_xy_shape[1]))
    canonical_stack = np.empty((reversed_stack.shape[0], target_y, target_x), dtype=np.uint8)
    # Resize each slice in X/Y; the number of slices is unchanged.
    for slice_index, anatomy_slice in enumerate(reversed_stack):
        resized_slice = resize(
            anatomy_slice,
            (target_y, target_x),
            order=1,
            preserve_range=True,
            anti_aliasing=True,
        )
        canonical_stack[slice_index] = np.clip(np.rint(resized_slice), 0, UINT8_MAX).astype(np.uint8)
    spacing_x_um, spacing_y_um, spacing_z_um = (float(value) for value in source_spacing_xyz_um)
    # Same field of view on a new grid: X/Y spacing scales by old/new size; Z unchanged.
    output_spacing = (spacing_x_um * raw_stack.shape[2] / target_x, spacing_y_um * raw_stack.shape[1] / target_y, spacing_z_um)
    writer = write_registration_nrrd(canonical_stack, output_path, output_spacing)
    anatomy_record = {
        "source_path": str(Path(anatomy_path)),
        "output_path": str(Path(output_path)),
        "source_shape_zyx": list(raw_stack.shape),
        "output_shape_zyx": list(canonical_stack.shape),
        "source_dtype": str(raw_stack.dtype),
        "output_dtype": str(canonical_stack.dtype),
        "source_spacing_xyz_um": [spacing_x_um, spacing_y_um, spacing_z_um],
        "output_spacing_xyz_um": list(output_spacing),
        "spacing_units": "um",
        "reader": read_record,
        "range_conversion": conversion_record,
        "xy_transform": XY_TRANSFORM_BY_POLARITY[normalize_polarity(polarity)],
        "z_transform": Z_TRANSFORM,
        "writer": writer,
    }
    return anatomy_record


# TODO: for Danin to check -- the spatial manifest names, to align them with the
# renamed workflow (canonical_preprocessing.py, preprocess_canonical_fish):
# - stored on disk: the file name `spatial_preprocessing_manifest.json` and
#   `"stage": "canonical_spatial_preprocessing"` inside it;
# - in the code: spatial_manifest_path, write_spatial_manifest,
#   validate_spatial_manifest, add_suite2p_record_to_manifest.
# Renaming the stored ones needs a migration: existing manifests would fail validation.
def spatial_manifest_path(fish_dir):
    """Return the standard spatial-manifest path for one fish.

    Args:
        fish_dir (str | Path): Root directory for one fish.

    Returns:
        Path: Standard path to the spatial preprocessing manifest under
        `02_reg/00_preprocessing`.
    """
    manifest_path = Path(fish_dir) / "02_reg" / "00_preprocessing" / SPATIAL_MANIFEST_NAME
    return manifest_path


def write_spatial_manifest(
    *,
    fish_dir,
    polarity,
    functional_planes,
    anatomy,
    sessions=(),
    output_path=None,
):
    """Write the authoritative record of spatial inputs, outputs, and transforms.

    The manifest lets later stages confirm that functional and anatomy images
    use the same X/Y frame before registration or NCC matching.

    Args:
        fish_dir (str | Path): Root directory for one fish; used to derive
            `fish_id` and the default manifest path.
        polarity (PolarityResolution): Resolved polarity to record, including
            its source and supporting evidence.
        functional_planes (Sequence[dict]): Per-plane functional
            records to include in the manifest.
        anatomy (dict): Anatomy conversion details to include in
            the manifest.
        sessions (Sequence[dict]): Optional per-session records
            to include in the manifest. Defaults to an empty sequence.
        output_path (str | Path | None): Optional explicit manifest path.
            Defaults to None, which uses `spatial_manifest_path`.

    Returns:
        dict: The manifest payload that was written to disk.

    Raises:
        FileExistsError: If the manifest already exists.
    """
    root = Path(fish_dir)
    path = Path(output_path) if output_path else spatial_manifest_path(root)
    # Never overwrite an existing manifest.
    if path.exists():
        raise FileExistsError(f"Spatial preprocessing manifest already exists: {path}")
    xy_transform = XY_TRANSFORM_BY_POLARITY[polarity.polarity]
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
            "functional_xy": xy_transform,
            "anatomy_xy": xy_transform,
            "anatomy_z": Z_TRANSFORM,
        },
        "functional_planes": [dict(value) for value in functional_planes],
        "anatomy": dict(anatomy),
        "sessions": [dict(value) for value in sessions],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def validate_spatial_manifest(path):
    """Load a spatial manifest and reject incomplete or unknown coordinate frames.

    Args:
        path (str | Path): Path to the spatial preprocessing manifest JSON
            file.

    Returns:
        dict: The parsed manifest payload.

    Raises:
        ValueError: If the manifest is incomplete or records an unknown frame.
    """
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


def add_suite2p_record_to_manifest(
    fish_dir,
    *,
    plane_index,
    output_path,
    suite2p_plane_dir,
):
    """Add a plane's Suite2P record to the fish's spatial preprocessing manifest.

    The record lists the plane's motion-corrected recording (canonical
    orientation) and points to its Suite2P folder (with `ops.npy`). A later
    call for the same plane replaces its record.

    Args:
        fish_dir (str | Path): Root directory for one fish, used to locate
            the existing spatial preprocessing manifest.
        plane_index (int): Index of the plane the motion-corrected recording
            belongs to; replaces any existing record for the same plane.
        output_path (str | Path): Path to the motion-corrected recording.
        suite2p_plane_dir (str | Path): Path to the Suite2P plane directory
            that produced the output.

    Returns:
        dict: The updated manifest payload that was written to
        disk.
    """
    path = spatial_manifest_path(fish_dir)
    payload = validate_spatial_manifest(path)
    # Keep every other plane's record; this plane's is replaced below.
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
    # Write to a temporary file, then swap it in, so a crash can't leave a half-written manifest.
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
    "VALID_POLARITIES",
    "XY_TRANSFORM_BY_POLARITY",
    "Z_TRANSFORM",
    "anatomy_z_spacing_um",
    "apply_canonical_xy",
    "spatial_manifest_path",
    "normalize_polarity",
    "preprocess_anatomy",
    "read_anatomy_pages",
    "read_raw_metadata_polarity",
    "add_suite2p_record_to_manifest",
    "resolve_polarity",
    "signed_integer_to_uint8",
    "validate_spatial_manifest",
    "write_spatial_manifest",
]
