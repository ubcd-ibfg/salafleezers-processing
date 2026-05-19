# salafleezers-processing

Python port of the **SalaFleezer** optical tweezers data processing pipeline, originally written in MATLAB by A. Tong (Berkeley Lab, GPL v3).

SalaFleezer is a timeshared optical tweezers instrument that reads raw QPD signals from binary `.dat` files, calibrates trap stiffness via Lorentzian power spectrum fitting, and converts raw signals to force (pN) and extension (nm).

> The original MATLAB codebase is preserved untouched in `legacy/BLabOTMatlab/`.  
> See [COMPARISON.md](COMPARISON.md) for a full table of MATLAB → Python library changes and their trade-offs.

---

## Requirements

- Python ≥ 3.13
- [uv](https://docs.astral.sh/uv/) (package manager)

---

## Installation

```bash
git clone <repo-url>
cd salafleezers_processing

# Install all dependencies (creates .venv automatically)
uv sync

# Install with dev tools (pytest, ruff, mypy)
uv sync --dev
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

### 4. Common options

All sub-commands accept calibration and processing options:

| Option | Default | Description |
| --- | --- | --- |
| `--ra-a` | 500 nm | Bead radius for trap A |
| `--ra-b` | 500 nm | Bead radius for trap B |
| `--fmin` | 100 Hz | Lower fit frequency for Lorentzian |
| `--fmax` | Nyquist | Upper fit frequency |
| `--n-bin` | 1563 | Points per spectral bin |
| `--no-normalize` | — | Skip QPD sum normalization |
| `--save-format` | `hdf5` | Output format: `hdf5`, `npz`, or `mat` |
| `--verbose` | — | Print calibration values and progress |

```bash
uv run sfz process batch.txt \
    --ra-a 485 --ra-b 515 \
    --fmin 50 --fmax 25000 \
    --save-format mat \
    --verbose
```

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

---

## Project structure

```text
salafleezers_processing/
├── pyproject.toml              — package metadata and dependencies
├── main.py                     — thin entry point (delegates to sfz CLI)
├── COMPARISON.md               — MATLAB → Python change log with pros/cons
├── README.md                   — this file
├── legacy/                     — original MATLAB codebase (untouched)
│   └── BLabOTMatlab/
└── src/
    └── salafleezers/
        ├── constants.py        — instrument constants, channel maps
        ├── io/
        │   ├── reader.py       — binary .dat / _fl / _pos / _grn parser
        │   └── writer.py       — HDF5 / npz / mat output
        ├── calibration/
        │   ├── power_spectrum.py  — FFT + spectral binning
        │   ├── lorentzian.py      — Lorentzian PSD models
        │   └── fit.py             — lorentz_guess + scipy optimizer
        ├── processing/
        │   ├── offset.py       — trap-delta offset computation
        │   ├── normalize.py    — QPD sum normalization + offset subtraction
        │   └── pipeline.py     — full dat/off/cal pipeline orchestrator
        ├── fluorescence/
        │   └── apd.py          — APD photon count processing
        ├── utils/
        │   └── signal.py       — windowFilter, smooth, block decimation
        └── cli/
            └── main.py         — sfz inspect / calibrate / process commands
```

---

## Running tests

```bash
uv run pytest               # run all tests
uv run pytest -v            # verbose output
uv run pytest --cov=src     # with coverage report
```

Tests use synthetic `.dat` fixtures generated entirely in memory — no real instrument files required.

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

---

## Dependencies

| Package | Purpose |
| --- | --- |
| `numpy ≥ 2.0` | Array math, binary I/O, FFT |
| `scipy ≥ 1.14` | `least_squares`, `interp1d`, `savemat` |
| `h5py ≥ 3.11` | HDF5 output (primary format) |
| `matplotlib ≥ 3.9` | Power spectrum plots (`--plot` flag) |
| `click ≥ 8.1` | CLI (`sfz` command) |

---

## License

This Python port is released under the same terms as the original MATLAB codebase: **GNU General Public License v3**.  
See `legacy/BLabOTMatlab/COPYING.m` for the full license text.
