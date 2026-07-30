"""Lorentzian fitting and calibration — port of tscalibrate.m.

Calibration pipeline:
  1. Compute one-sided PSD from raw normalised signal.
  2. Bin the PSD (uniform bins of n_bin points).
  3. Initial guess via ``lorentz_guess`` (closed-form linear estimator).
  4. Nonlinear log-space least-squares via scipy.optimize.least_squares
     (mirrors MATLAB lsqnonlin with log-residuals).
  5. Convert fit parameters (fc, D) → physical quantities (alpha, kappa).

Output calibration values:
    fc    : corner frequency (Hz)
    D     : diffusion coefficient (V²·Hz)  (in detector units)
    alpha : position sensitivity (nm/V)
    kappa : trap stiffness (pN/nm)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from scipy.optimize import least_squares

from salafleezers.calibration.lorentzian import lorentzian_pure
from salafleezers.calibration.power_spectrum import (
    bin_spectrum,
    compute_power_spectrum,
    select_fit_range,
)
from salafleezers.constants import (
    BEAD_RADIUS_NM,
    CAL_FMIN_HZ,
    CAL_N_ALIAS,
    CAL_NBIN,
    KT_24C,
    WATER_VISC_24C,
)


@dataclass
class CalibrationResult:
    """Result of a single-detector Lorentzian calibration."""
    fc: float             # corner frequency, Hz
    D: float              # diffusion coeff in detector voltage units, V²·Hz
    alpha: float          # position sensitivity, nm/V
    kappa: float          # trap stiffness, pN/nm
    drag: float           # Stokes drag coefficient, pN·s/nm
    D_theory: float       # theoretical D = kT/drag, nm²/s
    fit_params: np.ndarray  # raw optimiser output [fc, D]
    F_fit: np.ndarray     # frequency axis used for fit
    P_fit: np.ndarray     # PSD points used for fit
    F_full: np.ndarray    # full binned frequency axis (for plotting)
    P_full: np.ndarray    # full binned PSD (for plotting)
    name: str = ""        # detector name, e.g. "AX"
    chi2: float = 0.0      # sum of squared log-space residuals at the optimum
    converged: bool = True  # scipy.optimize.least_squares' reported success flag


def lorentz_guess(
    Fb: np.ndarray,
    Pb: np.ndarray,
) -> tuple[float, float]:
    """Closed-form initial guess for fc and D from a binned Lorentzian PSD.

    Derived from the linear estimator in tscalibrate_lorentzguess.m:
    The Lorentzian S(f) = D/(2π²)/(fc²+f²) implies
        1/S(f) = (2π²/D)·(fc² + f²)
    which is linear in f².  A least-squares line through (f², 1/S) gives fc² and D.

    Parameters
    ----------
    Fb : 1-D array
        Binned frequency axis (Hz).
    Pb : 1-D array
        Binned PSD values (V²/Hz).

    Returns
    -------
    fc_guess : float
    D_guess  : float
    """
    x = Fb ** 2
    y = 1.0 / Pb
    # Fit y = a + b*x  → fc² = a/b,  D = 2π²/b
    A = np.column_stack([np.ones_like(x), x])
    coeffs, *_ = np.linalg.lstsq(A, y, rcond=None)
    a, b = coeffs
    # Guard against degenerate fits (flat spectrum / pure white noise)
    if b <= 0 or a / b < 0:
        # Fall back to a guess at the centre of the frequency range
        fc_guess = float(Fb[len(Fb) // 2])
        D_guess = float(np.mean(Pb) * 2 * np.pi**2 * fc_guess**2)
    else:
        fc_guess = float(np.sqrt(a / b))
        D_guess = float(2 * np.pi**2 / b)
    return max(fc_guess, 1.0), max(D_guess, 1e-20)


def fit_lorentzian(
    F_fit: np.ndarray,
    P_fit: np.ndarray,
    fc_guess: float,
    D_guess: float,
    fs: float,
    n_alias: int = 20,
    model_fn: Callable | None = None,
    full_output: bool = False,
):
    """Nonlinear log-space least-squares fit to a Lorentzian model.

    Minimises ``log(model(x, f)) - log(P)`` — identical to the MATLAB:
        fitfcn = @(x)(log(lzian(x,Fbf,opts)) - lPbf)
        lsqnonlin(fitfcn, Guess, lb, ub)

    Parameters
    ----------
    F_fit, P_fit : 1-D arrays
        Frequency and PSD in the fit range.
    fc_guess, D_guess : float
        Initial parameter guesses.
    fs : float
        Sampling frequency (Hz) — needed for aliasing.
    n_alias : int
        Aliasing order.
    model_fn : callable or None
        Model function ``f(params, F, fs, n_alias) -> PSD``.
        Defaults to :func:`lorentzian_pure`.
    full_output : bool
        If True, also return the raw :class:`scipy.optimize.OptimizeResult`.

    Returns
    -------
    params : np.ndarray, shape (2,)
        Best-fit ``[fc, D]``.
    result : scipy.optimize.OptimizeResult
        Only returned when ``full_output`` is True.
    """
    if model_fn is None:
        model_fn = lorentzian_pure

    log_P = np.log(P_fit)

    def residuals(x: np.ndarray) -> np.ndarray:
        pred = model_fn(x, F_fit, fs, n_alias)
        pred = np.maximum(pred, 1e-30)  # guard against log(0)
        return np.log(pred) - log_P

    x0 = np.array([fc_guess, D_guess], dtype=np.float64)
    lb = np.array([1.0, 1e-20])
    ub = np.array([fs / 2, 1e10])

    result = least_squares(
        residuals,
        x0,
        bounds=(lb, ub),
        method="trf",
        ftol=1e-10,
        xtol=1e-10,
        gtol=1e-10,
        max_nfev=5000,
    )
    if full_output:
        return result.x, result
    return result.x


def calibrate(
    data: np.ndarray,
    fs: float,
    *,
    ra: float = BEAD_RADIUS_NM,
    kt: float = KT_24C,
    wv: float = WATER_VISC_24C,
    f_min: float = CAL_FMIN_HZ,
    f_max: float | None = None,
    n_bin: int = CAL_NBIN,
    n_alias: int = CAL_N_ALIAS,
    name: str = "",
) -> CalibrationResult:
    """Full single-detector Lorentzian calibration pipeline.

    Parameters
    ----------
    data : 1-D array
        Normalised detector signal (volts).
    fs : float
        Sampling frequency (Hz).
    ra : float
        Bead radius (nm).
    kt : float
        Thermal energy kB·T (pN·nm).
    wv : float
        Water viscosity (pN·s/nm²).
    f_min, f_max : float
        Frequency range for fitting (Hz).
    n_bin : int
        Points per spectral bin.
    n_alias : int
        Number of aliasing orders in the Lorentzian model.
    name : str
        Detector name label (e.g. "AX").

    Returns
    -------
    CalibrationResult
    """
    if f_max is None:
        f_max = fs / 2  # Nyquist

    # 1. Power spectrum
    F, P = compute_power_spectrum(data, fs)

    # 2. Bin
    Fb, Pb = bin_spectrum(F, P, n_bin)

    # 3. Select fit range
    Fbf, Pbf = select_fit_range(Fb, Pb, f_min, f_max)
    if len(Fbf) == 0:
        raise ValueError(
            f"No spectrum points fall in the fit range ({f_min:.1f}, {f_max:.1f}) Hz "
            f"-- the binned spectrum spans ({Fb[0]:.1f}, {Fb[-1]:.1f}) Hz. "
            "Widen f_min/f_max or lower n_bin."
        )

    # 4. Initial guess
    fc_guess, D_guess = lorentz_guess(Fbf, Pbf)

    # 5. Optimise
    fit_params, opt_result = fit_lorentzian(
        Fbf, Pbf, fc_guess, D_guess, fs, n_alias, full_output=True
    )
    fc, D_fit = fit_params
    chi2 = float(np.sum(opt_result.fun ** 2))
    converged = bool(opt_result.success)

    # 6. Physical conversion
    # Stokes drag: γ = 6π·η·r
    drag = 6 * np.pi * wv * ra  # pN·s/nm
    D_theory = kt / drag         # theoretical D in nm²/s
    # alpha: position sensitivity (nm/V)
    # D_fit is in V²·Hz = V²/s; D_theory is in nm²/s
    # → alpha² = D_theory / D_fit → alpha = sqrt(D_theory / D_fit)
    alpha = float(np.sqrt(D_theory / D_fit))
    # kappa: trap stiffness (pN/nm)
    # fc = kappa / (2π·γ) → kappa = 2π·γ·fc
    kappa = float(2 * np.pi * drag * fc)

    return CalibrationResult(
        fc=float(fc),
        D=float(D_fit),
        alpha=alpha,
        kappa=kappa,
        drag=drag,
        D_theory=D_theory,
        fit_params=fit_params,
        F_fit=Fbf,
        P_fit=Pbf,
        F_full=Fb,
        P_full=Pb,
        name=name,
        chi2=chi2,
        converged=converged,
    )
