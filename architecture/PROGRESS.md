# Progress

```mermaid
flowchart LR
    base("<img src='barnacle:check.svg' width='20' alt=''/><br/>Baseline") --> b1("<img src='barnacle:pen-line.svg' width='20' alt=''/><br/>Batch 1")
    b1 --> b2("<img src='barnacle:pen-line.svg' width='20' alt=''/><br/>Batch 2")
    b2 --> next("<img src='barnacle:circle-dot.svg' width='20' alt=''/><br/>…")
    click next href "TASK_POOL.md"
```

Worktree: `arch-entropy` (isolated from `main`).

## Baseline

- Commit: `f802330` (`fix(auth): attach CSRF token to same-origin browser writes`)
- Command: `uv run pytest -q --disable-warnings`
- Result: **580 passed, 19 skipped** (461 s)
- Formatting: to be checked with `./scripts/format.sh --check` before each commit.

## Intended architecture (to converge toward)

1. One authoritative implementation per business concept (recipe identity,
   library paths, front-matter rules, configuration, Ollama transport).
2. Dependencies point from HTTP/UI inward to domain modules; no domain module
   imports the server or the core orchestrator.
3. No unexplained circular imports; no forwarding-only modules.
4. Engineering standards are enforced by tests in `test/` (which CI runs).

## Completed batches

### Batch 0 — architecture governance (`9cdbf9c`)

Created the progress file, task pool, and ADR-0001; excluded `architecture/`
from the generated site. No production code changed. Formatting check clean.

### Batch 1 — canonical library-path rules (in progress)

Single owner for `recipe.md`/`.md` constants and for Markdown-path, folder-path,
and display-path rules: new `src/recipeserver/recipe_paths.py`. Migrated
`server.py`, `ai_assistant.py`, `core.py`, `metadata_options.py`, and
`index_html_generator.py`; removed the duplicated validators and the
independent bind-address default from `server.py`. Added behavioural tests and
structural tests in `test/test_architecture.py`. Fixed an inaccurate
HTTPS-trust docstring in `server.py`.

Evidence: focused run `129 passed, 1 skipped`; first full run exposed one stale
test that read the removed constant (migrated to the canonical one) and one
flaky e2e test that passes in isolation. Final full run pending.

## Verification record

| Batch | Tests                                            | Formatting | Docs                             | Commit    |
| ----- | ------------------------------------------------ | ---------- | -------------------------------- | --------- |
| —     | baseline: 580 passed, 19 skipped                 | —          | —                                | `f802330` |
| 0     | n/a (docs only)                                  | clean      | n/a                              | `9cdbf9c` |
| 1     | focused: 129 passed, 1 skipped; full run pending | clean      | generated, no broken local links | pending   |
