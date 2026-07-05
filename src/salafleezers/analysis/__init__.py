"""Analysis package — pure, headless NumPy-in / NumPy-out scientific routines.

Ports the DataGUIs analysis layer from MATLAB to Python.  Every public
function in this package:

- accepts and returns numpy arrays
- has no dependency on FastAPI, matplotlib, or any GUI toolkit
- is independently usable from the CLI, a notebook, or the web API
"""

from salafleezers.analysis import (
    crop,
    filters,
    kinetics,
    pwd,
    stats,
    velocity,
    wlc,
)
from salafleezers.analysis.stepfind import kv, hmm

__all__ = [
    "crop",
    "filters",
    "hmm",
    "kinetics",
    "kv",
    "pwd",
    "stats",
    "velocity",
    "wlc",
]
