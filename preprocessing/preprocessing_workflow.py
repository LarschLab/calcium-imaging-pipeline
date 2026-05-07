from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PREPROCESSING_MODE_STREAMING = "streaming_two_pass"
PREPROCESSING_MODE_FULL_MEMORY = "full_memory"
VALID_PREPROCESSING_MODES = {PREPROCESSING_MODE_STREAMING, PREPROCESSING_MODE_FULL_MEMORY}
VALID_PROTOCOLS = {"resonant", "linear"}


@dataclass(frozen=True)
class PreprocessingConfig:
    fish_ids: list[str]
    input_base: Path
    output_base: Path
    protocol: str = "resonant"
    mode: str = PREPROCESSING_MODE_STREAMING
    blocks: list[int] | None = None
    n_planes: int | None = None
    n_frames_per_plane: int | None = None
    volume_flyback_frames: int = 1
    remove_first_frame: bool = False
    progress: bool = True


@dataclass(frozen=True)
class Suite2PConfig:
    data_root: Path
    ops_path: Path
    fps: float
    fish_ids: list[str]
    selected_planes: list[int]
    fast_disk: Path | None = None
    storage_root: Path | None = None


@dataclass(frozen=True)
class FishValidationResult:
    fish_id: str
    ok: bool
    errors: list[str]
    warnings: list[str]


def load_json_config(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Config JSON must contain an object.")
    return data


def write_json_config(path: str | Path, data: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def parse_csv_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(part).strip() for part in value if str(part).strip()]
    raise ValueError("Expected a comma-separated string or list of strings.")


def parse_optional_int_list(value: Any) -> list[int] | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    values = parse_csv_strings(value) if isinstance(value, str) else value
    try:
        parsed = [int(item) for item in values]
    except (TypeError, ValueError) as exc:
        raise ValueError("Expected integer values.") from exc
    return parsed or None


def parse_required_int_list(value: Any, label: str) -> list[int]:
    parsed = parse_optional_int_list(value)
    if not parsed:
        raise ValueError(f"{label} is required.")
    return parsed


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", ""}:
            return False
    return bool(value)


def optional_path(value: Any) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    return Path(text) if text else None


def preprocessing_config_from_dict(data: dict[str, Any]) -> PreprocessingConfig:
    fish_ids = parse_csv_strings(data.get("fish_ids"))
    if not fish_ids:
        raise ValueError("At least one fish ID is required.")

    protocol = str(data.get("protocol", "resonant")).strip().lower()
    if protocol not in VALID_PROTOCOLS:
        raise ValueError("protocol must be 'resonant' or 'linear'.")

    mode = str(data.get("mode", PREPROCESSING_MODE_STREAMING)).strip()
    if mode not in VALID_PREPROCESSING_MODES:
        raise ValueError(f"mode must be one of: {', '.join(sorted(VALID_PREPROCESSING_MODES))}.")

    input_base = optional_path(data.get("input_base"))
    output_base = optional_path(data.get("output_base"))
    if input_base is None:
        raise ValueError("input_base is required.")
    if output_base is None:
        raise ValueError("output_base is required.")

    n_planes = data.get("n_planes")
    n_frames_per_plane = data.get("n_frames_per_plane")
    if protocol == "resonant":
        if n_planes in (None, "") or n_frames_per_plane in (None, ""):
            raise ValueError("n_planes and n_frames_per_plane are required for resonant preprocessing.")
        n_planes = int(n_planes)
        n_frames_per_plane = int(n_frames_per_plane)
        if n_planes <= 0 or n_frames_per_plane <= 0:
            raise ValueError("n_planes and n_frames_per_plane must be positive.")
    else:
        n_planes = None
        n_frames_per_plane = None

    volume_flyback_frames = int(data.get("volume_flyback_frames", 1) or 0)
    if volume_flyback_frames < 0:
        raise ValueError("volume_flyback_frames cannot be negative.")

    return PreprocessingConfig(
        fish_ids=fish_ids,
        input_base=input_base,
        output_base=output_base,
        protocol=protocol,
        mode=mode,
        blocks=parse_optional_int_list(data.get("blocks")),
        n_planes=n_planes,
        n_frames_per_plane=n_frames_per_plane,
        volume_flyback_frames=volume_flyback_frames,
        remove_first_frame=parse_bool(data.get("remove_first_frame", False)),
        progress=parse_bool(data.get("progress", True)),
    )


def suite2p_config_from_dict(data: dict[str, Any]) -> Suite2PConfig:
    fish_ids = parse_csv_strings(data.get("fish_ids"))
    if not fish_ids:
        raise ValueError("At least one fish ID is required.")

    data_root = optional_path(data.get("data_root"))
    ops_path = optional_path(data.get("ops_path"))
    if data_root is None:
        raise ValueError("data_root is required.")
    if ops_path is None:
        raise ValueError("ops_path is required.")

    fps = float(data.get("fps"))
    if fps <= 0:
        raise ValueError("fps must be positive.")

    return Suite2PConfig(
        data_root=data_root,
        ops_path=ops_path,
        fps=fps,
        fish_ids=fish_ids,
        selected_planes=parse_required_int_list(data.get("selected_planes"), "selected_planes"),
        fast_disk=optional_path(data.get("fast_disk")),
        storage_root=optional_path(data.get("storage_root")),
    )


def individual_planes_dir(base: str | Path, fish_id: str) -> Path:
    return Path(base) / fish_id / "02_reg/00_preprocessing/2p_functional/01_individualPlanes"


def validate_preprocessing_outputs(data_root: str | Path, fish_ids: list[str], selected_planes: list[int]) -> list[FishValidationResult]:
    results = []
    for fish_id in fish_ids:
        errors = []
        warnings = []
        pre_dir = individual_planes_dir(data_root, fish_id)
        metadata = pre_dir / f"{fish_id}_preprocessing_metadata.json"

        if not pre_dir.exists():
            errors.append(f"Missing preprocessing folder: {pre_dir}")
        if not metadata.exists():
            errors.append(f"Missing preprocessing metadata: {metadata}")

        for plane_idx in selected_planes:
            expected = pre_dir / f"{fish_id}_plane{plane_idx}.tif"
            if not expected.exists():
                errors.append(f"Missing plane TIFF for plane {plane_idx}: {expected}")

        if metadata.exists():
            try:
                metadata_data = json.loads(metadata.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                warnings.append(f"Could not parse preprocessing metadata: {metadata}")
            else:
                protocol = metadata_data.get("protocol")
                if protocol != "resonant":
                    warnings.append(f"Suite2P GUI currently expects resonant plane TIFFs; metadata protocol is {protocol!r}.")

        results.append(FishValidationResult(fish_id=fish_id, ok=not errors, errors=errors, warnings=warnings))
    return results


def raise_for_invalid_suite2p_inputs(config: Suite2PConfig) -> None:
    if not config.data_root.exists():
        raise ValueError(f"data_root does not exist: {config.data_root}")
    if not config.ops_path.exists():
        raise ValueError(f"ops_path does not exist: {config.ops_path}")

    results = validate_preprocessing_outputs(config.data_root, config.fish_ids, config.selected_planes)
    errors = [message for result in results for message in result.errors]
    if errors:
        raise ValueError("Preprocessing outputs are not ready for Suite2P:\n" + "\n".join(errors))


def run_preprocessing_config(config: PreprocessingConfig) -> None:
    import preprocessing_tiff

    for fish_id in config.fish_ids:
        print(f"[preprocess] Starting {fish_id}", flush=True)
        if config.mode == PREPROCESSING_MODE_STREAMING:
            preprocessing_tiff.process_fish_streaming(
                fish_id,
                config.input_base,
                config.output_base,
                protocol=config.protocol,
                blocks=config.blocks,
                n_planes=config.n_planes,
                n_frames_per_plane=config.n_frames_per_plane,
                volume_flyback_frames=config.volume_flyback_frames,
                remove_first_frame=config.remove_first_frame,
                progress=config.progress,
            )
        elif config.mode == PREPROCESSING_MODE_FULL_MEMORY:
            preprocessing_tiff.process_fish(
                fish_id,
                config.input_base,
                config.output_base,
                protocol=config.protocol,
                blocks=config.blocks,
                n_planes=config.n_planes,
                n_frames_per_plane=config.n_frames_per_plane,
                volume_flyback_frames=config.volume_flyback_frames,
                remove_first_frame=config.remove_first_frame,
            )
        else:
            raise ValueError(f"Unknown preprocessing mode: {config.mode}")
        print(f"[preprocess] Finished {fish_id}", flush=True)


def run_suite2p_config(config: Suite2PConfig) -> None:
    raise_for_invalid_suite2p_inputs(config)

    import motion_segmentation_suite2p

    motion_segmentation_suite2p.batch_process(
        config.data_root,
        config.ops_path,
        config.fps,
        fish_ids=config.fish_ids,
        selected_planes=config.selected_planes,
        fast_disk=config.fast_disk,
        storage_root=config.storage_root,
    )
