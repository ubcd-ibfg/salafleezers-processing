# SalaFleezers Processing — Refactor & Expansion Roadmap

**Goal:** grow `salafleezers-processing` from a raw-data → force/extension pipeline into a
complete, MATLAB-free optical-tweezers analysis platform with three faces:

1. A **friendly CLI** (Typer + Rich).
2. A **polished interactive GUI** — a FastAPI backend + a React/Svelte SPA that replaces the
   custom MATLAB `DataGUIs` (the main reason the lab is stuck on MATLAB).
3. **Documentation** for users *and* developers, from the physics of optical tweezers through
   the maths and numerical methods behind every processing/analysis step.

**Decisions locked in for this plan**

| Decision | Choice |
|---|---|
| Frontend | FastAPI backend + SPA (**recommend Svelte + uPlot/WebGL**; React acceptable) |
| Deployment | **Local-first** (`sfz gui` → localhost), designed to deploy to a shared server later |
| Scope | **Full analysis parity** with `DataGUIs` (step-finding, WLC, velocity, PWD, dwell-times) |
| Packaging | `uv` throughout; single installable package + optional web extra |
| Numerics | Match MATLAB to <0.1% on real data; golden-file regression tests |

---

## 1. Where we are today

The current package (`src/salafleezers/`, ~2k LOC) already ports the **`RawDataProcessing`**
half of the MATLAB code:

- `io/reader.py` — binary `.dat` / `_fl` / `_pos` / `_grn` parser
- `calibration/` — power spectrum, Lorentzian models, `least_squares` fit
- `processing/` — offset, normalization, `pipeline.process_one`
- `fluorescence/apd.py`
- `cli/main.py` — `sfz inspect | calibrate | process` (currently **click**)

**Not yet ported** — the entire `DataGUIs/` analysis + interaction layer, which is the bulk of
day-to-day scientific work:

| MATLAB area | What it does | Target Python home |
|---|---|---|
| `PhageGUIv4.m` (1067 lines) | Master trace viewer: load `.mat`, filter/decimate, crop, measure, step overlays, kernel-density, "easy analyze" | `analysis` + GUI |
| `ForExtGUI_V2.m` (574) | Force–extension curve viewer + WLC fitting | `analysis.wlc` + GUI |
| `StepFind_KV/` | Kalafut–Visscher step detection (has C mex kernels) | `analysis.stepfind.kv` |
| `StepFind_HMM/` | HMM/Viterbi step detection | `analysis.stepfind.hmm` |
| `Velocity/` (`ppKV*`, `vdist*`) | Pause-free velocity, velocity distributions | `analysis.velocity` |
| `PairwiseDist/` | Pairwise-distance (PWD) step-size histograms + autocorr | `analysis.pwd` |
| `Fitting/` (`fitnexp`, `ngamdist`, dwell dists) | n-exponential / n-gamma dwell-time fitting | `analysis.kinetics` |
| `ForceExt/XWLC.m` | Extensible WLC extension↔contour conversion (3 methods) | `analysis.wlc` |
| `Plotting/`, `Helpers/` | violin, KDE, MSD, smoothing, cropping utilities | `analysis.stats` + GUI |

> Note: the README references `legacy/BLabOTMatlab/` but the MATLAB tree currently lives as a
> sibling directory. Phase 0 vendors or submodules it under `legacy/` so golden-file tests and
> docs can reference it by a stable path.

---

## 2. Target architecture

A single `uv`-managed repo, cleanly separated so the core science has **no** web/UI dependencies.

```
salafleezers-processing/
├── pyproject.toml            # optional-dependency extras: [gui], [docs], [dev]
├── uv.lock
├── legacy/BLabOTMatlab/      # vendored MATLAB reference (read-only)
├── src/salafleezers/
│   ├── constants.py
│   ├── io/                   # (exists) readers/writers  + new: session/project store
│   ├── calibration/          # (exists)
│   ├── processing/           # (exists)
│   ├── fluorescence/         # (exists)
│   ├── analysis/             # NEW — the DataGUIs port, pure & headless
│   │   ├── filters.py        #   windowFilter/smooth/decimate (move from utils)
│   │   ├── crop.py           #   crop/trim/measure primitives
│   │   ├── wlc.py            #   XWLC (3 methods) + fitForceExt
│   │   ├── stepfind/
│   │   │   ├── kv.py         #   Kalafut–Visscher (vectorized numpy / numba)
│   │   │   └── hmm.py        #   HMM + Viterbi step detection
│   │   ├── velocity.py       #   ppKV, sgolay differentiation, vdist
│   │   ├── pwd.py            #   pairwise distance, peak finding, autocorr
│   │   ├── kinetics.py       #   dwell-time fits (n-exp, n-gamma), MLE
│   │   └── stats.py          #   KDE, histograms, violin data, MSD
│   ├── cli/                   # Typer + Rich (replaces click)
│   └── web/                   # NEW — FastAPI app (import-optional)
│       ├── app.py            #   FastAPI factory, mounts SPA build
│       ├── api/              #   REST + WebSocket routers
│       ├── schemas.py        #   pydantic models (share types w/ frontend)
│       ├── sessions.py       #   in-memory + on-disk session state
│       └── storage.py        #   local-fs backend (server backend later)
├── frontend/                 # NEW — Svelte SPA (built assets served by FastAPI)
│   ├── package.json
│   └── src/ ... (viewer, plots, panels)
├── docs/                     # NEW — MkDocs Material (this file lives here)
└── tests/                    # unit + golden-file regression vs MATLAB
```

**Design rules**

- `analysis/` and `processing/` are **pure, headless, numpy-in/numpy-out**. No FastAPI, no
  plotting, no globals. Everything the GUI does, the CLI and a notebook can do too.
- The web layer is an **optional extra** (`pip install salafleezers-processing[gui]`); the core
  science installs and tests without it.
- One **canonical data model** (pydantic + dataclasses) shared by CLI, API, and stored files, so
  a `.mat`/`.h5` trace, an API payload, and a GUI session are the same shape.

---

## 3. Workstreams

### A. Packaging & CLI — Typer + Rich

- Migrate `cli/main.py` from **click → Typer**; keep command names/behavior stable
  (`inspect`, `calibrate`, `process`) so existing muscle memory and batch files still work.
- Rich upgrades: colored tables for calibration results, `rich.progress` bars for batch runs,
  `rich.traceback` for friendly errors, `--json` output mode for scripting.
- New commands mirroring the analysis modules so the CLI reaches parity with the GUI:
  `sfz stepfind`, `sfz wlc-fit`, `sfz velocity`, `sfz pwd`, `sfz gui` (launches the web app).
- `uv` polish: `[project.optional-dependencies]` extras (`gui`, `docs`, `dev`); `uvx sfz`
  entry point; `uv build` wheels; a `uv run` task list documented in the README.
- Config precedence: CLI flag > project config file (`sfz.toml`) > built-in defaults, so the
  MATLAB `DataOptsPopup` defaults become a versioned, discoverable config.

### B. Core library — complete the port (the science)

Port each `DataGUIs` numeric routine as a pure function with a docstring citing the MATLAB
source and the maths (see §4). Prefer vectorized numpy; reach for **numba** only where the
MATLAB used C mex kernels (KV `C_qe*.c`, PWD `acorr2mx.c`) and profiling shows a Python hot loop.

Priority order within this workstream: filters/crop → WLC → step-finding (KV then HMM) →
velocity → PWD → dwell-time kinetics → stats/KDE.

### C. FastAPI backend (local-first, server-ready)

- **App factory** `create_app()` returning a FastAPI instance; `sfz gui` runs it under uvicorn
  and opens the browser (or a `pywebview` shell for a native-feeling desktop window).
- **API surface** (REST for CRUD, WebSocket for live crop/measure/filter feedback on big traces):
  - `POST /api/files/open` → parse `.dat`/`.mat`/`.h5`, return metadata + downsampled preview
  - `GET  /api/traces/{id}?decimate=N&range=...` → server-side decimation so 10⁶-point traces
    stream as ~few-k-point payloads (this is what keeps the frontend "smooth")
  - `POST /api/stepfind`, `/api/wlc/fit`, `/api/velocity`, `/api/pwd`, `/api/kinetics/fit`
  - `WS   /ws/session/{id}` → interactive filter-width / crop-line / measurement updates
- **Storage abstraction** (`storage.py`): a `LocalFilesystemStore` now; interface leaves room
  for a server-side `UserScopedStore` (auth + isolation) later without touching business logic.
- **Sessions**: a session = loaded files + crops + fits + view state, serializable to disk so
  work survives a restart and is shareable as a file (the modern `GUIsettings.mat`).

### D. Frontend SPA — the polished GUI

Rebuild the two flagship GUIs as SPA views, feature-by-feature against the MATLAB originals.

- **Plotting:** use a canvas/WebGL library (**uPlot** or regl-based) rather than SVG — traces are
  10⁵–10⁶ points and must pan/zoom/crop at 60 fps. Server sends decimated data for the current
  viewport; client re-requests on zoom (level-of-detail streaming).
- **TraceViewer** (≙ `PhageGUIv4`): file slider, filter-width & decimation inputs, draggable crop
  lines, measure tool, step overlays, linked kernel-density side panel, comment field, export.
- **ForceExtensionViewer** (≙ `ForExtGUI_V2`): F–X curve with color-by-time, WLC fit overlay,
  editable persistence-length / stretch-modulus / offsets, residuals subplot.
- **Analysis panels**: step-finding (KV penalty / HMM states), velocity, PWD histogram, dwell-time
  fits — each a panel that calls its API endpoint and overlays results on the trace.
- **Polish:** keyboard shortcuts, undo/redo on crops, dark/light theme, responsive layout,
  session save/load. This is where we beat the MATLAB UX, not just match it.

### E. Documentation (MkDocs Material)

Three books under one site, versioned with the code:

1. **User Guide** — install (`uv`), CLI reference (auto-gen from Typer), GUI walkthrough with
   screenshots, batch-file format, data-format reference (already drafted in the README).
2. **Physics & Methods** — the "why": optical trapping basics, QPD signals, trap stiffness,
   the timeshared/dual-trap geometry, force & extension definitions, WLC/XWLC models,
   step-finding theory (KV information criterion, HMM/Viterbi), velocity & pause analysis,
   pairwise-distance method, dwell-time kinetics. Equations in KaTeX, figures generated from
   real pipeline output.
3. **Developer Guide** — architecture (this doc), the MATLAB→Python mapping (extend
   `COMPARISON.md`), how to add an analysis module, API reference (auto-gen from docstrings +
   OpenAPI), testing & golden-file strategy, contribution workflow.

### F. Validation — trust the port

- **Golden-file regression:** run representative MATLAB routines once, save inputs+outputs as
  fixtures under `tests/golden/`, and assert the Python port matches within tolerance
  (the <0.1% / <1%-at-edges budgets already documented in `COMPARISON.md`).
- Property-based tests (Hypothesis) for filters/crop/reshape invariants.
- CI: `uv run pytest`, `ruff`, `mypy`, plus a frontend `vitest`/Playwright smoke test and a
  docs build check.

---

## 4. Analysis port matrix (MATLAB → Python)

| MATLAB | Method / maths | Python target | Numerical notes |
|---|---|---|---|
| `windowFilter`, `smooth`, `bilFilter` | boxcar / triangular / bilateral moving average, block decimation | `analysis/filters.py` | `scipy.ndimage.uniform_filter1d`; watch edge-kernel diff (§6 of COMPARISON) |
| `XWLC.m` | Extensible worm-like chain, 3 formulations (basic, legacy, Wikipedia interpolation) | `analysis/wlc.py::xwlc` | vectorized over F; guard F≤0; default kT=4.14 pN·nm, P=50 nm, S=900 pN |
| `fitForceExt.m`, `getFCs_fx.m` | least-squares fit of P, S, offsets to an F–X curve | `analysis/wlc.py::fit_force_ext` | `scipy.optimize.least_squares`, `trf` |
| `BatchKV`, `AFindStepsV5`, `C_qe*.c` | Kalafut–Visscher: greedy step insertion + counter-fit, penalty ∝ SIC/BIC | `analysis/stepfind/kv.py` | numba for the χ² update loop; expose `penalty_factor` |
| `fitVitterbi*`, `findStepHMM*` | Gaussian-emission HMM, Viterbi decode of discrete step states | `analysis/stepfind/hmm.py` | `hmmlearn` or a small custom Viterbi; seed from KV |
| `ppKVv4`, `sgolaydiff`, `vthresh` | Savitzky–Golay differentiation → velocity, pause thresholding | `analysis/velocity.py` | `scipy.signal.savgol_filter(deriv=1)` |
| `vdist`, `vdist_force` | velocity histograms vs force | `analysis/velocity.py` | `np.histogram`, weighted |
| `calcPWDV1b`, `sumPWD*`, `findPWDpeaks`, `acorr2` | pairwise-distance histogram of a trace → step size; autocorrelation | `analysis/pwd.py` | FFT autocorr; peak find via `scipy.signal.find_peaks` |
| `fitnexp*`, `ngamdist*`, `phage_dwelldist` | n-exponential / n-gamma dwell-time distributions, MLE + bootstrap | `analysis/kinetics.py` | `scipy.optimize.minimize` (neg-log-lik), `scipy.stats` |
| `kdf.m`, `violin.m`, `nhistc`, `msd*` | kernel density, violin data, histograms, mean-squared displacement | `analysis/stats.py` | `scipy.stats.gaussian_kde`, `msdFFT` via FFT |

---

## 5. Phased roadmap

Each phase is shippable and independently useful.

**Phase 0 — Foundation (repo hygiene)**
Vendor `legacy/BLabOTMatlab/`; add `[gui]`/`[docs]`/`[dev]` extras; stand up MkDocs skeleton;
create `tests/golden/` harness; move `utils/signal.py` → `analysis/filters.py`.

**Phase 1 — CLI & pipeline polish**
click → Typer/Rich migration; `--json` mode; progress bars; `sfz.toml` config; harden existing
pipeline with more golden-file tests. *Deliverable: a noticeably nicer `sfz`.*

**Phase 2 — Core analysis port**
Port filters/crop, WLC, KV step-finding, velocity, PWD, HMM, dwell-time kinetics as pure
functions with tests. Add matching CLI subcommands. *Deliverable: full analysis available
headless via CLI/library — MATLAB no longer needed for the numbers.*

**Phase 3 — FastAPI backend**
App factory, storage/session abstractions, REST+WS endpoints wrapping Phase-2 functions,
viewport-decimation streaming. OpenAPI docs auto-published. *Deliverable: `sfz gui` serves an
API; testable with curl/Playwright.*

**Phase 4 — Frontend SPA (TraceViewer + ForceExtensionViewer)**
Svelte app, WebGL plotting, crop/measure/filter interactions, step & WLC overlays, session
save/load, theming. Package the built assets into the wheel. *Deliverable: the GUI that
replaces `PhageGUIv4` and `ForExtGUI_V2`.*

**Phase 5 — Analysis panels & UX polish**
Wire velocity / PWD / dwell-time panels into the SPA; keyboard shortcuts, undo/redo,
export-to-figure. *Deliverable: full GUI parity + better-than-MATLAB UX.*

**Phase 6 — Documentation completion & server-ready**
Finish the Physics & Methods and Developer books; add the server storage backend + auth stub
behind the existing abstraction; containerize for optional shared-lab deployment.

---

## 6. Risks & open decisions

- **Svelte vs React** — recommend Svelte (less boilerplate, great for a canvas-heavy scientific
  app); React is fine if the lab already knows it. *Pick before Phase 4.*
- **Native window vs browser tab** — `pywebview` gives a desktop-app feel for the local case;
  plain browser is simpler. Low-cost to support both.
- **Step-finding fidelity** — KV/HMM ports must be validated against MATLAB on real traces
  (golden files); greedy/optimizer paths can diverge on marginal data. Highest-risk numerics.
- **C mex kernels** (`C_qe*.c`, `acorr2mx.c`) — reimplement in numba/numpy rather than compiling
  C; validate equivalence.
- **Large files** — multi-hour recordings are big; rely on server-side decimation + HDF5 chunked
  reads so the frontend never loads a full trace.
- **`.mat` compatibility** — keep `--save-format mat` and add `.mat` *reading* for legacy trace
  files so existing datasets open in the new GUI on day one.

---

*Next concrete step:* Phase 0 + the Typer/Rich CLI migration (Phase 1), which is self-contained
and immediately improves the tool while the analysis port proceeds in parallel.
