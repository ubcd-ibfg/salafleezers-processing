"""Trap-delta offset computation — port of tsoffset.m.

tsoffset.m computes the mean detector signal in each trap-delta bin using
a complementary-CDF (CCDF) derivative trick:

    ccdf[i] = sum( ax[td > binshift[i]] )
    n[i]    = count( td > binshift[i] )
    out_ax  = diff(ccdf) / diff(n)         ← mean(ax) per bin

This is equivalent to binning by trap-delta and computing the within-bin
mean of the signal, but expressed via cumulative sums for conciseness.
The Python implementation uses sorted arrays for O(n log n) performance
instead of the O(n·m) MATLAB arrayfun loops.
"""

from __future__ import annotations

import numpy as np


def compute_offset(
    trap_delta: np.ndarray,
    signal: np.ndarray,
    bin_size: float = 0.1,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute the mean signal in each trap-delta bin.

    Direct port of ``tsoffset(intd, inax, binsz)`` in tsoffset.m.

    Parameters
    ----------
    trap_delta : 1-D array
        Trap separation delta (TX values), e.g. in nm.
    signal : 1-D array
        Detector signal to bin (e.g. AX/AS normalised values), same length.
    bin_size : float
        Bin width in the same units as *trap_delta* (default 0.1 nm).

    Returns
    -------
    off_ax : np.ndarray
        Mean signal per bin (length = len(off_td)).
    off_td : np.ndarray
        Bin centre positions corresponding to each entry in *off_ax*.
    """
    td = np.asarray(trap_delta, dtype=np.float64)
    ax = np.asarray(signal, dtype=np.float64)

    # Bin grid matching MATLAB's fmin:binsz:fmax
    fmin = np.floor(td.min() / bin_size) * bin_size
    fmax = np.ceil(td.max()  / bin_size) * bin_size
    out_td = np.arange(fmin, fmax + bin_size * 0.5, bin_size)

    # Bin thresholds (shifted by -binsz/2 so values are centred in bins)
    binshift = out_td - bin_size / 2

    # Efficient CCDF computation via sorting
    sort_idx = np.argsort(td)[::-1]   # descending order
    td_sorted = td[sort_idx]
    ax_sorted = ax[sort_idx]

    # For each threshold in binshift, count how many td_sorted > threshold
    # and accumulate sum(ax) for those points.
    # Use searchsorted on the reversed (ascending after flip) array.
    td_asc = td_sorted[::-1]          # ascending for searchsorted

    # Number of points with td > x: n[i] = N - searchsorted(td_asc, x, 'right')
    n_pts = len(td)
    n = n_pts - np.searchsorted(td_asc, binshift, side="right")

    # Cumulative sum of ax for points with td > x:
    # ccdf[i] = sum(ax[td > binshift[i]])
    # = cumsum from the largest td downward
    ax_cumsum_desc = np.concatenate([[0.0], np.cumsum(ax_sorted)])
    # n[i] points exceed binshift[i], so ccdf[i] = ax_cumsum_desc[n[i]]
    # (sum of the top-n[i] values in the descending-sorted array)
    ccdf = ax_cumsum_desc[n]

    # MATLAB: outoffax = [diff(ccdf)./diff(n),  ccdf(end)/n(end)]
    dn = np.diff(n.astype(np.float64))
    # Avoid division by zero in empty bins
    with np.errstate(invalid="ignore", divide="ignore"):
        off_ax_inner = np.where(dn != 0, np.diff(ccdf) / dn, np.nan)

    last = ccdf[-1] / n[-1] if n[-1] > 0 else np.nan
    off_ax = np.concatenate([off_ax_inner, [last]])

    # Fill NaNs (empty bins) with linear interpolation from neighbours
    if np.any(np.isnan(off_ax)):
        valid = ~np.isnan(off_ax)
        if valid.any():
            xp = np.where(valid)[0]
            fp = off_ax[valid]
            off_ax = np.interp(np.arange(len(off_ax)), xp, fp)

    return off_ax, out_td
