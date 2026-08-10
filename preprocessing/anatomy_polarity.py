"""Anatomy-based polarity inference trained only from raw fish metadata."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
from skimage import exposure, filters, transform
from skimage.feature import hog

from preprocessing.spatial_preprocessing import (
    PolarityPrediction,
    apply_canonical_xy,
    normalize_polarity,
    read_anatomy_pages,
    read_raw_metadata_polarity,
)


@dataclass(frozen=True)
class AnatomyPolarityConfig:
    projection_percentiles: tuple[int, ...] = (90, 95, 99)
    feature_shape: tuple[int, int] = (128, 128)
    include_edges: bool = True
    calibration_fraction: float = 1.0
    model_name: str = "raw_metadata_hog_template"
    model_version: str = "1"


@dataclass(frozen=True)
class AnatomyPolarityModel:
    templates: Mapping[tuple[int, bool], np.ndarray]
    calibration_floor: float
    reference_fish_ids: tuple[str, ...]
    config: AnatomyPolarityConfig


def discover_anatomy(fish_dir: str | Path) -> Path:
    root = Path(fish_dir) / "01_raw" / "2p" / "anatomy"
    hits = sorted(
        path for path in root.glob("*.tif*")
        if path.is_file() and "ex_vivo" not in path.name.lower() and "exvivo" not in path.name.lower()
    )
    if len(hits) != 1:
        raise ValueError(f"Expected exactly one in-vivo anatomy TIFF for {Path(fish_dir).name}; found {len(hits)}")
    return hits[0]


def projection_variants(path: str | Path, percentiles: Sequence[int]) -> dict[int, np.ndarray]:
    stack, _ = read_anatomy_pages(path)
    data = stack.astype(np.float32)
    if float(data.min()) < 0:
        data -= float(data.min())
    output: dict[int, np.ndarray] = {}
    for percentile in percentiles:
        projection = np.percentile(data, int(percentile), axis=0).astype(np.float32)
        low, high = np.percentile(projection, (2.0, 99.7))
        output[int(percentile)] = np.clip((projection - low) / (high - low + 1e-6), 0, 1).astype(np.float32)
    return output


def _keys(config: AnatomyPolarityConfig) -> tuple[tuple[int, bool], ...]:
    modes = (False, True) if config.include_edges else (False,)
    return tuple((value, edge) for value in config.projection_percentiles for edge in modes)


def _feature(image: np.ndarray, edge: bool, config: AnatomyPolarityConfig) -> np.ndarray:
    data = transform.resize(image, config.feature_shape, preserve_range=True, anti_aliasing=True).astype(np.float32)
    data = exposure.equalize_adapthist(np.clip(data, 0, 1), clip_limit=0.02).astype(np.float32)
    if edge:
        data = np.hypot(filters.sobel_h(data), filters.sobel_v(data))
    vector = hog(
        data,
        orientations=9,
        pixels_per_cell=(16, 16),
        cells_per_block=(2, 2),
        feature_vector=True,
    ).astype(np.float32)
    return vector / (float(np.linalg.norm(vector)) + 1e-8)


def _features(projections: Mapping[int, np.ndarray], config: AnatomyPolarityConfig) -> dict[tuple[int, bool, str], np.ndarray]:
    output: dict[tuple[int, bool, str], np.ndarray] = {}
    for percentile, edge in _keys(config):
        for polarity in ("north", "south"):
            output[(percentile, edge, polarity)] = _feature(
                apply_canonical_xy(projections[percentile], polarity), edge, config
            )
    return output


def build_model(
    projections: Mapping[str, Mapping[int, np.ndarray]],
    labels: Mapping[str, str],
    *,
    config: AnatomyPolarityConfig | None = None,
    calibration_floor: float = 0.0,
) -> AnatomyPolarityModel:
    cfg = config or AnatomyPolarityConfig()
    fish_ids = tuple(sorted(projections))
    if not fish_ids or set(fish_ids) - set(labels):
        raise ValueError("Every reference projection needs a raw-metadata polarity label")
    feature_sets = {fish_id: _features(projections[fish_id], cfg) for fish_id in fish_ids}
    templates = {}
    for percentile, edge in _keys(cfg):
        vectors = [feature_sets[fish_id][(percentile, edge, normalize_polarity(labels[fish_id]))] for fish_id in fish_ids]
        templates[(percentile, edge)] = np.mean(vectors, axis=0).astype(np.float32)
    return AnatomyPolarityModel(templates, float(calibration_floor), fish_ids, cfg)


def predict(
    model: AnatomyPolarityModel,
    projections: Mapping[int, np.ndarray],
) -> tuple[PolarityPrediction, tuple[float, ...]]:
    feature_set = _features(projections, model.config)
    margins = []
    for percentile, edge in _keys(model.config):
        template = model.templates[(percentile, edge)]
        margins.append(float(feature_set[(percentile, edge, "north")] @ template) - float(feature_set[(percentile, edge, "south")] @ template))
    votes = tuple("north" if margin > 0 else "south" for margin in margins)
    unanimous = len(set(votes)) == 1
    min_abs = min(abs(value) for value in margins)
    accepted = unanimous and min_abs >= model.calibration_floor
    prediction = PolarityPrediction(
        polarity=votes[0] if accepted else None,
        status="predicted" if accepted else "review",
        model_name=model.config.model_name,
        model_version=model.config.model_version,
        median_margin=float(np.median(margins)),
        min_abs_margin=float(min_abs),
        unanimous=unanimous,
    )
    return prediction, tuple(margins)


def _references(
    microscopy_root: str | Path,
    config: AnatomyPolarityConfig,
    exclude_prefixes: Sequence[str],
) -> tuple[dict[str, dict[int, np.ndarray]], dict[str, str]]:
    root = Path(microscopy_root)
    projections: dict[str, dict[int, np.ndarray]] = {}
    labels: dict[str, str] = {}
    for fish_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        if any(fish_dir.name.startswith(prefix) for prefix in exclude_prefixes):
            continue
        polarity, _ = read_raw_metadata_polarity(fish_dir)
        if polarity not in {"north", "south"}:
            continue
        try:
            anatomy_path = discover_anatomy(fish_dir)
        except ValueError:
            continue
        labels[fish_dir.name] = polarity
        projections[fish_dir.name] = projection_variants(anatomy_path, config.projection_percentiles)
    counts = {value: sum(label == value for label in labels.values()) for value in ("north", "south")}
    if min(counts.values()) < 2:
        raise ValueError(f"Need at least two raw-metadata references per polarity; found {counts}")
    return projections, labels


def train_from_raw_metadata(
    microscopy_root: str | Path,
    *,
    config: AnatomyPolarityConfig | None = None,
    exclude_prefixes: Sequence[str] = ("L427",),
) -> tuple[AnatomyPolarityModel, list[dict[str, object]]]:
    cfg = config or AnatomyPolarityConfig()
    projections, labels = _references(microscopy_root, cfg, exclude_prefixes)
    validation: list[dict[str, object]] = []
    floors: list[float] = []
    for fish_id in sorted(projections):
        group = fish_id.split("_", 1)[0]
        train_ids = [value for value in projections if value.split("_", 1)[0] != group]
        if len(train_ids) < 2:
            raise ValueError(f"Too few references after holding out acquisition group {group}")
        held_model = build_model(
            {value: projections[value] for value in train_ids},
            {value: labels[value] for value in train_ids},
            config=cfg,
        )
        held_prediction, margins = predict(held_model, projections[fish_id])
        voted = "north" if float(np.median(margins)) > 0 else "south"
        correct = voted == labels[fish_id]
        validation.append({
            "fish_id": fish_id,
            "held_out_group": group,
            "true_polarity": labels[fish_id],
            "predicted_polarity": voted,
            "correct": correct,
            "unanimous": bool(held_prediction.unanimous),
            "median_margin": held_prediction.median_margin,
            "min_abs_margin": held_prediction.min_abs_margin,
            "training_fish_count": len(train_ids),
        })
        if correct and held_prediction.unanimous:
            floors.append(float(held_prediction.min_abs_margin or 0.0))
    all_valid = len(floors) == len(validation)
    floor = min(floors) * cfg.calibration_fraction if all_valid else float("inf")
    return build_model(projections, labels, config=cfg, calibration_floor=floor), validation


def predict_fish(model: AnatomyPolarityModel, fish_dir: str | Path) -> PolarityPrediction:
    path = discover_anatomy(fish_dir)
    projections = projection_variants(path, model.config.projection_percentiles)
    return predict(model, projections)[0]


def save_model(model: AnatomyPolarityModel, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "calibration_floor": model.calibration_floor,
        "reference_fish_ids": list(model.reference_fish_ids),
        "config": {
            "projection_percentiles": list(model.config.projection_percentiles),
            "feature_shape": list(model.config.feature_shape),
            "include_edges": model.config.include_edges,
            "calibration_fraction": model.config.calibration_fraction,
            "model_name": model.config.model_name,
            "model_version": model.config.model_version,
        },
    }
    arrays = {
        f"template_{percentile}_{int(edge)}": value
        for (percentile, edge), value in model.templates.items()
    }
    np.savez_compressed(output, metadata=np.asarray(json.dumps(metadata)), **arrays)
    return output


def load_model(path: str | Path) -> AnatomyPolarityModel:
    archive = np.load(Path(path), allow_pickle=False)
    metadata = json.loads(str(archive["metadata"].item()))
    cfg_data = metadata["config"]
    config = AnatomyPolarityConfig(
        projection_percentiles=tuple(int(value) for value in cfg_data["projection_percentiles"]),
        feature_shape=tuple(int(value) for value in cfg_data["feature_shape"]),
        include_edges=bool(cfg_data["include_edges"]),
        calibration_fraction=float(cfg_data["calibration_fraction"]),
        model_name=str(cfg_data["model_name"]),
        model_version=str(cfg_data["model_version"]),
    )
    templates = {
        (percentile, edge): np.asarray(archive[f"template_{percentile}_{int(edge)}"], dtype=np.float32)
        for percentile, edge in _keys(config)
    }
    return AnatomyPolarityModel(
        templates=templates,
        calibration_floor=float(metadata["calibration_floor"]),
        reference_fish_ids=tuple(str(value) for value in metadata["reference_fish_ids"]),
        config=config,
    )


__all__ = [
    "AnatomyPolarityConfig",
    "AnatomyPolarityModel",
    "build_model",
    "discover_anatomy",
    "load_model",
    "predict",
    "predict_fish",
    "projection_variants",
    "save_model",
    "train_from_raw_metadata",
]
