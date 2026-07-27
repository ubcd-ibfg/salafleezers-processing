# SalaFleezer Processing

![SalaFleezers logo](assets/logo/salafleezers_logo_small.png){ width="200" align="right" }

An optical-tweezers data processing and analysis platform, in pure Python.

This site has three books:

- **[User Guide](user-guide/installation.md)** — installing `sfz`, the CLI reference, a GUI
  walkthrough, and the data/batch-file formats.
- **[Physics & Methods](physics/optical-trapping.md)** — the "why": optical trapping basics,
  trap-stiffness calibration, force/extension models, and the maths behind every analysis
  routine (step-finding, velocity, pairwise distance, dwell-time kinetics).
- **[Developer Guide](developer/architecture.md)** — architecture, how to add a new analysis
  module, the API reference, and the golden-file testing strategy.

## Structure of the code

`sfz` is organized into three complementary layers:

- A **CLI** (`sfz inspect|calibrate|process|stepfind|wlc-fit|velocity|pwd|gui`) that runs
  anywhere Python runs — SSH, HPC, CI — with no display.
- A **web GUI** (`sfz gui`) — a FastAPI backend + Svelte SPA — for interactive trace viewing
  and force-extension analysis.
- A **pure-NumPy analysis library** (`salafleezers.analysis`) used by both interfaces, so every
  number shown in the GUI is reproducible from a script or notebook.

For implementation details and testing strategy, see
[Testing & golden files](developer/testing-golden-files.md).

## Worked examples

[`examples/`](https://github.com/ubcd-ibfg/salafleezers-processing/tree/main/examples) holds
full worked examples built on top of `salafleezers.analysis` — code for analyses specific to one
assay that don't belong in the general-purpose library or GUI. Currently:

- **[`rnap_nuc_crossing/`](https://github.com/ubcd-ibfg/salafleezers-processing/tree/main/examples/rnap_nuc_crossing)**
  — the full RNAP–nucleosome-crossing-with-a-molecular-ruler workflow, end to end. Walked
  through step by step, both from scripts and from `sfz gui`, in
  [RNAP nucleosome crossing](user-guide/rnap-nucleosome-crossing.md).
