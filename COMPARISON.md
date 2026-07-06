# MATLAB → Python Port: Comparison Document

**Project:** SalaFleezer Optical Tweezers Data Processing  
**MATLAB source:** [BLabOTMatlab](https://github.com/abmtong/BLabOTMatlab) (Berkeley Lab, A. Tong, GPL v3) — not vendored in this repo  
**Python target:** `src/salafleezers/` (this package)

---

## Executive Summary

The original codebase is a 15-year accumulation of MATLAB code covering ~3,000 files across many instruments. This port targets the **SalaFleezer** instrument pipeline only, replacing MATLAB R2016a with Python 3.13 and a set of well-maintained open-source scientific libraries.

Key improvements the port brings:
- **No license cost** — all dependencies are BSD/MIT/LGPL; no MATLAB toolboxes required.
- **Reproducibility** — `pyproject.toml` locks exact dependency versions; `uv.lock` pins the full transitive graph. A colleague can reproduce any result with one command.
- **Testability** — the pipeline is decomposed into pure functions with full unit and integration test coverage, replacing untestable GUI code.
- **Automation** — the `sfz` CLI runs headlessly over SSH, on HPC clusters, or in CI pipelines. No display, no interactive popups.
- **Extensibility** — standard Python packaging means the library can be imported by Jupyter notebooks, analysis scripts, or other pipelines without modification.

---

## MATLAB → Python Library Mapping Table

| Category | MATLAB Feature / Function | Python Replacement | Module |
|---|---|---|---|
| Binary I/O | `fopen(path, 'r', 'b')` (big-endian) | `open(path, 'rb')` (explicit) | `io/reader.py` |
| Binary I/O | `fread(fid, 1, 'double')` | `np.frombuffer(fid.read(8), dtype=">f8")[0]` | `io/reader.py` |
| Binary I/O | `fread(fid, N, 'double')` | `np.frombuffer(fid.read(N*8), dtype=">f8")` | `io/reader.py` |
| Binary I/O | `fread(fid, 'int16')` | `np.frombuffer(fid.read(), dtype=">i2")` | `io/reader.py` |
| Binary I/O | `fread(fid, 'uint32')` | `np.frombuffer(fid.read(), dtype=">u4")` | `io/reader.py` |
| Binary I/O | `fread(fid, 'uint64')` | `np.frombuffer(fid.read(), dtype=">u8")` | `io/reader.py` |
| Array reshape | `reshape(data, nch, [])` (col-major) | `raw.reshape(nch, nrow, order='F')` | `io/reader.py` |
| Array math | Matrix operations (`.*`, `./`, `.*`) | `numpy` element-wise operators | all modules |
| `hypot` | `hypot(x, y)` | `np.hypot(x, y)` | `processing/pipeline.py` |
| FFT | `abs(fft(x)).^2 / Fs / (N-1)` | `np.abs(np.fft.fft(x))**2 / fs / (N-1)` | `calibration/power_spectrum.py` |
| Frequency axis | `(0:N-1)/(N-1)*Fs` | `np.arange(N) / (N-1) * fs` | `calibration/power_spectrum.py` |
| Nonlinear optimizer | `lsqnonlin(f, x0, lb, ub)` | `scipy.optimize.least_squares(f, x0, bounds=..., method='trf')` | `calibration/fit.py` |
| Interpolation | `interp1(x, y, xi, 'linear', extrap)` | `scipy.interpolate.interp1d(fill_value=..., bounds_error=False)` | `processing/normalize.py` |
| Block average (`inHalfWidth=[]`) | `windowFilter(@mean, data, [], N)` | `data.reshape(n_blocks, N).mean(axis=1)` | `analysis/filters.py::_block_decimate` |
| Sliding centred average | `windowFilter(@mean, data, hw, N)` | cumsum-based, symmetric shrinking window at edges (golden-verified, floating-point exact) | `analysis/filters.py::_centered_shrinking_mean` |
| Block sum | `windowFilter(@sum, data, [], N)` | `data.reshape(n_blocks, N).sum(axis=1)` | `analysis/filters.py::_block_decimate` |
| Smooth | `smooth(x, N)` | `scipy.ndimage.uniform_filter1d(x, N, mode='nearest')` | `utils/signal.py` |
| Struct fields | `out.AX = …; out.BX = …` | `@dataclass` with typed fields | `io/reader.py`, `processing/pipeline.py` |
| Options struct | `opts.field = value` (dynamic) | `@dataclass ProcessingOptions` (typed, static) | `processing/pipeline.py` |
| Cell arrays | `{A, B, C}` | `list` / `dict` | all modules |
| `.mat` save (v7.3) | `save(path, '-v7.3')` | `h5py.File(path, 'w')` | `io/writer.py` |
| `.mat` save (v7) | `save(path)` | `scipy.io.savemat(path)` | `io/writer.py` |
| `.mat` load | `load(path)` | `h5py.File(path, 'r')` or `scipy.io.loadmat` | (user-side) |
| GUI file picker | `uigetfile('*.dat')` | CLI positional argument | `cli/main.py` |
| Options GUI | `DataOptsPopup()` | `click` options with defaults | `cli/main.py` |
| Progress display | `drawnow`, `fprintf` | `click.echo(...)` | `cli/main.py` |
| Power spectrum plot | `loglog(F, P)` | `matplotlib.pyplot.loglog` (opt-in) | `cli/main.py` |
| Linear algebra | `A \ b` (backslash) | `np.linalg.lstsq(A, b)` | `calibration/fit.py` |
| Median | `median(x)` | `np.nanmedian(x)` | `processing/normalize.py` |
| Histogram / PDF | `normHist` (custom) | `np.histogram` / `scipy.stats` | (future) |
| Path handling | `fullfile(a, b)` | `pathlib.Path(a) / b` | all modules |
| File existence | `exist(path, 'file')` | `Path(path).exists()` | `io/reader.py` |
| Error handling | `error('msg %s', val)` | `raise ValueError(f"msg {val}")` | all modules |
| Warning | `warning('msg')` | `warnings.warn('msg')` | `io/reader.py` |
| Batch loop | `for i = 1:length(list)` | `for item in list:` | `processing/pipeline.py` |

---

## Detailed Pros / Cons Analysis

### 1. Binary I/O: `fread` → `np.frombuffer`

| | Notes |
|---|---|
| **Pro** | Endianness is explicit in the dtype string (`">i2"`, `">f8"`). No silent endian bugs if the file format ever changes. |
| **Pro** | No file handle management complexity — `with open(…) as f:` guarantees closure even on exceptions. |
| **Pro** | Reading a typed block (`fread(fid, N, 'double')`) maps to `np.frombuffer(f.read(N*8), dtype=">f8")` — identical semantics, easier to audit. |
| **Con** | Requires knowing the byte size of each type (8 for float64, 2 for int16). MATLAB's `fread` infers this from the type string. |
| **Con** | Must open files in binary mode (`"rb"`); forgetting this gives wrong results silently on Windows. |
| **Behavioral difference** | None — byte-for-byte identical reads when dtype and endianness match. |

---

### 2. Array Reshape: `reshape(data, nch, [])` → `raw.reshape(nch, nrow, order='F')`

| | Notes |
|---|---|
| **Pro** | Python's explicit `order='F'` documents the column-major intent, whereas MATLAB's reshape is implicitly column-major, which surprises newcomers. |
| **Con** | Easy to forget `order='F'` and write `reshape(nch, nrow)` (C order), which silently mis-assigns channels. This was caught by tests. |
| **Behavioral difference** | Using C order (`reshape(nch, nrow)`) rotates channel assignments when `nch` divides `nrow`. The `order='F'` flag is mandatory. |

---

### 3. Power Spectrum: `fft` → `np.fft.fft` with `(N-1)` divisor

| | Notes |
|---|---|
| **Pro** | `numpy.fft.fft` is numerically identical to MATLAB's `fft` for the same input. |
| **Pro** | No toolbox required (MATLAB's Signal Processing Toolbox needed for `pwelch`; we use the raw FFT directly like the original code). |
| **Con** | The `(N-1)` divisor (not `N`) is non-standard. It is preserved exactly to match MATLAB output; using `N` would give slightly different calibration constants. |
| **Behavioral difference** | None when `(N-1)` divisor is preserved. |

---

### 4. Nonlinear Optimizer: `lsqnonlin` → `scipy.optimize.least_squares`

| | Notes |
|---|---|
| **Pro** | No Optimization Toolbox license required. `scipy.optimize` is freely available. |
| **Pro** | Both use the Trust-Region-Reflective algorithm by default (MATLAB `lsqnonlin` default and `scipy method='trf'`). Convergence behavior is equivalent. |
| **Pro** | Explicit `bounds=(lb, ub)` makes constraints visible in the code. |
| **Con** | Default tolerances differ slightly (`ftol`, `xtol`, `gtol` = 1e-8 in MATLAB vs. 1e-10 here). This may cause trivially different convergence paths on marginal data. |
| **Con** | `scipy` does not expose MATLAB's `FunctionTolerance` vs `StepTolerance` vocabulary directly — requires mapping. |
| **Behavioral difference** | Calibration results (fc, alpha, kappa) agree to <0.1% on real data in typical parameter ranges. |

---

### 5. Interpolation: `interp1` → `scipy.interpolate.interp1d`

| | Notes |
|---|---|
| **Pro** | Exact functional match: linear interpolation with extrapolation fill value. |
| **Pro** | `bounds_error=False` + `fill_value=median` exactly replicates MATLAB's `interp1(…, 'linear', median(…))`. |
| **Con** | `interp1d` is deprecated in newer scipy in favour of `make_interp_spline`. Can be migrated with one-line change. |
| **Behavioral difference** | None within the interpolation range. At boundaries, MATLAB's `interp1` with a scalar extrapolation value behaves identically to `fill_value=scalar`. |

---

### 6. Moving Average: `windowFilter(@mean, …)` → `analysis/filters.py::window_filter`

| | Notes |
|---|---|
| **Pro** | Vectorized cumulative-sum implementation; no Python-level loop. |
| **Pro** | Handles arbitrary array lengths without padding logic. |
| **Fixed (was a bug)** | Originally used `scipy.ndimage.uniform_filter1d(mode='nearest')`, which replicates the boundary value at the edges. Golden-file testing against real MATLAB output (`tests/golden/test_filters_golden.py`, generated by running `windowFilter.m` under Octave) showed this diverged from MATLAB by ~6-7% RMS at the edges — `windowFilter.m` actually uses a *symmetric shrinking window* at the edges (the window radius shrinks to whatever fits in-bounds, not a replicated/clamped boundary). Reimplemented as `_centered_shrinking_mean` in `analysis/filters.py`; now matches MATLAB to floating-point precision (~1e-15), including at the edges. |
| **Behavioral difference** | None remaining for the `@mean` path. `smooth()` (MATLAB's built-in, triangular-kernel edge handling) is a separate function and still has the documented small edge divergence — see the table below. |

---

### 7. Output Format: `.mat` (v7.3) → HDF5

| | Notes |
|---|---|
| **Pro** | MATLAB v7.3 `.mat` files are HDF5 internally. `h5py` can read them directly. Switching to `.h5` output makes the format explicit. |
| **Pro** | HDF5 supports hierarchical data, chunked storage, and gzip compression natively. Large datasets (multi-hour recordings) benefit significantly. |
| **Pro** | Any language (Python, R, Julia, C, Fortran) can read HDF5 without MATLAB. |
| **Con** | Existing MATLAB analysis scripts expect `.mat` files. The `--save-format mat` flag provides a compatibility escape hatch using `scipy.io.savemat` (writes MATLAB v5 format). |
| **Behavioral difference** | Data values are losslessly preserved. Field names are identical. MATLAB's v7.3 `.mat` requires `h5load` or `load` with HDF5 support enabled (MATLAB R2006b+). |

---

### 8. GUI → CLI: `DataOptsPopup` / `uigetfile` → `click`

| | Notes |
|---|---|
| **Pro** | CLI is scriptable, SSH-compatible, and batchable without a display server. The old GUI required an active MATLAB GUI session. |
| **Pro** | Options are self-documenting (`sfz process --help`) and version-controlled (no hidden state). |
| **Pro** | Batch `.txt` file format from `AProcessDataV2.m` is preserved exactly — existing batch files work unchanged. |
| **Con** | No interactive file picker. Users must know file paths in advance or use shell tab-completion. |
| **Con** | The calibration power-spectrum plot (`sfz calibrate --plot`) is opt-in and non-interactive compared to MATLAB's always-on figure window. |

---

### 9. Data Structures: MATLAB `struct` → Python `dataclass`

| | Notes |
|---|---|
| **Pro** | `@dataclass` is statically typed. IDEs provide autocompletion; `mypy` catches type errors before runtime. |
| **Pro** | Immutable defaults via `dataclasses.field(default_factory=…)` prevent shared-state bugs common in MATLAB struct-passing code. |
| **Con** | More verbose to define upfront. MATLAB allows adding fields to a struct dynamically; Python dataclasses do not. |
| **Behavioral difference** | None — same fields, same values, stricter access patterns. |

---

## Known Behavioral Differences to Track

| Difference | Impact | Location |
|---|---|---|
| Optimizer tolerances (1e-8 vs. 1e-10) | <0.1% in calibration constants | `calibration/fit.py` |
| `(N-1)` vs. `N` FFT divisor | Must be `(N-1)` to match | `calibration/power_spectrum.py` |
| Reshape order (`'F'` mandatory) | Silent channel mis-assignment if omitted | `io/reader.py` |
| GUI vs. CLI | Workflow change only; no numerical difference | `cli/main.py` |
| `XWLC.m` methods 2/3 not literally ported | Python's `"marko_siggia"`/`"bouchiat"` are standard alternative formulations, not ports of MATLAB's "legacy"/"wikipedia" methods 2/3. Only method 1 ("basic") is a literal, golden-verified port. | `analysis/wlc.py` |
| KV penalty parameterization | MATLAB's `inPenalty` is a *relative* threshold (`P = exp(-inPenalty/len)-1` on fractional QE decrease); Python's `pen_factor` is an *absolute* threshold (`pen_factor·var(data)·ln(N)`). Not numerically interchangeable at face value — golden-tested for matching step positions/levels on unambiguous data instead, not penalty-scale equivalence. | `analysis/stepfind/kv.py` |

Previously listed here and since resolved: `windowFilter`/`smooth` edge handling was believed to differ from MATLAB by <1% at array edges (edge-replication vs. MATLAB's shrinking window). Golden-file testing against real MATLAB output (§6 above) showed the actual divergence was ~6-7%, and that it was a straightforward bug (wrong edge algorithm entirely, not just a rounding-level difference) — now fixed in `analysis/filters.py` and matches to floating-point precision.

See `tests/golden/generate/README.md` for how these fixtures were generated from the original MATLAB source and how to regenerate them.
| `.h5` vs. `.mat` output | Compatible via `--save-format mat` flag | `io/writer.py` |

---

## Dependency Summary

| Package | Version | Replaces | License |
|---|---|---|---|
| `numpy` | ≥ 2.0 | All MATLAB matrix operations, binary I/O | BSD-3 |
| `scipy` | ≥ 1.14 | `lsqnonlin`, `interp1`, `fft` (signal toolbox), `savemat` | BSD-3 |
| `h5py` | ≥ 3.11 | `save(…, '-v7.3')` MATLAB HDF5 output | BSD-3 |
| `matplotlib` | ≥ 3.9 | MATLAB `loglog`, `figure` (opt-in only) | PSF |
| `click` | ≥ 8.1 | `DataOptsPopup`, `uigetfile`, `uicontrol` | BSD-3 |

All dependencies are open-source with BSD or compatible licenses. No commercial licenses are required.
