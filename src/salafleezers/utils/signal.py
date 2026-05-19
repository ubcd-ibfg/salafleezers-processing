"""Signal processing utilities — port of windowFilter.m.

windowFilter.m in legacy/BLabOTMatlab/DataGUIs/Helpers/windowFilter.m
provides a generic sliding-window operation with optional decimation.

The two dominant use-cases in the SalaFleezer pipeline are:
  1. block-mean decimation   → window_filter(data, "mean", decimate=N)
  2. block-sum  decimation   → window_filter(data, "sum",  decimate=N)

Both collapse contiguous blocks of N samples, which is equivalent to:
  reshape → apply (mean|sum) over axis 0
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
    data : 1-D array
    fn : str or callable
        ``"mean"`` or ``"sum"``, or any callable ``f(block) -> scalar``.
    half_width : int or None
        Half-width of the sliding window (centred, size = 2*half_width+1).
        Pass ``None`` (or omit) when using *decimate* instead.
    decimate : int or None
        Block size for non-overlapping decimation.  When provided and
        *half_width* is ``None``, the data is split into non-overlapping
        blocks of *decimate* samples and *fn* is applied to each block.

    Returns
    -------
    np.ndarray
        Filtered (and optionally decimated) data.
    """
    data = np.asarray(data, dtype=np.float64)

    if decimate is not None and half_width is None:
        return _block_decimate(data, decimate, fn)

    if half_width is None:
        raise ValueError("Provide either half_width or decimate")

    window_size = 2 * half_width + 1

    if fn == "mean" or fn is np.mean:
        filtered = uniform_filter1d(data, window_size, mode="nearest")
    elif fn == "sum" or fn is np.sum:
        filtered = uniform_filter1d(data, window_size, mode="nearest") * window_size
    else:
        # Generic sliding window via stride tricks (slow, avoids scipy dep)
        n = len(data)
        padded = np.pad(data, half_width, mode="edge")
        filtered = np.array(
            [fn(padded[i: i + window_size]) for i in range(n)],
            dtype=np.float64,
        )

    if decimate is not None:
        return filtered[::decimate]
    return filtered


def _block_decimate(
    data: np.ndarray,
    block: int,
    fn: str | Callable,
) -> np.ndarray:
    """Non-overlapping block reduction — fast path for block mean/sum."""
    n = len(data)
    n_blocks = n // block
    trimmed = data[: n_blocks * block].reshape(n_blocks, block)

    if fn == "mean" or fn is np.mean:
        return trimmed.mean(axis=1)
    if fn == "sum" or fn is np.sum:
        return trimmed.sum(axis=1)
    # Generic callable
    return np.array([fn(trimmed[i]) for i in range(n_blocks)], dtype=np.float64)


def smooth(data: np.ndarray, n: int) -> np.ndarray:
    """Uniform moving average of width *n* (port of MATLAB's ``smooth(x, n)``).

    MATLAB's ``smooth`` uses a symmetric window with edge shortening.
    This implementation uses ``scipy.ndimage.uniform_filter1d`` with
    ``mode='nearest'`` (edge replication), which differs slightly at
    boundaries but is equivalent in the interior.
    """
    data = np.asarray(data, dtype=np.float64)
    return uniform_filter1d(data, size=n, mode="nearest")
