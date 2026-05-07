# Symbol Index

Purpose

Provide the compact callable surface that other scripts should rely on before adding new helpers.

## Shared utilities
- `utils.init_experiment_tree(base_dir, fish_name)`: create the canonical experiment tree and return key paths. Layout authority for the repo.

## Preprocessing surface
- `preprocessing/preprocessing_tiff.py`
  - `load_tiff_file(filepath, n_planes, n_frames_per_plane)`: read multi-page TIFFs into memory with partial-read fallback.
  - `remove_vflyback_frames(frames, frames_per_volume, vflyback_frames=1)`: drop volume flyback frames.
  - `correct_negative_values_mp_safe(frames, num_chunks=5)`: shift negative pixel values into `uint16`.
  - `concatenate_blocks(...)`: load and concatenate selected raw blocks.
  - `process_fish(...)`: preprocess one fish and write stage-2 outputs.
  - `process_fish_streaming(...)`: preprocess one fish with two-pass disk streaming and write the same stage-2 outputs.
  - `parallel_preprocess(...)`: orchestration entrypoint for multiple fish.
- `preprocessing/motion_segmentation_suite2p.py`
  - `join_reg_tiffs_to_one(reg_folder, out_tiff)`: join Suite2P `reg_tif` chunks into one BigTIFF.
  - `move_processed_files(plane_idx, analysis_s2p_folder, mcorrected_folder, fish_id)`: place Suite2P outputs in canonical folders.
  - `run_suite2p(plane_file, global_ops, save_path0, fps, fast_disk=None)`: run Suite2P on one plane TIFF.
  - `find_plane_file(pre_dir, plane_idx)`: locate the source TIFF for one plane.
  - `process_fish(...)`: stage-3 owner for one fish.
  - `batch_process(..., storage_root=None)`: orchestration entrypoint for multiple fish with optional mirrored outputs.
- `preprocessing/preprocessing_workflow.py`
  - `preprocessing_config_from_dict(data)`: parse GUI/CLI preprocessing config.
  - `suite2p_config_from_dict(data)`: parse GUI/CLI Suite2P config.
  - `validate_preprocessing_outputs(data_root, fish_ids, selected_planes)`: check selected plane TIFFs and preprocessing metadata before Suite2P.
  - `run_preprocessing_config(config)`: run stage 2 for one or more fish.
  - `run_suite2p_config(config)`: validate stage 2 outputs and run stage 3.
- `preprocessing/preprocessing_cli.py`
  - `preprocess --config <json>`: run TIFF preprocessing in a process suitable for GUI launch.
  - `suite2p --config <json>`: run Suite2P in a separate process after validation.
- `preprocessing/preprocessing_gui.py`
  - `launch_preprocessing_gui()`: Tkinter workflow GUI with separate preprocessing and Suite2P stage buttons.
- `preprocessing/dFoF_extraction.py`
  - `load_fluorescence_data(path)`: load transposed fluorescence traces from Suite2P output.
  - `filter_dim_rois(fluorescence_trace, threshold_std=2)`: drop dim ROIs.
  - `compute_percentile_baseline(...)`: compute smoothed percentile baselines with instability filtering.
  - `compute_dff(fluorescence_trace, F0_baseline)`: compute dF/F.
  - `process_suite2p_fluorescence(...)`: stage-4 owner for one plane folder.

## Migration wrapper surface
- `old2new_migration_no_docstrings.py`
  - `get_new_name(df, experiment_root, old_name)`: resolve the new fish name from the Excel mapping.
  - `migrate_files(experiment_root, base_dir, xlsx_path, fish_list=None)`: copy legacy folders into the canonical tree.

## Script-entrypoint note
- Visual stimulation scripts are primarily runnable top-level owners rather than a reusable API. Prefer editing existing owner scripts over creating new shared helpers unless the same behavior is clearly repeated across the family.
