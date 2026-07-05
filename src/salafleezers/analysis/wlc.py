"""Worm-Like Chain (WLC) and eXtensible WLC (XWLC) models + fitting.

Port of MATLAB originals:
  DataGUIs/ForceExt/XWLC.m          — three-method extension model
  DataGUIs/ForceExt/fitForceExt.m   — least-squares F-x curve fitting
  DataGUIs/ForceExt/getFCs_fx.m     — helper: initial parameter guesses

Physics
-------
The extensible WLC (Odijk 1995) relates end-to-end distance *x* of a
polymer with contour length Lc, persistence length P, and stretch modulus S
to the stretching force *F*:

    x(F) ≈ Lc * [1 − ½√(kT/(P·F)) + F/S]          (basic eWLC)

For force given extension the Marko-Siggia (1995) formula is inverted:

    F(t) = kT/P · [1/(4(1−t)²) − ¼ + t]   where t = x_eff / Lc
    x_eff = x − Lc·F/S   (self-consistent)

A more accurate polynomial correction (Bouchiat et al. 1999,
Biophys J 76:409) is also provided.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from scipy.optimize import brentq, least_squares

# Bouchiat et al. 1999 correction coefficients a2…a7
# F(t) = kT/P * [1/(4*(1-t)^2) - 1/4 + t + sum(a_i * t^(i+2))]
_BOUCHIAT = np.array([
    -0.5164228,   # a2 · t^2
    -2.737418,    # a3 · t^3
     16.07497,    # a4 · t^4
    -38.87607,    # a5 · t^5
     39.49944,    # a6 · t^6
    -14.17718,    # a7 · t^7
])

_KT_DEFAULT = 4.14    # pN·nm  (25 °C)
_P_DEFAULT = 50.0     # nm
_S_DEFAULT = 900.0    # pN  (DNA stretch modulus)


# ---------------------------------------------------------------------------
# Extension given force (forward model)
# ---------------------------------------------------------------------------

def xwlc_extension(
    F: np.ndarray | float,
    Lc: float,
    P: float = _P_DEFAULT,
    S: float = _S_DEFAULT,
    kT: float = _KT_DEFAULT,
    method: Literal["basic", "marko_siggia", "bouchiat"] = "basic",
) -> np.ndarray:
    """Compute end-to-end extension for an array of forces.

    Parameters
    ----------
    F:
        Applied force(s) in pN.  Values ≤ 0 are clipped to a small
        positive number before evaluation.
    Lc:
        Contour length (nm).
    P:
        Persistence length (nm).
    S:
        Stretch modulus (pN).  Use ``np.inf`` for inextensible WLC.
    kT:
        Thermal energy (pN·nm).
    method:
        ``"basic"``         — Odijk/eWLC analytical approximation (default).
        ``"marko_siggia"``  — Full Marko-Siggia formula, numerically inverted.
        ``"bouchiat"``      — Bouchiat et al. (1999) polynomial correction.

    Returns
    -------
    np.ndarray
        Extension(s) in nm, same shape as *F*.
    """
    F = np.atleast_1d(np.asarray(F, dtype=np.float64))
    F = np.clip(F, 1e-6, None)

    if method == "basic":
        return _xwlc_basic(F, Lc, P, S, kT)
    elif method == "marko_siggia":
        return _xwlc_marko_siggia(F, Lc, P, S, kT)
    elif method == "bouchiat":
        return _xwlc_bouchiat(F, Lc, P, S, kT)
    else:
        raise ValueError(f"Unknown method '{method}'; choose basic|marko_siggia|bouchiat")


def _xwlc_basic(F, Lc, P, S, kT):
    """Odijk (1995) extensible WLC: x = Lc*(1 - ½√(kT/(P·F)) + F/S)."""
    x = Lc * (1.0 - 0.5 * np.sqrt(kT / (P * F)) + F / S)
    return x


def _xwlc_marko_siggia(F, Lc, P, S, kT):
    """Marko-Siggia eWLC, numerically inverted for extension."""
    result = np.empty_like(F)
    for i, fi in enumerate(F.ravel()):
        # x_eff = x - Lc * F / S; solve via root-finding
        def _residual(t):
            x_eff = t * Lc
            F_model = (kT / P) * (1.0 / (4.0 * (1.0 - t) ** 2) - 0.25 + t)
            return F_model - fi

        lo, hi = 1e-6, 1.0 - 1e-4
        try:
            t_sol = brentq(_residual, lo, hi, xtol=1e-9, maxiter=200)
        except ValueError:
            t_sol = 0.99
        x_eff = t_sol * Lc
        x = x_eff + Lc * fi / S
        result.ravel()[i] = x
    return result


def _xwlc_bouchiat(F, Lc, P, S, kT):
    """Bouchiat et al. (1999) eWLC: extension via corrected Marko-Siggia."""
    result = np.empty_like(F)
    for i, fi in enumerate(F.ravel()):
        def _residual(t):
            corr = sum(_BOUCHIAT[k] * t ** (k + 2) for k in range(len(_BOUCHIAT)))
            F_model = (kT / P) * (1.0 / (4.0 * (1.0 - t) ** 2) - 0.25 + t + corr)
            return F_model - fi

        try:
            t_sol = brentq(_residual, 1e-6, 1.0 - 1e-4, xtol=1e-9, maxiter=200)
        except ValueError:
            t_sol = 0.99
        x_eff = t_sol * Lc
        x = x_eff + Lc * fi / S
        result.ravel()[i] = x
    return result


# ---------------------------------------------------------------------------
# Force given extension (inverse model — for display, not fitting)
# ---------------------------------------------------------------------------

def xwlc_force(
    x: np.ndarray | float,
    Lc: float,
    P: float = _P_DEFAULT,
    S: float = _S_DEFAULT,
    kT: float = _KT_DEFAULT,
    method: Literal["basic", "marko_siggia", "bouchiat"] = "marko_siggia",
) -> np.ndarray:
    """Compute force for given extension values (numerical inversion).

    Parameters
    ----------
    x:
        Extension(s) in nm.  Values ≥ Lc are clamped to 0.999·Lc.
    """
    x = np.atleast_1d(np.asarray(x, dtype=np.float64))
    x = np.clip(x, 0.0, 0.999 * Lc)
    result = np.empty_like(x)
    for i, xi in enumerate(x.ravel()):
        def _residual(F_try):
            return float(xwlc_extension(F_try, Lc, P, S, kT, method=method)) - xi
        try:
            F_sol = brentq(_residual, 1e-4, 1e4, xtol=1e-6, maxiter=200)
        except ValueError:
            F_sol = np.nan
        result.ravel()[i] = F_sol
    return result


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------

@dataclass
class WLCFitResult:
    """Result of a force-extension WLC fit."""
    P: float               # persistence length, nm
    Lc: float              # contour length, nm
    S: float               # stretch modulus, pN
    x_offset: float        # extension offset, nm
    F_offset: float        # force offset, pN
    method: str
    residuals: np.ndarray  # fit residuals (nm)
    chi2: float            # sum of squared residuals
    F_fit: np.ndarray      # force values used for fit
    x_fit: np.ndarray      # extension values used for fit
    x_model: np.ndarray    # model extension at F_fit values


def fit_force_ext(
    F: np.ndarray,
    x: np.ndarray,
    P0: float = _P_DEFAULT,
    Lc0: float | None = None,
    S0: float = _S_DEFAULT,
    kT: float = _KT_DEFAULT,
    method: Literal["basic", "marko_siggia", "bouchiat"] = "basic",
    fit_S: bool = True,
    fit_offsets: bool = True,
    P_bounds: tuple[float, float] = (1.0, 200.0),
    S_bounds: tuple[float, float] = (50.0, 1e5),
) -> WLCFitResult:
    """Fit a WLC model to an experimental force-extension (F-x) curve.

    Port of fitForceExt.m + getFCs_fx.m.

    The model is:
        x_model(F; P, Lc, S) = xwlc_extension(F - F_offset, Lc, P, S, kT)
                                + x_offset

    Parameters
    ----------
    F, x:
        Arrays of experimental force (pN) and extension (nm).
    P0, Lc0, S0:
        Initial guesses.  If *Lc0* is None it defaults to ``0.95 * max(x)``.
    kT:
        Thermal energy (pN·nm).
    method:
        WLC formulation (see :func:`xwlc_extension`).
    fit_S:
        If False, hold S = S0 fixed.
    fit_offsets:
        If True, fit x_offset and F_offset as free parameters.

    Returns
    -------
    WLCFitResult
    """
    F = np.asarray(F, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)

    # Remove NaN / Inf
    mask = np.isfinite(F) & np.isfinite(x)
    F, x = F[mask], x[mask]

    if Lc0 is None:
        Lc0 = float(np.max(x)) * 1.05

    # Build parameter vector and bounds
    # Core: [P, Lc] — always free
    # Optional: S (if fit_S), x_offset and F_offset (if fit_offsets)
    p0: list[float] = [P0, Lc0]
    lb: list[float] = [P_bounds[0], max(x) * 0.5]
    ub: list[float] = [P_bounds[1], max(x) * 5.0]

    if fit_S:
        p0.append(S0)
        lb.append(S_bounds[0])
        ub.append(S_bounds[1])

    if fit_offsets:
        p0 += [0.0, 0.0]
        lb += [-500.0, -10.0]
        ub += [500.0, 10.0]

    def residuals(params):
        P, Lc = params[0], params[1]
        idx = 2
        S = S0
        if fit_S:
            S = params[idx]; idx += 1
        x_off = 0.0
        F_off = 0.0
        if fit_offsets:
            x_off = params[idx]
            F_off = params[idx + 1]
        F_eff = np.clip(F - F_off, 1e-6, None)
        x_mod = xwlc_extension(F_eff, Lc, P, S, kT, method=method) + x_off
        return x_mod - x

    result = least_squares(
        residuals, p0, bounds=(lb, ub), method="trf",
        ftol=1e-10, xtol=1e-10, gtol=1e-10, max_nfev=10000,
    )

    params = result.x
    P_opt = params[0]
    Lc_opt = params[1]
    idx = 2
    S_opt = S0
    if fit_S:
        S_opt = params[idx]; idx += 1
    x_off = 0.0
    F_off = 0.0
    if fit_offsets:
        x_off = params[idx]
        F_off = params[idx + 1]

    F_eff = np.clip(F - F_off, 1e-6, None)
    x_model = xwlc_extension(F_eff, Lc_opt, P_opt, S_opt, kT, method=method) + x_off
    res = x_model - x

    return WLCFitResult(
        P=float(P_opt),
        Lc=float(Lc_opt),
        S=float(S_opt),
        x_offset=float(x_off),
        F_offset=float(F_off),
        method=method,
        residuals=res,
        chi2=float(np.sum(res ** 2)),
        F_fit=F,
        x_fit=x,
        x_model=x_model,
    )
