"""Signal normalization and offset subtraction.

Ports the normalization logic from ProcessOneDataV2.m and tsprocess.m.

The pipeline for each detector axis (e.g. AX) is:
  1. Normalize by QPD sum:        norm = ax / sum_signal
  2. Subtract offset interpolated over trap-delta:
        offset(td) = interp1(off_td, off_ax/off_sum, td, 'linear', median(...))
  3. Return: (ax / sum_signal) - offset(td)

The scipy.interpolate.interp1d with fill_value=median exactly reproduces
MATLAB's interp1(..., 'linear', median(...)) extrapolation.
"""

from __future__ import annotations

import numpy as np
from scipy.interpolate import interp1d


def normalize_by_sum(
    signal: np.ndarray,
    sum_signal: np.ndarray,
) -> np.ndarray:
    """Divide detector signal by the QPD sum channel.

    Parameters
    ----------
    signal : 1-D array
        Raw detector channel (e.g. AX), volts.
    sum_signal : 1-D array
        QPD sum channel (e.g. AS), volts.  Must be same length.

    Returns
    -------
    np.ndarray
        Normalised signal (dimensionless).
    """
    sum_sig = np.asarray(sum_signal, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(sum_sig != 0,
                        np.asarray(signal, dtype=np.float64) / sum_sig,
                        0.0)


def apply_offset(
    data_signal: np.ndarray,
    data_sum: np.ndarray,
    data_td: np.ndarray,
    off_signal: np.ndarray,
    off_sum: np.ndarray,
    off_td: np.ndarray,
) -> np.ndarray:
    """Subtract the trap-position-dependent offset from normalised data.

    Mirrors the MATLAB call in ProcessOneDataV2.m:
        interp1(off.TX, off.AX./off.AS, rawdat.TX, 'linear', median(off.AX./off.AS))

    Parameters
    ----------
    data_signal : 1-D array
        Data file's raw detector signal (e.g. AX).
    data_sum : 1-D array
        Data file's QPD sum (e.g. AS).
    data_td : 1-D array
        Data file's trap-delta axis (TX, nm).
    off_signal : 1-D array
        Offset file's raw detector signal.
    off_sum : 1-D array
        Offset file's QPD sum.
    off_td : 1-D array
        Offset file's trap-delta axis.

    Returns
    -------
    np.ndarray
        Normalised and offset-corrected signal.
    """
    # Normalise both data and offset files
    norm_data = normalize_by_sum(data_signal, data_sum)
    norm_off = normalize_by_sum(off_signal, off_sum)

    # Build interpolant over the offset's trap-delta range
    med = float(np.nanmedian(norm_off))
    interp = interp1d(
        off_td,
        norm_off,
        kind="linear",
        bounds_error=False,
        fill_value=med,  # extrapolate with median (matches MATLAB convention)
    )
    offset_at_data = interp(data_td)

    return norm_data - offset_at_data
