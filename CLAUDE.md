# CLAUDE.md — Coding Guidelines

Rules distilled from *The Good Research Code Handbook* (goodresearch.dev),
plus Larsch lab conventions. Apply these whenever writing, editing, or
reviewing code in this repository.

## Repository & Project Reference

- **Data folder structure**: each experiment gets a fixed tree
  (`01_raw → 02_reg → 03_analysis → 04_plots`) created via
  `init_experiment_tree()` in `utils.py`. Always create experiment folders
  through that function; add new pipeline stages to its `rel_dirs` list
  rather than `mkdir`-ing ad hoc elsewhere.
- **Naming**: `fish_id` (e.g. `L500_f01`) is the key threaded through every
  script and filename; per-plane artifacts use `{fish_id}_plane{i}_...`
  (`file_prefix`). Keep this pattern for new artifacts so existing `glob()`
  lookups keep working.
- **Metadata sidecars**: every step that writes derived arrays also writes a
  `..._metadata.json` next to them (params used, shapes, `fish_id`,
  `time.strftime(...)` timestamp). New processing steps should do the same —
  it's the only provenance record for how an array was produced.
- **Memory hygiene**: stacks are multi-GB; `del` big arrays and
  `gc.collect()` once no longer needed (see `process_fish` in
  `preprocessing/preprocessing_tiff.py`).
- **Never delete files on a network path.** Several lab data roots are
  network-mounted drives with no backup. Don't write code that deletes or
  overwrites files there, even in an apparently-disposable subfolder —
  confirm with the user first if a task seems to call for it.

## Naming & Style

- `snake_case` for variables, functions, and modules; `CamelCase` for classes.
- Try to follow PEP 8: 4-space indentation. Keep lines readable, but don't hard-wrap
  at 80 columns.
- No single-letter or cryptic variable names — use `word`, `line`, `key`, not
  `w`, `l`, `k`
- Keep imports at the top of the file, not inline inside functions or
  `if __name__ == "__main__":` blocks.
- Use f-strings for string formatting.
- No magic numbers/strings — define named constants.
- Prefer standard-library tools over manual logic.
- Readability beats cleverness: a plain `for` loop over a dense vectorized
  one-liner is fine once you've confirmed performance isn't a bottleneck —
  vectorize for anything operating on full tracking videos or full imaging
  traces.

## Function & Module Design (Decoupling)

- One function does one thing. Keep functions short — roughly one screen (~40 lines).
- Prefer pure functions: take inputs as arguments, return outputs via `return`.
  Don't rely on hidden state.
- Never both mutate an argument in place *and* return a new value — pick one
  contract per function.
- Concentrate I/O (file reads/writes, network calls, printing) in dedicated
  functions; keep computation logic separate from I/O.
- Avoid global variables — pass values explicitly or encapsulate state in a
  class. In notebooks this often shows up as cells run out of order leaving
  stale variables in memory — don't write a cell that depends on a variable
  set by a cell that isn't directly above it.
- Reduce nesting: use guard clauses / early `continue`/`return` instead of
  deeply nested conditionals.
- Avoid `lambda` functions — define a named `def` instead when the logic is
  reused or non-trivial. A name documents what the function does, shows up
  in tracebacks, and can be reused/tested on its own; an inline `lambda`
  can't. A short, unreused `key=lambda x: ...` sort is a reasonable
  exception.

## Documentation

- Every function gets a docstring. Write it Google-style: summary, args
  with types, return value with type.
- Every `.py` file starts with a short module-level docstring (a few lines,
  before the imports) explaining what the file does (e.g. as in `visual_stimulation/`).
- Raise explicit errors (`ValueError`, `NotImplementedError`, `assert`, etc.)
  with descriptive messages instead of relying on users reading docs. In a
  batch loop over multiple fish/files, prefer warning-and-skipping
  (print a warning, then `continue`/`return`) for missing or bad per-item
  data instead — one bad item shouldn't crash a run processing many others.
  Reserve raising for invalid config or programmer errors.
- Don't add inline type hints (`def f(name: str) -> int:`) — document
  argument and return types in the docstring instead.
- Add short inline comments on lines doing non-obvious work (a tricky slice,
  why a constant has the value it does, what a loop iteration represents) —
  the goal is that a reader can follow the logic without re-deriving it.
- Don't `return` a multi-step computation directly (e.g.
  `return float(peak + np.clip(offset, -1.0, 1.0))`). Assign it to a
  well-named variable first, then return that name — the name documents
  what the value means, and it shows up if you need to inspect it in a
  debugger or traceback.

## Notebooks

- Structure notebooks as a sequence of short code cells each preceded by
  a markdown cell explaining what the step does — keep the markdown
  concise (a sentence or two), not a restatement of the code.
- Put imports and constants in cells at the top of the notebook, same
  as a script's top-of-file imports. Constants get `UPPER_CASE` names
  (e.g. `FRAME_RATE_HZ = 30`) so they read as configuration, distinct
  from ordinary `snake_case` variables.
- It's fine to prototype computation directly in a cell while exploring,
  but the end state should have that logic moved into reusable functions
  imported from the project's `.py` modules, not left inline in the
  notebook. Plotting/visualization code is the exception — keep it in
  notebook cells so plot parameters (axes, colors, thresholds) stay easy
  to tweak interactively without editing a module.

## Version Control

- Commit early and often, with each commit representing one coherent unit of work.
- Write meaningful commit messages.

**Delegating commits to Claude.** The user will sometimes ask Claude to
commit directly. When that happens:

- Before committing, run `git status` / `git diff` and show what's actually
  about to be staged — don't blindly `git add -A`.
- If the working tree has several unrelated changes bundled together, split
  them into separate commits (or ask which one is meant), rather than
  lumping unrelated work into one commit. Each commit should still be one
  coherent unit of work, same as the rule above.
- Write a commit message that describes the actual change, not a generic one.

**Claude should never, without an explicit request for that specific action:**

- `git push` — commits stay local until explicitly asked to push.
- `git rebase`, `git commit --amend`, or `git push --force` — or any other
  history-rewriting operation.
