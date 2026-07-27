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
    ├── api/              —   REST routers (sessions, files, uploads, traces, analysis)
    ├── ws/               —   WebSocket session protocol (live filter/crop/measure)
    ├── schemas.py        —   pydantic models shared by REST + WS + (conceptually) the frontend
    ├── sessions.py       —   session state: durable FileRef/document + a byte-bounded ArrayCache
    ├── workspace.py      —   per-user durable upload storage (browser drag-and-drop intake)
    ├── storage.py        —   session-document disk persistence, pluggable backend
    └── auth.py           —   principal resolution (anonymous / bearer-token / proxy-identity)

frontend/                — Svelte 5 + Vite + TypeScript SPA, built separately with npm
```

**The one rule that matters most:** `analysis/` and `processing/` never import from `web/` or
`cli/`. Every number the GUI shows you, the CLI can also print, and a notebook can also compute
by importing the same function — there is exactly one implementation of "how do you fit a WLC
curve" or "how does Kalafut-Visscher decide to add a step," not one for the GUI and a
subtly-different one for the CLI. This is also what makes [golden-file
testing](testing-golden-files.md) meaningful: a fixture generated once against an independently
computed reference validates the analysis function directly, and every caller (CLI, API, GUI)
inherits that correctness for free.

## Request flow (web GUI)

1. `sfz gui` calls `web.app.create_app()`, which builds a FastAPI app, mounts the REST routers
   and the WebSocket endpoint, and serves the built SPA's static files at `/`.
2. The frontend calls `POST /api/sessions` once on load to get a session ID (persisted in
   `localStorage` so a page refresh resumes the same session). Data gets in via
   `POST /api/uploads` + `POST /api/uploads/{id}/files` (one request per file, streamed into a
   durable per-user workspace — see `web/workspace.py`), then `POST /api/files/open` with a
   `{dataset_id, relative_path}` reference to parse a trace and get a decimated preview. The
   same endpoint also accepts a bare server path, kept for session-reload and scripted callers.
3. Interactive operations that need low latency (dragging a crop line, a live filter-width
   slider, the measure tool) go over the `/ws/session/{id}` WebSocket rather than round-tripping
   through REST — see `web/ws/session.py` for the message protocol. Browsers can't attach an
   `Authorization` header to a WS handshake, so the socket authenticates with a short-lived
   single-use ticket obtained from `POST /api/ws-ticket` instead.
4. Every analysis button (step-find, WLC fit, velocity, PWD, kinetics, KDE, distributions, MSD)
   is a `POST /api/<name>` call into `web/api/analysis.py`, which does essentially nothing but
   unwrap the request, call straight into `analysis.*`, and wrap the result — see [Adding an
   analysis module](adding-analysis-module.md) for the exact pattern.

## Session state, storage & auth

A session's *durable document* (which files are loaded, by reference; crops; cached analysis
results) is separate from the *array cache* (the parsed numpy arrays themselves):

- **`sessions.FileRef`** is a re-resolvable pointer to one file's bytes — either
  `{kind: "dataset", dataset_id, relative_path}` (an uploaded file, confined to its owner's
  workspace) or `{kind: "path", path}` (a server path). `Session.get_file()` resolves a ref
  through `sessions.ArrayCache`, a process-wide LRU cache bounded by total bytes rather than by
  session or file count, transparently re-parsing on a cache miss. Evicting an entry is never
  destructive — it's derived state, not the source of truth.
- **`storage.StorageBackend`** (a `Protocol`) formalizes the session-document persistence
  contract: save/load/list/delete a session's JSON state (file refs, crops, cached results).
  **`storage.LocalFilesystemStore`** is the only real implementation today, writing to
  `~/.salafleezers/sessions/<session_id>/`; **`storage.UserScopedStore`** wraps any backend,
  namespacing IDs under `<user_id>/<session_id>` so sessions can't collide across principals.
- **`workspace.WorkspaceStore`** is the equivalent for uploaded bytes, at
  `~/.salafleezers/uploads/<user_id>/<dataset_id>/` — quota-enforced while streaming, with
  sidecar-completeness checked against each `.dat` header on finalize.
- **`auth.get_current_principal`** is a FastAPI dependency resolving *who's calling*, in three
  modes: anonymous by default; a shared-secret bearer token (`SFZ_AUTH_TOKEN`) that
  authenticates but doesn't distinguish callers; or a header set by an authenticating reverse
  proxy (`SFZ_TRUSTED_USER_HEADER`) giving each caller a real, distinct identity — only honored
  when that env var is explicitly configured, since trusting a client-settable header by default
  would be an auth bypass. See the docstring in `web/auth.py` for exactly what each mode does
  and doesn't do.

Swapping in a database- or object-store-backed `StorageBackend`/`WorkspaceStore`, or a real
OIDC principal resolver, means writing one new class each, with zero changes to the routes or to
`analysis/`. What isn't yet behind such a seam: `sessions.SessionManager` itself is an in-memory,
process-local singleton, so a multi-worker deployment isn't safe today — see the note in
`sessions.py`.

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
construction, since the frontend's TypeScript types mirror it) the GUI — a `.dat`/`.h5`/`.npz`
trace (`.mat` is currently write-only, produced by `sfz process --save-format mat` but not
readable by the GUI), an API payload, and a GUI session state are the same shape everywhere, which is
what let the [violin/distribution-comparison panel](../user-guide/gui-walkthrough.md) treat
"multiple loaded files" as interchangeable groups with zero special-casing.
