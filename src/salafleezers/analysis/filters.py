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
        filtered = uniform_filter1d(data, window_size, mode="nearest")
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

    Uses edge-replication at boundaries (``mode='nearest'``), which differs
    slightly from MATLAB's edge-shortening convention at the boundaries but
    is equivalent in the interior.
    """
    data = np.asarray(data, dtype=np.float64)
    return uniform_filter1d(data, size=n, mode="nearest")


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
