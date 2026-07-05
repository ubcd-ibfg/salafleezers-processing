"""Kalafut-Visscher (KV) step detection — port of BatchKV.m / AFindStepsV5.m.

Algorithm
---------
1. Initialize with 0 steps: fit is the global mean.
2. **Greedy insertion**: iterate over all existing segments; within each
   segment try all possible split positions; pick the split that most
   reduces χ² across all segments.  Insert it if the improvement exceeds
   the SIC/BIC penalty.  Repeat until no step is accepted.
3. **Counter-fit** (pruning): try removing each step; remove it if the χ²
   increase is below the counter penalty (default = insertion penalty).
4. Repeat insertion + counter-fit until convergence.

Reference: Kalafut & Visscher, *Nat Methods* **5**, 751-754 (2008).

Numerical notes
---------------
χ² for a split is computed in O(N_seg) using cumulative sums — fully
vectorized in NumPy.  The worst-case O(N²) is acceptable for typical trace
lengths; a numba JIT path can be dropped in later without changing the API.
"""

from __future__ import annotations

from bisect import bisect_left, insort
from dataclasses import dataclass, field

import numpy as np


@dataclass
class KVResult:
    """Result of Kalafut-Visscher step detection."""
    step_positions: np.ndarray   # integer indices where steps occur (1-based: step at i means the transition is between sample i-1 and i)
    levels: np.ndarray           # mean value in each segment (len = n_steps + 1)
    n_steps: int
    chi2: float                  # final residual sum of squares
    step_times: np.ndarray       # step times (seconds); empty if time not provided


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _chi2_total(data: np.ndarray) -> float:
    """χ² for a single flat segment (sum of squared deviations from mean)."""
    n = len(data)
    if n == 0:
        return 0.0
    s = data.sum()
    return float(data.dot(data) - s * s / n)


def _chi2_all_splits(data: np.ndarray) -> np.ndarray:
    """χ² for every possible split of *data* into two contiguous segments.

    Returns a 1-D array of length ``N-1`` where element *k* is the χ²
    for left = data[:k+1], right = data[k+1:].
    """
    N = len(data)
    x2 = data * data
    cs = np.cumsum(data)
    cs2 = np.cumsum(x2)

    k = np.arange(1, N)   # left segment has k points, right has N-k
    sum_l = cs[k - 1]
    sum_r = cs[-1] - cs[k - 1]
    sum2_l = cs2[k - 1]
    sum2_r = cs2[-1] - cs2[k - 1]

    chi2_l = sum2_l - sum_l ** 2 / k
    chi2_r = sum2_r - sum_r ** 2 / (N - k)
    return chi2_l + chi2_r


def _best_split(
    data: np.ndarray, l: int, r: int, min_pts: int
) -> tuple[int, float, float]:
    """Find the best split position in data[l:r].

    Returns (abs_position, improvement, chi2_split) where
    improvement = chi2_no_split - chi2_split.
    """
    seg = data[l:r]
    N = len(seg)
    if N < 2 * min_pts:
        return -1, -np.inf, np.inf

    chi0 = _chi2_total(seg)
    chi_splits = _chi2_all_splits(seg)

    # Mask out splits that leave fewer than min_pts on either side
    chi_splits[:min_pts - 1] = np.inf
    chi_splits[-(min_pts - 1):] = np.inf

    idx = int(np.argmin(chi_splits))
    best_chi = float(chi_splits[idx])
    improvement = chi0 - best_chi
    return l + idx + 1, improvement, best_chi   # abs position = l + split_idx + 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_steps(
    data: np.ndarray,
    time: np.ndarray | None = None,
    pen_factor: float = 2.0,
    min_step_pts: int = 3,
    max_iter: int | None = None,
    counter_fit: bool = True,
    counter_pen_factor: float | None = None,
) -> KVResult:
    """Kalafut-Visscher step detection.

    Parameters
    ----------
    data:
        1-D time series (force or extension in any consistent units).
    time:
        Matching time axis (seconds).  Used only to populate
        ``KVResult.step_times``; does not affect detection.
    pen_factor:
        Penalty multiplier.  The acceptance threshold is::

            penalty = pen_factor * sigma² * ln(N)

        where σ² = var(data) and N = len(data).  The default value 2 gives
        a BIC-like criterion.  The original KV SIC uses ``pen_factor = 2``.
    min_step_pts:
        Minimum number of points in each segment.
    max_iter:
        Maximum number of steps to insert.  Defaults to ``N // min_step_pts``.
    counter_fit:
        If True, run the counter-fit pruning pass after insertion.
    counter_pen_factor:
        Penalty multiplier for the counter-fit (step removal).  Defaults to
        the same value as *pen_factor*.

    Returns
    -------
    KVResult
    """
    data = np.asarray(data, dtype=np.float64)
    N = len(data)
    if N < 2 * min_step_pts:
        return KVResult(
            step_positions=np.array([], dtype=int),
            levels=np.array([float(np.mean(data))]),
            n_steps=0,
            chi2=float(_chi2_total(data)),
            step_times=np.array([]),
        )

    sigma2 = float(np.var(data, ddof=1))
    if sigma2 == 0:
        sigma2 = 1e-20
    penalty = pen_factor * sigma2 * np.log(N)
    c_penalty = (counter_pen_factor or pen_factor) * sigma2 * np.log(N)

    if max_iter is None:
        max_iter = N // min_step_pts

    # breakpoints: sorted list of step positions (absolute indices)
    breakpoints: list[int] = []

    # ------------------------------------------------------------------ #
    # Greedy insertion pass
    # ------------------------------------------------------------------ #
    for _ in range(max_iter):
        edges = [0] + sorted(breakpoints) + [N]
        best_imp = 0.0
        best_pos = -1

        for i in range(len(edges) - 1):
            pos, imp, _ = _best_split(data, edges[i], edges[i + 1], min_step_pts)
            if imp > best_imp:
                best_imp = imp
                best_pos = pos

        if best_imp <= penalty:
            break
        insort(breakpoints, best_pos)

    # ------------------------------------------------------------------ #
    # Counter-fit pass (pruning)
    # ------------------------------------------------------------------ #
    if counter_fit and breakpoints:
        changed = True
        while changed:
            changed = False
            edges = [0] + sorted(breakpoints) + [N]
            for k in range(1, len(edges) - 1):
                bp = edges[k]
                l, r = edges[k - 1], edges[k + 1]
                chi_split = (
                    _chi2_total(data[l:bp]) + _chi2_total(data[bp:r])
                )
                chi_merged = _chi2_total(data[l:r])
                if chi_merged - chi_split < c_penalty:
                    breakpoints.remove(bp)
                    changed = True
                    break   # restart with updated segment list

    # ------------------------------------------------------------------ #
    # Build output
    # ------------------------------------------------------------------ #
    steps = np.array(sorted(breakpoints), dtype=int)
    edges = [0] + list(steps) + [N]
    levels = np.array([
        float(np.mean(data[edges[i]: edges[i + 1]]))
        for i in range(len(edges) - 1)
    ])
    chi2 = float(sum(_chi2_total(data[edges[i]: edges[i + 1]])
                     for i in range(len(edges) - 1)))

    step_times: np.ndarray
    if time is not None:
        time = np.asarray(time)
        step_times = time[steps] if len(steps) > 0 else np.array([])
    else:
        step_times = np.array([])

    return KVResult(
        step_positions=steps,
        levels=levels,
        n_steps=len(steps),
        chi2=chi2,
        step_times=step_times,
    )
