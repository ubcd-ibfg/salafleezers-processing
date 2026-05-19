"""Fluorescence APD processing for SalaFleezer.

The _fl sidecar is read by io/reader.py and stored as raw uint16 counts
in DatFile.apd1 / .apd2.  This module provides higher-level processing:
  - downsampling APD counts to match QPD time resolution
  - computing photon rates (counts/s)
  - (optional) background subtraction

Ports the APD sections of timeshareread.m and processAPDScan.m.
"""

from __future__ import annotations

import numpy as np

from salafleezers.utils.signal import window_filter


def downsample_apd(
    apd: np.ndarray,
    apd_dt: float,
    target_dt: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Downsample APD photon counts to match a coarser time grid.

    Parameters
    ----------
    apd : 1-D array (uint16)
        Raw photon counts at APD sampling interval *apd_dt*.
    apd_dt : float
        APD time step (s).
    target_dt : float
        Desired output time step (s) — usually the QPD sample interval.

    Returns
    -------
    counts : np.ndarray (float64)
        Sum of photons per output bin.
    time : np.ndarray (float64)
        Time axis of output bins (centre of each bin, s).
    """
    ratio = int(round(target_dt / apd_dt))
    if ratio < 1:
        ratio = 1

    counts = window_filter(apd.astype(np.float64), fn="sum", decimate=ratio)
    n = len(counts)
    dt_out = ratio * apd_dt
    time = np.arange(n) * dt_out + dt_out / 2
    return counts.astype(np.float64), time.astype(np.float64)


def apd_rate(
    counts: np.ndarray,
    bin_dt: float,
) -> np.ndarray:
    """Convert photon counts per bin to photon rate (counts/s)."""
    return counts / bin_dt


def process_apd_scan(
    apd1: np.ndarray,
    apd2: np.ndarray,
    apd_dt: float,
    scan_n_steps_x: int,
    scan_n_scans: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Reshape and average a 2D APD raster scan.

    Ports the processAPDScan.m logic for AOM/MCL raster scans.
    Forward and backward passes are averaged.

    Parameters
    ----------
    apd1, apd2 : 1-D arrays
        Raw APD counts for each detector.
    apd_dt : float
        APD time step (s).
    scan_n_steps_x : int
        Number of pixels along the fast (X) axis.
    scan_n_scans : int
        Number of scan lines (Y pixels × 2 for bidirectional).

    Returns
    -------
    img1, img2 : np.ndarray, shape (scanNScans//2, scanNStepsX)
        Averaged forward/backward images for APD1 and APD2.
    """
    n_x = scan_n_steps_x
    n_lines = scan_n_scans  # includes both forward and backward

    def _reshape_avg(apd: np.ndarray) -> np.ndarray:
        # Sum over each pixel step, then reshape to [n_lines, n_x]
        n_pts_per_step = len(apd) // (n_x * n_lines)
        blocked = window_filter(apd.astype(np.float64), fn="sum", decimate=n_pts_per_step)
        grid = blocked[: n_x * n_lines].reshape(n_lines, n_x)
        # Average forward and backward passes
        fwd = grid[0::2]
        bwd = grid[1::2, ::-1]  # flip backward scan
        return (fwd + bwd) / 2

    return _reshape_avg(apd1), _reshape_avg(apd2)
