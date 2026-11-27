# Registration outputs: how to put ROIs in the common (reference) space

All 2P fish were registered to one reference brain, **`ref_L433_f02`** (fish
L433_f02). This file says where the outputs are and how to use them to place
suite2p ROIs of any fish in that common space.

## Where the data is

```
C:\Users\suribear\OneDrive - Université de Lausanne\Lab\Data\2p\<folder>\
```

`<folder>` is the fish folder, e.g. `L978_f01_Exp_9_RF_memory_inhibition`.
`<fish_id>` is the first part of it, e.g. `L978_f01`.

Registered: **35 fish** from Exp_1, Exp_5, Exp_7, Exp_8, Exp_9. The list of fish per
experiment (with use / review / exclude) is in
`Lab\Results\Paper\2p_derived\global\overview.csv`.

## The chain

```
suite2p ROI (functional plane)
   │  step 1: plane → the fish's own anatomy stack (2D affine, per plane)
   │  step 2: anatomy → "canonical" anatomy (flip + resize, fixed math)
   ▼
ROI position in the fish's canonical anatomy      ← already computed, in a CSV
   │  step 3: canonical anatomy → reference brain (ANTs 3D: affine + warp)
   ▼
ROI position in the reference brain (common space)   ← computed, in a second CSV
```

All three steps are done. Step 3 was applied to the ROIs with
`notebooks/rois_to_reference.ipynb` (see "ROI positions in the reference" below):
**use that table**; the recipe further down is kept as documentation.

## ROI positions in the reference (result of step 3)

`<folder>\02_reg\08_2pa-ref\roi_positions\ref_L433_f02\<fish_id>_roi_positions_in_ref.csv`,
with a `_metadata.json` next to it (transform files, voxel sizes, date). One row per
suite2p ROI (all ROIs, not only cells):

| column | meaning |
|---|---|
| `fish_id`, `plane`, `suite2p_index` | ROI identity (same as the ROI position table) |
| `is_cell`, `cell_probability` | from suite2p `iscell.npy` |
| `x_ref_um`, `y_ref_um`, `z_ref_um` | **ROI centre in the reference brain, µm** |
| `x_ref_vox`, `y_ref_vox`, `z_ref_vox` | same centre in reference voxels (x = column, y = row, z = slice); for drawing on the reference NRRD |
| `x_canonical`, `y_canonical`, `z_canonical` | original centre in the fish's canonical anatomy (voxels) |

A few ROIs per fish have no position (NaN): their pixels fell outside the anatomy
in step 1. The reference fish (L433_f02) is copied without transform. Never
overwritten: delete a fish's table by hand to redo it.

QC per experiment: `Lab\Results\Paper\2p_derived\registration\<experiment>\rois_in_ref\`
(one figure per fish, an overview, and `<experiment>_rois_in_ref_qc.csv`). The QC
checks that each ROI lands on the same anatomy in the fish's warped image as in
its own anatomy (`correlation`, expected ≥ 0.9). All 36 mapped fish (Exp 1, 5, 7,
8, 9) gave 0.96–1.00 with 100% of ROIs inside. Not mapped (no step 1 ROI table):
L742_f08, L978_f08.

The QC also flags fish whose **step 1** plane matching looks wrong (two planes on
the same anatomy slice, or planes out of depth order). Step 3 moves those
positions faithfully, so the affected planes are misplaced in the reference too:
L684_f01 and L733_f01 (planes 0 and 1 share one slice), L800_f06 (plane depths
52, 51, 25, 35, 33). Check them in the step 1 QC before trusting their positions.

**Linking to dF/F traces:** in `<fish_id>_dFoF_merged_map.csv`, `roi_index_in_plane`
is the column inside that plane's *filtered* dF/F, **not** the suite2p index.
Join on the map's `plane` (written `plane0`, `plane1`, ...) + `filtered_roi_index`
↔ this table's `plane` (0, 1, ...) + `suite2p_index`.

## Files per fish

### ROI positions (result of steps 1 + 2)

`<folder>\02_reg\07_2pf-a\<fish_id>_roi_positions.csv`, with a `_metadata.json` next to it.

One row per ROI:

| column | meaning |
|---|---|
| `fish_id`, `plane` | fish and functional plane |
| `suite2p_index` | ROI index in that plane's suite2p `stat.npy` / `iscell.npy` |
| `is_cell`, `cell_probability` | from suite2p `iscell.npy` |
| `x_canonical`, `y_canonical`, `z_canonical` | **ROI centre in the fish's canonical anatomy, in voxels** ← use these |
| `x_anatomy`, `y_anatomy`, `z_anatomy` | same centre in the raw anatomy TIFF (not needed) |

### Canonical anatomy (the fish's 3D stack that was registered)

`<folder>\02_reg\00_preprocessing\2p_anatomy\<folder>_anatomy_2P_GCaMP.nrrd`

- 750 × 750 × (number of slices) voxels, origin (0, 0, 0).
- **The voxel size is different for each fish** (xy 0.40–0.60 µm, z 1 or 2 µm).
  Read it from the NRRD header (`space directions`) or from the
  `_metadata.json` next to it (`output_spacing_xyz_um`).

### Transforms to the reference (result of step 3)

`<folder>\02_reg\08_2pa-ref\transMatrices\ref_L433_f02\row0\`

| file | what it is |
|---|---|
| `<fish_id>_2P_to_ref_0GenericAffine.mat` | affine part (rotation, scale, shift) |
| `<fish_id>_2P_to_ref_1Warp.nii.gz` | non-linear warp (for **images**) |
| `<fish_id>_2P_to_ref_1InverseWarp.nii.gz` | inverse warp (for **points / ROIs**) |
| `<fish_id>_2P_to_ref_metadata.json` | which files to use, in which order |

The two warp files are about 1 GB each.

### Fish anatomy already warped onto the reference (for checking and display)

`<folder>\02_reg\08_2pa-ref\aligned\ref_L433_f02\<fish_id>_2P_in_ref.nrrd`

This is on the same grid as the reference. Use it as background to check that ROIs land in the right place.

## The reference brain

`Data\2p\L433_f02_Exp_1_flickering\02_reg\00_preprocessing\2p_anatomy\L433_f02_Exp_1_flickering_anatomy_2P_GCaMP.nrrd`

750 × 750 × 176 voxels, voxel size **0.5505 × 0.5505 × 2 µm**, origin (0, 0, 0), about 413 × 413 × 352 µm.

## How to move ROIs to the reference (step 3)

1. **Convert voxels to µm, using that fish's own voxel size:**
   `x_um = x_canonical * sx`, `y_um = y_canonical * sy`, `z_um = z_canonical * sz`
2. **Apply the transforms in the "points" direction:** the affine **inverted**, then the
   **InverseWarp**. With ANTsPy:
   ```python
   points = pd.DataFrame({"x": x_um, "y": y_um, "z": z_um})
   points_in_ref = ants.apply_transforms_to_points(
       3, points,
       transformlist=[affine_mat, inverse_warp_nii],
       whichtoinvert=[True, False])
   ```
   The output is in µm in the reference brain.
3. **To get reference voxels** (for drawing on the reference image), divide by
   (0.5505, 0.5505, 2).

This recipe was tested on 2 fish with different voxel sizes: fish intensities and
reference intensities at the mapped points correlate at r = 0.98–0.99. With the
transforms in the wrong order or direction, r ≈ 0.

**Note:** points use the **InverseWarp** and the **inverted** affine. Images use
`1Warp` plus the affine, not inverted. The two directions are opposite; mixing them
up gives wrong positions without any error message.

## Gotchas

- **Non-ASCII path:** ANTs and SimpleITK can't open paths containing "é"
  (`Université`). Copy the files to an ASCII folder first, e.g. a temp folder.
- **One depth per plane:** `z_canonical` is the same for every ROI of a plane,
  because each functional plane was matched to a single anatomy slice.
- **Which fish to trust:** a per-experiment QC of step 3 is in
  `Lab\Results\Paper\2p_derived\registration\<experiment>\reg_to_ref\`, as figures plus
  `<experiment>_ref_qc.csv`. All fish look good except **L800_f04**, which is aligned
  but has a dim anatomy image (check it). L978_f08 and L742_f08 have no registration.
- **Linking ROIs to dF/F traces:** use `plane` and `suite2p_index`. The merged
  dF/F of a fish is in `<folder>\03_analysis\functional\suite2P\merged_dFoF\`, and
  `<fish_id>_dFoF_merged_map.csv` maps each column to `plane` and
  `filtered_roi_index` (the suite2p index). `roi_index_in_plane` is an index
  after filtering; don't join on it (see "Linking to dF/F traces" above).
