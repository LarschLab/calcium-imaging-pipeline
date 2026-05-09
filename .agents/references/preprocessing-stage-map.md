# Preprocessing Stage Map

Purpose

Show the ordered preprocessing flow from raw functional TIFFs to Suite2P outputs and dF/F artifacts.

Use this file when

- The task changes a preprocessing stage or its outputs.
- You need rerun implications or the first downstream consumer.

## Stages
1. Raw functional ingest
   - Owner: `preprocessing/preprocessing_tiff.py`
   - Inputs: `01_raw/2p/functional/*.tif`
   - Key functions: `parse_functional_tiff_name`, `get_functional_tiff_sessions`, `load_tiff_file`, `extract_block_number`, `concatenate_blocks`
   - Outputs: raw TIFF groups filtered by protocol, selected blocks, and detected session (`<fish>_00001.tif` -> `r1`, `<fish>_r2_00001.tif` -> `r2`)
2. Frame cleanup and plane extraction
   - Owner: `preprocessing/preprocessing_tiff.py`
   - Key functions: `remove_vflyback_frames`, `correct_negative_values_mp_safe`, `process_fish`, `process_fish_streaming`
   - Outputs: `02_reg/00_preprocessing/2p_functional/01_individualPlanes/<fish>_plane*.tif` for resonant or `<fish>_stack.tif` for linear, plus `<fish>_preprocessing_metadata.json`; resonant multi-session outputs assign each session the next plane range.
   - Low-memory option: `process_fish_streaming` writes the same outputs with two-pass TIFF streaming instead of loading full raw blocks into memory, and can parallelize independent sessions or raw TIFF blocks with the `workers` setting.
   - GUI/CLI orchestration: `preprocessing/preprocessing_gui.py` launches `preprocessing/preprocessing_cli.py preprocess --config <json>` in a separate process; the GUI uses one data root for input and output.
3. Suite2P motion correction and segmentation
   - Owner: `preprocessing/motion_segmentation_suite2p.py`
   - Key functions: `find_plane_file`, `run_suite2p`, `join_reg_tiffs_to_one`, `move_processed_files`, `process_fish`
   - Outputs: `<fish>_plane*_mcorrected.tif` in `02_motionCorrected` and renamed `.npy` artifacts in `03_analysis/functional/suite2P/plane*`
   - GUI/CLI orchestration: `preprocessing/preprocessing_gui.py` blocks Suite2P until selected plane TIFFs and preprocessing metadata exist, then launches `preprocessing/preprocessing_cli.py suite2p --config <json>` in a separate process. `selected_planes=all` expands to all preprocessed plane TIFFs for each fish. GUI-launched Suite2P defaults to the local legacy MPS runtime at `/Users/ddharmap/miniforge3/envs/suite2p0146_cpu/bin/python`, requires Suite2P 0.14.6, Cellpose 4.0.6, and MPS/Cellpose GPU availability during preflight, clears `CALCIUM_SUITE2P_FORCE_CPU`, and resolves the ops path by keeping an existing saved path, otherwise using known ops filenames under the selected data root, otherwise falling back to `preprocessing/suite2p_ops_sep_2025_cp.npy`.
   - Runtime compatibility: the Suite2P owner detects old `run_s2p(ops=...)` versus current `run_s2p(db=..., settings=...)` APIs. It forces the default Cellpose model name `2pf_cpsam_20250915_134652` with `anatomical_only=2` before every plane run, resolving it to a local `cellpose/models` file under the data root or known processing root when available instead of letting Cellpose fall back to `cpsam`. It preserves legacy ops semantics for old Suite2P, maps legacy Cellpose model/detection fields into current Suite2P's nested settings, normalizes legacy ops only for current Suite2P, selects the best available torch device for current Suite2P, honors `CALCIUM_SUITE2P_FORCE_CPU=1` as a CPU-only runtime override, patches current Suite2P MPS float64 taper construction in-process, preserves all-zero `Fneu` when `neuropil_extract=False`, and accepts both old and current registered TIFF chunk names when joining motion-corrected stacks.
   - Comparison support: `scripts/compare_suite2p_roi_sets.py` compares accepted Suite2P cells between runs by centroid distance and mask IoU, writes match/new-cell CSVs and diagnostic plots, can extract baseline-mask traces from the comparison run's motion-corrected TIFF for unmatched baseline cells, and plots remainder ROI activity as a wide inspection grid with up to five per-cell z-scored dF/F traces per row computed transiently from Suite2P `F.npy`. Its built-in `all_l395_conditions` manifest compares the historical `L395_f11` baseline against all tested Suite2P condition roots and writes aggregate condition and per-plane ROI-retention summaries plus cross-condition retention plots.
4. Fluorescence filtering and dF/F extraction
   - Owner: `preprocessing/dFoF_extraction.py`
   - Key functions: `load_fluorescence_data`, `filter_dim_rois`, `compute_percentile_baseline`, `compute_dff`, `process_suite2p_fluorescence`
   - Outputs: `<fish>_plane*_dFoF.npy`, `<fish>_plane*_filtered_roi_indices.npy`, and `<fish>_plane*_dFoF_metadata.json`

## Downstream checks
- After stage 2 changes, verify expected plane TIFF names and preprocessing metadata JSON.
- After stage 3 changes, verify the first plane folder contains correctly renamed Suite2P `.npy` outputs and a joined motion-corrected TIFF.
- After stage 4 changes, verify saved dF/F arrays and ROI index arrays match the expected plane folder.

## Validation surface
- Default lightweight check: `python3 -m py_compile preprocessing/*.py utils.py old2new_migration_no_docstrings.py`
- Pure-function changes can be validated with a narrow local snippet or fixture if available.
- Full Suite2P and filesystem-heavy runs are manual/integration validation unless the user explicitly wants them executed.

## Navigation notes
- For path ownership, read `canonical-data-layout.md`.
- For callable ownership, read `symbol-index.md`.
- For mixed-state issues or resume work, read `current-state.md`.
