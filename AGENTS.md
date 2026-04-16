# Agent Entrypoint

This repository uses a routed instruction system under `.agents/`. Start here, then follow the workflow router and only read the smallest reference file needed for the current task.

## Required startup order
1. Open `.agents/workflows/repo-router.md`.
2. Follow its dispatch table to the correct workflow profile.
3. Read the smallest relevant reference doc named by that profile router.
4. Open stage maps or symbol indexes only if the first reference doc is not enough.
5. Open owning modules before large runnable scripts.
6. Open large script regions only when the owner module or reference doc is insufficient.

## Non-negotiable repo rules
- Preserve the canonical experiment tree defined in `utils.py` unless the task is an intentional layout migration.
- Fix semantics at the writer stage that produces an artifact, not in a downstream consumer.
- Treat preprocessing stage scripts as the owners of their written outputs.
- Treat visual stimulation run scripts as wrapper-orchestration owners; keep shared behavior aligned across the relevant script family unless divergence is deliberate.
- Validate after edits. Do not claim success from static reasoning alone.
- If public behavior, output ownership, or callable surfaces change, update the relevant `.agents/references/` doc in the same pass.
- After each completed or paused change slice, append the matching workflow `recent-changes-*.md` log entry (not only unfinished work).

## Reference files
- `.agents/workflows/repo-router.md`: top-level dispatcher for all repo tasks.
- `.agents/workflows/preprocessing-router.md`: routing for TIFF preprocessing, Suite2P, dF/F, and migration/layout work.
- `.agents/workflows/visual-stimulation-router.md`: routing for PsychoPy runs, triggers, metadata logs, and support tools.
- `.agents/references/canonical-data-layout.md`: authoritative folder tree and writer-stage outputs.
- `.agents/references/preprocessing-stage-map.md`: ordered preprocessing stages and validation surfaces.
- `.agents/references/visual-stimulation-stage-map.md`: ordered visual stimulation run flow and outputs.
- `.agents/references/symbol-index.md`: compact callable/public surface for shared utilities and preprocessing.
- `.agents/references/current-state.md`: mixed-state caveats and active inconsistencies.

## Scope note

Keep this file short. Repo-specific routing, ownership, validation, and handoff details live under `.agents/`.
