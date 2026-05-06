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

## 2026-05-05 - dots GUI test-bouts orientation and fish age
- Date and label: 2026-05-05, dots GUI test-bouts orientation and fish age
- Slice goal: Make GUI-launched visual test bouts use the selected fish orientation and keep fish age derived from remembered birth date.
- Passes completed in this session: GUI launcher update -> visual test helper import-safe CLI refactor -> derived age GUI handling -> tests/reference/log update -> lightweight validation.
- What changed:
  - `visual_stimulation/dots_gui.py`: `Visual test bouts` now launches `visual_test_bouts.py` with `--fish-orientation` from the current metadata form.
  - `visual_stimulation/dots_gui.py`: `fish_age_dpf` is treated as a derived, non-editable metadata field and refreshed from the prepared plan instead of collected as operator input.
  - `visual_stimulation/visual_test_bouts.py`: refactored into import-safe helpers with optional CLI orientation; standalone use still asks for orientation when the argument is omitted.
  - `tests/test_dots_gui_layout.py` and `tests/test_visual_test_bouts.py`: added coverage for forwarded orientation, derived-age collection, and import-safe argument parsing.
- What remains broken: Manual projector/PsychoPy validation is still needed to confirm full-screen test-bout presentation on the operator machine.
- Remaining in-slice work: None.
- Next likely breakpoint: If operators want the test-bouts helper to reuse the selected GUI stimulus folder or timing fields, pass those through the same CLI/helper boundary.
- Rerun implications: GUI-launched test bouts now match selected fish orientation; experiment metadata output keeps computing fish age from `fish_birth`.

## 2026-05-05 - dots GUI test-bouts stop toggle
- Date and label: 2026-05-05, dots GUI test-bouts stop toggle
- Slice goal: Let operators stop visual test bouts from the dots GUI after confirming fish responsiveness.
- Passes completed in this session: GUI process-state update -> toggle/poll tests -> reference/log update -> lightweight validation.
- What changed:
  - `visual_stimulation/dots_gui.py`: the `Visual test bouts` button now toggles between launching the standalone helper and terminating its running process.
  - `visual_stimulation/dots_gui.py`: the button text changes to `Stop visual test bouts` while the helper is active and resets after early stop or natural process exit.
  - `tests/test_dots_gui_layout.py`: added coverage for launch, second-click stop, and natural-exit polling.
  - `.agents/references/visual-stimulation-stage-map.md` and `.agents/references/visual-stimulation-script-index.md`: documented the start/stop test-bouts launcher.
- What remains broken: Manual validation on the projector/hardware display is still needed to confirm process termination closes the full-screen PsychoPy window cleanly.
- Remaining in-slice work: None.
- Next likely breakpoint: If termination is too abrupt on the operator machine, refactor `visual_test_bouts.py` into an import-safe runner with a cooperative stop signal.
- Rerun implications: No experiment metadata, trigger timing, or saved output paths changed.

## 2026-05-05 - dots GUI manual alignment and test bouts
- Date and label: 2026-05-05, dots GUI manual alignment and test-bouts launcher
- Slice goal: Make fish alignment a manual-only setup action and expose the visual test bouts helper from the dots GUI.
- Passes completed in this session: GUI run-flow update -> launcher button wiring -> regression/reference/log update -> lightweight validation.
- What changed:
  - `visual_stimulation/dots_gui.py`: `Run` no longer shows fish alignment before starting the experiment; alignment is available only from the `Orient fish` button.
  - `visual_stimulation/dots_gui.py`: added a `Visual test bouts` button below `Orient fish` that launches `visual_test_bouts.py` as a separate Python process.
  - `tests/test_dots_gui_layout.py`: updated run-flow coverage and added launcher subprocess coverage.
  - `.agents/references/visual-stimulation-stage-map.md` and `.agents/references/visual-stimulation-script-index.md`: documented manual-only alignment and the GUI test-bouts launcher.
- What remains broken: Manual validation on the projector/hardware display is still needed for actual PsychoPy windows.
- Remaining in-slice work: None.
- Next likely breakpoint: If operators want test bouts to reuse the selected GUI stimulus folder or fish orientation, refactor `visual_test_bouts.py` into import-safe callable helpers.
- Rerun implications: Hardware runs now begin directly after the pre-run checklist; no metadata, trigger timing, or saved output paths changed.

## 2026-05-01 - dots full-stem timeline legend
- Date and label: 2026-05-01, dots full-stem timeline legend update
- Slice goal: Ensure the GUI timeline legend/list and segment colors distinguish each CSV stimulus by full file stem instead of grouping by underscore-delimited prefixes.
- Passes completed in this session: Owner/routing verification -> GUI identity-coloring fix -> protocol helper cleanup -> regression/docs/log update -> compile/unit checks -> screenshot validation.
- What changed:
  - `visual_stimulation/dots_gui.py`: timeline legend and stimulus segment colors now use full `segment.stimulus_name` identities such as `Ll_RB_trajectory` and `Ll_RC_trajectory`.
  - `visual_stimulation/dots_protocol.py`: removed the now-unused `infer_stimulus_type(...)` helper and its obsolete prefix-grouping test.
  - `tests/test_dots_gui_layout.py`: added regression coverage that timeline stimulus identities keep full underscore-containing stems and do not collapse to `Ll`/`Rl`.
  - `.agents/references/visual-stimulation-stage-map.md` and `.agents/references/visual-stimulation-script-index.md`: updated GUI preview wording from stimulus-type coloring to full-stem stimulus identity coloring.
- What remains broken: No known breakage from this slice.
- Remaining in-slice work: None.
- Next likely breakpoint: If operators later want family-level grouping, add it as a separate optional control without replacing full-stem legend identity.
- Rerun implications: GUI preview presentation changes; experiment execution, trigger timing, saved metadata paths, and catalog keys are unchanged from the prior full-stem loader update.

## 2026-05-01 - dots underscore stimulus names
- Date and label: 2026-05-01, dots full-stem stimulus key update
- Slice goal: Prevent underscore-delimited stimulus filenames from collapsing to the same GUI/planning stimulus entry in block-based dots modes.
- Passes completed in this session: Owner/routing verification -> protocol loader fix -> regression test/docs/log update -> lightweight validation.
- What changed:
  - `visual_stimulation/dots_protocol.py`: block/continuous catalog loading now uses the full CSV stem for both `runtime_key` and `display_name`, matching operator-visible filenames such as `Ll_RB_trajectory`.
  - `tests/test_dots_protocol.py`: added regression coverage for underscore-containing names that previously collapsed to `Ll`/`Rl` keys.
  - `.agents/references/visual-stimulation-script-index.md`: documented full-stem catalog key/display behavior in the protocol owner description.
- What remains broken: No known breakage from this slice.
- Remaining in-slice work: Manual GUI confirmation with the target `danin` stimulus folder.
- Next likely breakpoint: If operators need separate stimulus-type grouping labels, add a new GUI-local grouping helper without changing catalog keys.
- Rerun implications: Block/continuous trial logs and planned schedules now show full stimulus stems for underscore-containing CSV names instead of truncated prefixes.

## 2026-05-01 - dots GUI labelframe dark-theme completion
- Date and label: 2026-05-01, dots GUI labelframe dark-theme completion
- Slice goal: Remove remaining light native Tk surfaces from the dots launcher content area.
- Passes completed in this session: Tk/ttk theme correction -> palette regression test -> compile/unit checks -> GUI launch -> screenshot verification.
- What changed:
  - `visual_stimulation/dots_gui.py`: corrected labelframe style names to Tk's `TLabelframe` forms, added dark option defaults for Tk popup/listbox surfaces, and extended entry/combobox/scrollbar selection/border colors.
  - `tests/test_dots_gui_layout.py`: added coverage that the dark theme uses the effective Tk labelframe style names and not the inert `TLabelFrame` spelling.
- What remains broken: Nothing known for launcher-owned dark-theme surfaces; native OS chrome remains platform-controlled.
- Remaining in-slice work: None.
- Next likely breakpoint: If platform-native file dialogs or messageboxes need dark styling, replace those specific modal surfaces intentionally rather than widening main-launcher theme code.
- Rerun implications: Presentation only; experiment outputs, trigger timing, metadata, saved setting keys, and run planning are unchanged.

## 2026-05-01 - dots GUI dark console theme
- Date and label: 2026-05-01, dots GUI dark console theme
- Slice goal: Make the dots GUI look sleeker with a dark console style without changing run or preview semantics.
- Passes completed in this session: Theme constants -> ttk style setup -> canvas palette update -> palette regression test -> reference/log update -> compile/unit checks.
- What changed:
  - `visual_stimulation/dots_gui.py`: added the dark-console default theme for ttk widgets, timeline canvas, legends, tooltips, and the pre-run checklist.
  - `tests/test_dots_gui_layout.py`: added coverage that the dark palette covers timeline and block-guide drawing surfaces.
  - `.agents/references/visual-stimulation-script-index.md`: updated dots GUI ownership to include the dark-console default theme.
- What remains broken: Manual GUI confirmation remains useful for final visual tuning on the operator display.
- Remaining in-slice work: None.
- Next likely breakpoint: If operators want a light/dark toggle later, add it as GUI-local state rather than changing protocol or runner code.
- Rerun implications: Presentation only; experiment outputs, trigger timing, metadata, saved setting keys, and run planning are unchanged.

## 2026-05-01 - dots GUI timeline block guide lane
- Date and label: 2026-05-01, dots GUI timeline block guide lane
- Slice goal: Keep planned block context visible while operators zoom and pan the timeline preview.
- Passes completed in this session: Block-span helper -> timeline lane drawing -> helper regression tests -> reference/log update -> compile/unit checks.
- What changed:
  - `visual_stimulation/dots_gui.py`: timeline preview now draws a bottom block guide lane from `planned_blocks`, clipped to the current zoom/pan viewport.
  - `tests/test_dots_gui_layout.py`: added coverage for visible/clipped planned-block spans and omitted out-of-view blocks.
  - `.agents/references/visual-stimulation-script-index.md`: updated dots GUI ownership to include the planned-block guide lane.
- What remains broken: Manual GUI confirmation remains useful for visual spacing with real long protocols.
- Remaining in-slice work: None.
- Next likely breakpoint: If operators want block labels in the hover popup or a minimap-style overview, keep that GUI-local and based on `planned_blocks`.
- Rerun implications: Preview interaction only; experiment outputs, trigger timing, and metadata are unchanged.

## 2026-05-01 - dots GUI timeline right-click pan binding
- Date and label: 2026-05-01, dots GUI timeline right-click pan binding
- Slice goal: Move timeline panning off the observed scroll-wheel-click binding and onto the right-click binding used by the operator GUI.
- Passes completed in this session: Binding correction -> compile/unit checks.
- What changed:
  - `visual_stimulation/dots_gui.py`: timeline pan bindings now use Tk button 2 drag, with control-left-drag fallback retained.
- What remains broken: Manual GUI confirmation is still needed because Tk mouse button numbering can vary by platform/input device.
- Remaining in-slice work: None.
- Next likely breakpoint: If another operator platform maps secondary click differently, support both platform mappings intentionally.
- Rerun implications: Preview interaction only; experiment outputs, trigger timing, and metadata are unchanged.

## 2026-05-01 - dots GUI interactive timeline preview
- Date and label: 2026-05-01, dots GUI interactive timeline preview
- Slice goal: Make the dots GUI timeline preview navigable and inspectable without changing protocol/run semantics.
- Passes completed in this session: GUI preview interaction update -> helper regression tests -> reference/log update -> compile/unit checks.
- What changed:
  - `visual_stimulation/dots_gui.py`: timeline preview now supports mouse-wheel zoom, right-click drag panning, hover highlighting, and segment description popups for rests, pauses, and stimuli.
  - `tests/test_dots_gui_layout.py`: added pure-helper coverage for timeline viewport clamping, zoom, pan, and segment description text.
  - `.agents/references/visual-stimulation-script-index.md`: updated dots GUI ownership to include interactive timeline preview behavior.
- What remains broken: Manual GUI confirmation on the operator machine remains useful for trackpad/mouse gesture feel and popup placement.
- Remaining in-slice work: None.
- Next likely breakpoint: If operators want keyboard reset/fit controls, keep them GUI-local and preserve run-plan semantics.
- Rerun implications: Preview interaction only; experiment outputs, trigger timing, and metadata are unchanged.

## 2026-05-01 - dots baseline inter-block pause parity
- Date and label: 2026-05-01, dots baseline inter-block pause parity
- Slice goal: Match legacy block scripts by inserting the inter-block pause between baseline `B0` and first stimulus block `B1`.
- Passes completed in this session: Legacy comparison -> protocol/runner pause update -> regression/docs/log update -> compile/unit checks.
- What changed:
  - `visual_stimulation/dots_protocol.py`: planned schedules now include `B0` inter-block pause before `B1`.
  - `visual_stimulation/dots_runner.py`: hardware and mock execution now log and wait through `B0_interblock_pause`.
  - `visual_stimulation/dots_gui.py`: inter-block pause summary now counts all planned inter-block pauses, including baseline-to-first-stimulus.
- What remains broken: Hardware timing still needs manual confirmation against microscope acquisition.
- Remaining in-slice work: None.
- Next likely breakpoint: If operators decide baseline should transition immediately into `B1`, remove this pause consistently from protocol, runner, tests, and policy.
- Rerun implications: Total planned duration increases by one inter-block pause for block-based runs; acquisition frame counts are unchanged.

## 2026-05-01 - dots block protocol baseline standard
- Date and label: 2026-05-01, dots block protocol baseline standard
- Slice goal: Update block-based dots timing to baseline `B0` plus stimulus blocks with standard two-times-unique block size.
- Passes completed in this session: Protocol planning update -> runner/mock alignment -> GUI default/rest derivation -> regression/docs/log update -> compile/unit checks.
- What changed:
  - `visual_stimulation/dots_protocol.py`: block-based plans now create baseline-rest planned block `B0`, start stimulus blocks at `B1`, derive baseline rest duration from the first stimulus block, and add `block_kind` to planned block rows.
  - `visual_stimulation/dots_runner.py`: hardware and mock block runs now execute rest-only baseline blocks and trigger acquisition at baseline and each stimulus block start.
  - `visual_stimulation/dots_gui.py`: auto `Stimuli / block` now uses two times the unique presented stimulus count; derived rest is reflected in the form after preview; unequal block volume counts block Run.
- What remains broken: Manual validation on hardware remains needed for trigger timing and microscope acquisition settings.
- Remaining in-slice work: None.
- Next likely breakpoint: If downstream analysis assumes stimulus blocks start at `B0`, update those consumers to use `block_kind` or skip baseline rows explicitly.
- Rerun implications: Planned block CSVs now include baseline `B0`; planned total acquisition frames and derived `n_volumes` include baseline rest.

## 2026-04-30 - dots GUI fish orientation integration
- Date and label: 2026-04-30, dots GUI fish orientation integration
- Slice goal: Integrate fish-orientation projector alignment into the dots GUI and document post-run metadata dialogs.
- Passes completed in this session: Alignment refactor -> GUI integration -> post-run dialog coverage -> docs/log update -> compile/unit checks.
- What changed:
  - `visual_stimulation/line_fish_alignment.py`: refactored into import-safe helpers while preserving standalone prompt-and-display behavior.
  - `visual_stimulation/dots_gui.py`: added an `Orient fish` button, pre-run checklist orientation reminder, and automatic hardware-run alignment display before acquisition; mock runs skip alignment.
  - `tests/test_line_fish_alignment.py`, `tests/test_dots_gui_layout.py`, and `tests/test_dots_runner_hardware.py`: added coverage for alignment geometry/import safety, mock skipping, and post-run Metadata/Anatomy dialogs.
- What remains broken: Manual validation on the projector/hardware display is still needed for the actual full-screen alignment experience.
- Remaining in-slice work: None.
- Next likely breakpoint: If operators want alignment after rather than before the checklist, keep the alignment call GUI-local and preserve runner output behavior.
- Rerun implications: Hardware runs now show an alignment window before acquisition starts; output files and metadata keys are unchanged.

## 2026-04-30 - dots GUI friendly field labels
- Date and label: 2026-04-30, dots GUI friendly field labels
- Slice goal: Replace raw parameter-key form labels with easier operator-facing labels without changing output keys.
- Passes completed in this session: GUI label mapping -> regression/reference/log update -> compile/unit checks.
- What changed:
  - `visual_stimulation/dots_gui.py`: form labels now render through a GUI-only display mapping while `field_vars`, settings, protocol inputs, and metadata outputs keep existing parameter keys.
  - Stimulus labels now use plain language such as `Pre-stim rest (s)`, `Stimuli / block`, `Stimuli repetitions`, and `Max number of dots`; functional labels include `Frames / plane` and `Number of planes`.
  - `tests/test_dots_gui_layout.py`: added coverage for label mapping and fallback behavior.
- What remains broken: The interpretation of `Stimuli repetitions` versus block count still needs lab clarification before any semantic change.
- Remaining in-slice work: None.
- Next likely breakpoint: If `Stimuli repetitions` semantics change, update protocol behavior and downstream docs together rather than only relabeling the GUI.
- Rerun implications: Existing outputs and saved setting keys are unchanged; only visible form labels changed.

## 2026-04-30 - dots GUI derived functional settings
- Date and label: 2026-04-30, dots GUI derived functional settings
- Slice goal: Remove manual `n_volumes`/`framerate` GUI entry and remember editable functional microscope settings.
- Passes completed in this session: Protocol derivation -> GUI settings update -> regression/docs/log update -> compile/unit checks.
- What changed:
  - `visual_stimulation/dots_protocol.py`: derives `framerate` as `30 / n_frames / n_slices` and writes `n_volumes` from planned total acquisition frames into run functional metadata.
  - `visual_stimulation/dots_gui.py`: hides derived functional fields from the form and remembers editable functional params per mode after valid previews.
  - Tests and visual-stimulation references now cover the derived functional contract.
- What remains broken: Manual GUI confirmation on the operator display remains useful for field layout.
- Remaining in-slice work: None.
- Next likely breakpoint: If microscope rate derivation needs flyback terms, update the protocol helper and docs together.
- Rerun implications: Existing saved GUI settings keep loading; derived fields in old settings are ignored.

## 2026-04-30 - dots GUI string fish IDs
- Date and label: 2026-04-30, dots GUI string fish IDs
- Slice goal: Allow tank/fish composite IDs such as `L395_f01` in all dots GUI modes.
- Passes completed in this session: Default metadata type update -> regression test -> compile/unit checks.
- What changed:
  - `visual_stimulation/dots_protocol.py`: Loop Blocks and Continuous Session metadata defaults now use string `fish_ID` values so GUI coercion does not force integer parsing.
  - `tests/test_dots_gui_layout.py`: added coverage that block-mode `fish_ID` defaults are string typed.
- What remains broken: No known breakage.
- Remaining in-slice work: None.
- Next likely breakpoint: If additional metadata fields need mixed numeric/string input, handle them by field name rather than relying only on default value type.
- Rerun implications: Output paths and filenames will use the string fish ID exactly as entered.

## 2026-04-30 - dots GUI checklist single block volume
- Date and label: 2026-04-30, dots GUI checklist single block volume
- Slice goal: Simplify the pre-run checklist volume reminder to one total volume count because planned blocks should share the same count.
- Passes completed in this session: Checklist helper update -> regression/docs/log update -> compile/unit checks.
- What changed:
  - `visual_stimulation/dots_gui.py`: checklist now shows one `total volumes per block` value from the first planned block instead of listing every block.
  - `tests/test_dots_gui_layout.py`: updated checklist helper expectations for the single count.
  - `scientific-policy.md` and `.agents/references/visual-stimulation-script-index.md`: updated checklist wording.
- What remains broken: Manual GUI confirmation remains useful for modal layout on the operator display.
- Remaining in-slice work: None.
- Next likely breakpoint: If a future protocol intentionally allows unequal block counts, add warning text rather than silently showing one value.
- Rerun implications: Run behavior and outputs are unchanged; only the pre-run checklist instruction changed.

## 2026-04-30 - dots GUI dynamic block size and pre-run checklist
- Date and label: 2026-04-30, dots GUI dynamic block size and pre-run checklist
- Slice goal: Default block size from the current stimulus set, exclude initial rest from planned acquisition counts, and gate Run behind operator reminders.
- Passes completed in this session: Protocol acquisition-window timing -> GUI dynamic block size/checklist -> helper/protocol regression tests -> policy/reference/log update -> compile/unit checks.
- What changed:
  - `visual_stimulation/dots_protocol.py`: planned block start/duration/frame counts now exclude the first pre-stimulus rest while total timeline duration still includes it.
  - `visual_stimulation/dots_gui.py`: `n_trials_per_block` auto-fills from unique presented stimulus keys for block modes until the user manually edits it; remembered stimulus settings no longer restore that field.
  - `visual_stimulation/dots_gui.py`: Run now opens a checkable pre-run checklist with microscope volume-rate and light-path lever reminders before launching.
  - `tests/test_dots_protocol.py`, `tests/test_dots_gui_preview.py`, and `tests/test_dots_gui_layout.py`: updated timing expectations and added helper coverage for unique stimulus counts, microscope volume rate, and checklist text.
  - `scientific-policy.md`, `.agents/references/visual-stimulation-stage-map.md`, and `.agents/references/visual-stimulation-script-index.md`: updated the timing/default/checklist contract.
- What remains broken: Manual GUI confirmation on the operator machine is still needed for modal checklist layout and actual run flow with hardware.
- Remaining in-slice work: None.
- Next likely breakpoint: If operators need custom checklist text, keep the checklist item builder GUI-local and update its reminders without changing protocol timing.
- Rerun implications: Planned block CSV durations/frame counts will be lower by the initial rest duration for the first block; total planned run duration remains unchanged.

## 2026-04-30 - dots GUI checklist block volumes
- Date and label: 2026-04-30, dots GUI checklist block volumes
- Slice goal: Correct the pre-run checklist to show total planned volumes per block instead of microscope volume rate.
- Passes completed in this session: Checklist helper update -> regression tests/docs/log update -> compile/unit checks.
- What changed:
  - `visual_stimulation/dots_gui.py`: pre-run checklist now lists planned block volume counts from `planned_blocks[*].acquisition_frame_count`.
  - `tests/test_dots_gui_layout.py`: replaced volume-rate helper coverage with block-volume checklist coverage.
  - `scientific-policy.md` and `.agents/references/visual-stimulation-script-index.md`: updated checklist wording to describe per-block total volumes.
- What remains broken: Manual GUI confirmation remains useful for modal layout with multi-block volume text.
- Remaining in-slice work: None.
- Next likely breakpoint: If the microscope UI needs one value per run rather than per block, derive a shared value only when all planned blocks match and otherwise show the per-block list.
- Rerun implications: Run behavior and planned outputs are unchanged; only the pre-run checklist instruction changed.

## 2026-04-30 - dots GUI stable shuffle and stimulus defaults
- Date and label: 2026-04-30, dots GUI stable shuffle and stimulus defaults
- Slice goal: Prevent non-stimulus GUI edits from reshuffling random block-mode orders, keep large stimulus-type legends visible, and remember stimulus parameters for successive runs.
- Passes completed in this session: Seeded protocol order -> GUI dirty-source tracking/settings update -> wrapped legend helper -> regression tests/docs -> compile/unit checks.
- What changed:
  - `visual_stimulation/dots_protocol.py`: random stimulus order can now use `runtime["stimulus_shuffle_seed"]`, and CSV catalog loading is deterministic before ordering.
  - `visual_stimulation/dots_gui.py`: maintains a GUI shuffle seed that refreshes only for stimulus parameter, stimulus folder, or protocol changes; metadata/functional/mock-output edits keep the existing randomized order.
  - `visual_stimulation/dots_gui.py`: remembered GUI settings now include per-protocol stimulus parameters, and the timeline legend wraps across rows when many stimulus types are present.
  - `tests/test_dots_protocol.py` and `tests/test_dots_gui_layout.py`: added coverage for seeded order stability, remembered per-mode stimulus parameters, and wrapped legend positions.
  - `.agents/references/visual-stimulation-script-index.md`: updated GUI/protocol ownership notes for stable shuffle, wrapped legend, and remembered stimulus parameters.
- What remains broken: Manual GUI confirmation on the operator display is still useful to inspect wrapped legend spacing with real large stimulus catalogs.
- Remaining in-slice work: None.
- Next likely breakpoint: If operators want a visible "reshuffle" button, keep it GUI-local by refreshing the same shuffle seed used for stimulus-affecting edits.
- Rerun implications: Random block-mode orders remain stable across non-stimulus preview refreshes; valid previews update saved stimulus parameters for the active protocol mode.

## 2026-04-30 - dots GUI remembered setup defaults
- Date and label: 2026-04-30, dots GUI remembered setup defaults
- Slice goal: Remember common operator metadata and stimulus folder across successive GUI sessions, and make Loop Blocks the standalone GUI default.
- Passes completed in this session: GUI settings helper -> standalone default update -> helper regression tests -> docs/log update -> compile/unit checks.
- What changed:
  - `visual_stimulation/dots_gui.py`: now loads/saves remembered `experiment_name`, `experimenter`, `fish_ID`, `fish_birth`, `genotype`, and stimulus folder through a small JSON settings file after valid previews.
  - `visual_stimulation/dots_gui.py`: direct script launch now starts in Loop Blocks; mode-specific wrapper scripts still launch their named modes.
  - `tests/test_dots_gui_layout.py`: added coverage for remembered settings filtering, settings JSON round-trip/error handling, and the standalone default mode constant.
  - `.agents/references/visual-stimulation-script-index.md`: updated the GUI ownership summary for remembered defaults and direct-launch mode.
- What remains broken: Manual GUI confirmation on the operator machine is still useful to confirm the saved settings path and startup auto-preview behavior.
- Remaining in-slice work: None.
- Next likely breakpoint: If operators want per-mode remembered values or a visible reset button, keep it GUI-local unless protocol defaults intentionally change.
- Rerun implications: A valid preview writes operator convenience state under the user home directory; experiment metadata/output semantics are unchanged until the operator previews/runs with those values.

## 2026-04-30 - dots detectable trigger pulse width
- Date and label: 2026-04-30, dots GUI 50 ms trigger pulses
- Slice goal: Make dots acquisition trigger outputs detectable by the microscope external-trigger input after COM3 access was confirmed working.
- Passes completed in this session: Runtime pulse default -> runner pulse helper -> pin-11 Arduino diagnostic -> regression tests/docs -> compile/unit checks.
- What changed:
  - `visual_stimulation/dots_protocol.py`: added hidden runtime default `trigger_pulse_sec=0.05` for all dots modes.
  - `visual_stimulation/dots_runner.py`: acquisition trigger pulses and short aux markers now hold high for the configured pulse duration instead of immediate high-low writes; block-mode aux stimulus-on/stimulus-off level behavior remains unchanged.
  - `visual_stimulation/test_arduino.py`: now pulses COM3 digital pin 11 five times with the same 50 ms pulse width for pre-run microscope trigger testing.
  - `tests/test_dots_runner_hardware.py`: added coverage for the pulse-width default and pulse helper write/wait/write contract.
  - `.gitignore`: added local ignores for Python caches, common local test/tool caches, `tmp/`, and `.DS_Store`; tracked `.pyc` cache files were removed from the git index.
- What remains broken: Manual microscope confirmation is still required to verify that 50 ms is sufficient for the external-trigger input.
- Remaining in-slice work: None.
- Next likely breakpoint: If the microscope still does not start, confirm wiring to Arduino pin 11 and increase `trigger_pulse_sec` or expose it in the GUI.
- Rerun implications: Hardware dots runs are intentionally delayed by 50 ms per acquisition/short aux pulse; output event names and CSV artifacts are unchanged.

## 2026-04-30 - dots GUI Arduino trigger preflight
- Date and label: 2026-04-30, dots GUI COM3 startup failure handling
- Slice goal: Prevent the GUI hardware path from starting projection when the Arduino trigger port cannot be opened, and release partially opened serial resources on setup failures.
- Passes completed in this session: Runner trigger setup refactor -> serial failure regression tests -> reference/log update -> compile/unit checks.
- What changed:
  - `visual_stimulation/dots_runner.py`: now opens/configures Arduino trigger pins before creating the PsychoPy window, reports a clear port-access failure naming the configured port, and exits a partially opened board when pin setup or initial writes fail.
  - `tests/test_dots_runner_hardware.py`: added fake-hardware regressions for COM3 open failure, pin setup failure, and initial pin write failure.
  - `.agents/references/visual-stimulation-script-index.md`: updated `dots_runner.py` ownership to include Arduino trigger preflight/cleanup.
- What remains broken: Manual microscope confirmation is still required for real COM3 permissions and trigger pulses.
- Remaining in-slice work: None.
- Next likely breakpoint: If operators need a projection-only fallback, add an explicit operator choice in the GUI instead of silently continuing without triggers.
- Rerun implications: Failed COM3 access should now abort before projection starts and should not leave the GUI process holding a partially opened Arduino handle.

## 2026-04-30 - dots GUI direct-launch import fix
- Date and label: 2026-04-30, dots runner repo-root import bootstrap
- Slice goal: Make documented direct GUI launches resolve repo-root `utils.py` reliably, even when a third-party `utils` package is installed.
- Passes completed in this session: Runner import-path update -> direct-script import regression -> lightweight compile/unit checks.
- What changed:
  - `visual_stimulation/dots_runner.py`: now places the repository root at the front of `sys.path` before importing `init_experiment_tree` from root-level `utils.py`.
  - `tests/test_dots_imports.py`: added subprocess coverage for the direct-script path shape with a fake competing `utils` package.
- What remains broken: No known breakage from this slice.
- Remaining in-slice work: Manual GUI launch on the operator machine remains the final UI/hardware confirmation.
- Next likely breakpoint: If the visual stimulation scripts are converted to package/module execution later, revisit all sibling imports together.
- Rerun implications: Direct GUI and dots wrapper launches should no longer fail at startup with `ModuleNotFoundError: No module named 'utils'`; runtime protocol/output semantics are unchanged.

## 2026-04-16 - dots single-block inter-block pause preview clarity
- Date and label: 2026-04-16, dots GUI inter-block pause applicability messaging
- Slice goal: Clarify why inter-block pause appears inactive when only one block is planned, so operators can distinguish expected behavior from a broken pause input.
- Passes completed in this session: Owner/routing re-check -> protocol/preview path verification -> GUI summary update -> preview regression updates -> compile/unit test pass.
- What changed:
  - `visual_stimulation/dots_gui.py`: block-mode preview summary now reports inter-block pause contribution (`count x seconds`) and explicitly states when a configured inter-block pause is not applied because only one block is planned.
  - `tests/test_dots_gui_preview.py`: expanded summary assertions and added regression coverage for the single-block case where inter-block pause is configured but intentionally unused.
  - `.agents/references/visual-stimulation-script-index.md`: updated `dots_gui.py` ownership note to include single-block inter-block pause applicability messaging.
- What remains broken: No known breakage from this slice.
- Remaining in-slice work: Optional manual GUI confirmation on operator workflows that keep `n_trials_per_block` equal to the total trial count.
- Next likely breakpoint: If operators want inter-block pause to apply after the final block, that is a protocol-semantics change and should be handled in `dots_protocol.py` and `dots_runner.py`, not GUI-only.
- Rerun implications: Preview text now distinguishes “configured but not applicable” inter-block pause in single-block plans; execution semantics and output files are unchanged.

## 2026-04-16 - dots inter-block pause event restoration
- Date and label: 2026-04-16, dots block-log inter-block pause restoration
- Slice goal: Restore explicit inter-block pause visibility in run artifacts while preserving corrected block duration/frame calculations.
- Passes completed in this session: Owner/routing re-check -> runner event logging update -> mock-run regression update -> docs/log update -> unit test pass.
- What changed:
  - `visual_stimulation/dots_runner.py`: block-based hardware and mock paths now log `B{block_num}_interblock_pause` through the shared event logger, so the inter-block pause is present in both `experiment_log.csv` and `block_log.csv`.
  - `tests/test_dots_protocol.py`: updated mock block-run marker expectation to include `B0_interblock_pause`.
  - `.agents/references/visual-stimulation-script-index.md`: updated `dots_runner.py` ownership note to reflect explicit inter-block pause event logging.
- What remains broken: No known breakage from this slice.
- Remaining in-slice work: Optional manual hardware confirmation if operators want to inspect live timing traces.
- Next likely breakpoint: If downstream analysis expects pause start/end pairs instead of a single pause marker, add paired events consistently in both logs.
- Rerun implications: Block-based runs now emit explicit inter-block pause markers in `block_log.csv`; downstream consumers parsing block events may need to account for the additional event.

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

## 2026-05-05 - dots GUI MP4 stimulus support
- Date and label: 2026-05-05, dots GUI CSV/MP4 stimulus loading
- Slice goal: Let GUI-selected stimulus folders include MP4 files alongside existing CSV dot stimuli.
- Passes completed in this session: Owner discovery -> protocol/runner/GUI update -> tests/docs update.
- What changed:
  - `visual_stimulation/dots_protocol.py`: stimulus catalog loading now accepts `.csv` and `.mp4`, records each stimulus media type, derives MP4 duration from video metadata, and includes MP4 durations in plan/block frame counts.
  - `visual_stimulation/dots_runner.py`: hardware runs present MP4 stimuli with PsychoPy `MovieStim`; mock runs simulate MP4 trials by planned duration while leaving CSV dot rendering unchanged.
  - `visual_stimulation/dots_gui.py`: stimulus folder chooser copy now says CSV/MP4, and timeline hover details label MP4 stimuli as video media instead of zero-dot stimuli.
  - Tests added mixed CSV/MP4 catalog, MP4 planning, mock-run, and video playback coverage.
- What remains broken: Runtime MP4 playback still requires the target PsychoPy environment/codecs to support the file; unreadable MP4 durations fail preview with a clear catalog error.
- Remaining in-slice work: Manual GUI/hardware confirmation with real MP4 stimuli on the projector workstation.
- Next likely breakpoint: If operators use duplicate CSV/MP4 stems in block modes, rename files or intentionally change runtime-key policy.
- Rerun implications: GUI preview and planned acquisition frames now include MP4 durations; metadata/log output schemas are unchanged.

## 2026-05-05 - fish alignment marker color
- Date and label: 2026-05-05, fish alignment marker color update
- Slice goal: Change the fish-orientation alignment marker from white to black.
- Passes completed in this session: Owner discovery -> support-script update -> focused validation/log update.
- What changed:
  - `visual_stimulation/line_fish_alignment.py`: added `MARKER_COLOR = "black"` and applied it to both alignment lines and the dot marker.
  - `tests/test_line_fish_alignment.py`: added regression coverage for the marker color constant.
- What remains broken: No known breakage from this slice.
- Remaining in-slice work: Manual projector confirmation that the black marker is visible against the selected alignment background.
- Next likely breakpoint: If operators need contrast control per background, add an explicit runtime-configured marker color.
- Rerun implications: GUI “Orient fish” and standalone alignment display now show a black marker; run metadata/output behavior is unchanged.

## 2026-05-05 - dots GUI compact preview + run diagnostics
- Date and label: 2026-05-05, dots GUI compact layout and console diagnostics
- Slice goal: Make microscope testing easier by printing explicit run-progress checkpoints and make the metadata forms visible on lower-resolution GUI windows.
- Passes completed in this session: Owner discovery -> GUI/runner update -> tests/docs update -> screenshot verification.
- What changed:
  - `visual_stimulation/dots_gui.py`: added console-only run diagnostics around checklist handling, GUI withdrawal, fish alignment, and `run_planned_experiment(...)`; added compact one-line visible preview summary; reduced timeline height and preview padding; lowered minimum GUI width to support constrained screenshot checks.
  - `visual_stimulation/dots_runner.py`: added console-only diagnostics at runner entry, hardware/mock branch startup, metadata directory resolution, Arduino/window setup, B0/block acquisition trigger pulses, and final output save boundaries.
  - Tests cover compact summary formatting, GUI runner-call diagnostics, runner error diagnostics, and hardware setup-through-B0 diagnostics.
  - Screenshot checks captured `/tmp/dots_gui_1366x768.png` and `/tmp/dots_gui_1600x900.png`; both show the compact summary, nonblank timeline, and visible metadata section.
- What remains broken: No known breakage from this slice; screenshots do not validate real microscope/Arduino hardware execution.
- Remaining in-slice work: Use the new console diagnostics during a 2P workstation run to identify any hardware-only startup breakpoint.
- Next likely breakpoint: If stdout is still hidden on the microscope workstation, add a metadata-folder debug trace file in a follow-up.
- Rerun implications: GUI layout and console output changed; trigger timing, metadata schemas, and saved CSV outputs are unchanged.
