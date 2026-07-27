# Installation

## Requirements

- Python ≥ 3.13
- [uv](https://docs.astral.sh/uv/) — the package manager this project uses throughout

## Install

```bash
git clone <repo-url>
cd salafleezers-processing

# Core install (CLI + processing pipeline, no GUI)
uv sync
```

`sfz` ships with three optional extras, layered on top of the core install:

| Extra | Adds | Command |
| --- | --- | --- |
| `gui` | FastAPI + uvicorn + the built Svelte SPA — needed for `sfz gui` | `uv sync --extra gui` |
| `docs` | MkDocs Material + mkdocstrings — needed to build this site | `uv sync --extra docs` |
| `dev` | pytest, ruff, mypy, hypothesis | `uv sync --extra dev` |

Extras compose — e.g. for a full development environment:

```bash
uv sync --extra gui --extra docs --extra dev
```

Everything runs via `uv run`, which uses the project's locked virtual environment without
needing to activate it:

```bash
uv run sfz inspect path/to/230415_001.dat
uv run sfz gui
uv run pytest
```

## Building the web GUI frontend

The Svelte SPA that `sfz gui` serves is built separately with Node — it isn't part of the
Python package build. If `frontend/dist/` doesn't already exist:

```bash
cd frontend
npm ci
npm run build
```

`sfz gui` looks for the built assets at `frontend/dist` (source checkout) or
`salafleezers/web/frontend_dist` (installed wheel — the build embeds the SPA via
`pyproject.toml`'s `force-include`, so a `pip`/`uv` install of a built wheel already has it).

!!! warning "Missing build = blank browser tab, not an error"
    A `git clone` + `uv sync` checkout is an editable install, so it never has
    `salafleezers/web/frontend_dist` — only the `frontend/dist` fallback applies, and that
    directory doesn't exist until you run the build above. If you skip it, `sfz gui` still
    starts and prints its usual "listening on ..." banner, but `create_app()` never mounts the
    SPA (`_SPA_DIR.exists()` is `False`), so every route returns 404 and the browser just shows
    an empty page — it isn't hung, there's just nothing being served. If `sfz gui` looks stuck
    empty, run the Node build first.

## Docker

A multi-stage `Dockerfile` builds the frontend and the Python runtime into one image. Nothing
needs to be configured first — data gets in via upload:

```bash
docker compose up -d
```

See `docker-compose.yml` in the repo root. Session data and uploaded datasets persist in a named
volume (`sfz-sessions`) across container restarts/upgrades. Optional hardening for a shared-lab
deployment, set via environment (see `.env.example`):

- `SFZ_AUTH_TOKEN` — gate access behind a shared secret.
- `SFZ_TRUSTED_USER_HEADER` — read the caller's identity from a header set by an authenticating
  reverse proxy, so each person gets an isolated workspace instead of sharing one under
  `SFZ_AUTH_TOKEN`.

To also reach files already on the host by server path (the legacy flow — useful for scripted
workflows, not needed for normal upload-based use), copy `docker-compose.override.yml.example`
to `docker-compose.override.yml` and set `SFZ_DATA_DIR` there; it mounts your directory
read-only at `/data` and sets `SFZ_DATA_ROOT` to confine path-based opens to it.

## Verifying the install

```bash
uv run sfz --help
uv run pytest -q
```
