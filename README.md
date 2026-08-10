# Calcium imaging pipeline

Code for visual stimulation, two-photon acquisition, preprocessing, Suite2P,
and functional-anatomy quality control.

## Functional-anatomy NCC quality gate

The opt-in NCC stage runs after Suite2P motion registration and before ROI
segmentation. It uses the raw in-vivo anatomy TIFF, searches per-plane scaling
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
the NCC result is `pass_candidate`. The historical combined Suite2P function
is unchanged and remains available.

See [docs/functional_anatomy_qc.md](docs/functional_anatomy_qc.md) for output
semantics and deferred work.
