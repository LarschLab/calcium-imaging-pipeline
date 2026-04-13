# Visual Stimulation Router

Purpose

Route tasks for PsychoPy stimulus scripts, Arduino synchronization, metadata/log CSV writing, calibration helpers, and sync-analysis support scripts.

Use this file when

- The target lives in `visual_stimulation/`.
- The task mentions dots sessions, loom/grating experiments, projector calibration, fish alignment, Arduino triggers, or metadata synchronization.
- The task involves CSV logs written during or after an experiment run.

## Read order
1. `../references/visual-stimulation-stage-map.md` for run order and written outputs.
2. `../references/visual-stimulation-script-index.md` for script ownership.
3. `../references/canonical-data-layout.md` for experiment tree and metadata destination rules.
4. `../references/current-state.md` for inconsistent save-path behavior or resume work.
5. Open the owning script.
6. Open support scripts only if the run-script owner is insufficient.

## Task routing table
- Dots experiment timing, trial/block loops, stimulus CSV loading, trigger pulses, experiment/block/trial CSV logs, post-run anatomy metadata append -> `visual-stimulation-stage-map.md`, then the relevant `visual_stimulation/dots_*.py` script
- Loom/grating protocol behavior or its saved metadata/timestamp CSVs -> `visual-stimulation-script-index.md`, then `visual_stimulation/loom_gratings.py`
- Synchronization trigger pulse experiments -> `visual-stimulation-script-index.md`, then `visual_stimulation/syncronization_experiment.py`
- Trigger decoding from ScanImage TIFF metadata -> `visual-stimulation-script-index.md`, then `visual_stimulation/metadata_sync_analysis.py`
- Projector focus, alignment, fish-orientation display, quick response checks, or Arduino communication checks -> `visual-stimulation-script-index.md`, then the support script owner
- Offline stimulus movie generation -> `visual-stimulation-script-index.md`, then `visual_stimulation/save_video_stimuli.py`
- Questions about where logs and metadata should land in the canonical experiment tree -> `canonical-data-layout.md`, then the owning run script

## Ownership guidance
- The `dots_*` scripts are primary owners for dots-session execution semantics and their CSV outputs.
- `loom_gratings.py` is its own protocol owner with a different output path convention than the canonical tree; treat that as current mixed state, not repo-wide authority.
- `grid.py`, `line_fish_alignment.py`, `visual_test_bouts.py`, and `test_arduino.py` are setup/support tools, not metadata authorities.
- `metadata_sync_analysis.py` and `save_video_stimuli.py` are offline support owners.
- Hardware, GUI, and full-screen behavior require manual validation unless the user explicitly asks to run them.
- Handoff log for unfinished work: `../references/recent-changes-visual-stimulation.md`
