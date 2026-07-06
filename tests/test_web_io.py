"""Tests for salafleezers.web.io helpers."""

from __future__ import annotations

import numpy as np

from salafleezers.web.io import estimate_sampling_rate


def test_estimate_sampling_rate_normal():
    time = np.array([0.0, 0.01, 0.02, 0.03])
    assert estimate_sampling_rate(time) == 100.0


def test_estimate_sampling_rate_single_sample():
    assert estimate_sampling_rate(np.array([0.0])) == 1.0


def test_estimate_sampling_rate_empty():
    assert estimate_sampling_rate(np.array([])) == 1.0


def test_estimate_sampling_rate_duplicate_leading_timestamps():
    """Would otherwise divide by zero and return inf."""
    time = np.array([1.0, 1.0, 1.02, 1.03])
    assert estimate_sampling_rate(time) == 1.0
