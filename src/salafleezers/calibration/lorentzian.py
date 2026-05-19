"""Lorentzian power spectrum models — port of Lorentzian.m.

Only lortype=1 (pure Lorentzian with aliasing) is needed for SalaFleezer.
The model is:

    S(f) = sum_{n=-nAlias}^{nAlias} D / (2π²) / (fc² + (f + n·Fs)²)

where:
    fc  = corner frequency (Hz)
    D   = diffusion coefficient (nm²/s)
    Fs  = sampling frequency (Hz)
    nAlias = number of aliasing orders to include
"""

from __future__ import annotations

import numpy as np


def lorentzian_pure(
    params: np.ndarray,
    f: np.ndarray,
    fs: float,
    n_alias: int = 20,
) -> np.ndarray:
    """Pure Lorentzian with aliasing correction (lortype=1).

    Parameters
    ----------
    params : array-like, shape (2,)
        ``[fc, D]`` — corner frequency (Hz) and diffusion coefficient (nm²/s).
    f : 1-D array
        Frequency axis (Hz) at which to evaluate the model.
    fs : float
        Sampling frequency (Hz) used for aliasing sum.
    n_alias : int
        Number of aliasing orders (sum from -n_alias to +n_alias).

    Returns
    -------
    S : np.ndarray
        Power spectral density (same units as D / fc²).
    """
    fc, D = float(params[0]), float(params[1])
    f = np.asarray(f, dtype=np.float64)

    # Aliasing orders: shape (2*n_alias+1, 1) for broadcasting
    n = np.arange(-n_alias, n_alias + 1, dtype=np.float64)[:, np.newaxis]
    # f_shifted shape: (2*n_alias+1, len(f))
    f_shifted = f[np.newaxis, :] + n * fs

    # Sum over aliasing orders
    S = np.sum(D / (2 * np.pi**2) / (fc**2 + f_shifted**2), axis=0)
    return S


def lorentzian_hydro(
    params: np.ndarray,
    f: np.ndarray,
    fs: float,
    n_alias: int = 20,
    ra: float = 500.0,
    wv: float = 9.1e-10,
) -> np.ndarray:
    """Lorentzian with hydrodynamic correction (lortype=2 in tscalibrate.m).

    The hydrodynamic correction accounts for frequency-dependent drag
    on a sphere (Faxén correction / Oseen tensor).  For most SalaFleezer
    calibrations lortype=1 (pure) is sufficient; this is provided for
    completeness.

    Parameters
    ----------
    params : array-like, shape (2,)
        ``[fc, D]``.
    f, fs, n_alias : see lorentzian_pure.
    ra : float
        Bead radius (nm).
    wv : float
        Water viscosity (pN·s/nm²).
    """
    fc, D = float(params[0]), float(params[1])
    f = np.asarray(f, dtype=np.float64)
    n = np.arange(-n_alias, n_alias + 1, dtype=np.float64)[:, np.newaxis]
    f_shifted = f[np.newaxis, :] + n * fs

    # Frequency-dependent drag correction (Stokes + Basset)
    omega = 2 * np.pi * np.abs(f_shifted)
    rho = 1e-21  # water density, kg/nm³
    delta = np.sqrt(2 * wv / (rho * omega + 1e-30))  # penetration depth
    gamma_r = 1 + ra / delta + ra**2 / (9 * delta**2)  # relative drag

    S = np.sum(D / (2 * np.pi**2) / (fc**2 * gamma_r**2 + f_shifted**2), axis=0)
    return S
