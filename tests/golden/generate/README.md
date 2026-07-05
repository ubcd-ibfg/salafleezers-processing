# Golden fixture generation

Regenerates `tests/golden/fixtures/*.npz` by running the vendored MATLAB
source (`legacy/BLabOTMatlab/`, a git submodule) under GNU Octave and
converting its output.

## One-time setup

```bash
# Octave (MATLAB-compatible interpreter) via conda-forge
mamba create -n octave -c conda-forge octave

# Compile the KV mex kernels for your platform (Octave's mkoctfile bakes in
# a build-time compiler path that usually doesn't exist locally -- point it
# at system gcc explicitly)
cd legacy/BLabOTMatlab/DataGUIs/StepFind_KV
CC=/usr/bin/gcc CXX=/usr/bin/g++ mamba run -n octave mkoctfile --mex C_qe.c
CC=/usr/bin/gcc CXX=/usr/bin/g++ mamba run -n octave mkoctfile --mex C_qe_single.c
CC=/usr/bin/gcc CXX=/usr/bin/g++ mamba run -n octave mkoctfile --mex C_qe_window.c
```

The compiled `.mex` files are local build artifacts — do not commit them
into the `legacy/BLabOTMatlab` submodule. Remove them when done:
`rm legacy/BLabOTMatlab/DataGUIs/StepFind_KV/*.mex`.

## Regenerating fixtures

```bash
cd tests/golden/generate
mamba run -n octave octave-cli --no-gui gen_filters.m
mamba run -n octave octave-cli --no-gui gen_wlc.m
mamba run -n octave octave-cli --no-gui gen_kv.m
uv run python convert_mat_to_npz.py
```

Each `gen_*.m` script builds a small, fully-specified synthetic input
in-script (documented in the script itself), runs the real MATLAB routine on
it, and saves inputs + outputs to `fixtures/raw/*.mat`. `convert_mat_to_npz.py`
reshapes those into the `.npz` layout `tests/golden/conftest.py::load_golden`
expects. The frozen `.npz` files are what's committed and what the golden
tests in `tests/golden/test_*_golden.py` actually run against — Octave is
only needed to *regenerate* fixtures, not to run the test suite.

## Coverage so far

| Fixture | MATLAB source | Notes |
|---|---|---|
| `filters.npz` | `DataGUIs/StepFind_KV/windowFilter.m` | Mean filter, two half-widths. Caught and led to fixing a real edge-handling bug (see `test_filters_golden.py`) — now matches to floating-point precision. |
| `wlc.npz` | `DataGUIs/ForceExt/XWLC.m` | Method 1 ("Basic theory") only — see `test_wlc_golden.py` for why methods 2/3 aren't golden-tested. |
| `kv.npz` | `DataGUIs/StepFind_KV/AFindStepsV5.m` | 5-step synthetic staircase. Penalty parameterization differs from the Python port by design (see `test_kv_golden.py`); this fixture validates recovered step positions/levels, not penalty-scale equivalence. |

Not yet covered: HMM step-finding, velocity, PWD, kinetics, stats/KDE,
calibration/processing (Phase 0-2 pipeline). Follow the same pattern to add
more: find the MATLAB source under `legacy/BLabOTMatlab/`, write a
`gen_<name>.m` with a small deterministic (or fixed-seed, for cases needing
noise) synthetic input, add a converter entry, and a
`test_<name>_golden.py` using `load_golden`/`assert_close` from `conftest.py`.
