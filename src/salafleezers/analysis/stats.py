"""Statistical utilities — port of kdf.m, violin.m, nhistc.m, msd*.m.

Provides:
  kde        — kernel density estimation (wraps scipy.stats.gaussian_kde)
  violin_data — violin plot summary statistics
  msd_fft    — mean-squared displacement via FFT (O(N log N))
  weighted_histogram — weighted histograms (port of nhistc.m)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import gaussian_kde


# ---------------------------------------------------------------------------
# Kernel density estimation
# ---------------------------------------------------------------------------

@dataclass
class KDEResult:
    """Output of a KDE computation."""
    x: np.ndarray          # evaluation grid
    density: np.ndarray    # estimated density at each x
    bandwidth: float       # effective bandwidth used


def kde(
    data: np.ndarray,
    n_points: int = 512,
    bandwidth: float | str = "scott",
    x_range: tuple[float, float] | None = None,
    weights: np.ndarray | None = None,
) -> KDEResult:
    """Kernel density estimate — port of kdf.m.

    Parameters
    ----------
    data:
        1-D data array.
    n_points:
        Number of evaluation grid points.
    bandwidth:
        Bandwidth selection: ``"scott"`` (default), ``"silverman"``,
        or a positive float.
    x_range:
        (x_min, x_max) for evaluation grid.  Defaults to data ± 3σ.
    weights:
        Optional per-point weights.

    Returns
    -------
    KDEResult
    """
    data = np.asarray(data, dtype=np.float64)
    finite = np.isfinite(data)
    data = data[finite]
    if weights is not None:
        weights = np.asarray(weights, dtype=np.float64)[finite]

    if x_range is None:
        std = float(np.std(data))
        x_range = (float(data.min()) - 3 * std, float(data.max()) + 3 * std)

    x_grid = np.linspace(x_range[0], x_range[1], n_points)

    kernel = gaussian_kde(data, bw_method=bandwidth, weights=weights)
    density = kernel(x_grid)

    bw = float(kernel.factor * np.std(data))

    return KDEResult(x=x_grid, density=density, bandwidth=bw)


# ---------------------------------------------------------------------------
# Violin plot data
# ---------------------------------------------------------------------------

@dataclass
class ViolinData:
    """Data sufficient to draw one violin."""
    x: np.ndarray         # KDE x grid
    density: np.ndarray   # KDE density
    median: float
    quartile_25: float
    quartile_75: float
    whisker_lo: float
    whisker_hi: float
    n: int


def violin_data(
    groups: dict[str, np.ndarray] | list[np.ndarray],
    bandwidth: float | str = "scott",
    iqr_scale: float = 1.5,
) -> dict[str, ViolinData]:
    """Compute violin plot summary for one or more groups.

    Port of violin.m.

    Parameters
    ----------
    groups:
        Dict of label → 1-D data array, or a plain list (labels become "0",
        "1", …).
    bandwidth:
        KDE bandwidth.
    iqr_scale:
        Whisker extent = Q3 + iqr_scale·IQR  (Tukey convention).

    Returns
    -------
    Dict mapping label → ViolinData.
    """
    if isinstance(groups, list):
        groups = {str(i): g for i, g in enumerate(groups)}

    result: dict[str, ViolinData] = {}
    for label, data in groups.items():
        data = np.asarray(data, dtype=np.float64)
        data = data[np.isfinite(data)]
        if len(data) == 0:
            continue
        kd = kde(data, bandwidth=bandwidth)
        q25, q50, q75 = np.percentile(data, [25, 50, 75])
        iqr = q75 - q25
        wlo = float(data[data >= q25 - iqr_scale * iqr].min())
        whi = float(data[data <= q75 + iqr_scale * iqr].max())
        result[label] = ViolinData(
            x=kd.x,
            density=kd.density,
            median=float(q50),
            quartile_25=float(q25),
            quartile_75=float(q75),
            whisker_lo=wlo,
            whisker_hi=whi,
            n=len(data),
        )
    return result


# ---------------------------------------------------------------------------
# Mean-squared displacement via FFT (Calandrini et al. 2011)
# ---------------------------------------------------------------------------

def msd_fft(
    trajectory: np.ndarray,
    max_lag: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Mean-squared displacement using the FFT cross-correlation method.

    Port of msd*.m.  O(N log N) instead of naïve O(N²).

    Reference: Calandrini et al. 2011, *École thématique de la Société
    Française de la Neutronique* 12, 201–232.

    MSD(n) = (1 / (N−n)) * Σ_{t} (x[t+n] − x[t])²
           = (Σ x[n:]² + Σ x[:N-n]² − 2·xcorr(n)) / (N−n)

    Parameters
    ----------
    trajectory:
        1-D position trace (nm, uniform time spacing).
    max_lag:
        Maximum lag to compute.  Defaults to ``N // 2``.

    Returns
    -------
    lags, msd:
        Integer lag indices and MSD values in nm².
    """
    x = np.asarray(trajectory, dtype=np.float64)
    N = len(x)
    if max_lag is None:
        max_lag = N // 2

    # Cross-correlation via FFT: xcorr[n] = Σ_{t=0}^{N-1-n} x[t]*x[t+n]
    x_ext = np.concatenate([x, np.zeros(N)])
    X = np.fft.rfft(x_ext)
    xcorr = np.fft.irfft(X * np.conj(X))[:N]

    # Cumulative sum of squares for the two "sum of squared terms"
    cumx2 = np.concatenate([[0.0], np.cumsum(x ** 2)])

    lags = np.arange(max_lag + 1)
    n_pairs = N - lags   # number of valid (t, t+n) pairs

    # Σ x[n:]² = cumx2[N] - cumx2[n]
    sum_right = cumx2[N] - cumx2[lags]
    # Σ x[:N-n]² = cumx2[N-n]
    # Guard last element (lag=0 → cumx2[N]; lag=max_lag → cumx2[N-max_lag])
    sum_left = np.array([cumx2[N - int(lag)] for lag in lags])

    msd = (sum_right + sum_left - 2.0 * xcorr[:max_lag + 1]) / np.maximum(n_pairs, 1)
    return lags, msd


# ---------------------------------------------------------------------------
# Weighted histogram (port of nhistc.m)
# ---------------------------------------------------------------------------

def weighted_histogram(
    data: np.ndarray,
    bins: int | np.ndarray,
    weights: np.ndarray | None = None,
    density: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Weighted histogram — port of nhistc.m.

    Thin wrapper around ``np.histogram`` that always returns bin centres.

    Returns
    -------
    (centres, counts)
    """
    counts, edges = np.histogram(data, bins=bins, weights=weights, density=density)
    centres = (edges[:-1] + edges[1:]) / 2
    return centres, counts
