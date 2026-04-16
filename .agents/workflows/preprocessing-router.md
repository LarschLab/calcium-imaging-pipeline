# Preprocessing Router

Purpose

Route tasks for functional TIFF preprocessing, Suite2P segmentation, dF/F extraction, and layout migration.

Use this file when

- The target lives in `preprocessing/`, `utils.py`, or `old2new_migration_no_docstrings.py`.
- The task mentions raw functional TIFFs, plane files, motion-corrected TIFFs, Suite2P outputs, ROI filtering, or dF/F.
- The task is about canonical storage under `01_raw`, `02_reg`, `03_analysis`, or migration from old folder names.

## Read order
1. `../references/canonical-data-layout.md` for path or artifact ownership questions.
2. `../references/preprocessing-stage-map.md` for stage order, outputs, and rerun implications.
3. `../references/symbol-index.md` for callable ownership.
4. `../references/current-state.md` if the task is resume/fix/cleanup work.
5. Open the owning module.
6. Open downstream consumers only after the writer stage is understood.

## Task routing table
- Raw TIFF load failures, flyback removal, block concatenation, plane extraction, preprocessing metadata JSON -> `preprocessing-stage-map.md`, then `preprocessing/preprocessing_tiff.py`
- Suite2P ops setup, plane-file discovery, reg_tif joining, motion-corrected TIFF output, mirrored segmentation copy -> `preprocessing-stage-map.md`, then `preprocessing/motion_segmentation_suite2p.py`
- ROI filtering, baseline estimation, `*_dFoF.npy`, filtered ROI indices, dF/F metadata JSON -> `preprocessing-stage-map.md`, then `preprocessing/dFoF_extraction.py`
- Folder tree or output-location confusion -> `canonical-data-layout.md`, then `utils.py`
- Old-to-new data migration, legacy folder mapping, copy rules, manifest semantics -> `current-state.md`, then `old2new_migration_no_docstrings.py`, then `utils.py`
- Shared callable surface or deciding where reusable logic belongs -> `symbol-index.md`

## Ownership guidance
- `utils.py` owns the canonical experiment tree and directory naming.
- `preprocessing/preprocessing_tiff.py` owns the ingest-to-plane stage and preprocessing metadata.
- `preprocessing/motion_segmentation_suite2p.py` owns Suite2P execution, joined motion-corrected TIFFs, and plane-specific Suite2P output placement.
- `preprocessing/dFoF_extraction.py` owns downstream fluorescence filtering and dF/F artifacts.
- `old2new_migration_no_docstrings.py` is a migration wrapper over canonical layout rules; change it only for migration behavior, not to redefine the tree.
- Rolling change log (append after each completed or paused slice): `../references/recent-changes-preprocessing.md`
