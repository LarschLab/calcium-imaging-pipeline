# Functional-anatomy NCC QC

This preprocessing gate runs after Suite2P motion registration and before ROI
segmentation. It uses the raw in-vivo 2P anatomy TIFF in acquisition
orientation, estimates per-plane scale and best anatomy Z, and measures
temporal Z drift for every acquisition block. Every block is divided into
thirds; Block 0 is shown for settling assessment but excluded from the
scientific drift decision.

The existing combined Suite2P path remains unchanged. The opt-in gated entry
point runs registration-only Suite2P, performs NCC QC, and resumes segmentation
from the retained registered binary. Use `report_only` during parity validation;
`enforce` stops before segmentation unless the result is `pass_candidate`.
The gated CLI accepts `--ncc-python` so Suite2P and scientific NCC can remain in
separate reproducible environments.

The NCC runtime requires NumPy, SciPy, pandas, tifffile, Matplotlib,
scikit-image, and OpenCV. These dependencies do not need to be installed in the
Suite2P environment when `--ncc-python` points to a separate scientific Python.

## Canonical outputs

Outputs live under `<fish>/03_analysis/functional/ncc/`. Validation runs should
use a unique subdirectory under `validation/` and must not overwrite accepted
results. The stage writes interval measurements, full NCC depth profiles,
per-plane scale/best-Z placements, session summaries, global-versus-local XY
benchmarks, QC PNGs, and a provenance manifest.

`pass_candidate`, `review_required`, and `fail_candidate` are screening states,
not automatic scientific acceptance. The default material-drift threshold is
2 anatomy slices with at least 60% of planes changing in the same direction;
the manifest records the exact thresholds and always marks scientific review
as required.

The raw in-vivo anatomy TIFF is read directly from
`01_raw/2p/anatomy/`. Its acquisition XY orientation and Z order are preserved.
The reader validates the physical TIFF pages and falls back to page-wise
stacking when embedded series metadata reports an inconsistent frame count.

## Deferred follow-up

Support segmentation restricted to NCC-identified stable intervals. The NCC
stage should eventually expose stable frame ranges to Suite2P, but it must not
silently discard frames. Implement this only after the gate is validated and
the lab agrees on an explicit frame-selection policy.

## Validation record

Validation on Helga on 2026-08-07 included unit tests, synthetic stable and
coherent-drift cases, two real fish, and a Suite2P split-path parity check.

- L758_f04 was `pass_candidate` in both sessions. Median NCC was 0.76-0.79;
  consensus change was below 0.15 anatomy slices in magnitude.
- L758_f02 R1 was `pass_candidate` at -1.48 slices. R2 was
  `review_required` at -1.44 slices because one plane's total range exceeded
  the 2-slice threshold. This preserves the earlier conclusion that the fish
  needs reference-window review rather than calling it a clean stable case.
- Across both fish, tracked-local XY and global XY selected exactly the same
  best Z and max NCC for all 180 interval-plane comparisons. Median speedup was
  1.64x for L758_f04 and 1.56x for L758_f02.
- On a 600-frame L758_f04 plane, combined Suite2P and split registration then
  segmentation both produced 419 ROIs, identical offsets, identical `F`, and
  identical `iscell`. Split runtime was 37.9 s versus 46.2 s combined.

The raw anatomy and prior project-specific canonical NRRD can have opposite Z
index directions. Therefore the sign of delta Z is meaningful only relative to
the manifest-recorded input stack; drift magnitude and temporal shape remain
comparable.
