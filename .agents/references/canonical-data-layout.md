# Canonical Data Layout

Purpose

Document the authoritative experiment tree and which stage writes each artifact family.

Use this file when

- A task asks where an output should be written.
- A script uses a path that looks inconsistent.
- You need to decide which stage owns a filename, folder, or artifact contract.

Authoritative owner

- `utils.init_experiment_tree` is the canonical source for the experiment tree.

## Canonical tree
- Root: `<base_dir>/<fish_name>`
- Raw metadata: `01_raw/2p/metadata`
- Raw functional TIFFs: `01_raw/2p/functional`
- Raw anatomy TIFFs: `01_raw/2p/anatomy`
- Preprocessed individual planes: `02_reg/00_preprocessing/2p_functional/01_individualPlanes`
- Motion-corrected TIFFs: `02_reg/00_preprocessing/2p_functional/02_motionCorrected`
- Functional analysis outputs: `03_analysis/functional/suite2P`
- Plots: `04_plots`

## Writer-stage ownership
- Visual stimulation acquisition scripts own CSV logs, planned block summaries, and run metadata written into `01_raw/2p/metadata`.
- `preprocessing/preprocessing_tiff.py` owns plane TIFFs and preprocessing metadata JSONs in `02_reg/00_preprocessing/2p_functional/01_individualPlanes`.
- `preprocessing/motion_segmentation_suite2p.py` owns joined motion-corrected TIFFs in `02_motionCorrected` and plane-specific Suite2P outputs under `03_analysis/functional/suite2P/plane*`.
- `preprocessing/dFoF_extraction.py` owns `*_dFoF.npy`, filtered ROI index arrays, and dF/F metadata JSONs in each plane folder.

## Rules
- Preserve this tree unless the task is an explicit migration.
- Downstream readers should not redefine writer-stage folders or filenames.
- If a script writes somewhere else for historical reasons, record that in `current-state.md`; do not silently promote it to canonical behavior.
- When path semantics change, update this file and the relevant stage map in the same pass.
