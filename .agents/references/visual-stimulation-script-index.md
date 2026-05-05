# Visual Stimulation Script Index

Purpose

Map common visual-stimulation tasks to the smallest owning script.

## Acquisition owners
- `visual_stimulation/dots_gui.py`: primary operator entrypoint for the dots-family GUI, dark-console default theme, parameter editing with a fixed three-column Metadata/Functional/Stimulus form row, compact one-line visible preview summary, GUI-only operator-friendly field labels backed by unchanged parameter keys, high-contrast delayed hover-help on field labels, remembered operator metadata/stimulus-folder defaults plus per-protocol stimulus and editable functional defaults after valid previews, derived non-editable `framerate` and `n_volumes`, CSV/MP4 stimulus folder preview, dynamic `n_trials_per_block` default from two times the unique presented stimulus count until the user edits it, derived block-based baseline rest duration, Loop Blocks as the standalone direct-launch default, GUI-stable random order that reshuffles only after stimulus-affecting edits, fish-orientation alignment button and automatic hardware-run orientation display, automatic block-duration/frame preview for block-based modes, explicit summary messaging when inter-block pause is configured but inactive because only one stimulus block is planned, auto-refresh-only compact interactive timeline preview (path + field changes, mouse-wheel zoom, right-drag pan, hover segment descriptions, bottom planned-block guide lane), wrapped full-stem stimulus identity timeline legend/coloring, pre-run checklist with one total-volume-per-block value and light-path reminders, console-only run diagnostics, sample-stimulus selection, mock-run toggle, and run launch.
- `visual_stimulation/dots_protocol.py`: shared dots-family owner for deterministic stimulus CSV/MP4 loading with full CSV stems as unique stimulus keys/display names, MP4 metadata-duration planning, exact trial-order generation including optional seeded random order, baseline `B0` planning for block-based runs, planned block derivation with `block_kind`, and planned schedule construction.
- `visual_stimulation/dots_runner.py`: shared dots-family owner for PsychoPy execution including dot CSV rendering and MP4 `MovieStim` playback, Arduino trigger preflight/cleanup and 50 ms pulse emission, console-only startup/trigger/save diagnostics, mock execution, and metadata/log CSV writes (including explicit inter-block pause events in both experiment and block logs for block-based modes).
- `visual_stimulation/dots_loop_stimuli.py`: thin wrapper that opens the GUI with sequential per-stimulus acquisition mode preselected.
- `visual_stimulation/dots_loop_blocks.py`: thin wrapper that opens the GUI with block-based mode preselected.
- `visual_stimulation/dots_continous_session.py`: thin wrapper that opens the GUI with continuous-session mode preselected.
- `visual_stimulation/loom_gratings.py`: loom and moving grating protocol with its own date/fish save path and timestamp/metadata CSVs.
- `visual_stimulation/syncronization_experiment.py`: simple synchronized dynamic-dots trigger test.

## Setup and support owners
- `visual_stimulation/grid.py`: projector focus and coarse alignment display.
- `visual_stimulation/line_fish_alignment.py`: import-safe fish orientation/alignment helper display used by the dots GUI and still runnable standalone.
- `visual_stimulation/visual_test_bouts.py`: quick pre-experiment response check using a subset of stimuli.
- `visual_stimulation/test_arduino.py`: Arduino acquisition-trigger sanity check that pulses COM3 pin 11 before full dots runs.

## Offline/support analysis owners
- `visual_stimulation/metadata_sync_analysis.py`: parse ScanImage TIFF metadata and compare aux trigger timestamps.
- `visual_stimulation/save_video_stimuli.py`: render a stimulus movie to disk.

## Shared ownership notes
- The `dots_*` family now shares planning and execution through `dots_protocol.py` and `dots_runner.py`; wrapper scripts are launch surfaces, not behavior owners.
- `utils.init_experiment_tree` still owns canonical output location semantics even when a visual script hardcodes a path.
- Bundled remote-test stimuli live in `visual_stimulation/sample_stimuli/dots_mock`.
- Mock runs write the canonical experiment tree under the GUI-selected mock output root, defaulting to `tmp/mock_runs`.
