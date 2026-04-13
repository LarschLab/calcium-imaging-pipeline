# Visual Stimulation Stage Map

Purpose

Show the ordered flow of a visual stimulation run and identify which script regions own run-time behavior and written CSV outputs.

Use this file when

- The task changes a PsychoPy run loop, trigger behavior, or metadata/log writing.
- You need to know which visual script section to open first.

## Main run flow for `dots_*` scripts
1. Operator setup
   - Owner region: `visual_stimulation/dots_gui.py` and `visual_stimulation/dots_protocol.py`
   - Outputs: in-memory metadata, selected stimulus directory, monitor config, planned trial order, preview timeline
2. Experiment tree bootstrap
   - Owner region: `visual_stimulation/dots_runner.py` `init_experiment_tree` call and `meta_dir` selection
   - Output destination: `01_raw/2p/metadata` in the canonical experiment tree
3. Stimulus CSV loading and trial sequence construction
   - Owner region: `visual_stimulation/dots_protocol.py` stimulus catalog load and run-plan build
   - Outputs: in-memory stimulus tables, exact trial order, planned schedule rows
4. PsychoPy and Arduino execution loop
   - Owner region: `visual_stimulation/dots_runner.py` window creation, pin setup, clocks, trial/block loops
   - Outputs: event logs held in memory until finalization
5. Finalization and log writing
   - Owner region: `visual_stimulation/dots_runner.py` save/output block
   - Outputs: experiment log CSV, block log CSV, trial sequence CSV, planned schedule CSV, metadata CSV
6. Post-run anatomy append
   - Owner region: `visual_stimulation/dots_runner.py` follow-up dialogs after the first metadata write
   - Output: metadata CSV overwritten with anatomy values appended

## Other script families
- `loom_gratings.py`: standalone protocol with its own metadata/timestamp CSV save path, outside the canonical tree.
- `syncronization_experiment.py`: minimal trigger experiment writing one timestamp CSV.
- `metadata_sync_analysis.py`: offline analysis of ScanImage TIFF metadata, no canonical write surface.
- `grid.py`, `line_fish_alignment.py`, `visual_test_bouts.py`, `test_arduino.py`: setup/support tools, typically no canonical outputs.
- `save_video_stimuli.py`: offline visual export owner.

## Validation surface
- Default lightweight checks:
  - `python3 -m py_compile visual_stimulation/*.py utils.py`
  - `python3 -m unittest tests.test_dots_protocol`
- Runtime validation for PsychoPy, Arduino, dialogs, and full-screen rendering is manual unless explicitly requested.
- For metadata-writing changes, inspect the save block in the owner script and verify filename patterns and destination directory.

## Navigation notes
- For script ownership, read `visual-stimulation-script-index.md`.
- For output-path questions, read `canonical-data-layout.md`.
- For mixed save-path conventions and inconsistencies, read `current-state.md`.
