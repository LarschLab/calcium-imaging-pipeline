# Recent Changes: Visual Stimulation

Append-only handoff log for PsychoPy run scripts, triggers, metadata logging, and support tools.

## Template
- Date and label:
- Slice goal:
- Passes completed in this session:
- What changed:
- What remains broken:
- Remaining in-slice work:
- Next likely breakpoint:
- Rerun implications:

## 2026-04-16 - dots automatic block planning
- Date and label: 2026-04-16, dots automatic block planning and boundary correction
- Slice goal: Replace manual block-frame entry with derived per-block acquisition planning and fix the empty pre-block rollover artifact so B0 is the first real acquisition block.
- Passes completed in this session: Owner/routing re-check -> protocol/planner update -> runner/GUI/output update -> docs/policy update -> regression test pass.
- What changed:
  - `visual_stimulation/dots_protocol.py`: added `PlannedBlock` and `DotsRunPlan.planned_blocks`; block-based plans now derive real block groupings, align `B0_start` with acquisition start, exclude inter-block pauses from block durations, and compute `acquisition_frame_count` with `ceil(duration_sec * framerate)`.
  - `visual_stimulation/dots_runner.py`: hardware and mock runners now execute from the planned blocks, no longer emit an empty B0 rollover artifact, and write `*_planned_blocks.csv` plus derived metadata rows for block counts/frame counts.
  - `visual_stimulation/dots_gui.py`: removed the manual block-frame field and preview/run gating path; block-based previews now show computed block durations and acquisition frame counts.
  - `.agents/references/visual-stimulation-stage-map.md`, `.agents/references/visual-stimulation-script-index.md`, `.agents/references/canonical-data-layout.md`: updated ownership/output notes for automatic block planning and the new block artifact.
  - `scientific-policy.md`: added the plain-English timing contract for operators and developers.
  - `tests/test_dots_protocol.py`, `tests/test_dots_gui_preview.py`: updated protocol, GUI preview, and mock-run coverage for zero-based blocks, frame-count ceiling behavior, and new output files.
- What remains broken: No known breakage from this slice.
- Remaining in-slice work: Manual GUI/run confirmation on the target hardware path if desired.
- Next likely breakpoint: If operators want block previews to show a different formatting style, adjust GUI summary formatting only.
- Rerun implications: Block-based run plans, logs, and metadata now follow automatic acquisition-window planning; manual block-frame input no longer exists.

## 2026-04-16 - dots GUI manual-frame preview regression fix
- Date and label: 2026-04-16, dots GUI preview/run-state decoupling for strict manual block-frame summary
- Slice goal: Keep strict protocol-side manual block-frame validation while preventing block-mode auto-preview from breaking when the manual list is blank/invalid.
- Passes completed in this session: Owner/routing re-check -> GUI preview-state/helper update -> GUI regression tests -> docs/log update -> compile/unit checks.
- What changed:
  - `visual_stimulation/dots_gui.py`: split preview summary flow into base-plan summary plus non-fatal block-mode manual-frame enrichment; invalid manual lists now keep preview/timeline current with inline unavailable-derived-planes warning instead of throwing from auto-preview.
  - `visual_stimulation/dots_gui.py`: introduced explicit run-block state (`run_block_reason`) separate from preview freshness; Run now stays disabled with a specific manual-frame validation reason until corrected.
  - `tests/test_dots_gui_preview.py`: added regression coverage for blank/mismatched/non-numeric/non-positive manual block-frame inputs, valid recovery behavior, and unchanged loop-stimuli summary path.
  - `.agents/references/visual-stimulation-script-index.md`: updated dots GUI ownership note to reflect recoverable preview warning plus run-block behavior for invalid manual block-frame lists.
- What remains broken: No known breakage from this slice.
- Remaining in-slice work: Manual GUI confirmation on target machine (blank/invalid list keeps timeline visible and blocks Run; valid list restores derived lines and enables Run).
- Next likely breakpoint: If operators want different warning wording or partial-derived display behavior, adjust GUI-local summary/run-block messaging only.
- Rerun implications: Block-mode GUI preview no longer fails on strict manual-frame summary validation errors; protocol strictness and runtime execution APIs remain unchanged.

## 2026-04-16 - dots manual block-frame summary inputs
- Date and label: 2026-04-16, dots block-frame summary derivation update
- Slice goal: Add required manual per-block 2P frame-count input for block-based dots modes and expose derived plane summaries without changing runtime execution behavior.
- Passes completed in this session: Owner/routing verification -> protocol + GUI update -> protocol tests/docs update -> lightweight compile/unit checks.
- What changed:
  - `visual_stimulation/dots_protocol.py`: added `stimuli_params["manual_block_frames"]` defaults for `loop_blocks` and `continuous_session`; added parsing/validation and planned-block-count checks derived from built trial sequence; `summarize_plan(...)` now adds `manual_block_frames`, `derived_planes_per_block`, and `derived_total_planes` for block-based modes using `block_frames / 60 * framerate`.
  - `visual_stimulation/dots_gui.py`: added help text for `manual_block_frames`; summary now includes manual frame list plus derived planes per block/final planes for block-based modes; timeline preview and run semantics remain unchanged.
  - `tests/test_dots_protocol.py`: added coverage for valid manual block-frame lists, mismatch count errors, non-numeric/non-positive errors, formula correctness, and mode-specific summary keys.
  - `.agents/references/visual-stimulation-script-index.md`: updated dots GUI ownership note for manual block-frame entry and derived plane summary behavior.
- What remains broken: No known breakage from this slice.
- Remaining in-slice work: None.
- Next likely breakpoint: If operators request relaxed validation or alternate display rounding for derived planes, adjust summary formatting/validation messages.
- Rerun implications: GUI summary content changed for block-based modes; metadata includes raw `manual_block_frames` via existing stimuli-parameter writing contract; run timing/trigger/block-rollover behavior unchanged.

## 2026-04-16 - dots GUI auto-preview + stimulus-type timeline colors
- Date and label: 2026-04-16, dots GUI preview/readability update
- Slice goal: Auto-refresh the preview when stimulus path/inputs change; improve long-run timeline readability.
- Passes completed in this session: Owner discovery -> GUI/protocol update -> tests/docs update.
- What changed:
  - `visual_stimulation/dots_gui.py`: added debounced auto-preview on stimulus path + field edits; background auto-refresh avoids modal popups; timeline stimulus segments now use per-stimulus-type colors; dynamic legend includes stimulus type entries.
  - `visual_stimulation/dots_protocol.py`: added `infer_stimulus_type(stimulus_name)` helper.
  - `tests/test_dots_protocol.py`: added coverage for stimulus-type inference grouping.
  - Updated visual-stimulation reference docs to reflect auto-refresh preview and stimulus-type coloring.
- What remains broken: No known breakage from this slice.
- Remaining in-slice work: None.
- Next likely breakpoint: If users want different color grouping semantics, adjust `infer_stimulus_type`.
- Rerun implications: Preview timing and legend behavior changed immediately in GUI; no metadata/output-path contract changes.

## 2026-04-16 - dots GUI layout and label-help usability pass
- Date and label: 2026-04-16, dots GUI layout + usability update
- Slice goal: Keep preview height fixed, enforce category row ordering, add delayed hover help on field labels, and remove manual preview button.
- Passes completed in this session: Owner discovery -> GUI layout/UX update -> tests/docs update.
- What changed:
  - `visual_stimulation/dots_gui.py`: added fixed `TIMELINE_PREVIEW_HEIGHT_PX` sizing and root row-weight changes so resize growth favors lower input area; category forms are now explicitly rendered in metadata/functional/stimulus row order via `INPUT_GROUP_ROWS`.
  - `visual_stimulation/dots_gui.py`: added `DelayedTooltip` with 1-second delay and `FIELD_HELP_TEXT` mapping, wired to each generated field label with fallback copy for unmapped fields.
  - `visual_stimulation/dots_gui.py`: removed manual Preview footer button and rebalanced footer controls (Run/Quit only), preserving debounced auto-preview scheduling.
  - `.agents/references/visual-stimulation-script-index.md`: updated dots GUI ownership note to reflect auto-preview-only behavior.
- What remains broken: No known breakage from this slice.
- Remaining in-slice work: Manual GUI confirmation of fixed-height preview behavior and delayed tooltip timing.
- Next likely breakpoint: If operators request different tooltip copy or delay, adjust `FIELD_HELP_TEXT`/`LABEL_TOOLTIP_DELAY_MS`.
- Rerun implications: GUI interaction changed (no manual Preview button, hover help visible after delay); protocol/run semantics unchanged.

## 2026-04-16 - dots GUI layout and tooltip visibility fixes
- Date and label: 2026-04-16, dots GUI stack/tooltip reliability update
- Slice goal: Ensure parameter groups render as a single vertical stack, expose default window geometry in one constant with taller startup height, and guarantee tooltip readability.
- Passes completed in this session: Ownership re-check -> GUI layout/tooltip fix pass -> docs/log update -> regression checks.
- What changed:
  - `visual_stimulation/dots_gui.py`: added `DEFAULT_WINDOW_GEOMETRY` and switched `DotsGuiApp.__init__` to use it (`1380x1020`) so startup height is larger while width is preserved.
  - `visual_stimulation/dots_gui.py`: fixed summary layout ownership so the summary label lives inside the Summary label frame, not as an overlapping sibling widget.
  - `visual_stimulation/dots_gui.py`: made one-column group placement explicit via `FORM_GROUP_COLUMNS = 1` and row/column computation in `_load_mode`; configured `forms_container` column 0 to stretch cleanly.
  - `visual_stimulation/dots_gui.py`: reworked tooltip rendering to explicit high-contrast surfaces (`tk.Label` + explicit bg/fg colors) while preserving delay/wrap behavior.
  - `.agents/references/visual-stimulation-script-index.md`: updated dots GUI description to note fixed vertical group stacking and visible delayed hover-help.
- What remains broken: No known breakage from this slice.
- Remaining in-slice work: Manual GUI run to visually confirm stacking, startup height, and tooltip contrast on the target display theme.
- Next likely breakpoint: If operators want different startup height or tooltip color contrast, tune `DEFAULT_WINDOW_GEOMETRY` and tooltip color constants.
- Rerun implications: GUI-only presentation behavior changed; auto-preview/run semantics and metadata/log output behavior unchanged.

## 2026-04-16 - dots GUI fixed three-column form layout
- Date and label: 2026-04-16, dots GUI three-column layout correction
- Slice goal: Replace the temporary single-column stack with a fixed three-column operator form and widen/clamp startup geometry for readability.
- Passes completed in this session: Owner discovery -> GUI layout/geometry update -> unit test + docs/log update.
- What changed:
  - `visual_stimulation/dots_gui.py`: switched to `FORM_GROUP_COLUMNS = 3` with fixed placement for `INPUT_GROUP_ROWS` in row 0 columns 0/1/2 via pure helper `compute_group_grid_positions(...)`.
  - `visual_stimulation/dots_gui.py`: configured `forms_container` columns 0..2 with equal `weight=1` and shared `uniform="form-group"`; added horizontal inter-group padding while preserving field-level label/input columns.
  - `visual_stimulation/dots_gui.py`: moved startup sizing to `_configure_window_geometry()` and updated defaults to `DEFAULT_WINDOW_GEOMETRY = "1800x1020"` with `MIN_WINDOW_WIDTH = 1600`; startup/min sizing now clamps to screen bounds with `WINDOW_SAFETY_MARGIN_PX`.
  - `tests/test_dots_gui_layout.py`: added regression coverage for fixed three-column placement and layout-helper validation.
  - `.agents/references/visual-stimulation-script-index.md`: updated dots GUI ownership note to describe the fixed three-column operator form.
- What remains broken: No known breakage from this slice.
- Remaining in-slice work: Manual GUI launch to confirm three side-by-side sections and width floor behavior on target displays.
- Next likely breakpoint: If operators request larger/smaller default widths on specific monitors, tune `DEFAULT_WINDOW_GEOMETRY`, `MIN_WINDOW_WIDTH`, and `WINDOW_SAFETY_MARGIN_PX`.
- Rerun implications: This supersedes the earlier uncommitted vertical-stack slice in “2026-04-16 - dots GUI layout and tooltip visibility fixes”; runtime protocol/output semantics remain unchanged.
