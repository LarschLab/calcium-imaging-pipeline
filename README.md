# Calcium imaging pipeline

Code for visual stimulation, two-photon acquisition, preprocessing, Suite2P,
and functional-anatomy quality control.

## Canonical spatial preprocessing

Raw functional and anatomy TIFFs are immutable. Before Suite2P, resolve fish
polarity from raw `fish_orientation` metadata or the anatomy classifier, then
write the only functional plane movies in canonical XY (`north=flipY`,
`south=flipX`). The anatomy stack receives the same XY transform, the required
registration Z reversal, uint8 conversion, and 750x750 resize. A shared
`02_reg/00_preprocessing/spatial_preprocessing_manifest.json` records frames,
transforms, evidence, paths, shapes, dtypes, and spacing. `L427` is rejected.

Run into a new, empty fish directory while the migration is being validated:

```bash
python -m preprocessing.canonical_spatial_preprocessing_cli \
  --source-fish-dir /data/Matilde/Microscopy/L000_f00 \
  --output-fish-dir /validation/L000_f00 \
  --reference-microscopy-root /data/Matilde/Microscopy \
  --protocol resonant --blocks 1 2 3 --n-planes 5 --n-frames-per-plane 3
```

The classifier is trained only from valid raw metadata, uses acquisition-group
holdout validation, and always excludes `L427`. It does not read
`matchingMetadata.csv`. An abstention or metadata disagreement stops the run
for manual review. Train and validate the compact model once with
`tools/train_anatomy_polarity_model.py`, then pass `--classifier-model` and
`--classifier-validation` to avoid rereading every reference stack per fish.

## Functional-anatomy NCC quality gate

The opt-in NCC stage runs after Suite2P motion registration and before ROI
segmentation. It uses the canonical registration-ready anatomy NRRD, searches per-plane scaling
and best anatomy Z, and assesses temporal Z drift with empirically validated
tracked-local XY placement plus a conservative full-frame fallback. Every
acquisition block is shown in thirds. Block 0 is included to visualize settling
but excluded from the drift decision.

Run NCC against existing motion-corrected movies:

```bash
python -m preprocessing.functional_anatomy_qc_cli \
  --fish-dir /path/to/Microscopy/L000_f00 \
  --output-dir /path/to/validation-output \
  --workers 8
```

Run the opt-in split Suite2P workflow:

```bash
python -m preprocessing.ncc_gated_suite2p_cli \
  --fish-dir /path/to/Microscopy/L000_f00 \
  --ops-path /path/to/suite2p_ops.npy \
  --fps 2 \
  --planes 0 1 2 3 4 \
  --gate-mode report_only \
  --ncc-python /path/to/scientific/python \
  --ncc-workers 5
```

`report_only` always resumes segmentation and is intended for validation.
`enforce` preserves registration outputs but stops before segmentation unless
the NCC result is `pass_candidate`. Both Suite2P paths reject plane TIFFs that
are not declared canonical by the shared spatial manifest.

The version-4 NCC bundle also saves one pooled post-Block-0 reference per
plane, the authoritative scale/best-Z/XY placement table, complete pooled and
temporal NCC depth profiles, and both best-Z confidence and temporal-profile
PNGs. codeANTs can consume this manifest directly and proceed to ANTs residual
refinement without repeating reference construction or NCC searches.

See [docs/functional_anatomy_qc.md](docs/functional_anatomy_qc.md) for output
semantics and deferred work.
