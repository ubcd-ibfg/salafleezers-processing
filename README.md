# salafleezers-processing

![SalaFleezers logo](docs/assets/logo/salafleezers_logo_small.png)

**SalaFleezer-processing** is a Python toolkit for turning SalaFleezer optical-tweezers acquisitions into calibrated, analysis-ready force spectroscopy data.

The SalaFleezer instrument records raw QPD voltage traces in binary `.dat` files. This repository provides the end-to-end processing workflow: loading and validating raw traces, calibrating trap stiffness with Lorentzian power-spectrum fitting, and converting detector signals into force (pN) and extension (nm) outputs for downstream single-molecule analysis. The project is organized into three pillars:

- A **CLI** (`sfz`) — inspect, calibrate, batch-process, and run every analysis routine headlessly.
- A **web GUI** (`sfz gui`) — a FastAPI backend + Svelte SPA for interactively browsing traces, calibrating trap stiffness and converting raw acquisitions into force/extension, fitting force-extension curves, and running every analysis routine, with browser upload as the primary way to get data in.
- A **documentation site** — user guide, physics & methods, and developer guide.

---

## Requirements

- Python ≥ 3.13
- [uv](https://docs.astral.sh/uv/) (package manager)
- Node.js ≥ 20 — only needed if you're on a **built wheel/PyPI install** (the compiled SPA ships
  inside it) *and* don't want to touch the frontend. A `git clone` + `uv sync` checkout has no
  built copy and **requires** an `npm run build` before `sfz gui` will serve anything — see
  [Launch the interactive web GUI](#5-launch-the-interactive-web-gui) below.

---

## Installation

```bash
git clone https://github.com/ubcd-ibfg/salafleezers-processing
cd salafleezers-processing

# Install core dependencies (creates .venv automatically)
uv sync

# Install with the web GUI (FastAPI + uvicorn)
uv sync --extra gui

# Install with docs tooling (MkDocs Material)
uv sync --extra docs

# Install with dev tools (pytest, ruff, mypy, hypothesis)
uv sync --extra dev
```

---

## Quickstart

### 1. Inspect a raw data file

Print the header metadata of any `.dat` file without loading the full signal:

```bash
uv run sfz inspect path/to/230415_001.dat
```

Example output:

```text
File: 230415_001.dat
----------------------------------------
  filever             : 9.0
  Fsampraw            : 187500.0
  Fsamp               : 1.6e-05          ← sample interval (s); Fs = 62500 Hz
  nChannels           : 13
  channelID           : 2               ← SalaFleezer default (13-channel layout)
  datatype            : 0               ← regular data (0=data, 1=cal, 2=AOM scan)
  initMHz             : [60. 70. ...]   ← initial trap positions (MHz)
  extraData           : 3               ← FL + pos sidecars present
```

---

### 2. Calibrate a single file

Run a Lorentzian power spectrum calibration on a calibration `.dat` file:

```bash
uv run sfz calibrate path/to/230415_003.dat
```

Add `--plot` to display the power spectrum and fitted Lorentzian:

```bash
uv run sfz calibrate path/to/230415_003.dat --plot
```

Example output:

```text
Calibrating 230415_003.dat  (Fs = 62500 Hz)
--------------------------------------------------
  AX: fc =    982.3 Hz  |  alpha =   187.4 nm/V  |  kappa = 0.0583 pN/nm
  BX: fc =   1041.7 Hz  |  alpha =   175.2 nm/V  |  kappa = 0.0618 pN/nm
  AY: fc =    874.1 Hz  |  alpha =   199.0 nm/V  |  kappa = 0.0519 pN/nm
  BY: fc =    923.5 Hz  |  alpha =   188.6 nm/V  |  kappa = 0.0548 pN/nm
```

---

### 3. Process a batch of files

Create a plain-text batch file:

```text
# batch.txt
230415
1   2   3   first tether
4   2   3   second tether
7   2   3   third tether
```

- **Line 1:** date string `YYMMDD`
- **Subsequent lines:** `dat_num  off_num  cal_num  [comment]`
  - `dat_num` — data file number
  - `off_num` — offset file number (bead interaction baseline)
  - `cal_num` — calibration file number (free bead in trap)

Run the batch:

```bash
uv run sfz process batch.txt --data-dir path/to/data/ --output-dir path/to/output/
```

Outputs one `ForceExtension230415_NNN.h5` file per data file. Use `--save-format mat` to write MATLAB-compatible `.mat` files instead.

---

### 4. Run analysis headlessly

Each analysis routine is available as its own subcommand, operating on an already-processed HDF5/npz file (the output of `sfz process`):

```bash
# Step-finding (Kalafut-Visscher or HMM) on the extension channel
uv run sfz stepfind ForceExtension230415_001.h5 --algorithm kv --pen-factor 2.0

# Fit a worm-like-chain model to a force-extension curve
uv run sfz wlc-fit ForceExtension230415_001.h5 --method marko_siggia

# Velocity distribution (Savitzky-Golay differentiation)
uv run sfz velocity ForceExtension230415_001.h5 --window 21 --polyorder 2

# Pairwise-distance step-size histogram
uv run sfz pwd ForceExtension230415_001.h5 --bins 200
```

Add `--json` to any of these for machine-readable output. Run `uv run sfz <command> --help` for the full option list — see the [CLI reference](docs/user-guide/cli-reference.md) for all defaults.

---

### 5. Launch the interactive web GUI

Requires the `gui` extra (`uv sync --extra gui`).

The GUI backend serves a prebuilt Svelte SPA — it does **not** build it for you. On a `git
clone` checkout, `frontend/dist/` doesn't exist yet, so build it once first (needs Node ≥ 20):

```bash
cd frontend
npm ci
npm run build
cd ..
```

(A built wheel/PyPI install already embeds the compiled SPA, so this step only applies to
source checkouts. Skipping it doesn't error — `sfz gui` starts fine, but every route 404s and
the browser tab just stays blank.)

```bash
uv run sfz gui
```

This starts a local FastAPI server (default `http://127.0.0.1:8765`) serving the Svelte SPA — drag files or a folder onto the page to load data (no path to type, no server-side configuration required), then a **TraceViewer** (filter/crop/measure, step overlays, undo/redo, PNG export, keyboard shortcuts) and a **ForceExtensionViewer** (WLC fit overlay + residuals), plus tabbed analysis panels for velocity, pairwise distance, dwell-time kinetics, kernel density, and violin/MSD comparisons. Sessions (loaded files, crops, fits, view state) save/load to disk and survive a restart; uploaded data lives in a durable per-user workspace under `~/.salafleezers/uploads/`.

```text
Options:
  --host          Bind address                 [default: 127.0.0.1]
  --port          Bind port                     [default: 8765]
  --no-browser    Don't auto-open a browser tab
  --data-root     Confine legacy path-based /api/files/open to a directory tree
                  (unset = unrestricted; doesn't affect uploads, which are
                  always confined to the caller's own workspace)
  --allow-origin  CORS origin to allow (repeatable)
  --rate-limit    Max requests per client IP per minute (unset = unlimited)
  --log-level     Python logging level          [default: warning]
```

Auth for a small shared-lab deployment is controlled by two environment variables (not CLI flags, so neither appears in shell history):

- `SFZ_AUTH_TOKEN` — a shared-secret bearer-token gate. Unset means anonymous single-user mode; set it and every request needs a matching `Authorization: Bearer <token>` header (the SPA prompts for it). This *authenticates* but does not *identify* — everyone with the token shares one workspace.
- `SFZ_TRUSTED_USER_HEADER` — the name of a header set by an authenticating reverse proxy (oauth2-proxy, Authelia, Cloudflare Access) carrying the caller's identity. Set this to give each person their own isolated sessions and upload workspace. Only enable it behind a proxy that overwrites the header rather than forwarding a client-supplied value.

See [`src/salafleezers/web/auth.py`](src/salafleezers/web/auth.py).

To serve the GUI under a path prefix instead of the domain root (e.g. behind a reverse proxy at `https://lab.example.org/salafleezer/`), set `FRONTEND_BASE_PATH` (e.g. `/salafleezer`) *before* building the frontend — it's baked into the compiled JS at build time (Vite's `base` config) and mirrored by the backend, which mounts the SPA, `/api`, and `/ws` under the same prefix instead of at `/`. See [`src/salafleezers/web/app.py`](src/salafleezers/web/app.py)'s `resolve_frontend_base_path`.

See the [GUI walkthrough](docs/user-guide/gui-walkthrough.md) for a full tour with screenshots.

---

### 6. Run with Docker

A multi-stage `Dockerfile` (Node build → Python runtime) and `docker-compose.yml` are provided for a containerized deployment. Nothing is required to get a usable instance running — data goes in via upload:

```bash
docker compose up --build
```

The GUI is then reachable at `http://localhost:8765` by default (override the host port with `SFZ_PORT` in a `.env` file, see `.env.example`). Sessions and uploaded data persist in a named volume (`sfz-sessions`) across container replacement. Set `SFZ_AUTH_TOKEN`/`SFZ_TRUSTED_USER_HEADER` in the environment to harden a shared deployment (see `.env.example`).

To reach it under a path prefix instead of the root (e.g. `http://localhost:8765/salafleezer/`, for a reverse proxy that forwards the path through unstripped), set `FRONTEND_BASE_PATH` in `.env` and rebuild:

```bash
# .env
FRONTEND_BASE_PATH=/salafleezer
```

```bash
docker compose up --build
```

The rebuild is required because the value is baked into the compiled frontend at image-build time (`docker-compose.yml` passes it as both a build arg, for the Node build stage, and a runtime env var, for the Python backend, from the same `.env` value) — it isn't picked up by just restarting the container.

Behind a reverse proxy under a hostname other than `localhost`/`127.0.0.1`, also set `SFZ_ALLOW_ORIGIN` (comma-separated, e.g. `https://lab.example.org`) in `.env` — otherwise the page loads and REST calls work, but the app's own WebSocket-origin check rejects the live filter/crop/measure socket. The proxy itself also needs to forward WebSocket upgrades (`Upgrade`/`Connection` headers), which most reverse proxies don't do by default for a plain `location`/`proxy_pass` block. See [`nginx-salafleezers.conf.example`](nginx-salafleezers.conf.example) for a ready-to-paste nginx `location` block with all of this wired up.

To also reach files already on the host by server path (the legacy flow, useful for scripted workflows), copy `docker-compose.override.yml.example` to `docker-compose.override.yml` and set `SFZ_DATA_DIR`.

---

## Using as a Python library

```python
from pathlib import Path
from salafleezers.io.reader import read_dat
from salafleezers.processing.pipeline import ProcessingOptions, process_one

# Read a raw .dat file
dat = read_dat("path/to/230415_001.dat")
print(dat.meta["Fs"])          # sampling frequency (Hz)
print(dat.channels["AX"])      # trap-A X-axis signal (float32, volts)
print(dat.channels["AS"])      # trap-A sum channel (float32, volts)
print(dat.t1f)                 # trap 1 frequency (MHz), if _pos sidecar present
print(dat.apd1)                # APD 1 photon counts, if _fl sidecar present

# Full processing pipeline
opts = ProcessingOptions(
    ra_a=500,          # bead radius, nm
    ra_b=500,
    f_min=100,         # calibration fit range, Hz
    f_max=20000,
    normalize=True,    # divide by QPD sum
    verbose=True,
)

result = process_one(
    path="path/to/data/",
    nums=(1, 2, 3),    # (dat_num, off_num, cal_num)
    mmddyy="230415",
    opts=opts,
)

# Output arrays
print(result.time)       # seconds
print(result.force)      # pN  (differential, √(ΔFx² + ΔFy²))
print(result.extension)  # nm  (bead-to-bead distance)
print(result.force_ax)   # pN  (trap A, X axis only)
print(result.cal["AX"].kappa)  # trap stiffness, pN/nm
print(result.cal["AX"].alpha)  # position sensitivity, nm/V

# Save to HDF5
from salafleezers.io.writer import save
save("output/ForceExtension230415_001", result.to_dict(), fmt="hdf5")
```

### Calibration only

```python
from salafleezers.calibration.fit import calibrate
import numpy as np

# data: normalised 1-D signal (volts), fs: sampling frequency (Hz)
cal = calibrate(data, fs=62500.0, ra=500.0, f_min=100.0, f_max=20000.0)

print(f"fc    = {cal.fc:.1f} Hz")
print(f"alpha = {cal.alpha:.1f} nm/V")
print(f"kappa = {cal.kappa:.4f} pN/nm")
print(f"D     = {cal.D:.3e} V²/Hz")
```

### Reading fluorescence data

```python
from salafleezers.fluorescence.apd import downsample_apd, apd_rate

dat = read_dat("230415_001.dat")          # reads _fl sidecar automatically

apd_dt = dat.meta["apddt"]               # APD sample interval (s)
qpd_dt = float(dat.meta["Fsamp"])        # QPD sample interval (s)

# Downsample APD to match QPD time resolution
counts, apd_time = downsample_apd(dat.apd1, apd_dt, target_dt=qpd_dt)
rate = apd_rate(counts, bin_dt=qpd_dt)   # photons/s
```

### Analysis modules (headless, no web/CLI deps)

`salafleezers.analysis` is pure NumPy/SciPy — everything the CLI and GUI do, a notebook can do too:

```python
from salafleezers.analysis import filters, crop, wlc, velocity, pwd, kinetics, stats
from salafleezers.analysis.stepfind import kv, hmm

# e.g. Kalafut-Visscher step-finding on an extension trace
steps = kv.find_steps(extension, pen_factor=2.0)

# e.g. worm-like-chain fit
fit = wlc.fit_force_ext(force, extension, method="marko_siggia")
```

See the [Physics & Methods](docs/physics/optical-trapping.md) book for the maths behind each routine, and the [Developer Guide](docs/developer/architecture.md) for how to add a new analysis module.

---

## Project structure

```text
salafleezers-processing/
├── pyproject.toml              — package metadata, [gui]/[docs]/[dev] extras
├── main.py                     — thin entry point (delegates to sfz CLI)
├── README.md                   — this file
├── Dockerfile / docker-compose.yml  — containerized deployment (multi-stage build)
├── docker-compose.override.yml.example  — optional legacy server-path file access
├── mkdocs.yml                  — MkDocs Material site config
├── docs/                       — User Guide / Physics & Methods / Developer Guide
├── frontend/                   — Svelte 5 + Vite + TS SPA (uPlot plotting)
│   ├── dist/                   — built assets, force-included into the wheel
│   └── src/lib/
│       ├── data/                — upload intake: dropzone, upload queue, dataset rail
│       ├── ui/                  — shared primitives (RunButton/useRun, Card, Tabs)
│       ├── theme/               — theme-aware chart color resolution
│       └── panels/              — the six analysis tabs
├── src/salafleezers/
│   ├── constants.py            — instrument constants, channel maps
│   ├── io/
│   │   ├── reader.py           — binary .dat / _fl / _pos / _grn parser
│   │   └── writer.py           — HDF5 / npz / mat output
│   ├── calibration/
│   │   ├── power_spectrum.py   — FFT + spectral binning
│   │   ├── lorentzian.py       — Lorentzian PSD models
│   │   └── fit.py              — lorentz_guess + scipy optimizer
│   ├── processing/
│   │   ├── offset.py           — trap-delta offset computation
│   │   ├── normalize.py        — QPD sum normalization + offset subtraction
│   │   └── pipeline.py         — full dat/off/cal pipeline orchestrator
│   ├── fluorescence/
│   │   └── apd.py              — APD photon count processing
│   ├── analysis/                — pure-NumPy analysis library (no web/CLI deps)
│   │   ├── filters.py          — windowFilter/smooth/decimate
│   │   ├── crop.py             — crop/trim/measure primitives
│   │   ├── wlc.py              — XWLC models + force-extension fitting
│   │   ├── stepfind/
│   │   │   ├── kv.py           — Kalafut-Visscher step detection
│   │   │   └── hmm.py          — HMM/Viterbi step detection
│   │   ├── velocity.py         — Savitzky-Golay differentiation, velocity distributions
│   │   ├── pwd.py              — pairwise-distance step-size histograms
│   │   ├── kinetics.py         — dwell-time fitting (n-exp/n-gamma)
│   │   └── stats.py            — KDE, violin data, MSD
│   ├── cli/
│   │   └── main.py             — sfz inspect/calibrate/process/stepfind/wlc-fit/velocity/pwd/gui
│   └── web/                     — FastAPI backend (optional `gui` extra)
│       ├── app.py              — app factory, mounts the built SPA
│       ├── api/                 — REST routers (files, uploads, sessions, traces, analysis, calibration)
│       ├── ws/session.py       — WebSocket for live filter/crop/measure/decimate
│       ├── schemas.py          — pydantic request/response models
│       ├── sessions.py         — session state: durable file refs + a byte-bounded array cache
│       ├── workspace.py        — per-user durable upload storage (browser drag-and-drop intake)
│       ├── storage.py          — session persistence backends (local filesystem, user-scoped)
│       └── auth.py             — anonymous-by-default / bearer-token / proxy-identity auth
└── tests/                       — unit tests + tests/golden/ numerical regression fixtures
```

---

## Running tests

```bash
uv run pytest               # run all tests
uv run pytest -v            # verbose output
uv run pytest --cov=src     # with coverage report
```

The suite covers the I/O, calibration, processing, analysis, CLI, and web (REST + WebSocket)
layers, plus upload intake and multi-user isolation. Most tests use synthetic `.dat` fixtures
generated entirely in memory — no real instrument files required. `tests/golden/` additionally
checks numerical parity against reference outputs generated independently under GNU Octave; see
[Testing & golden files](docs/developer/testing-golden-files.md) for how to regenerate fixtures
and the known coverage gaps (HMM, velocity, PWD, kinetics, and the calibration/processing
pipeline aren't golden-tested yet).

---

## Documentation

The full documentation site (MkDocs Material) covers installation, CLI reference, GUI walkthrough, the physics behind every analysis routine, and developer/architecture docs:

```bash
uv sync --extra docs
uv run mkdocs serve                    # http://127.0.0.1:8000
uv run mkdocs serve -a 127.0.0.1:8001  # pick a different port if 8000 is already in use
```

---

## Data file format reference

SalaFleezer `.dat` files are big-endian binary with this layout:

```text
float64        hdrlen        — number of header doubles
float64 × N    hdr           — header fields (see below)
float64        cmtlen        — comment byte count
char × M       cmt           — ASCII comment string
int16 × K      data          — interleaved QPD channels (nch × nsamples, column-major)
```

Key header fields (0-based index):

| Index | Field | Description |
| --- | --- | --- |
| 0 | `filever` | File format version (must be ≥ 9) |
| 1 | `Fsampraw` | Raw ADC sampling rate (Hz) |
| 2 | `Fsamp` | Output sample interval (s); `Fs = 1/Fsamp` |
| 3 | `nChannels` | Number of interleaved channels |
| 4 | `channelID` | Channel layout selector (2 = SalaFleezer default) |
| 5 | `datatype` | 0 = regular, 1 = calibration, 2 = AOM scan, 3 = MCL scan |
| 6–11 | `initMHz` | Initial trap positions (MHz) |
| 12 | `extraData` | Bitmask: bit 0 = `_fl` saved, bit 1 = `_pos` saved |

Associated sidecar files (same stem, same directory):

| File | Format | Content |
| --- | --- | --- |
| `_fl.dat` | big-endian uint32 | Interleaved APD1/APD2 photon counts |
| `_pos.dat` | big-endian uint64 | DDS trap frequencies → MHz via `× 49.152×6 / 2⁴⁸` |
| `_grn.dat` | big-endian float64 | Green laser status (4 channels) |

See [Data formats](docs/user-guide/data-formats.md) for the full reference, including processed HDF5/npz/mat output layouts.

---

## Dependencies

| Package | Purpose |
| --- | --- |
| `numpy ≥ 2.0` | Array math, binary I/O, FFT |
| `scipy ≥ 1.14` | `least_squares`, `interp1d`, `savemat` |
| `h5py ≥ 3.11` | HDF5 output (primary format) |
| `typer ≥ 0.12` | CLI (`sfz` command) |
| `rich ≥ 13.0` | CLI tables, progress bars, tracebacks |

Optional (`[gui]` extra):

| Package | Purpose |
| --- | --- |
| `fastapi ≥ 0.111` | Web backend (`sfz gui`) |
| `uvicorn[standard] ≥ 0.30` | ASGI server |
| `websockets ≥ 12.0` | Live trace interaction |
| `pydantic ≥ 2.7` | API request/response schemas |
| `matplotlib ≥ 3.9` | Power spectrum plots (`--plot` flag) |
| `python-multipart ≥ 0.0.9` | Multipart parsing for browser file uploads |

Optional (`[docs]` extra): `mkdocs-material`, `mkdocstrings[python]`.
Optional (`[dev]` extra): `pytest`, `pytest-cov`, `pytest-asyncio`, `httpx`, `ruff`, `mypy`, `hypothesis`.

The Svelte SPA in `frontend/` has its own `package.json` (Svelte 5, Vite, TypeScript, uPlot) — see [frontend/README.md](frontend/README.md).

---

## License

Released under the **GNU General Public License v3**.
