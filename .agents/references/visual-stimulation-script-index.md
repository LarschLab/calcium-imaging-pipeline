# Visual Stimulation Script Index

Purpose

Map common visual-stimulation tasks to the smallest owning script.

## Acquisition owners
- `visual_stimulation/dots_gui.py`: primary operator entrypoint for the dots-family GUI, parameter editing with a fixed three-column Metadata/Functional/Stimulus form row, high-contrast delayed hover-help on field labels, remembered operator metadata/stimulus-folder defaults and per-protocol stimulus-parameter defaults after valid previews, dynamic `n_trials_per_block` default from the unique presented stimulus count until the user edits it, Loop Blocks as the standalone direct-launch default, GUI-stable random order that reshuffles only after stimulus-affecting edits, automatic block-duration/frame preview for block-based modes, explicit summary messaging when inter-block pause is configured but inactive because only one block is planned, auto-refresh-only timeline preview (path + field changes, no manual preview button), wrapped per-stimulus-type timeline legend/coloring, pre-run checklist with one total-volume-per-block value and light-path reminders, sample-stimulus selection, mock-run toggle, and run launch.
- `visual_stimulation/dots_protocol.py`: shared dots-family owner for deterministic stimulus CSV loading, exact trial-order generation including optional seeded random order, planned block derivation that excludes initial rest from planned acquisition duration/frame counts, and planned schedule construction.
- `visual_stimulation/dots_runner.py`: shared dots-family owner for PsychoPy execution, Arduino trigger preflight/cleanup and 50 ms pulse emission, mock execution, and metadata/log CSV writes (including explicit inter-block pause events in both experiment and block logs for block-based modes).
- `visual_stimulation/dots_loop_stimuli.py`: thin wrapper that opens the GUI with sequential per-stimulus acquisition mode preselected.
- `visual_stimulation/dots_loop_blocks.py`: thin wrapper that opens the GUI with block-based mode preselected.
- `visual_stimulation/dots_continous_session.py`: thin wrapper that opens the GUI with continuous-session mode preselected.
- `visual_stimulation/loom_gratings.py`: loom and moving grating protocol with its own date/fish save path and timestamp/metadata CSVs.
- `visual_stimulation/syncronization_experiment.py`: simple synchronized dynamic-dots trigger test.

## Setup and support owners
- `visual_stimulation/grid.py`: projector focus and coarse alignment display.
- `visual_stimulation/line_fish_alignment.py`: fish orientation/alignment helper display.
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
