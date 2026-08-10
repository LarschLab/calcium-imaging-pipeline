# Functional-anatomy NCC QC

This preprocessing gate runs after Suite2P motion registration and before ROI
segmentation. It uses the registration-ready in-vivo 2P anatomy NRRD in the
same canonical XY frame as Suite2P, estimates per-plane scale and best anatomy Z, and measures
temporal Z drift for every acquisition block. Every block is divided into
thirds; Block 0 is shown for settling assessment but excluded from the
scientific drift decision.

Both Suite2P entry points validate their input plane TIFFs against the canonical
spatial preprocessing manifest. The opt-in gated entry
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
results. The stage writes interval measurements, full temporal and pooled-reference
NCC depth profiles, per-plane scale/best-Z/XY placements, one pooled
post-Block-0 reference TIFF per plane, session summaries, depth-stability and
NCC-profile QC PNGs, and a provenance manifest. Temporal
placement uses tracked-local XY with an automatic full-frame safety fallback
when the local match is weak or reaches the search-window boundary.

The version-4 manifest is the downstream handoff contract. Because functional
movies and anatomy already share the declared canonical XY frame and anatomy
already uses registration Z, codeANTs can reuse the saved reference, scale,
best Z, full depth profile, and XY placement without repeating the NCC search.
ANTs remains a downstream residual-refinement step.

`pass_candidate`, `review_required`, and `fail_candidate` are screening states,
not automatic scientific acceptance. The default material-drift threshold is
2 anatomy slices with at least 60% of planes changing in the same direction;
the manifest records the exact thresholds and always marks scientific review
as required.

The NCC stage reads
`02_reg/00_preprocessing/2p_anatomy/<fish>_anatomy_2P_GCaMP.nrrd` through
SimpleITK as Z,Y,X. The spatial manifest must declare canonical functional and
anatomy XY plus registration Z; absent, unknown, or contradictory frames stop
the stage. Best-Z indices therefore already use registration Z.

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
- A full L765_f03 preprocessing run on 2026-08-10 reproduced the same best Z
  and maximum NCC for all 90 interval-plane comparisons. The complete depth
  profiles had median correlation 0.998 (minimum 0.985), and tracked-local XY
  was 1.09x faster overall despite 20 conservative full-frame fallbacks. The
  resulting drift calls remained `fail_candidate` at +10.32 slices for R1 and
  +12.23 slices for R2.
- On a 600-frame L758_f04 plane, combined Suite2P and split registration then
  segmentation both produced 419 ROIs, identical offsets, identical `F`, and
  identical `iscell`. Split runtime was 37.9 s versus 46.2 s combined.
- On 2026-08-10, an isolated Helga/J: run used a 27-fish model trained only
  from raw metadata; acquisition-group-held-out validation was 27/27 correct
  and unanimous. Missing-metadata `L395_f11` predicted south unanimously.
  Direct functional transforms exactly matched the prior effective transforms,
  and the new anatomy output exactly matched the legacy oriented uint8 TIFF
  after the required Z reversal. It did not match the pre-existing NRRD, which
  is therefore treated as stale/internally inconsistent and was not modified.

Pre-migration QC manifests that used raw anatomy have a different Z index
direction and must be treated as legacy-frame results. New best-Z and delta-Z
values are defined in the manifest-recorded registration Z frame.

These empirical benchmarks justified removing the duplicated global temporal
analysis and comparison figure from production output. Tracked-local placement
is now the sole temporal engine because it was faster without sacrificing best
Z, peak NCC, or depth-profile quality. The initial scale/anchor search and the
explicit weak/boundary fallback still use full-frame matching; those are safety
mechanisms, not a second reported engine.
