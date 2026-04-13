# Current State

Purpose

Record practical mixed-state caveats so agents do not mistake them for stable repo rules.

## Current caveats
- The repo is script-heavy and has no package manifest, test config, or existing agent scaffolding.
- `utils.init_experiment_tree` defines the canonical experiment tree, but not every visual script follows it.
- `visual_stimulation/dots_loop_stimuli.py` writes under `data_path / experimenter`, while `dots_loop_blocks.py` and `dots_continous_session.py` add `/Microscopy`. Treat this as an inconsistency to resolve intentionally, not implicit policy.
- `visual_stimulation/loom_gratings.py` writes to a separate date/fish folder layout outside the canonical tree. That is current local behavior, not a repo-wide standard.
- The `dots_*` scripts duplicate large sections of setup, trigger, and finalization logic; future fixes may need to be applied across the family.
- `old2new_migration_no_docstrings.py` appears semantically fragile: `copy_file` copies to `dst.stem` instead of `dst`, and the manifest filename uses a literal `{now}` string. Treat migration changes as high-risk and validate them carefully.
- `preprocessing/motion_segmentation_suite2p.py` has a likely runtime issue in `batch_process`: the `__main__` call passes `storage_root` positionally where the function signature expects `fps`.
- `preprocessing/dFoF_extraction.py` has likely runtime issues in the `__main__` block around `f_path`, file naming expectations, and not all saved filenames obviously match the renamed Suite2P outputs.

## How to use this file
- Read this before resume or bug-fix work that touches legacy or inconsistent behavior.
- Move items out of this file only when code and docs have been brought into a consistent state.
