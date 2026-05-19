"""Power spectrum calculation and binning — port of tscalibrate.m.

The MATLAB formula (tscalibrate.m lines 58–63) is:
    P = abs(fft(inData)).^2 / Fs / (len-1)
    F = (0:len-1)/(len-1)*Fs
    F(1) = []; P(1) = [];   % drop DC
    % uses only F < Fnyq (one-sided)

Note the ``(len-1)`` divisor — NOT ``len``.  This is a specific convention
from the Berkeley OT codebase and must be matched exactly to reproduce the
same alpha/kappa calibration values.
"""

from __future__ import annotations

import numpy as np


def compute_power_spectrum(
    data: np.ndarray,
    fs: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute one-sided power spectrum (DC removed) matching tscalibrate.m.

    Parameters
    ----------
    data : 1-D array
        Time-series signal (normalised, in volts).
    fs : float
        Sampling frequency in Hz.

    Returns
    -------
    F : np.ndarray  (float64)
        Frequency axis (Hz), DC removed, one-sided (F > 0, F < Fnyq).
    P : np.ndarray  (float64)
        Power spectral density (V² / Hz), same length as *F*.
    """
    data = np.asarray(data, dtype=np.float64)
    N = len(data)

    # MATLAB convention: (len-1) not len
    P_full = np.abs(np.fft.fft(data)) ** 2 / fs / (N - 1)
    F_full = np.arange(N) / (N - 1) * fs

    # Drop DC (index 0) and keep only one-sided (F < Fnyq = fs/2)
    # MATLAB drops index 1 (1-based) = index 0 (0-based), then uses len=len-1
    F = F_full[1: N // 2]
    P = P_full[1: N // 2]
    return F, P


def bin_spectrum(
    F: np.ndarray,
    P: np.ndarray,
    n_bin: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Average F and P into bins of *n_bin* points.

    Matches the binValues() nested function in tscalibrate.m:
        binF = (0:nBin:len-1)+1   % bin start indices (1-based in MATLAB)

    Parameters
    ----------
    F, P : 1-D arrays
        Frequency axis and PSD (same length).
    n_bin : int
        Number of points per bin.

    Returns
    -------
    Fb, Pb : np.ndarray
        Binned frequency and PSD arrays.
    """
    n = len(F)
    # Bin start indices (0-based): 0, n_bin, 2*n_bin, ...
    starts = np.arange(0, n - 1, n_bin)
    n_bins = len(starts) - 1  # number of complete bins

    Fb = np.empty(n_bins, dtype=np.float64)
    Pb = np.empty(n_bins, dtype=np.float64)
    for i in range(n_bins):
        sl = slice(starts[i], starts[i + 1])
        Fb[i] = F[sl].mean()
        Pb[i] = P[sl].mean()

    return Fb, Pb


def select_fit_range(
    Fb: np.ndarray,
    Pb: np.ndarray,
    f_min: float,
    f_max: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return the subset of (Fb, Pb) within [f_min, f_max]."""
    mask = (Fb > f_min) & (Fb < f_max)
    return Fb[mask], Pb[mask]
