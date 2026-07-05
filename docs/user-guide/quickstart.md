# Quickstart (CLI)

This walks through the same pipeline the GUI drives — inspect a raw file, calibrate, process it
into force/extension, then run analysis — but entirely from the command line, so it also works
over SSH or in a batch job with no display.

## 1. Inspect a raw data file

Print the header metadata of any `.dat` file without loading the full signal:

```bash
uv run sfz inspect path/to/230415_001.dat
```

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

Add `--json` to get the same metadata as machine-readable JSON.

## 2. Calibrate a single file

Run a Lorentzian power-spectrum calibration on a calibration `.dat` file (see
[Calibration & trap stiffness](../physics/calibration.md) for the underlying model):

```bash
uv run sfz calibrate path/to/230415_003.dat --plot
```

```text
Calibrating 230415_003.dat  (Fs = 62500 Hz)
--------------------------------------------------
  AX: fc =    982.3 Hz  |  alpha =   187.4 nm/V  |  kappa = 0.0583 pN/nm
  BX: fc =   1041.7 Hz  |  alpha =   175.2 nm/V  |  kappa = 0.0618 pN/nm
  AY: fc =    874.1 Hz  |  alpha =   199.0 nm/V  |  kappa = 0.0519 pN/nm
  BY: fc =    923.5 Hz  |  alpha =   188.6 nm/V  |  kappa = 0.0548 pN/nm
```

## 3. Process a batch of files

```bash
uv run sfz process batch.txt --data-dir path/to/data/ --output-dir path/to/output/
```

See [Batch files](batch-files.md) for the `.txt` format. Outputs one HDF5 (or `.mat`/`.npz`
with `--save-format`) file per data file, each holding a time/force/extension trace.

## 4. Analyze a processed file

The `stepfind`, `wlc-fit`, `velocity`, and `pwd` commands all take the HDF5/npz output of
`process` and run one analysis module headlessly:

```bash
# Kalafut-Visscher step detection
uv run sfz stepfind output/ForceExtension230415_001.h5 --channel extension --algorithm kv

# WLC fit to the force-extension curve
uv run sfz wlc-fit output/ForceExtension230415_001.h5 --method basic

# Savitzky-Golay velocity distribution
uv run sfz velocity output/ForceExtension230415_001.h5 --window 21

# Pairwise-distance step-size histogram
uv run sfz pwd output/ForceExtension230415_001.h5 --bins 200
```

Every one of these has a `--json` flag for scripting, and is the exact same code the web GUI's
analysis panels call — see [Architecture](../developer/architecture.md).

## 5. Launch the interactive GUI

```bash
uv run sfz gui
```

Opens a browser at `http://127.0.0.1:8765` with the same processed-file analyses as an
interactive trace viewer and force-extension viewer. See the
[GUI walkthrough](gui-walkthrough.md).

## Using it as a library

Every CLI command is a thin wrapper around `salafleezers.analysis` / `salafleezers.processing`
/ `salafleezers.calibration` — pure NumPy functions with no CLI or web dependency, so you can
call them directly from a notebook or script:

```python
from pathlib import Path
from salafleezers.io.reader import read_dat
from salafleezers.processing.pipeline import ProcessingOptions, process_one

dat = read_dat("path/to/230415_001.dat")
print(dat.meta["Fs"])          # sampling frequency (Hz)
print(dat.channels["AX"])      # trap-A X-axis signal (float32, volts)

opts = ProcessingOptions(ra_a=500, ra_b=500, f_min=100, f_max=20000, normalize=True)
result = process_one(path="path/to/data/", nums=(1, 2, 3), mmddyy="230415", opts=opts)

print(result.force)      # pN
print(result.extension)  # nm

from salafleezers.io.writer import save
save("output/ForceExtension230415_001", result.to_dict(), fmt="hdf5")
```

```python
from salafleezers.analysis.stepfind.kv import find_steps
from salafleezers.analysis.wlc import fit_force_ext

steps = find_steps(result.extension, time=result.time, pen_factor=2.0)
fit = fit_force_ext(result.force, result.extension, method="basic")
```
