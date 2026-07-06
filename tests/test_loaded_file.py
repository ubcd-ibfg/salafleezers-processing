"""Tests for LoadedFile's cached float64 views (time64 / resolve_channel64)."""

from __future__ import annotations

import numpy as np

from salafleezers.web.sessions import LoadedFile


def _make_file() -> LoadedFile:
    n = 100
    return LoadedFile(
        file_id="f1",
        filename="t.npz",
        path="/tmp/t.npz",
        n_samples=n,
        sampling_rate_hz=1000.0,
        channels={"force": np.arange(n, dtype=np.float32)},
        time=np.linspace(0, 1, n, dtype=np.float32),
        meta={},
    )


def test_time64_matches_float64_cast_of_time():
    f = _make_file()
    np.testing.assert_allclose(f.time64, f.time.astype(np.float64))
    assert f.time64.dtype == np.float64


def test_time64_is_cached_across_accesses():
    f = _make_file()
    first = f.time64
    second = f.time64
    assert first is second   # same object, not recomputed


def test_resolve_channel64_case_insensitive():
    f = _make_file()
    assert f.resolve_channel64("FORCE") is not None
    assert f.resolve_channel64("Force") is not None
    assert f.resolve_channel64("force").dtype == np.float64


def test_resolve_channel64_missing_returns_none():
    f = _make_file()
    assert f.resolve_channel64("nonexistent") is None


def test_resolve_channel64_is_cached_per_name():
    f = _make_file()
    first = f.resolve_channel64("force")
    second = f.resolve_channel64("force")
    assert first is second
