# Plan: prepare anatomy stacks for registration

Status (2026-11-12): **done.** Env `registration` created; inventory written; 25 already-averaged files copied; all 12 all-frames files averaged, plus L800_f06 (pass 1 of 2). Plane -> anatomy registration then ran for 36/38 in-scope fish via `notebooks/register_experiment.ipynb`. Open: L978_f08 (no anatomy anywhere); L742_f08 (its suite2p folder holds a copy of L733_f08's suite2p -- reprocess from raw, then rerun the notebook for Exp_7). Code: `preprocessing/anatomy_averaging.py`, `tools/prepare_anatomy_stacks.py` (`inventory` / `copy` / `average`). Clean files are processed automatically; only `review` rows wait for the user.

## Goal

Get one usable anatomy z-stack (one image per depth) per fish into the local OneDrive data folder, so `notebooks/register_plane_to_anatomy.ipynb` can read it. Some raw stacks on the network hold every repeated frame per depth (5–21 GB) and must be averaged first; others are already averaged by ScanImage (20–170 MB).

## Scope

- Experiments: **Exp_1, Exp_5, Exp_7, Exp_8, Exp_9** (not Exp_2, Exp_3, Exp_4).
- Fish: `Final decision` = `use` or `undecided` in `OneDrive/Lab/Results/Paper/2p_derived/global/overview.csv`; skip `exclude`.

## Locations

| Role | Path | Access |
|---|---|---|
| Source (raw) | `Z:\FAC\FBM\CIG\jlarsch\default\D2c\07_Data\Alejandro\<folder>\01_raw\2p\anatomy\*.tif`, plus loose files in `...\Alejandro\0 new folder\` | **read-only, never write/delete** |
| Destination | `C:\Users\suribear\OneDrive - Université de Lausanne\Lab\Data\2p\<folder>\01_raw\2p\anatomy\` | write new files only, never overwrite |
| Inventory + review lists | `C:\Users\suribear\OneDrive - Université de Lausanne\Lab\Results\Paper\2p_derived\registration\` | write new files only |

Folders are never renamed. Network and OneDrive folders are matched by the **fish ID at the start of the name** (`L800_f01` ↔ `L800_f01_Exp_8_accumulation_ev`), via `utils.fish_id_from_folder_name`.

## Steps

0. **Environment.** New conda env `registration` with `tifffile`, `numpy`, `pandas`. Extended later with `antspyx`, `opencv`, `scikit-image`, `SimpleITK`, `matplotlib`, `jupyter` for registration.
1. **Inventory (read-only).** One row per anatomy file, saved as a CSV for the user to review:
   `experiment, fish_id, network_folder, onedrive_folder, final_decision, file, size_gb, n_pages, num_slices, frames_per_slice, log_average_factor, n_channels, csv_frames_per_slice_anatomy, status, note`.
   - From the ScanImage header: `SI.hStackManager.numSlices`, `SI.hStackManager.framesPerSlice`, `SI.hScan2D.logAverageFactor`, `SI.hChannels.channelSave`. Frames per depth are **read, never assumed** (not always 150).
   - From the fish's `*_metadata.csv`: `frames_per_slice_anatomy`, as a cross-check.
   - `status`:
     - `already_averaged`: pages = slices × channels.
     - `needs_averaging`: pages = slices × (frames_per_slice / log_average_factor) × channels, with more than 1 frame per depth.
     - `review`: anything inconsistent, header vs CSV disagreement, more than one channel, two files for one fish, file outside the fish folder, fish missing on either side.
2. **User reviews the inventory.** Nothing is copied or averaged before this.
3. **Pilot:** one `needs_averaging` fish (e.g. L800_f01) and one `already_averaged` fish. User checks the result visually.
4. **All remaining fish.**
   - `already_averaged`: copy the file unchanged.
   - `needs_averaging`: average (see below).
   - `review` fish with small files (L433_f02, L733_f07 two files each; L733_f08, L742_f08 loose files): copy **all** their files and keep them on the review list.

## Averaging rules

- For each depth, average its N repeated frames into one image. The stack keeps **all depths**; depths are never averaged together.
- Plain mean, no frame alignment (fish are anesthetized). Bad depths can be dropped later.
- Read one depth at a time, so a 20 GB file never has to fit in memory.
- Output: `<fish_id>_anatomy_averaged.tif` (float32), carrying the source's pixel-size tags (`XResolution`, `ResolutionUnit`), which `image_utils.read_pixel_size_um` needs. The raw file is **not** copied for these fish.
- Sidecar `<fish_id>_anatomy_averaged_metadata.json`: source path and size, header values, N frames averaged, output shape/dtype, timestamp.

## Code (to write when step 1 is approved)

A module in `preprocessing/` (inventory + averaging functions, separate from I/O, per `CLAUDE.md`), with tests on a small synthetic TIFF, run from a short script or notebook.

## Open / for later

- Choosing one file for L433_f02 and L733_f07 before registration (the notebook requires exactly one anatomy TIFF).
- Next phase: run the registration notebook on the pilot fish, then decide on the reference brain.
