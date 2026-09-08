"""Tests for spatial orientation, anatomy matching, and temporal drift decisions."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
import tifffile
import SimpleITK as sitk

import preprocessing.drift_analysis as drift_analysis
import preprocessing.functional_anatomy_qc as compatibility_qc
from preprocessing.spatial_preprocessing import (
    PolarityResolution,
    apply_canonical_xy,
    canonical_manifest_path,
    preprocess_anatomy,
    record_motion_corrected_output,
    resolve_polarity,
    signed_integer_to_uint8,
    write_spatial_manifest,
)

from preprocessing.drift_analysis import (
    FunctionalAnatomyQCConfig,
    anatomy_z_spacing_um,
    block_third_bounds,
    block_third_labels,
    quadratic_peak_z,
    read_raw_anatomy,
    run_drift_analysis,
)
from preprocessing.preprocessing_tiff import process_fish


def _spot(shape: tuple[int, int], y: int, x: int) -> np.ndarray:
    """Create a small synthetic bright spot for anatomy test images."""
    yy, xx = np.indices(shape)
    return np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / 5.0).astype(np.float32)


def _make_fish(root: Path, *, drifting: bool = False) -> Path:
    """Create a minimal synthetic fish with either stable or drifting planes."""
    fish = root / "L000_f00"
    anatomy_dir = fish / "01_raw" / "2p" / "anatomy"
    metadata_dir = fish / "01_raw" / "2p" / "metadata"
    movie_dir = fish / "02_reg" / "00_preprocessing" / "2p_functional" / "02_motionCorrected"
    pre_dir = fish / "02_reg" / "00_preprocessing" / "2p_functional" / "01_individualPlanes"
    for directory in (anatomy_dir, metadata_dir, movie_dir, pre_dir):
        directory.mkdir(parents=True)

    anatomy = np.zeros((7, 32, 32), dtype=np.uint16)
    for z_index in range(anatomy.shape[0]):
        image = _spot((32, 32), 14, 14) + 0.65 * _spot((32, 32), 8 + z_index, 20)
        anatomy[z_index] = np.rint(image / image.max() * 50000).astype(np.uint16)
    tifffile.imwrite(anatomy_dir / "L000_f00_anatomy_00001.tif", anatomy, photometric="minisblack")
    with (metadata_dir / "run_metadata.csv").open("w", newline="") as handle:
        csv.writer(handle).writerow(["step_size_um_anatomy", "2"])

    stable_or_drifting = (
        ((0, (0, 2, 5)), (1, (1, 3, 6)))
        if drifting
        else ((0, (0, 2, 2)), (1, (1, 3, 3)))
    )
    for plane_index, z_by_block in stable_or_drifting:
        frames = []
        for z_index in z_by_block:
            crop = anatomy[z_index, 6:22, 7:23]
            frames.extend([crop] * 9)
        tifffile.imwrite(
            movie_dir / f"L000_f00_plane{plane_index}_mcorrected.tif",
            np.asarray(frames, dtype=np.uint16),
            photometric="minisblack",
        )
    metadata = {
        "fish_id": "L000_f00",
        "sessions": [
            {
                "session_label": "r1",
                "session_number": 1,
                "output_planes": [0, 1],
                "selected_tiffs": ["block0.tif", "block1.tif", "block2.tif"],
            }
        ],
    }
    (pre_dir / "L000_f00_preprocessing_metadata.json").write_text(json.dumps(metadata))
    canonical_anatomy = fish / "02_reg" / "00_preprocessing" / "2p_anatomy" / "L000_f00_anatomy_2P_GCaMP.nrrd"
    canonical_anatomy.parent.mkdir(parents=True)
    image = sitk.GetImageFromArray(anatomy.astype(np.uint8))
    image.SetSpacing((1.0, 1.0, 2.0))
    sitk.WriteImage(image, str(canonical_anatomy), useCompression=False)
    write_spatial_manifest(
        fish_dir=fish,
        polarity=PolarityResolution("south", "raw_metadata", "resolved", "run_metadata.csv", None),
        functional_planes=[],
        anatomy={"output_path": str(canonical_anatomy)},
        sessions=metadata["sessions"],
    )
    for plane_index in (0, 1):
        record_motion_corrected_output(
            fish,
            plane_index=plane_index,
            output_path=movie_dir / f"L000_f00_plane{plane_index}_mcorrected.tif",
            suite2p_plane_dir=fish / "03_analysis" / "functional" / "suite2P" / f"plane{plane_index}",
        )
    return fish


class FunctionalAnatomyQCTests(unittest.TestCase):
    def test_historical_qc_module_preserves_direct_helper_imports(self) -> None:
        """The renamed module must not break existing notebook imports."""
        for name in (
            "norm01",
            "corrcoef_img",
            "load_preprocessing_sessions",
            "build_window_references",
            "search_scale",
            "summarize_sessions",
            "run_functional_anatomy_qc",
        ):
            self.assertIs(getattr(compatibility_qc, name), getattr(drift_analysis, name))

    def test_functional_xy_orientation_is_one_opt_in_step(self) -> None:
        """The one flag must control both polarity use and X/Y reorientation."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_base = root / "source"
            raw_dir = source_base / "L000_f00" / "01_raw" / "2p" / "functional"
            raw_dir.mkdir(parents=True)
            raw = np.asarray([[[1, 2], [3, 4]], [[5, 6], [7, 8]]], dtype=np.uint16)
            tifffile.imwrite(raw_dir / "L000_f00_00001.tif", raw, photometric="minisblack")

            unchanged_base = root / "unchanged"
            process_fish(
                "L000_f00", source_base, unchanged_base, protocol="linear",
                apply_polarity_orientation=False, polarity="south",
                polarity_source="ignored test value",
            )
            unchanged_dir = unchanged_base / "L000_f00" / "02_reg" / "00_preprocessing" / "2p_functional" / "01_individualPlanes"
            np.testing.assert_array_equal(tifffile.imread(unchanged_dir / "L000_f00_stack.tif"), raw)
            unchanged_metadata = json.loads(
                (unchanged_dir / "L000_f00_preprocessing_metadata.json").read_text()
            )
            self.assertFalse(unchanged_metadata["apply_polarity_orientation"])
            self.assertIsNone(unchanged_metadata["polarity"])
            self.assertEqual(unchanged_metadata["xy_transform"], "none")
            self.assertEqual(unchanged_metadata["output_xy_frame"], "two_photon_acquisition_xy")

            oriented_base = root / "oriented"
            process_fish(
                "L000_f00", source_base, oriented_base, protocol="linear",
                apply_polarity_orientation=True, polarity="south",
                polarity_source="test",
            )
            oriented_dir = oriented_base / "L000_f00" / "02_reg" / "00_preprocessing" / "2p_functional" / "01_individualPlanes"
            np.testing.assert_array_equal(
                tifffile.imread(oriented_dir / "L000_f00_stack.tif"),
                np.flip(raw, axis=-1),
            )
            oriented_metadata = json.loads(
                (oriented_dir / "L000_f00_preprocessing_metadata.json").read_text()
            )
            self.assertTrue(oriented_metadata["apply_polarity_orientation"])
            self.assertEqual(oriented_metadata["polarity"], "south")
            self.assertEqual(oriented_metadata["xy_transform"], "flipX")
            self.assertEqual(oriented_metadata["output_xy_frame"], "codeants_2p_canonical_xy_v1")

            with self.assertRaisesRegex(ValueError, "requires a resolved north/south polarity"):
                process_fish(
                    "L000_f00", source_base, root / "invalid", protocol="linear",
                    apply_polarity_orientation=True,
                )

    def test_direct_orientation_transforms(self) -> None:
        """North and south polarity must apply their documented direct flips."""
        array = np.asarray([[1, 2], [3, 4]])
        np.testing.assert_array_equal(apply_canonical_xy(array, "north"), [[3, 4], [1, 2]])
        np.testing.assert_array_equal(apply_canonical_xy(array, "south"), [[2, 1], [4, 3]])

    def test_missing_metadata_uses_accepted_classifier_but_conflict_stops(self) -> None:
        """Classifier output may fill missing metadata but may not override it."""
        with tempfile.TemporaryDirectory() as temporary:
            fish = Path(temporary) / "L000_f00"
            fish.mkdir()
            resolved = resolve_polarity(
                fish,
                classifier_prediction={"polarity": "south", "status": "predicted", "model_name": "test"},
            )
            self.assertEqual((resolved.polarity, resolved.source), ("south", "anatomy_classifier"))

            metadata = fish / "01_raw" / "2p" / "metadata"
            metadata.mkdir(parents=True)
            (metadata / "run_metadata.csv").write_text("parameter,value\nfish_orientation,north\n")
            with self.assertRaisesRegex(RuntimeError, "conflicts"):
                resolve_polarity(
                    fish,
                    classifier_prediction={"polarity": "south", "status": "predicted", "model_name": "test"},
                )

    def test_anatomy_preprocess_applies_xy_then_z_once(self) -> None:
        """Anatomy preparation must apply each requested axis change exactly once."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = np.arange(2 * 3 * 4, dtype=np.int16).reshape(2, 3, 4) - 3
            source = root / "anatomy.tif"
            output = root / "anatomy.nrrd"
            tifffile.imwrite(source, raw, photometric="minisblack")
            record = preprocess_anatomy(
                anatomy_path=source,
                output_path=output,
                polarity="north",
                source_spacing_xyz_um=(1.0, 1.0, 2.0),
                target_xy_shape=(3, 4),
            )
            observed = sitk.GetArrayFromImage(sitk.ReadImage(str(output)))
            self.assertEqual(observed.dtype, np.uint8)
            converted, _ = signed_integer_to_uint8(raw)
            expected = np.flip(apply_canonical_xy(converted, "north"), axis=0)
            np.testing.assert_array_equal(observed, expected)
            self.assertEqual(record["xy_transform"], "flipY")
            self.assertEqual(record["z_transform"], "flipZ")
    def test_blocks_are_split_into_thirds_and_block_zero_is_named_explicitly(self) -> None:
        """Temporal windows must have complete and understandable block labels."""
        self.assertEqual(
            block_third_bounds(30, 3),
            (
                (0, 3),
                (3, 6),
                (6, 10),
                (10, 13),
                (13, 16),
                (16, 20),
                (20, 23),
                (23, 26),
                (26, 30),
            ),
        )
        self.assertEqual(
            block_third_labels(2),
            (
                "Block 0\nfirst third",
                "Block 0\nmiddle third",
                "Block 0\nfinal third",
                "Block 1\nfirst third",
                "Block 1\nmiddle third",
                "Block 1\nfinal third",
            ),
        )

    def test_quadratic_peak_reports_subslice_location(self) -> None:
        """A smooth peak estimate should report positions between integer slices."""
        self.assertTrue(np.isclose(quadratic_peak_z(np.asarray([0.0, 0.5, 1.0, 0.75, 0.0])), 2.1666666667))

    def test_raw_anatomy_preserves_page_order_and_signed_dtype(self) -> None:
        """Raw anatomy reading must not reorder pages or discard signed values."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stack = (np.arange(5 * 8 * 9).reshape(5, 8, 9) - 100).astype(np.int16)
            path = root / "fish_anatomy_00001.tif"
            tifffile.imwrite(path, stack, photometric="minisblack")
            loaded = read_raw_anatomy(path)
            self.assertEqual(loaded.data_zyx.shape, stack.shape)
            self.assertEqual(loaded.source_dtype, "int16")
            np.testing.assert_array_equal(loaded.data_zyx, stack)

    def test_anatomy_spacing_comes_from_metadata_and_must_agree(self) -> None:
        """Conflicting anatomy slice spacing must stop instead of being guessed."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("first_metadata.csv", "second_metadata.csv"):
                with (root / name).open("w", newline="") as handle:
                    csv.writer(handle).writerow(["step_size_um_anatomy", "2"])
            spacing, sources = anatomy_z_spacing_um(root)
            self.assertEqual(spacing, 2.0)
            self.assertEqual(len(sources), 2)

    def test_end_to_end_qc_shows_block_zero_but_excludes_it_from_gate(self) -> None:
        """Initial settling data should be plotted but excluded from drift decisions."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fish = _make_fish(root)
            output = root / "output"
            manifest = run_drift_analysis(
                fish_dir=fish,
                output_dir=output,
                config=FunctionalAnatomyQCConfig(
                    sampled_frames_per_window=3,
                    top_correlated_frames=2,
                    scale_coarse=(1.0, 1.0, 0.1),
                    scale_fine_half_window=0,
                    scale_xfine_half_window=0,
                    local_xy_radius_px=2,
                    workers=2,
                ),
            )
            intervals = pd.read_csv(output / "ncc_drift_intervals.csv")
            self.assertEqual(set(intervals["block_index"]), {0, 1, 2})
            self.assertFalse(intervals.loc[intervals["block_index"] == 0, "included_in_drift_gate"].any())
            self.assertTrue(intervals.loc[intervals["block_index"] > 0, "included_in_drift_gate"].all())
            summary = pd.read_csv(output / "ncc_drift_session_summary.csv")
            self.assertEqual(set(summary["status"]), {"pass_candidate"})
            self.assertEqual(manifest["status"], "pass_candidate")
            self.assertEqual(len(intervals), 2 * 9)
            self.assertEqual(
                set(intervals["placement_method"]),
                {"tracked_local_xy_with_global_fallback"},
            )
            self.assertNotIn("engine", intervals.columns)
            self.assertFalse((output / "ncc_xy_engine_comparison.csv").exists())
            self.assertFalse((output / "ncc_xy_engine_comparison.png").exists())
            self.assertGreater((output / "ncc_drift_tracks.png").stat().st_size, 0)
            self.assertGreater((output / "ncc_drift_profiles.png").stat().st_size, 0)
            self.assertGreater((output / "ncc_best_z_profiles.png").stat().st_size, 0)
            anchor_profiles = pd.read_csv(output / "ncc_anchor_profiles.csv")
            self.assertEqual(anchor_profiles["plane_index"].nunique(), 2)
            placements = pd.read_csv(output / "ncc_scale_bestz_by_plane.csv")
            self.assertTrue({"best_z", "best_z_subslice", "max_ncc", "placement_x", "placement_y"}.issubset(placements.columns))
            for reference_path in placements["reference_path"]:
                self.assertTrue(Path(reference_path).is_file())
            self.assertEqual(manifest["version"], 4)
            self.assertEqual(manifest["downstream_handoff"]["schema"], "functional_anatomy_ncc_handoff_v1")
            self.assertEqual(
                manifest["downstream_handoff"]["reusable_components"],
                ["functional_reference", "scale", "best_z", "ncc_depth_profile", "xy_placement"],
            )
            self.assertEqual(
                manifest["placement_method"]["name"],
                "tracked_local_xy_with_global_fallback",
            )

    def test_end_to_end_qc_fails_coherent_post_block_zero_drift(self) -> None:
        """Consistent movement across planes after settling should fail the gate."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fish = _make_fish(root, drifting=True)
            output = root / "output"
            manifest = run_drift_analysis(
                fish_dir=fish,
                output_dir=output,
                config=FunctionalAnatomyQCConfig(
                    sampled_frames_per_window=3,
                    top_correlated_frames=2,
                    scale_coarse=(1.0, 1.0, 0.1),
                    scale_fine_half_window=0,
                    scale_xfine_half_window=0,
                    local_xy_radius_px=2,
                    workers=2,
                ),
            )
            summary = pd.read_csv(output / "ncc_drift_session_summary.csv")
            self.assertEqual(set(summary["status"]), {"fail_candidate"})
            self.assertEqual(manifest["status"], "fail_candidate")
            self.assertTrue((summary["consensus_change_slices"].abs() >= 2).all())


if __name__ == "__main__":
    unittest.main()
