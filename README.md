# salafleezers-processing

**SalaFleezer-processing** is a Python toolkit for turning SalaFleezer optical-tweezers acquisitions into calibrated, analysis-ready force spectroscopy data.

The SalaFleezer instrument records raw QPD voltage traces in binary `.dat` files. This repository provides the end-to-end processing workflow: loading and validating raw traces, calibrating trap stiffness with Lorentzian power-spectrum fitting, and converting detector signals into force (pN) and extension (nm) outputs for downstream single-molecule analysis. The project is organized into three pillars:

- A **CLI** (`sfz`) — inspect, calibrate, batch-process, and run every analysis routine headlessly.
- A **web GUI** (`sfz gui`) — a FastAPI backend + Svelte SPA trace/force-extension viewer that replaces the MATLAB `DataGUIs`.
- A **documentation site** — user guide, physics & methods, and developer guide.

> See [COMPARISON.md](COMPARISON.md) for a full table of MATLAB → Python library changes and their trade-offs, and [docs/ROADMAP.md](docs/ROADMAP.md) for the phased build-out (all 6 phases complete).

---

## Requirements

- Python ≥ 3.13
- [uv](https://docs.astral.sh/uv/) (package manager)
- Node.js ≥ 20 (only if you want to rebuild the frontend; a built copy ships in the wheel)

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

Create a plain-text batch file (same format as the original MATLAB `AProcessDataV2.m`):

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

Each analysis routine ported from `DataGUIs` is available as its own subcommand, operating on an already-processed HDF5/npz file (the output of `sfz process`):

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

Requires the `gui` extra (`uv sync --extra gui`):

```bash
uv run sfz gui
```

This starts a local FastAPI server (default `http://127.0.0.1:8765`) serving the Svelte SPA — a **TraceViewer** (filter/crop/measure, step overlays, undo/redo, PNG export, keyboard shortcuts) and a **ForceExtensionViewer** (WLC fit overlay + residuals), plus tabbed analysis panels for velocity, pairwise distance, dwell-time kinetics, kernel density, and violin/MSD comparisons. Sessions (loaded files, crops, fits, view state) save/load to disk and survive a restart.

```text
Options:
  --host          Bind address                 [default: 127.0.0.1]
  --port          Bind port                     [default: 8765]
  --no-browser    Don't auto-open a browser tab
  --data-root     Confine /api/files/open to a directory tree (unset = unrestricted)
  --allow-origin  CORS origin to allow (repeatable)
  --rate-limit    Max requests per client IP per minute (unset = unlimited)
  --log-level     Python logging level          [default: warning]
```

Auth for a small shared-lab deployment is controlled by the `SFZ_AUTH_TOKEN` environment variable (not a CLI flag, so it never appears in shell history): unset means anonymous single-user mode; set it and every request needs a matching `Authorization: Bearer <token>` header. See [`src/salafleezers/web/auth.py`](src/salafleezers/web/auth.py).

See the [GUI walkthrough](docs/user-guide/gui-walkthrough.md) for a full tour with screenshots.

---

### 6. Run with Docker

A multi-stage `Dockerfile` (Node build → Python runtime) and `docker-compose.yml` are provided for a containerized deployment:

```bash
export SFZ_DATA_DIR=/path/to/your/trace-files   # mounted read-only at /data in the container
docker compose up --build
```

The GUI is then reachable at `http://localhost:8765`. Sessions persist in a named volume (`sfz-sessions`) across container replacement. Set `SFZ_AUTH_TOKEN` in the environment to enable the shared-secret auth gate.

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
├── COMPARISON.md                — MATLAB → Python change log with pros/cons
├── README.md                   — this file
├── Dockerfile / docker-compose.yml  — containerized deployment (multi-stage build)
├── mkdocs.yml                  — MkDocs Material site config
├── docs/                       — User Guide / Physics & Methods / Developer Guide + ROADMAP.md
├── frontend/                   — Svelte 5 + Vite + TS SPA (uPlot plotting)
│   └── dist/                   — built assets, force-included into the wheel
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
│       ├── api/                 — REST routers (files, sessions, traces, analysis)
│       ├── ws/session.py       — WebSocket for live filter/crop/measure/decimate
│       ├── schemas.py          — pydantic request/response models
│       ├── sessions.py         — session state (loaded files, crops, fits, view state)
│       ├── storage.py          — storage backends (local filesystem, user-scoped)
│       └── auth.py             — anonymous-by-default / opt-in bearer-token auth
└── tests/                       — unit tests + tests/golden/ MATLAB regression fixtures
```

---

## Running tests

```bash
uv run pytest               # run all tests
uv run pytest -v            # verbose output
uv run pytest --cov=src     # with coverage report
```

154 tests pass, covering the I/O, calibration, processing, analysis, CLI, and web (REST + WebSocket) layers. Most use synthetic `.dat` fixtures generated entirely in memory — no real instrument files required. `tests/golden/` additionally checks numerical parity against the real MATLAB source (run under GNU Octave); see [Testing & golden files](docs/developer/testing-golden-files.md) for how to regenerate fixtures and the known coverage gaps (HMM, velocity, PWD, kinetics, and the calibration/processing pipeline aren't golden-tested yet).

---

## Documentation

The full documentation site (MkDocs Material) covers installation, CLI reference, GUI walkthrough, the physics behind every analysis routine, and developer/architecture docs:

```bash
uv sync --extra docs
uv run mkdocs serve   # http://127.0.0.1:8000
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

Optional (`[docs]` extra): `mkdocs-material`, `mkdocstrings[python]`.
Optional (`[dev]` extra): `pytest`, `pytest-cov`, `pytest-asyncio`, `httpx`, `ruff`, `mypy`, `hypothesis`.

The Svelte SPA in `frontend/` has its own `package.json` (Svelte 5, Vite, TypeScript, uPlot) — see [frontend/README.md](frontend/README.md).

---

## License

This Python port is released under the same terms as the original MATLAB codebase: **GNU General Public License v3**.

---

## Acknowledgments

This project is a Python port of an optical tweezers data processing and analysis pipeline originally written in MATLAB by **A. Tong** (Berkeley Lab), released under the GNU General Public License v3. This port would not exist without that original work.
