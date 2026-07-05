"""Crop, trim and measure utilities for optical tweezers traces.

Ports the crop/select/measure primitives used in PhageGUIv4.m.
"""

from __future__ import annotations

import numpy as np


def crop(
    data: np.ndarray,
    time: np.ndarray,
    t_start: float,
    t_end: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Crop a time series to the window [t_start, t_end].

    Parameters
    ----------
    data:
        1-D signal array.
    time:
        Matching time axis (seconds), same length as *data*.
    t_start, t_end:
        Time bounds (seconds, inclusive).

    Returns
    -------
    (cropped_data, cropped_time)
    """
    mask = (time >= t_start) & (time <= t_end)
    return data[mask], time[mask]


def crop_multi(
    arrays: list[np.ndarray],
    time: np.ndarray,
    t_start: float,
    t_end: float,
) -> tuple[list[np.ndarray], np.ndarray]:
    """Crop multiple arrays sharing the same time axis."""
    mask = (time >= t_start) & (time <= t_end)
    return [a[mask] for a in arrays], time[mask]


def trim(data: np.ndarray, n_pts: int) -> np.ndarray:
    """Remove *n_pts* samples from both ends of *data*."""
    if 2 * n_pts >= len(data):
        raise ValueError("trim n_pts too large for array length")
    return data[n_pts: len(data) - n_pts]


def trim_time(
    data: np.ndarray,
    time: np.ndarray,
    n_pts: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Trim *n_pts* from both ends, updating both data and time."""
    return trim(data, n_pts), trim(time, n_pts)


def measure(
    data: np.ndarray,
    time: np.ndarray,
    t_start: float,
    t_end: float,
) -> dict:
    """Compute basic statistics over a time region of a trace.

    Returns
    -------
    dict with keys: mean, std, median, min, max, n_pts, t_start, t_end, duration
    """
    seg, t = crop(data, time, t_start, t_end)
    if len(seg) == 0:
        return {"n_pts": 0, "t_start": t_start, "t_end": t_end, "duration": 0.0}
    return {
        "mean": float(np.mean(seg)),
        "std": float(np.std(seg, ddof=1)),
        "median": float(np.median(seg)),
        "min": float(np.min(seg)),
        "max": float(np.max(seg)),
        "n_pts": len(seg),
        "t_start": float(t[0]),
        "t_end": float(t[-1]),
        "duration": float(t[-1] - t[0]),
    }


def split_at_steps(
    data: np.ndarray,
    step_positions: np.ndarray,
) -> list[np.ndarray]:
    """Split *data* into segments at integer *step_positions*.

    Parameters
    ----------
    data:
        1-D array.
    step_positions:
        Sorted integer array of split indices (0-based, exclusive left boundary).

    Returns
    -------
    list of sub-arrays (one per segment between consecutive step positions)
    """
    edges = np.concatenate([[0], step_positions, [len(data)]])
    return [data[edges[i]: edges[i + 1]] for i in range(len(edges) - 1)]


def segment_means(data: np.ndarray, step_positions: np.ndarray) -> np.ndarray:
    """Return the mean of each segment defined by *step_positions*."""
    segs = split_at_steps(data, step_positions)
    return np.array([np.mean(s) if len(s) > 0 else np.nan for s in segs])
