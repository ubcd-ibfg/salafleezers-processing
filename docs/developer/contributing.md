# Contributing

## Setting up

```bash
uv sync --extra gui --extra docs --extra dev

# Frontend, if you're touching the GUI
cd frontend && npm ci && npm run build
```

## Running everything locally

```bash
uv run pytest -q                # full test suite (fast, synthetic fixtures)
uv run ruff check src tests     # lint
uv run mypy src                 # type check (non-strict)
mamba run -n node npm run check --prefix frontend   # frontend typecheck (Svelte + TS)
mkdocs serve                    # this site, live-reloading, at http://127.0.0.1:8000
```

## Before opening a PR

- [ ] `uv run pytest -q` passes
- [ ] `ruff check` clean on files you touched (pre-existing lint debt elsewhere isn't your
      responsibility to fix in an unrelated PR)
- [ ] If you touched `analysis/`: does the change need a new unit test, or update an existing
      golden fixture? See [Testing & golden files](testing-golden-files.md).
- [ ] If you touched the frontend: `npm run check` clean, `npm run build` succeeds, and you
      **drove it in a real browser** — a clean typecheck doesn't prove a uPlot series renders
      correctly or a WebSocket message round-trips.
- [ ] If you touched `web/schemas.py`: update the matching TypeScript types in
      `frontend/src/lib/types.ts` in the same PR — they're meant to mirror each other exactly
      (see [Architecture](architecture.md)).

## Commit style

Small, focused commits; PR descriptions explain *why*, not just *what* (the diff already shows
what changed). If a change fixes a real bug found via golden-file testing or otherwise, say so
explicitly — that context is valuable and easy to lose once the fix lands.

## Code style

- `analysis/` and `processing/` stay pure — no `fastapi`, no `typer`, no plotting, no module-
  level mutable state. If you're tempted to import something GUI/CLI-specific there, the
  function probably belongs one layer up.
- Docstrings on algorithm implementations cite the method/reference they follow; deviations from
  that reference are called out explicitly, not left implicit.
- Don't add error handling for inputs that can't occur at that call site — validate at the
  actual boundary (a CLI argument, an API request body), trust internal callers.
