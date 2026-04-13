# Refactor Rules

Purpose

Keep edits at the correct owner layer for this repo.

## Rules
- `utils.py` owns canonical experiment-tree semantics. Change it before changing callers if the problem is path/layout behavior.
- Keep reusable preprocessing logic in the existing preprocessing modules. Do not duplicate stage logic in another script.
- Treat `__main__` blocks as orchestration wrappers around the owning functions. Fix reusable behavior in the functions first.
- The `dots_*` scripts are orchestration-heavy run owners. For repeated behavior across them, prefer aligning the repeated sections rather than patching one downstream symptom.
- Setup/calibration/support scripts in `visual_stimulation/` do not own canonical metadata semantics.
- Migration code in `old2new_migration_no_docstrings.py` should mirror canonical layout rules; it should not invent a new tree.
- Preserve artifact names, stage order, and directory contracts unless the task is an explicit migration.
- When a change affects written outputs, inspect the first downstream consumer and update the relevant reference doc.
