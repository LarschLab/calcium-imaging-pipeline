# Calcium Imaging Pipeline Router

Purpose

Dispatch repo tasks to the smallest workflow profile and reference doc before opening code.

Use this file when

- The prompt only names the repo or a broad feature area.
- The task could touch more than one top-level directory.
- You need to decide whether a question is about data layout, preprocessing, or visual stimulation execution.

## Read this first
- Open `../references/canonical-data-layout.md` first for path, folder, output, or artifact-ownership confusion.
- Open `../references/current-state.md` first for resume, inconsistency, or migration-continuation tasks.

## Workflow profile dispatch
- `preprocessing/*.py`, `utils.py`, `old2new_migration_no_docstrings.py`, raw TIFF ingest, plane extraction, Suite2P, motion correction, dF/F, or migration/layout tasks -> `preprocessing-router.md`
- `visual_stimulation/*.py`, PsychoPy run loops, Arduino trigger timing, CSV log semantics, projector setup, sync analysis, or stimulus playback tools -> `visual-stimulation-router.md`
- Questions about folder tree ownership, authoritative output locations, or naming conventions -> `../references/canonical-data-layout.md`, then the owning profile router

## Cross-workflow invariants
- Prefer editing the writer stage that creates an output over patching a downstream reader.
- Treat `utils.init_experiment_tree` as the canonical layout authority.
- Do not treat support scripts or migration wrappers as business-logic authority when a shared owner exists.
- Preserve canonical artifact names and stage order unless the task is an explicit migration.
- When a writer-stage behavior changes, verify the first downstream consumer.

## Compact scaling rule
- Add new entrypoints to an existing profile when they share the same stage map, ownership layer, and validation surface.
- Create a new workflow profile only if the repo gains a genuinely different pipeline with different owners, repeated semantics, and validation rules.
