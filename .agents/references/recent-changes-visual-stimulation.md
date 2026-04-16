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
