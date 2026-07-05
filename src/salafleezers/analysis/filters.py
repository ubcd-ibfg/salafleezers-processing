"""Signal filtering — port of windowFilter.m, smooth.m, bilFilter.m.

MATLAB originals:
  DataGUIs/Helpers/windowFilter.m
  DataGUIs/Helpers/bilFilter.m
  MATLAB built-in smooth(x, n)
"""

from __future__ import annotations

from typing import Callable

import numpy as np
from scipy.ndimage import uniform_filter1d


def window_filter(
    data: np.ndarray,
    fn: str | Callable[[np.ndarray], float] = "mean",
    half_width: int | None = None,
    decimate: int | None = None,
) -> np.ndarray:
    """Sliding window filter with optional decimation.

    Mirrors ``windowFilter(fn, data, inHalfWidth, inDecimate)`` in MATLAB.

    Parameters
    ----------
    data:
        1-D input array.
    fn:
        ``"mean"`` (default), ``"sum"``, or any callable ``f(block) -> scalar``.
    half_width:
        Half-width of the *centred* sliding window (window size = 2*half_width+1).
        Provide either this or *decimate*, not both (pass ``None`` to omit).
    decimate:
        Block size for non-overlapping decimation.  When *half_width* is ``None``
        the data is split into non-overlapping blocks and *fn* is applied to each.
    """
    data = np.asarray(data, dtype=np.float64)

    if decimate is not None and half_width is None:
        return _block_decimate(data, decimate, fn)

    if half_width is None:
        raise ValueError("Provide either half_width or decimate")

    window_size = 2 * half_width + 1

    if fn == "mean" or fn is np.mean:
        filtered = _centered_shrinking_mean(data, half_width)
    elif fn == "sum" or fn is np.sum:
        filtered = uniform_filter1d(data, window_size, mode="nearest") * window_size
    else:
        n = len(data)
        padded = np.pad(data, half_width, mode="edge")
        filtered = np.array(
            [fn(padded[i: i + window_size]) for i in range(n)],
            dtype=np.float64,
        )

    if decimate is not None:
        return filtered[::decimate]
    return filtered


def _centered_shrinking_mean(data: np.ndarray, half_width: int) -> np.ndarray:
    """Centred moving average with a symmetric shrinking window at the edges.

    Matches MATLAB's ``windowFilter(@mean, data, half_width, 1)`` exactly
    (verified against a golden fixture, see ``tests/golden/test_filters_golden.py``).
    Near either edge, rather than replicating the boundary value (as
    ``scipy.ndimage.uniform_filter1d(mode='nearest')`` does), the window
    radius shrinks to whatever fits symmetrically in-bounds — e.g. at the
    very first sample the "window" is just that one point; one step in, it's
    the centred 3-point average; and so on until the full ``half_width``
    window fits. Interior points (more than ``half_width`` from either edge)
    are identical to the full centred box average.
    """
    n = len(data)
    cs = np.concatenate([[0.0], np.cumsum(data)])
    idx = np.arange(n)
    r = np.minimum(np.minimum(idx, half_width), n - 1 - idx)
    lo = idx - r
    hi = idx + r + 1
    return (cs[hi] - cs[lo]) / (hi - lo)


def _block_decimate(
    data: np.ndarray,
    block: int,
    fn: str | Callable,
) -> np.ndarray:
    n = len(data)
    n_blocks = n // block
    trimmed = data[: n_blocks * block].reshape(n_blocks, block)

    if fn == "mean" or fn is np.mean:
        return trimmed.mean(axis=1)
    if fn == "sum" or fn is np.sum:
        return trimmed.sum(axis=1)
    return np.array([fn(trimmed[i]) for i in range(n_blocks)], dtype=np.float64)


def smooth(data: np.ndarray, n: int) -> np.ndarray:
    """Uniform moving average of width *n* — port of MATLAB's ``smooth(x, n)``.

    Uses the same symmetric shrinking-window edge handling as
    ``window_filter``'s ``@mean`` path (``windowFilter.m``'s own comment
    notes its mean implementation was "taken from @smooth"), so this matches
    MATLAB's default ``'moving'`` method exactly, including at the edges —
    not the edge-replication a naive ``uniform_filter1d`` would give.
    """
    data = np.asarray(data, dtype=np.float64)
    return _centered_shrinking_mean(data, half_width=(n - 1) // 2)


def bilateral_filter(
    data: np.ndarray,
    spatial_sigma: float,
    intensity_sigma: float,
) -> np.ndarray:
    """Edge-preserving bilateral filter — port of bilFilter.m.

    Combines a Gaussian spatial kernel with a Gaussian intensity kernel so
    that averaging is suppressed across sharp transitions (steps).

    Parameters
    ----------
    data:
        1-D signal to filter.
    spatial_sigma:
        Standard deviation of the spatial (distance) Gaussian, in samples.
    intensity_sigma:
        Standard deviation of the intensity (value-difference) Gaussian.

    Returns
    -------
    np.ndarray
        Filtered signal, same length as *data*.
    """
    data = np.asarray(data, dtype=np.float64)
    n = len(data)
    half_w = int(3 * spatial_sigma)
    xs = np.arange(-half_w, half_w + 1)
    spatial_kernel = np.exp(-0.5 * (xs / spatial_sigma) ** 2)

    result = np.empty(n)
    for i in range(n):
        lo = max(0, i - half_w)
        hi = min(n, i + half_w + 1)
        offset = lo - (i - half_w)
        nb = data[lo:hi]
        sk = spatial_kernel[offset: offset + len(nb)]
        ik = np.exp(-0.5 * ((nb - data[i]) / intensity_sigma) ** 2)
        w = sk * ik
        w_sum = w.sum()
        result[i] = (w * nb).sum() / w_sum if w_sum > 0 else data[i]

    return result


def decimate_trace(
    data: np.ndarray,
    factor: int,
    method: str = "mean",
) -> np.ndarray:
    """Block-decimate a 1-D trace by *factor*.

    Thin wrapper around :func:`window_filter` with ``decimate=factor``.
    """
    return window_filter(data, fn=method, decimate=factor)
