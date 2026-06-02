# Recent Changes: Preprocessing

Append-only handoff log for preprocessing, Suite2P, dF/F, and migration work.

## Template
- Date and label:
- Slice goal:
- Passes completed in this session:
- What changed:
- What remains broken:
- Remaining in-slice work:
- Next likely breakpoint:
- Rerun implications:

## 2026-05-11 - GUI blocks all alias
- Date and label: 2026-05-11, GUI blocks all alias
- Slice goal: Let the preprocessing GUI Blocks field accept `all` as an explicit request to process every matching raw TIFF block.
- Passes completed in this session: Workflow parser patch -> GUI hint update -> focused GUI workflow test -> compile check -> log update.
- What changed: `parse_optional_int_list(...)` now treats blank strings and case-insensitive `all` as `None`, preserving the existing internal all-blocks behavior. The GUI Blocks field hint now says comma-separated block numbers or `all`. Added regression coverage for `all`, `ALL`, and whitespace-padded `all`.
- What remains broken: None known for the Blocks field alias.
- Remaining in-slice work: None.
- Next likely breakpoint: If operators need mixed expressions such as `1,2,all`, define that behavior explicitly before expanding the parser.
- Rerun implications: Existing preprocessing outputs are unchanged. Operators can enter `all` in the GUI Blocks field instead of leaving it blank. Validation: `python3 -m unittest tests/test_preprocessing_gui_workflow.py` passed; `python3 -m py_compile preprocessing/*.py utils.py old2new_migration_no_docstrings.py` passed.

## 2026-05-09 - Local Cellpose model path resolution
- Date and label: 2026-05-09, Local Cellpose model path resolution
- Slice goal: Stop Cellpose from falling back to `~/.cellpose/models/cpsam` when the ops template carries the historical Windows custom-model path.
- Passes completed in this session: Runtime warning investigation -> Suite2P owner resolver patch -> focused regression tests -> compile check -> reference/log update.
- What changed: `motion_segmentation_suite2p.py` now resolves default model name `2pf_cpsam_20250915_134652` to an existing local model file before invoking Suite2P. Resolution checks `cellpose/models/<model>` under ancestors of the plane TIFF path, then the known processing-root candidate `/Users/ddharmap/dataProcessing/2p_processing/cellpose/models/2pf_cpsam_20250915_134652`, and only falls back to the historical `D:\cellpose\models\2pf_cpsam_20250915_134652` string if no local file exists. `run_suite2p(...)` prints the resolved model path before dispatch, making future GUI logs explicit. Tests cover data-root model resolution, historical fallback, and propagation into legacy/current Suite2P paths.
- What remains broken: None known for local custom-model selection on this workstation.
- Remaining in-slice work: None known.
- Next likely breakpoint: If the data root changes, place the custom model under `<data_root>/cellpose/models/2pf_cpsam_20250915_134652` or add that workstation's processing-root candidate deliberately.
- Rerun implications: Restart/re-run Suite2P from the GUI; the log should show `[Suite2P] Cellpose model: /Users/ddharmap/dataProcessing/2p_processing/cellpose/models/2pf_cpsam_20250915_134652` before ROI detection, and the previous `cpsam not found` fallback warning should not appear for the custom model. Validation: `python3 -m unittest tests/test_preprocessing_gui_workflow.py` passed; `python3 -m py_compile preprocessing/*.py utils.py old2new_migration_no_docstrings.py` passed.

## 2026-05-09 - GUI repo-local Suite2P ops fallback
- Date and label: 2026-05-09, GUI repo-local Suite2P ops fallback
- Slice goal: Make the preprocessing GUI find the committed Suite2P ops template when data-root-local ops files are absent or saved settings point at a missing file.
- Passes completed in this session: GUI ops resolver patch -> focused GUI workflow tests -> compile check -> reference/log update.
- What changed: `preprocessing_gui.py` now defines `REPO_DEFAULT_SUITE2P_OPS_PATH` for `preprocessing/suite2p_ops_sep_2025_cp.npy`, lets `find_default_suite2p_ops_path(...)` fall back to that file after checking known ops filenames in the selected data root, and uses `resolve_suite2p_ops_path(...)` so `_maybe_autofill_suite2p_ops_path()` keeps existing saved ops paths but replaces stale/missing ones with the best available default. Tests cover data-root precedence, repo fallback, stale saved path replacement, and existing saved path preservation.
- What remains broken: None known for ops-path discovery; Suite2P still validates that selected fish preprocessing outputs exist before launching.
- Remaining in-slice work: None known.
- Next likely breakpoint: If operators need multiple ops presets, add an explicit GUI preset selector instead of adding more implicit search rules.
- Rerun implications: Opening or starting Suite2P from the GUI with a missing saved ops path should now populate the committed `suite2p_ops_sep_2025_cp.npy` when no preferred data-root ops file exists. Validation: `python3 -m unittest tests/test_preprocessing_gui_workflow.py` passed; `python3 -m py_compile preprocessing/*.py utils.py old2new_migration_no_docstrings.py` passed.

## 2026-05-09 - Suite2P default Cellpose model enforcement
- Date and label: 2026-05-09, Suite2P default Cellpose model enforcement
- Slice goal: Ensure GUI/CLI Suite2P runs always use the intended default custom Cellpose model.
- Passes completed in this session: Suite2P owner patch -> focused regression tests -> compile check -> reference/log update.
- What changed: `motion_segmentation_suite2p.py` now defines `DEFAULT_CELLPOSE_MODEL = D:\cellpose\models\2pf_cpsam_20250915_134652` and stamps every per-plane ops dict with that model plus `anatomical_only=2` before dispatching to legacy or current Suite2P. Current Suite2P mapping therefore receives the same model under nested `detection.cellpose_settings.cellpose_model`; legacy `run_s2p(ops=...)` receives it directly in flat ops. Tests now cover default override and model propagation.
- What remains broken: The saved GUI settings currently may still point at a missing ops file; this change controls the model after a valid ops file is loaded, not ops-file discovery.
- Remaining in-slice work: None known.
- Next likely breakpoint: If the model file must be runnable on non-Windows machines, decide whether to map the Windows model string to a local model path or keep exact historical ops text.
- Rerun implications: Re-run Suite2P for any fish whose existing outputs were created without this custom model. Validation: `python3 -m unittest tests/test_preprocessing_gui_workflow.py` passed; `python3 -m py_compile preprocessing/*.py utils.py old2new_migration_no_docstrings.py` passed.

## 2026-05-09 - Multi-condition Suite2P ROI retention comparison
- Date and label: 2026-05-09, Multi-condition Suite2P ROI retention comparison
- Slice goal: Extend the `L395_f11` baseline ROI-retention analysis across all tested Suite2P condition roots.
- Passes completed in this session: Built-in manifest and aggregate output implementation -> focused unit tests -> compile check -> real six-condition `L395_f11` comparison with CSV/plot output verification.
- What changed: `scripts/compare_suite2p_roi_sets.py` now supports `--comparison-manifest all_l395_conditions` and `--multi-output-root` with default `/Users/ddharmap/dataProcessing/2p_processing/roi_retention_comparison/L395_f11`. Manifest runs reuse the existing centroid-distance <= 5 px and mask-IoU >= 0.05 matching/classification logic, write per-condition detailed CSVs/plots in condition subfolders, write `condition_roi_retention_summary.csv` and `condition_plane_roi_retention_summary.csv`, and generate cross-condition retention bar, category stacked-bar, and per-plane heatmap plots. Multi-condition runs skip activity trace plots and skip unmatched-mask TIFF trace extraction.
- What remains broken: This is still a spatial ROI-retention comparison, not a stimulus-locked response analysis.
- Remaining in-slice work: None known.
- Next likely breakpoint: If adopting a non-legacy Suite2P condition, inspect whether low retained-baseline ROI counts are acceptable for the downstream biological analysis rather than relying on total accepted-cell counts.
- Rerun implications: Output was written to `/Users/ddharmap/dataProcessing/2p_processing/roi_retention_comparison/L395_f11`. Condition-level retained-as-accepted counts: legacy CPU 3034/3132 (96.87%), legacy MPS 3018/3132 (96.36%), current GUI MPS sparsery 1962/3132 (62.64%), current CPU sparsery 1984/3132 (63.35%), current MPS custom Cellpose 660/3132 (21.07%), current CPU custom Cellpose 653/3132 (20.85%). Legacy MPS reproduced the known aggregate: 3018 matched accepted, 61 matched rejected, 53 unmatched, 102 new accepted. Validation: `python3 -m unittest tests/test_compare_suite2p_roi_sets.py` passed, `python3 -m py_compile scripts/compare_suite2p_roi_sets.py` passed, and `python3 scripts/compare_suite2p_roi_sets.py --comparison-manifest all_l395_conditions` completed. Interpretation note: legacy MPS should remain the default if it preserves baseline ROIs substantially better than current Suite2P Cellpose.

## 2026-05-09 - Remainder ROI activity trace diagnostic
- Date and label: 2026-05-09, Remainder ROI activity trace diagnostic
- Slice goal: Add an activity-trace view for the baseline-vs-legacy-MPS ROI remainder.
- Passes completed in this session: Helper/plot implementation -> focused unit tests -> real `L395_f11` comparison reruns -> visual inspection of the generated plot.
- What changed: `scripts/compare_suite2p_roi_sets.py` now writes `remainder_zscored_dff_traces_by_plane.png`, a large wide-panel inspection grid with at most five traces per row/panel. Baseline accepted-only cells (`matched_rejected` plus `unmatched`) are shown first, followed by legacy-MPS new accepted cells; each row overlays up to five differently colored traces with a legend naming plane, ROI, category, and trace-strength metric. The plot computes dF/F transiently from Suite2P `F.npy` with the existing percentile-baseline method, then z-scores each trace to itself. Added tests for z-scoring, remainder ROI selection, and the max-five-traces-per-panel layout. Updated the preprocessing stage map.
- What remains broken: This remains a non-stimulus-locked diagnostic and does not prove whether remainder ROIs are behaviorally or visually responsive.
- Remaining in-slice work: None known.
- Next likely breakpoint: If the remainder traces look biologically meaningful, add stimulus-aligned summaries using the raw metadata timing files.
- Rerun implications: Re-run `scripts/compare_suite2p_roi_sets.py` without `--skip-plots` to regenerate the new PNG for an existing comparison output root. No canonical stage-4 `*_dFoF.npy` artifacts are written.

## 2026-05-09 - Legacy MPS ROI retention comparison
- Date and label: 2026-05-09, Legacy MPS ROI retention comparison
- Slice goal: Test whether the selected legacy MPS Suite2P run loses biologically relevant accepted cells compared with the historical `L395_f11` baseline.
- Passes completed in this session: ROI matching script implementation -> synthetic unit tests -> real baseline-vs-legacy-MPS run -> CSV/plot output generation -> aggregate retention summary.
- What changed: Added `scripts/compare_suite2p_roi_sets.py` and `tests/test_compare_suite2p_roi_sets.py`. The script uses baseline accepted `iscell` ROIs as reference, matches to comparison ROIs by centroid distance and mask IoU, classifies baseline cells as `matched_accepted`, `matched_rejected`, or `unmatched`, reports new accepted comparison cells, computes trace-quality metrics, and extracts comparison-run traces from motion-corrected TIFFs for unmatched baseline masks. Updated the preprocessing stage map to mention this support script.
- What remains broken: This is a trace-quality screen, not a stimulus-locked response analysis. Some unmatched baseline cells have strong baseline trace metrics, so follow-up review of the generated plots/CSV is still needed before concluding they are biologically irrelevant.
- Remaining in-slice work: Review generated overlay plots and strongest-unmatched traces; optionally add stimulus-locked summaries once metadata alignment is in scope.
- Next likely breakpoint: If unmatched or rejected cells appear biologically important, test whether changing the `iscell` threshold/classifier treatment or preserving baseline masks for downstream extraction is preferable.
- Rerun implications: Real-data output was written to `/Users/ddharmap/dataProcessing/2p_processing_suite2p_legacy_mps/comparison_vs_baseline/L395_f11`. Across five planes, baseline accepted cells totaled 3132; legacy MPS accepted cells totaled 3120. Baseline accepted cells matched as accepted in legacy MPS: 3018 (96.36%); spatially matched but rejected: 61 (1.95%); unmatched: 53 (1.69%); new accepted legacy MPS cells: 102. Validation: `python3 -m unittest tests/test_compare_suite2p_roi_sets.py` passed, `python3 -m py_compile scripts/compare_suite2p_roi_sets.py` passed, and the real run reproduced expected baseline accepted counts `[659, 664, 666, 621, 522]` and legacy MPS accepted counts `[651, 663, 665, 630, 511]`.

## 2026-05-08 - GUI default legacy MPS Suite2P runtime
- Date and label: 2026-05-08, GUI default legacy MPS Suite2P runtime
- Slice goal: Make the preprocessing GUI default to the practical legacy Suite2P 0.14.6 + Cellpose 4.0.6 MPS runtime for Suite2P segmentation.
- Passes completed in this session: GUI command/preflight patch -> ops-path default helper -> focused unit tests -> compile check -> real local preflight.
- What changed: `preprocessing_gui.py` now launches Suite2P with `/Users/ddharmap/miniforge3/envs/suite2p0146_cpu/bin/python`, clears `CALCIUM_SUITE2P_FORCE_CPU` for the Suite2P subprocess, blocks GUI Suite2P launch unless the legacy env has Suite2P 0.14.6, Cellpose 4.0.6, Torch MPS availability, and Cellpose GPU/MPS availability, and auto-fills an empty ops path from known legacy ops filenames under the selected data root. GUI preprocessing still uses the current Python. Updated focused tests and the preprocessing stage map.
- What remains broken: The legacy env path is intentionally workstation-specific and will block on machines where `/Users/ddharmap/miniforge3/envs/suite2p0146_cpu/bin/python` does not exist. Strict byte identity to the old Windows/CUDA baseline remains unproven.
- Remaining in-slice work: Optional manual GUI click-through on the workstation to confirm the dialog/log text in the Tk UI.
- Next likely breakpoint: If this GUI needs to run on another workstation, make the legacy Python path configurable while keeping this path as the default.
- Rerun implications: GUI-launched Suite2P now uses the legacy-MPS replay path by default. Validation run: `python3 -m unittest tests/test_preprocessing_gui_workflow.py` passed, `python3 -m py_compile preprocessing/*.py` passed, and the real preflight returned Suite2P 0.14.6, Cellpose 4.0.6, Torch 2.11.0, `mps=True`, `cellpose_gpu=True`.

## 2026-05-08 - Suite2P legacy MPS replay comparison
- Date and label: 2026-05-08, Suite2P legacy MPS replay comparison
- Slice goal: Run an isolated `L395_f11` Suite2P replay with legacy Suite2P 0.14.6 settings while allowing Cellpose/Torch to use MPS, then compare runtime and ROI counts against baseline, legacy CPU, and current Suite2P runs.
- Passes completed in this session: Isolated legacy-MPS output root setup -> preflight environment check -> five-plane legacy API run through `preprocessing_cli.py suite2p` -> runtime/log capture -> ROI, `iscell`, `Fneu`, ops, and comparison extraction.
- What changed: Created `/Users/ddharmap/dataProcessing/2p_processing_suite2p_legacy_mps` with copied `L395_f11` plane TIFF inputs, `suite2p_ops_legacy_mps.npy`, `suite2p_legacy_mps_config.json`, `preflight_legacy_mps.txt`, and `suite2p_legacy_mps_run.log`. Repo code behavior did not change.
- What remains broken: Strict byte identity against the historical Windows/CUDA baseline was not attempted in this slice. Legacy MPS still remains a replay comparison, not proof of exact reproduction.
- Remaining in-slice work: None for the isolated `L395_f11` comparison.
- Next likely breakpoint: If adopting this setup, run a second fish or a one-plane smoke test from another cohort before a full batch, then decide whether the GUI should expose a legacy-MPS preset or whether operators should run it through the CLI only.
- Rerun implications: Legacy MPS used Suite2P 0.14.6, Cellpose 4.0.6, Torch 2.11.0, MPS available, CUDA unavailable, and `CALCIUM_SUITE2P_FORCE_CPU` unset. Five planes completed in 10.38 minutes (`real 626.68s`), versus the earlier inferred legacy CPU span of about 51 minutes and current CPU + CellposeSAM at 185.26 minutes. ROI counts were `[913, 960, 948, 908, 792]` and accepted `iscell` counts were `[651, 663, 665, 630, 511]`, with `Fneu` all zero; this is very close to baseline `[924, 958, 956, 897, 795]` and legacy CPU `[915, 956, 941, 903, 793]`.

## 2026-05-08 - Current Suite2P CPU custom Cellpose comparison
- Date and label: 2026-05-08, Current Suite2P CPU custom Cellpose comparison
- Slice goal: Run the remaining current Suite2P 1.x comparison on CPU with the custom Cellpose model and baseline per-plane diameters, then compare against baseline and prior runs.
- Passes completed in this session: Current force-CPU Cellpose patch -> focused tests/compile checks -> isolated five-plane CPU run -> settings verification -> byte/array/ROI comparisons.
- What changed: `CALCIUM_SUITE2P_FORCE_CPU=1` now also patches Cellpose GPU detection in the current Suite2P API path, so current Suite2P and Cellpose both stay on CPU. Added focused unit coverage for this behavior.
- What remains broken: Strict identity against `L395_f11` baseline still fails. Current CPU + custom model used `device=cpu`, `algorithm=cellpose`, model `2pf_cpsam_20250915_134652`, `meanImg`, baseline diameters, and `Fneu=0`, but produced ROI counts `[243, 316, 219, 302, 163]` versus baseline `[924, 958, 956, 897, 795]`.
- Remaining in-slice work: None for this comparison. Current Suite2P 1.x with CellposeSAM gives similarly low ROI counts on CPU and MPS, so the MPS backend alone is not the cause of the mismatch.
- Next likely breakpoint: For exact or near-exact reproduction, run old Suite2P 0.14.6 in the original Windows CUDA environment, or treat existing baseline Suite2P artifacts as fixed inputs for downstream analysis.
- Rerun implications: Current CPU + CellposeSAM is very slow on this machine: all five planes took 185.26 minutes. Avoid it for routine full-batch processing unless CPU-only current Suite2P output is explicitly required.

## 2026-06-02 - remove legacy confocal registration scaffold
- Date and label: 2026-06-02, remove legacy confocal registration scaffold
- Slice goal: Stop new 2P metadata/fish-folder initialization from creating legacy `round1`, `roundn`, `r1`, and `r2` confocal/registration folders.
- Passes completed in this session: Audited listed Danin fish folders, removed empty legacy folders, updated canonical tree writer, added focused layout regression test, and updated canonical layout docs.
- What changed: `utils.init_experiment_tree` now creates `01_raw/confocal/rbest`, `01_raw/confocal/rn`, `02_reg/00_preprocessing/rbest`, and `02_reg/00_preprocessing/rn`, and no longer pre-creates old ANTs registration scaffold folders such as `01_r1-2p`, `02_rn-r1`, `04_r1-ref`, or `05_r2-ref`.
- What remains broken: Registration-specific folder creation should be owned by the future registration staging workflow, not this 2P metadata initialization path.
- Remaining in-slice work: None known for the folder initializer.
- Rerun implications: Existing fish folders may still contain legacy folders until cleaned manually; new calls to `init_experiment_tree` will not recreate them.

## 2026-05-08 - Current Suite2P MPS custom Cellpose comparison
- Date and label: 2026-05-08, Current Suite2P MPS custom Cellpose comparison
- Slice goal: Run current Suite2P on Mac MPS with the local custom Cellpose model and baseline per-plane diameters, then compare against the existing Windows CUDA baseline and prior CPU runs.
- Passes completed in this session: Current Suite2P adapter patch -> focused tests/compile checks -> isolated five-plane MPS run -> settings verification -> byte/array/ROI comparisons.
- What changed: `motion_segmentation_suite2p.py` now maps legacy flat Cellpose fields into current Suite2P nested settings: `pretrained_model` to `detection.cellpose_settings.cellpose_model`, `anatomical_only` to the Cellpose detector and image selection, and old flow/cellprob/spatial high-pass fields to current Cellpose settings. Added focused unit coverage for this mapping.
- What remains broken: Strict identity against `L395_f11` baseline still fails. The current MPS + custom model run used `algorithm=cellpose`, model `2pf_cpsam_20250915_134652`, `meanImg`, baseline diameters, and `Fneu=0`, but produced ROI counts `[245, 333, 214, 316, 174]` versus baseline `[924, 958, 956, 897, 795]`.
- Remaining in-slice work: None for this comparison. Current Suite2P 1.x with CellposeSAM is not a close reproduction of the old Windows CUDA Suite2P 0.14.6 output even when the custom model path is mapped.
- Next likely breakpoint: If exact reproduction is still required, run the replay on the Windows CUDA environment that created the baseline, or keep the existing baseline Suite2P artifacts fixed for downstream dF/F.
- Rerun implications: Re-run current Suite2P for any fish that should use custom Cellpose models under Suite2P 1.x; do not compare these outputs byte-for-byte with historical Suite2P 0.14.6 CUDA artifacts.

## 2026-05-07 - Suite2P legacy CPU replay
- Date and label: 2026-05-07, Suite2P legacy CPU replay
- Slice goal: Re-run GUI/CLI Suite2P on isolated `L395_f11` inputs with Suite2P 0.14.6 and CPU-only Cellpose behavior, then compare outputs directly with the existing processed baseline.
- Passes completed in this session: Current Suite2P CPU control run -> legacy Suite2P 0.14.6 CPU environment setup -> GUI-stage Suite2P replay through the CLI subprocess path -> direct byte and metadata comparisons -> focused tests/compile checks.
- What changed: `motion_segmentation_suite2p.py` now detects the legacy `run_s2p(ops=...)` API, preserves old ops values such as `do_bidiphase=True`, `bidiphase=0.0`, and `diameter=0` for old Suite2P, adds `filelist` for old file selection, and treats `CALCIUM_SUITE2P_FORCE_CPU=1` as a runtime-only Cellpose CPU patch in legacy mode. Current Suite2P still uses the existing normalized settings path and can be forced to `torch_device=cpu`.
- What remains broken: Strict output identity against the existing `L395_f11` baseline still fails. The isolated individual-plane TIFF inputs are byte-identical to baseline, but both current CPU and legacy CPU Suite2P replays produce different motion-corrected TIFF bytes and different Suite2P arrays/ROI counts.
- Remaining in-slice work: None for the CPU replay implementation. Exact historical reproduction likely requires matching the original Cellpose/PyTorch/device stack that produced the Windows-path baseline, not just Suite2P 0.14.6 and the same model file.
- Next likely breakpoint: If exact replay remains required, identify the original Cellpose and PyTorch versions and whether the baseline used CUDA/GPU versus CPU, then run a third isolated replay in that matching environment.
- Rerun implications: Re-run Suite2P to benefit from legacy API preservation or the CPU override. Existing stage-2 plane TIFFs do not need regeneration when they are already byte-identical.

## 2026-05-07 - GUI workflowtest and Suite2P MPS compatibility
- Date and label: 2026-05-07, GUI workflowtest and Suite2P MPS compatibility
- Slice goal: Run the full GUI-launched preprocessing plus Suite2P workflow on isolated `L395_f11` data and compare against the existing processed fish.
- Passes completed in this session: Isolated raw copy -> GUI preprocessing -> GUI Suite2P retries with traceback-driven fixes -> focused tests/compile checks -> final GUI Suite2P completion and comparison diagnostics.
- What changed: `motion_segmentation_suite2p.py` now normalizes legacy runtime ops for current Suite2P, selects CUDA/MPS/CPU automatically unless CPU is explicit, patches current Suite2P MPS float64 taper construction in-process, preserves zero `Fneu` behavior when `neuropil_extract=False`, and joins current `file 0000.tif` registered chunks instead of writing empty motion-corrected TIFFs.
- What remains broken: Strict byte identity against the existing `L395_f11` baseline failed. Preprocessing TIFF sampled pixel data matched but TIFF bytes/sizes differed; Suite2P outputs differed in ROI counts because the current MPS/current-Suite2P run is not numerically identical to the old baseline.
- Remaining in-slice work: None for making the GUI workflow complete successfully; exact baseline reproduction would require matching the old Suite2P/runtime behavior rather than only current-code compatibility.
- Next likely breakpoint: If byte-identical historical reproduction is required, run with the original Suite2P version, original Windows ops semantics, and CPU/device settings rather than current Suite2P MPS.
- Rerun implications: Re-run Suite2P to regenerate nonempty motion-corrected TIFFs from current Suite2P chunk names; preprocessing outputs do not need regeneration unless byte-identical TIFF container output is required.

## 2026-05-07 - Suite2P run_s2p API adapter
- Date and label: 2026-05-07, Suite2P run_s2p API adapter
- Slice goal: Make GUI-launched Suite2P work with the installed Suite2P 1.0.0.1 `run_s2p(db=..., settings=...)` API.
- Passes completed in this session: Installed API inspection -> stage-owner adapter patch -> old/new API unit coverage -> focused tests and compile check.
- What changed: `motion_segmentation_suite2p.run_suite2p` now builds both legacy `tiff_list` and current `file_list` inputs, keeps canonical output paths, and adapts flat ops dictionaries through Suite2P's current settings converter when `run_s2p(ops=...)` is unavailable.
- What remains broken: Full real-data Suite2P completion still needs manual GUI validation after the operator restarts the stage.
- Remaining in-slice work: None known.
- Next likely breakpoint: Re-run `Start Suite2P` for the failed fish/plane and inspect whether Suite2P reaches registered TIFF and `.npy` output creation.
- Rerun implications: Existing preprocessing outputs do not need regeneration; rerun only the failed Suite2P stage.

## 2026-05-07 - Suite2P OpenMP environment repair
- Date and label: 2026-05-07, Suite2P OpenMP environment repair
- Slice goal: Repair the existing `2p` conda environment so GUI-launched Suite2P no longer aborts on duplicate `libomp.dylib` initialization.
- Passes completed in this session: Environment backup -> PyPI numeric/runtime wheel removal -> conda-forge reinstall -> import/unit/compile validation.
- What changed: Replaced PyPI `torch`, `torchvision`, `scikit-learn`, `scipy`, and `threadpoolctl` in `/Users/ddharmap/miniforge3/envs/2p` with conda-forge builds. No repo code or GUI behavior changed.
- What remains broken: GUI button click still needs manual validation with the operator's real Suite2P config and data selection.
- Remaining in-slice work: None known.
- Next likely breakpoint: Relaunch `preprocessing/preprocessing_gui.py` from the repaired `2p` environment and start Suite2P on a selected plane.
- Rerun implications: Existing preprocessing outputs do not need regeneration; rerun only the Suite2P stage that previously aborted.

## 2026-05-07 - GUI progress and block workers
- Date and label: 2026-05-07, GUI progress and block workers
- Slice goal: Restore GUI progress visibility without log clutter and add per-round parallelism for resonant streaming preprocessing.
- Passes completed in this session: GUI subprocess output parser -> resonant block worker implementation -> focused tests/docs -> compile checks.
- What changed: GUI-launched carriage-return progress now updates the status label instead of appending every tick to the stage log. Resonant streaming workers now resolve against selected raw TIFF blocks, keep direct session-parallel writing when sessions are already independent, and use temporary per-block plane outputs plus a merge step when a session has multiple blocks.
- What remains broken: Real-data throughput still needs benchmarking; block-level parallelism adds temporary output and merge I/O, so the best worker count may depend on storage speed.
- Remaining in-slice work: None known.
- Next likely breakpoint: Benchmark representative multi-block rounds with `scripts/benchmark_preprocessing_workers.py --blocks <blocks> --workers 1,2,4` and tune the GUI default if needed.
- Rerun implications: Re-run stage 2 preprocessing to benefit from block-level worker parallelism; output plane names and Suite2P validation surfaces are unchanged.

## 2026-05-07 - multi-session plane offsets
- Date and label: 2026-05-07, multi-session plane offsets
- Slice goal: Keep repeated 2P imaging sessions separate when preprocessing one fish folder and make the GUI match the single-root experiment layout.
- Passes completed in this session: Session parser and writer update -> workflow/GUI/Suite2P validation update -> benchmark utility -> focused regression tests/docs -> compile checks.
- What changed: Resonant preprocessing now detects implicit `r1` and explicit `_rN` raw TIFF sessions, writes each session into the next global plane range, records session-to-plane metadata, and keeps output TIFFs grayscale via `photometric=minisblack`. The GUI now uses one data root, defaults Suite2P planes to `all`, and exposes preprocessing workers. Suite2P config expands `all` to available preprocessed plane TIFFs per fish.
- What remains broken: Full Suite2P execution still needs manual/integration validation with a real Suite2P environment and real preprocessed plane TIFFs.
- Remaining in-slice work: None known for preprocessing. Optional: repeat the benchmark on all selected blocks before an unattended full experiment batch.
- Next likely breakpoint: If operators need different session naming beyond `_rN`, update `parse_functional_tiff_name` and its tests at the preprocessing writer stage.
- Rerun implications: Re-run stage 2 preprocessing for fish with `_r2` raw TIFFs to generate separate output plane ranges before running Suite2P with `selected_planes=all`. On `L758_f02` block 1, `scripts/benchmark_preprocessing_workers.py --workers 1,2` measured `workers=2` at 71.77s vs `workers=1` at 116.39s, a 1.62x speedup.

## 2026-05-07 - streaming preprocessing entrypoint
- Date and label: 2026-05-07, streaming preprocessing entrypoint
- Slice goal: Add a low-memory raw TIFF preprocessing path that streams pages from disk and reports progress on one updating terminal line.
- Passes completed in this session: Added implementation, tests, and reference updates.
- What changed: `preprocessing_tiff.py` now has `process_fish_streaming(...)` plus two-pass streaming helpers for exact negative-value correction, resonant plane writers, linear stack writing, and stdlib carriage-return progress. Added focused synthetic TIFF tests.
- What remains broken: Nothing known in this slice.
- Remaining in-slice work: None.
- Next likely breakpoint: Real-data trial on a large local TIFF block to confirm throughput and terminal progress behavior on macOS.
- Rerun implications: Re-run stage 2 preprocessing with `process_fish_streaming(...)` to generate the same canonical plane/stack TIFF outputs without loading full blocks into memory.

## 2026-05-07 - preprocessing workflow GUI
- Date and label: 2026-05-07, preprocessing workflow GUI
- Slice goal: Add a GUI workflow that keeps TIFF preprocessing and Suite2P as separate operator actions and separate subprocesses.
- Passes completed in this session: Added workflow config helpers, CLI subprocess entrypoint, Tkinter GUI, Suite2P preflight validation, and focused tests.
- What changed: `preprocessing_workflow.py` now parses stage configs, validates selected preprocessing plane outputs, and delegates to the owning stage modules. `preprocessing_cli.py` exposes `preprocess` and `suite2p` JSON-config commands. `preprocessing_gui.py` provides separate Start Preprocessing and Start Suite2P buttons with streaming mode as the default. `motion_segmentation_suite2p.batch_process` now accepts `storage_root` explicitly.
- What remains broken: Full Suite2P execution still needs manual/integration validation with a real Suite2P environment and real preprocessed plane TIFFs.
- Remaining in-slice work: None known.
- Next likely breakpoint: Real-data GUI trial: run streaming preprocessing for one fish, confirm output validation, then run Suite2P on one selected plane.
- Rerun implications: GUI-launched preprocessing writes the same stage-2 outputs; GUI-launched Suite2P writes the same stage-3 outputs after validation passes.
