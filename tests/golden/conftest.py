"""Golden-file regression test harness.

Usage
-----
To record a new golden fixture from MATLAB output:
  1. Run the MATLAB routine on representative data.
  2. Save inputs + outputs to ``tests/golden/fixtures/<name>.npz``.
  3. Write a test that calls ``load_golden(name)`` and compares the Python
     output to ``golden["expected_<field>"]``.

Tolerance targets:
  < 0.1 % RMS in the bulk of the signal
  < 1 %  at trace edges (first / last few samples)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_golden(name: str) -> dict[str, np.ndarray]:
    """Load a golden fixture .npz file by name (without extension)."""
    path = FIXTURE_DIR / f"{name}.npz"
    if not path.exists():
        pytest.skip(f"Golden fixture '{name}.npz' not yet recorded.")
    return dict(np.load(path, allow_pickle=False))


def assert_close(
    actual: np.ndarray,
    expected: np.ndarray,
    rtol: float = 1e-3,
    atol: float = 0.0,
    name: str = "",
) -> None:
    """Assert numerical closeness, producing a useful failure message."""
    rms = float(np.sqrt(np.mean((actual - expected) ** 2)))
    scale = float(np.sqrt(np.mean(expected ** 2))) or 1.0
    rel_rms = rms / scale
    label = f"[{name}] " if name else ""
    assert rel_rms < rtol or rms < atol, (
        f"{label}RMS relative error {rel_rms:.4%} exceeds tolerance {rtol:.4%}"
    )
