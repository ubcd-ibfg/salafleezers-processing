"""Velocity analysis — port of ppKVv4.m, sgolaydiff.m, vdist.m, vdist_force.m.

Three approaches to computing velocity from optical tweezers extension data:

1. **Step-based** (``step_velocities``): velocity is the extension change
   divided by the dwell time between consecutive steps, excluding pauses.
2. **Savitzky-Golay derivative** (``savgol_velocity``): instantaneous velocity
   via a polynomial-fit derivative.
3. **Velocity distribution** (``velocity_histogram``): histogram of velocities,
   optionally binned by force.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import savgol_filter

from salafleezers.analysis.stepfind.kv import KVResult


@dataclass
class VelocityResult:
    """Output of a velocity analysis pass."""
    velocities: np.ndarray     # velocity for each step or time point (nm/s)
    times: np.ndarray          # times at which velocities were computed
    pauses: np.ndarray         # boolean mask — True where velocity < threshold
    mean_velocity: float       # mean non-pause velocity (nm/s)
    pause_fraction: float      # fraction of time in pause


# ---------------------------------------------------------------------------
# Step-based velocity (from KV result)
# ---------------------------------------------------------------------------

def step_velocities(
    kv_result: KVResult,
    time: np.ndarray,
    pause_threshold: float = 0.0,
) -> VelocityResult:
    """Compute pause-free velocity from a KV step-detection result.

    Port of ppKVv4.m.

    ``kv_result`` has ``n`` steps and ``n + 1`` levels (one mean extension
    per plateau/segment). Velocity of transition *i* (into segment *i+1*)
    is defined as:
        v_i = (level[i+1] - level[i]) / dwell_time(segment i+1)

    i.e. the level change is divided by how long the trace then dwelt at
    the new level, giving ``n`` velocities -- one per transition. The very
    first segment (before the first detected step) has no preceding
    transition, so it doesn't contribute a velocity.

    Parameters
    ----------
    kv_result:
        Output of :func:`salafleezers.analysis.stepfind.kv.find_steps`.
    time:
        Full time axis matching the original data (seconds).
    pause_threshold:
        Absolute velocity threshold (nm/s) below which a segment is
        classified as a pause.  Default 0 means all steps are moving.

    Returns
    -------
    VelocityResult
    """
    steps = kv_result.step_positions
    levels = kv_result.levels
    if len(steps) == 0:
        return VelocityResult(
            velocities=np.array([]),
            times=np.array([]),
            pauses=np.array([], dtype=bool),
            mean_velocity=0.0,
            pause_fraction=1.0,
        )

    # Step times from full time axis
    t_steps = time[steps]
    # Edge times: t=0 and t=last
    t_all = np.concatenate([[time[0]], t_steps, [time[-1]]])

    # Segment k's dwell time is t_all[k+1] - t_all[k]; drop segment 0 (no
    # preceding transition) so dt lines up 1:1 with dx (n transitions).
    dt = np.diff(t_all)[1:]
    dx = np.diff(levels)
    v = dx / np.where(dt > 0, dt, np.nan)

    pauses = np.abs(v) < pause_threshold
    moving = v[~pauses]
    mean_v = float(np.mean(moving)) if len(moving) > 0 else 0.0
    pause_frac = float(np.sum(dt[pauses]) / np.sum(dt))

    # Midpoint of the arriving segment for each transition.
    t_mid = (t_all[1:-1] + t_all[2:]) / 2

    return VelocityResult(
        velocities=v,
        times=t_mid,
        pauses=pauses,
        mean_velocity=mean_v,
        pause_fraction=pause_frac,
    )


# ---------------------------------------------------------------------------
# Savitzky-Golay derivative
# ---------------------------------------------------------------------------

def savgol_velocity(
    data: np.ndarray,
    time: np.ndarray,
    window: int = 21,
    polyorder: int = 2,
) -> np.ndarray:
    """Instantaneous velocity via Savitzky-Golay derivative.

    Port of sgolaydiff.m.  Wraps ``scipy.signal.savgol_filter(deriv=1)``.

    Parameters
    ----------
    data:
        1-D extension trace (nm).
    time:
        Matching time axis (seconds).  Must be uniformly sampled.
    window:
        SG window length (odd integer, samples).
    polyorder:
        Polynomial order for the SG fit.

    Returns
    -------
    np.ndarray
        Velocity in nm/s, same length as *data*.
    """
    data = np.asarray(data, dtype=np.float64)
    time = np.asarray(time, dtype=np.float64)
    dt = float(np.mean(np.diff(time)))
    if window % 2 == 0:
        window += 1
    return savgol_filter(data, window_length=window, polyorder=polyorder,
                         deriv=1, delta=dt)


# ---------------------------------------------------------------------------
# Velocity distribution (histogram, optionally vs force)
# ---------------------------------------------------------------------------

def velocity_histogram(
    velocities: np.ndarray,
    forces: np.ndarray | None = None,
    n_bins: int = 50,
    v_range: tuple[float, float] | None = None,
    force_bins: int = 5,
) -> dict:
    """Histogram of velocities, optionally binned by force.

    Port of vdist.m and vdist_force.m.

    Parameters
    ----------
    velocities:
        Array of velocity values (nm/s).
    forces:
        Matching force values (pN).  If provided, returns a 2-D histogram
        (velocity × force bins).
    n_bins:
        Number of velocity bins.
    v_range:
        (v_min, v_max) for velocity axis.  Defaults to data extent.
    force_bins:
        Number of force bins (used only when *forces* is provided).

    Returns
    -------
    dict with keys:
        ``counts``, ``v_edges``, ``v_centers``,
        and if forces provided: ``counts_2d``, ``f_edges``, ``f_centers``
    """
    v = np.asarray(velocities, dtype=np.float64)
    finite = np.isfinite(v)
    v = v[finite]

    if v_range is None:
        v_range = (float(np.min(v)), float(np.max(v)))

    counts, v_edges = np.histogram(v, bins=n_bins, range=v_range)
    v_centers = (v_edges[:-1] + v_edges[1:]) / 2

    result: dict = {
        "counts": counts,
        "v_edges": v_edges,
        "v_centers": v_centers,
    }

    if forces is not None:
        f = np.asarray(forces, dtype=np.float64)[finite]
        f_range = (float(np.nanmin(f)), float(np.nanmax(f)))
        counts_2d, v_edges_2d, f_edges = np.histogram2d(
            v, f, bins=[n_bins, force_bins],
            range=[v_range, f_range],
        )
        result["counts_2d"] = counts_2d
        result["f_edges"] = f_edges
        result["f_centers"] = (f_edges[:-1] + f_edges[1:]) / 2

    return result
