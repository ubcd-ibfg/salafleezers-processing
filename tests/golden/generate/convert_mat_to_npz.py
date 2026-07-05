"""Convert the raw Octave-generated .mat fixtures into the .npz shape the
golden-file harness (tests/golden/conftest.py) expects.

Run once after regenerating tests/golden/fixtures/raw/*.mat via the
gen_*.m scripts (see tests/golden/generate/README.md).

    uv run python tests/golden/generate/convert_mat_to_npz.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import scipy.io as sio

RAW = Path(__file__).parent.parent / "fixtures" / "raw"
OUT = Path(__file__).parent.parent / "fixtures"


def convert_filters() -> None:
    d = sio.loadmat(RAW / "filters.mat")
    np.savez(
        OUT / "filters.npz",
        x=d["x"].ravel(),
        expected_hw5=d["hw5"].ravel(),
        expected_hw20=d["hw20"].ravel(),
    )
    print("wrote fixtures/filters.npz")


def convert_wlc() -> None:
    d = sio.loadmat(RAW / "wlc.mat")
    np.savez(
        OUT / "wlc.npz",
        F=d["F"].ravel(),
        P=float(d["P"].ravel()[0]),
        S=float(d["S"].ravel()[0]),
        kT=float(d["kT"].ravel()[0]),
        expected_x_over_L=d["x_over_L"].ravel(),
    )
    print("wrote fixtures/wlc.npz")


def convert_kv() -> None:
    d = sio.loadmat(RAW / "kv.mat")
    out_ind = d["outInd"].ravel().astype(np.int64)
    # outInd = [1, <interior step boundaries, 1-based>, N] (MATLAB, 1-based).
    # Python's kv.py step_positions are 0-based indices of segment starts.
    step_positions = out_ind[1:-1] - 1
    np.savez(
        OUT / "kv.npz",
        contour=d["contour"].ravel(),
        expected_step_positions=step_positions,
        expected_levels=d["outMean"].ravel(),
    )
    print("wrote fixtures/kv.npz")


if __name__ == "__main__":
    convert_filters()
    convert_wlc()
    convert_kv()
