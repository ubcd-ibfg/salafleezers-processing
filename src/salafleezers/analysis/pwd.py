"""Pairwise-distance (PWD) analysis — port of calcPWDV1b.m, sumPWD*.m,
findPWDpeaks.m, acorr2.m.

The PWD histogram of a step trace identifies the discrete step sizes present
in the data: each step size *d* appears at offset *d* (and *−d*) in the
pairwise-difference histogram.

FFT-based implementation
------------------------
The pairwise difference histogram is the autocorrelation of the data
histogram:

    PWD(δ) = Σ_{i,j} δ(x_i − x_j − δ) = (h * h̃)(δ)

where h is the histogram of x values and h̃(x) = h(−x) is its reflection.
This is computed efficiently via FFT convolution in O(N log N) for the
histogram step, then O(M log M) for the convolution.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks


@dataclass
class PWDResult:
    """Output of a pairwise-distance analysis."""
    pwd_counts: np.ndarray     # PWD histogram counts (symmetric about 0)
    bin_edges: np.ndarray      # bin edges (length = len(pwd_counts) + 1)
    bin_centers: np.ndarray    # bin centres
    step_sizes: np.ndarray     # detected step-size peaks (positive side, nm)
    peak_heights: np.ndarray   # peak heights at detected step sizes
    autocorr: np.ndarray       # autocorrelation of pwd_counts vs lag


def pairwise_distance(
    data: np.ndarray,
    bins: int | np.ndarray = 200,
    data_range: tuple[float, float] | None = None,
) -> PWDResult:
    """Compute the pairwise-distance histogram of a trace.

    Port of calcPWDV1b.m.

    Parameters
    ----------
    data:
        1-D extension or force trace (nm or pN).
    bins:
        Number of bins (int) or explicit bin edges.
    data_range:
        (min, max) for binning.  Defaults to full data range.

    Returns
    -------
    PWDResult
    """
    data = np.asarray(data, dtype=np.float64)
    data = data[np.isfinite(data)]

    if data_range is None:
        data_range = (float(data.min()), float(data.max()))

    h, edges = np.histogram(data, bins=bins, range=data_range)
    h = h.astype(np.float64)

    # Autocorrelate the histogram via FFT (gives PWD distribution)
    n_fft = 2 * len(h) - 1
    H = np.fft.rfft(h, n=n_fft)
    pwd_full = np.fft.irfft(H * np.conj(H), n=n_fft)
    # Keep the positive-lag half (symmetric, so we fold)
    pwd_counts = pwd_full[:len(h)]

    # Build a δ axis: each bin step in the pwd histogram corresponds to
    # one data-histogram bin width
    bin_width = float(edges[1] - edges[0])
    delta_edges = np.arange(len(pwd_counts) + 1) * bin_width
    delta_centers = (delta_edges[:-1] + delta_edges[1:]) / 2

    # Detect peaks (exclude the central peak at δ=0)
    min_prominence = 0.01 * pwd_counts.max()
    peaks, props = find_peaks(pwd_counts[1:], prominence=min_prominence)
    peaks += 1   # restore offset

    # Autocorrelation of the PWD histogram
    autocorr = _acorr(pwd_counts)

    return PWDResult(
        pwd_counts=pwd_counts,
        bin_edges=delta_edges,
        bin_centers=delta_centers,
        step_sizes=delta_centers[peaks],
        peak_heights=pwd_counts[peaks],
        autocorr=autocorr,
    )


def _acorr(x: np.ndarray) -> np.ndarray:
    """Normalized autocorrelation via FFT — port of acorr2.m."""
    n = len(x)
    x = x - x.mean()
    n_fft = 2 * n - 1
    X = np.fft.rfft(x, n=n_fft)
    acf = np.fft.irfft(X * np.conj(X), n=n_fft)
    acf = acf[:n]
    if acf[0] != 0:
        acf = acf / acf[0]
    return acf


def sum_pwd(
    traces: list[np.ndarray],
    bins: int = 200,
    data_range: tuple[float, float] | None = None,
) -> PWDResult:
    """Sum PWD histograms from multiple traces — port of sumPWD*.m.

    Useful for combining data from many molecules.
    """
    if data_range is None:
        all_data = np.concatenate(traces)
        all_data = all_data[np.isfinite(all_data)]
        data_range = (float(all_data.min()), float(all_data.max()))

    # Use fixed bin edges across all traces
    edges = np.linspace(data_range[0], data_range[1], bins + 1)
    combined: np.ndarray | None = None

    for trace in traces:
        result = pairwise_distance(trace, bins=edges)
        if combined is None:
            combined = result.pwd_counts.copy()
        else:
            combined += result.pwd_counts

    assert combined is not None
    # Recompute peaks on the summed histogram
    bin_width = float(edges[1] - edges[0])
    delta_edges = np.arange(len(combined) + 1) * bin_width
    delta_centers = (delta_edges[:-1] + delta_edges[1:]) / 2

    min_prominence = 0.01 * combined.max()
    peaks, _ = find_peaks(combined[1:], prominence=min_prominence)
    peaks += 1

    return PWDResult(
        pwd_counts=combined,
        bin_edges=delta_edges,
        bin_centers=delta_centers,
        step_sizes=delta_centers[peaks],
        peak_heights=combined[peaks],
        autocorr=_acorr(combined),
    )
