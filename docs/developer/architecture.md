# Architecture

## Layered design

```text
src/salafleezers/
├── constants.py        — instrument constants, channel maps
├── io/                  — binary .dat / _fl / _pos / _grn readers, HDF5/npz/mat writers
├── calibration/         — Lorentzian power-spectrum fitting
├── processing/          — offset/normalization, full dat→force/extension pipeline
├── fluorescence/        — APD photon-count processing
├── analysis/            — pure NumPy, headless: filters, crop, wlc, stepfind/{kv,hmm},
│                          velocity, pwd, kinetics, stats (kde/violin/msd)
├── cli/                 — Typer + Rich (sfz command)
└── web/                 — FastAPI backend (optional [gui] extra)
    ├── app.py           —   app factory, mounts the built SPA
    ├── api/              —   REST routers (sessions, files, traces, analysis)
    ├── ws/               —   WebSocket session protocol (live filter/crop/measure)
    ├── schemas.py        —   pydantic models shared by REST + WS + (conceptually) the frontend
    ├── sessions.py       —   in-memory session state
    ├── storage.py        —   disk persistence, pluggable backend
    └── auth.py           —   principal resolution (anonymous by default)

frontend/                — Svelte 5 + Vite + TypeScript SPA, built separately with npm
```

**The one rule that matters most:** `analysis/` and `processing/` never import from `web/` or
`cli/`. Every number the GUI shows you, the CLI can also print, and a notebook can also compute
by importing the same function — there is exactly one implementation of "how do you fit a WLC
curve" or "how does Kalafut-Visscher decide to add a step," not one for the GUI and a
subtly-different one for the CLI. This is also what makes [golden-file
testing](testing-golden-files.md) meaningful: a fixture generated once by running the real
MATLAB source validates the analysis function directly, and every caller (CLI, API, GUI)
inherits that correctness for free.

## Request flow (web GUI)

1. `sfz gui` calls `web.app.create_app()`, which builds a FastAPI app, mounts the REST routers
   and the WebSocket endpoint, and serves the built SPA's static files at `/`.
2. The frontend calls `POST /api/sessions` once on load to get a session ID (persisted in
   `localStorage` so a page refresh resumes the same session), then `POST /api/files/open` with
   a server-side file path to parse a trace and get a decimated preview.
3. Interactive operations that need low latency (dragging a crop line, a live filter-width
   slider, the measure tool) go over the `/ws/session/{id}` WebSocket rather than round-tripping
   through REST — see `web/ws/session.py` for the message protocol.
4. Every analysis button (step-find, WLC fit, velocity, PWD, kinetics, KDE, distributions, MSD)
   is a `POST /api/<name>` call into `web/api/analysis.py`, which does essentially nothing but
   unwrap the request, call straight into `analysis.*`, and wrap the result — see [Adding an
   analysis module](adding-analysis-module.md) for the exact pattern.

## Storage & auth

Session save/load (`POST /api/sessions/{id}/save`, `POST /api/sessions/load/{id}`) persists to
disk through a small abstraction designed for **local-first today, shared-server later**
without touching any of the business logic above it:

- **`storage.StorageBackend`** (a `Protocol`) formalizes the contract: save/load/list/delete a
  session's JSON state, and save/load named arrays too large for JSON.
- **`storage.LocalFilesystemStore`** is the only real implementation today — writes to
  `~/.salafleezers/sessions/<session_id>/`.
- **`storage.UserScopedStore`** wraps any backend, namespacing session IDs under
  `<user_id>/<session_id>` so multiple users' sessions can't collide or see each other's data —
  purely a path-prefixing decorator, no new storage engine.
- **`auth.get_current_principal`** is a FastAPI dependency resolving *who's calling*. With no
  `SFZ_AUTH_TOKEN` configured (the default), everyone resolves to one fixed anonymous
  principal — today's single-user behavior, unchanged. Setting `SFZ_AUTH_TOKEN` turns on a
  shared-secret bearer-token gate: anyone with the token is treated as one shared principal.
  This is intentionally minimal — a seam for a small shared-lab deployment behind a reverse
  proxy, not a full multi-user identity system — see the docstring in `web/auth.py` for exactly
  what it does and doesn't do.

The save/load routes compose these as `UserScopedStore(LocalFilesystemStore(), principal.user_id)`
— swapping in a real database- or S3-backed `StorageBackend`, or a real OAuth/SSO principal
resolver, means writing one new class each, with zero changes to the routes or to
`analysis/`.

## Frontend

Svelte 5 (runes) + Vite + TypeScript, plotting with [uPlot](https://github.com/leeoniya/uPlot)
(canvas-based — SVG can't keep up with 10⁵–10⁶-point traces panning/zooming at 60fps). The
`frontend/src/lib/api.ts`/`types.ts` client mirrors `web/schemas.py`'s pydantic models field for
field, so a backend schema change is a compile error in the frontend rather than a silent
runtime mismatch. Built assets are `force-include`d into the wheel at build time
(`pyproject.toml`) so an installed package works standalone — see
[Installation](../user-guide/installation.md).

## Data model

One canonical shape (`web/schemas.py`) is used by the REST API, the WebSocket protocol, and (by
construction, since the frontend's TypeScript types mirror it) the GUI — a `.dat`/`.h5`/`.mat`/
`.npz` trace, an API payload, and a GUI session state are the same shape everywhere, which is
what let the [violin/distribution-comparison panel](../user-guide/gui-walkthrough.md) treat
"multiple loaded files" as interchangeable groups with zero special-casing.
