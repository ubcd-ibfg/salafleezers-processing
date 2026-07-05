# BLabOTMatlab — MATLAB Reference Code

This directory is reserved for the vendored MATLAB source from which the
Python analysis modules in `src/salafleezers/` were ported.

## Status

The MATLAB tree is **not yet checked in** here.  To add it:

```bash
# Option A — git submodule (recommended, keeps history clean)
git submodule add <matlab-repo-url> legacy/BLabOTMatlab

# Option B — vendor snapshot (for air-gapped lab use)
cp -r /path/to/BLabOTMatlab legacy/BLabOTMatlab
git add legacy/BLabOTMatlab
git commit -m "Vendor MATLAB reference code under legacy/"
```

Once present, the golden-file test harness in `tests/golden/` can generate
reference fixtures by running the MATLAB routines and saving their output
as `.npz` files.

## Directory structure (expected)

```
BLabOTMatlab/
├── RawDataProcessing/   — timeshareread.m, tscalibrate.m, ProcessOneDataV2.m
└── DataGUIs/
    ├── PhageGUIv4.m
    ├── ForExtGUI_V2.m
    ├── StepFind_KV/     — BatchKV.m, AFindStepsV5.m, C_qe*.c
    ├── StepFind_HMM/    — fitViterbi*.m
    ├── Velocity/        — ppKVv4.m, vdist.m
    ├── PairwiseDist/    — calcPWDV1b.m, acorr2.m
    ├── Fitting/         — fitnexp.m, ngamdist.m
    ├── ForceExt/        — XWLC.m, fitForceExt.m
    ├── Plotting/        — violin.m, kdf.m
    └── Helpers/         — windowFilter.m, bilFilter.m
```
