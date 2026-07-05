# MATLAB → Python mapping

The full mapping table, every pros/cons analysis, and every known behavioral difference (some
intentional, some bugs found and fixed via golden-file testing) lives in `COMPARISON.md` at the
repo root — this page is a pointer into it plus the parts specific to the analysis/GUI port
that postdate that document's original scope.

## Where the MATLAB source lives

`legacy/BLabOTMatlab/` is a **git submodule** pointing at the original MATLAB codebase — not a
copied/frozen snapshot, so it can be updated if the upstream lab code changes. It's not needed
to run `sfz` (the Python port is fully self-contained); it's only needed to regenerate golden
fixtures — see [Testing & golden files](testing-golden-files.md).

```bash
git submodule update --init legacy/BLabOTMatlab
```

## Read `COMPARISON.md` for

- The full library-mapping table (binary I/O, FFT conventions, interpolation, optimizers,
  reshape order, `.mat`/HDF5 output, GUI→CLI, `struct`→`dataclass`).
- Every **known behavioral difference**, each with a measured or reasoned impact — e.g. the
  `(N-1)` vs. `N` FFT divisor, why reshape order must be `'F'`, and two analysis-specific
  divergences discovered while writing this site's Physics book:
  - [Force & extension](../physics/force-extension.md) — `analysis.wlc`'s `"marko_siggia"` and
    `"bouchiat"` methods are standard alternative formulations, **not** literal ports of
    MATLAB's `XWLC.m` methods 2/3.
  - [Step-finding theory](../physics/step-finding.md) — MATLAB's KV penalty is a *relative*
    threshold, Python's is *absolute*; same algorithm, different penalty scale.
- A real bug this project's golden-file testing caught and fixed: `window_filter`'s edge
  handling used to replicate the boundary value instead of MATLAB's actual symmetric shrinking
  window (~6-7% error at trace edges, not the <1% originally assumed) — see §6 of
  `COMPARISON.md` and [Testing & golden files](testing-golden-files.md).

## Porting philosophy

Every `analysis/` module's docstring names the exact MATLAB file(s) it ports (e.g.
`stepfind/kv.py`: *"port of BatchKV.m / AFindStepsV5.m"*). When Python deviates from a literal
port — a different penalty formula, a different (better) numerical method, a function that
doesn't exist in MATLAB at all — that's called out explicitly in the module docstring and/or
`COMPARISON.md`, not left implicit. If you're porting a new module and it's not a literal
translation, follow that same pattern: say so, and say why.
