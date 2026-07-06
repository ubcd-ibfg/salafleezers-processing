# SalaFleezer Processing

![SalaFleezers logo](assets/logo/salafleezers_logo_small.png){ width="200" align="right" }

A MATLAB-free optical-tweezers data processing and analysis platform, replacing the
BLab's [`BLabOTMatlab`](https://github.com/abmtong/BLabOTMatlab) `RawDataProcessing` +
`DataGUIs` codebase with Python.

This site has three books:

- **[User Guide](user-guide/installation.md)** — installing `sfz`, the CLI reference, a GUI
  walkthrough, and the data/batch-file formats.
- **[Physics & Methods](physics/optical-trapping.md)** — the "why": optical trapping basics,
  trap-stiffness calibration, force/extension models, and the maths behind every analysis
  routine (step-finding, velocity, pairwise distance, dwell-time kinetics).
- **[Developer Guide](developer/architecture.md)** — architecture, the MATLAB→Python mapping,
  how to add a new analysis module, the API reference, and the golden-file testing strategy.

## What this replaces

The original MATLAB codebase's biggest maintenance burden was
[`DataGUIs/PhageGUIv4.m`](https://github.com/abmtong/BLabOTMatlab/blob/master/DataGUIs/PhageGUIv4.m)
and
[`ForExtGUI_V2.m`](https://github.com/abmtong/BLabOTMatlab/blob/master/DataGUIs/ForExtGUI_V2.m)
— two large, monolithic, MATLAB-GUI-only interactive analysis tools with no headless path and no
tests. `sfz` replaces both with:

- A **CLI** (`sfz inspect|calibrate|process|stepfind|wlc-fit|velocity|pwd|gui`) that runs
  anywhere Python runs — SSH, HPC, CI — with no display.
- A **web GUI** (`sfz gui`) — a FastAPI backend + Svelte SPA — for the interactive trace
  viewing and force-extension analysis that made the lab dependent on MATLAB in the first
  place.
- A **pure-NumPy analysis library** (`salafleezers.analysis`) that both of the above call into,
  so every number the GUI shows you is reproducible from a script or a notebook.

See `COMPARISON.md` in the repo root for the full MATLAB→Python library mapping and every known
behavioral difference, several of which were found and fixed by testing against the real
MATLAB source under Octave — see [Testing & golden files](developer/testing-golden-files.md).
