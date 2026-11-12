# registration/

Maps suite2p ROIs from 2P functional planes into anatomical space, so ROIs from
different fish can eventually be compared in one common reference brain.

## Coordinate chain

Each ROI passes through four coordinate frames. Only steps 1–2 exist here.

| Step | From → to | How | Code | Status |
|---|---|---|---|---|
| 1 | functional plane → raw 2P anatomy stack | NCC search for best depth + scale + XY, then ANTs Rigid→Affine (2D, in-plane) | `plane_matching.match_plane_to_anatomy`, `plane_registration.register_plane_to_anatomy`, `plane_registration.warp_roi_masks_to_anatomy` | done |
| 2 | raw anatomy → canonical anatomy (NRRD) | fixed index math: polarity XY flip (north=flipY, south=flipX), Z reversal, resize to 750×750 | `roi_to_reference.convert_rois_to_canonical_space` (coords), `preprocessing.canonical_preprocessing.preprocess_canonical_anatomy` (image) | done, not yet called by the notebook |
| 3 | canonical anatomy → reference brain | 3D ANTs registration of the anatomy NRRD to a template | — | **not implemented**; reference brain not chosen |
| 4 | per-fish ROIs in reference → cross-fish maps | pool/density/average responsive ROIs | — | **not implemented** |

## Files

- `image_utils.py` — `norm01`, `local_unsharp`, `normalized_cross_correlation`, `read_pixel_size_um` (from TIFF tags).
- `plane_matching.py` — coarse-to-fine scale search (0.50–1.50) × every anatomy slice; returns `best_z`, `best_z_subslice`, `scale`, `score`, per-depth `scores`.
- `plane_registration.py` — loads suite2p plane (`{prefix}_ops.npy` meanImg, `{prefix}_stat.npy`); places plane by NCC, ANTs Rigid→Affine in a square mask (plane +10%); warps ROIs as a label image with nearest-neighbour; writes metadata JSON. Adds `xpix_aligned`, `ypix_aligned`, `med_aligned`, `z_pix` to each ROI dict.
- `roi_to_reference.py` — step 2 for ROI coordinates; step 3 belongs here.
- `notebooks/register_plane_to_anatomy.ipynb` — the driver: one fish, all planes, QC plots, then writes the canonical anatomy NRRD.

Method ported from Danin Dharmaperwira's external `ddharmap-ANTs` repo (not in this repo); tuning defaults are his.

## Expected input layout (per fish folder)

```
<fish_folder>/
  01_raw/2p/anatomy/*.tif                      one in-vivo anatomy stack (ex_vivo files ignored)
  01_raw/2p/metadata/*_metadata.csv            needs fish_orientation, step_size_um_anatomy
  03_analysis/functional/suite2P/plane{i}/{fish_id}_plane{i}_ops.npy, ..._stat.npy
      (older fish, e.g. Exp_1: suite2p defaults ops.npy, stat.npy, iscell.npy -- both are read)
```

Functional data must be in the **acquisition** XY frame (not pre-flipped); `read_functional_xy_frame` checks this and the notebook stops otherwise.

## Outputs (written inside the fish folder)

- `02_reg/07_2pf-a/transMatrices/{fish_id}_plane{i}_to_anatomy_0GenericAffine.mat` — ANTs transform.
- `02_reg/07_2pf-a/logs/{fish_id}_plane{i}_to_anatomy_registration_metadata.json` — match, transform, QC, ROI counts.
- `02_reg/00_preprocessing/2p_anatomy/<folder>_anatomy_2P_GCaMP.nrrd` (+ `_metadata.json`) — canonical anatomy, input for step 3. Never overwritten.

Warped ROI pixel lists are **not saved** — they live only in memory (`plane_results`). Rebuild them from the transform + `stat.npy`, or add a save step.

## QC to check per plane

`post_ncc` vs `pre_ants_ncc` (ANTs should raise it; `ants_lowered_fit=True` flags a drop), `valid_fraction`, and a single clear peak in the depth-score profile. Look at the overlay plots before trusting a plane.

## Known gotchas

- Fish folders are never renamed. Their name *starts* with `fish_id` but may carry a suffix (`L433_f02_Exp_1_flickering`); the notebook takes `fish_folder_name` and reads `fish_id` with `utils.fish_id_from_folder_name`. Always build paths from the folder name and file prefixes from `fish_id`.
- ROIs are taken from all of `stat.npy` (not only `iscell`). `warp_roi_masks_to_anatomy` drops empty/out-of-bounds ROIs **without storing their original suite2p index**, so list position ≠ suite2p index. Store the index before linking ROIs to traces (`*_dFoF_merged_map.csv`: `plane`, `roi_index_in_plane`, `global_col`; check which index `roi_index_in_plane` uses).
- ANTs and SimpleITK (ITK) can't open non-ASCII paths on Windows (UNIL OneDrive is `OneDrive - Université de Lausanne`): ANTs silently writes nothing, SimpleITK raises. Every ANTs/SimpleITK read or write must go through `utils.itk_safe_directory` / `utils.itk_readable_paths` (see `plane_registration._apply_transforms`).
- Paths under the data root may be network drives: never delete/overwrite there (see `CLAUDE.md`).

## Environment

Needs `antspyx`, `opencv-python`, `scikit-image`, `tifffile`, `scipy`, `SimpleITK`, `numpy`, `pandas`, `matplotlib`. Tests: `pytest tests/test_plane_matching.py tests/test_plane_registration.py tests/test_roi_to_reference.py`.
