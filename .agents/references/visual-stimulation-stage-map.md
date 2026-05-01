# Visual Stimulation Stage Map

Purpose

Show the ordered flow of a visual stimulation run and identify which script regions own run-time behavior and written CSV outputs.

Use this file when

- The task changes a PsychoPy run loop, trigger behavior, or metadata/log writing.
- You need to know which visual script section to open first.

## Main run flow for `dots_*` scripts
1. Operator setup
    - Owner region: `visual_stimulation/dots_gui.py` and `visual_stimulation/dots_protocol.py`
    - Outputs: in-memory metadata (via scrollable parameter forms), selected stimulus directory, monitor config, mock-run flags, planned trial order, dynamic `n_trials_per_block` default at two times unique presented stimuli, derived baseline rest duration, derived functional `framerate`/`n_volumes`, automatic block-duration/frame planning including baseline rest as `B0`, auto-refresh preview timeline with stimulus-type coloring, fish-orientation alignment display, pre-run operator checklist
2. Experiment tree bootstrap
   - Owner region: `visual_stimulation/dots_runner.py` `init_experiment_tree` call and `meta_dir` selection
   - Output destination: `01_raw/2p/metadata` in the canonical experiment tree
3. Stimulus CSV loading and trial sequence construction
    - Owner region: `visual_stimulation/dots_protocol.py` stimulus catalog load and run-plan build
    - Outputs: in-memory stimulus tables, exact trial order, planned schedule rows, planned block rows with `block_kind`, acquisition-window duration, and acquisition frame counts
4. Fish orientation, PsychoPy, and Arduino execution loop
   - Owner region: `visual_stimulation/dots_runner.py` window creation, pin setup, clocks, trial/block loops
   - Behavior: hardware runs show the fish-orientation alignment marker before acquisition; mock runs skip projector alignment; block-based runs trigger acquisition for baseline `B0` and each stimulus block, with an inter-block pause after `B0` and between stimulus blocks
   - Outputs: event logs held in memory until finalization
4a. Mock execution loop
   - Owner region: `visual_stimulation/dots_runner.py` mock backend
   - Behavior: no PsychoPy window, no Arduino access, deterministic simulated timestamps
   - Outputs: same CSV artifacts as a hardware run, written under the canonical tree rooted at the selected mock output directory
5. Finalization and log writing
    - Owner region: `visual_stimulation/dots_runner.py` save/output block
    - Outputs: experiment log CSV, block log CSV, trial sequence CSV, planned schedule CSV, planned blocks CSV, metadata CSV
6. Post-run anatomy append
   - Owner region: `visual_stimulation/dots_runner.py` follow-up dialogs after the first metadata write
   - Output: metadata CSV overwritten with anatomy values appended
   - Mock branch: writes default anatomy values without PsychoPy dialogs

## Other script families
- `loom_gratings.py`: standalone protocol with its own metadata/timestamp CSV save path, outside the canonical tree.
- `syncronization_experiment.py`: minimal trigger experiment writing one timestamp CSV.
- `metadata_sync_analysis.py`: offline analysis of ScanImage TIFF metadata, no canonical write surface.
- `grid.py`, `line_fish_alignment.py`, `visual_test_bouts.py`, `test_arduino.py`: setup/support tools, typically no canonical outputs.
- `save_video_stimuli.py`: offline visual export owner.

## Validation surface
- Default lightweight checks:
  - `python3 -m py_compile visual_stimulation/*.py utils.py`
  - `python3 -m unittest tests.test_dots_protocol tests.test_dots_gui_preview`
- Runtime validation for PsychoPy, Arduino, dialogs, and full-screen rendering is manual unless explicitly requested.
- Mock-run validation can be done remotely by launching the GUI, loading `visual_stimulation/sample_stimuli/dots_mock`, enabling `Mock run`, and checking the generated tree under `tmp/mock_runs`.
- For metadata-writing changes, inspect the save block in the owner script and verify filename patterns and destination directory.

## Navigation notes
- For script ownership, read `visual-stimulation-script-index.md`.
- For output-path questions, read `canonical-data-layout.md`.
- For mixed save-path conventions and inconsistencies, read `current-state.md`.
