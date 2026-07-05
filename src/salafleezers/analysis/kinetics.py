"""Dwell-time kinetics — port of fitnexp*.m, ngamdist*.m, phage_dwelldist.m.

Fits dwell-time distributions to:
  * n-exponential model:  P(t) = Σ a_i · λ_i · exp(−λ_i·t)
  * n-gamma model:        P(t) = Σ a_i · Gamma(t; k_i, θ_i)

Maximum-likelihood estimation (MLE) via ``scipy.optimize.minimize`` with
analytical gradient where available.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln


@dataclass
class ExpFitResult:
    """Result of n-exponential dwell-time fit."""
    rates: np.ndarray        # rate constants λ_i (s⁻¹)
    amplitudes: np.ndarray   # fractional amplitudes a_i (sum to 1)
    n: int                   # number of components
    log_likelihood: float
    aic: float               # Akaike Information Criterion
    bic: float               # Bayesian Information Criterion
    n_obs: int


@dataclass
class GammaFitResult:
    """Result of n-gamma dwell-time fit."""
    shapes: np.ndarray       # shape parameters k_i
    scales: np.ndarray       # scale parameters θ_i (mean = k·θ)
    amplitudes: np.ndarray   # fractional amplitudes a_i (sum to 1)
    n: int
    log_likelihood: float
    aic: float
    bic: float
    n_obs: int


# ---------------------------------------------------------------------------
# n-exponential MLE
# ---------------------------------------------------------------------------

def _negloglik_nexp(params: np.ndarray, t: np.ndarray) -> float:
    """Negative log-likelihood for n-exponential mixture."""
    n = len(params) // 2
    lam = np.exp(params[:n])    # rates > 0
    raw_a = params[n:]
    a = np.exp(raw_a) / np.sum(np.exp(raw_a))   # softmax → sum to 1

    # pdf = sum_i a_i * lam_i * exp(-lam_i * t)
    pdf = np.sum(a[:, None] * lam[:, None] * np.exp(-lam[:, None] * t[None, :]),
                 axis=0)
    pdf = np.clip(pdf, 1e-300, None)
    return float(-np.sum(np.log(pdf)))


def fit_n_exponential(
    dwell_times: np.ndarray,
    n: int = 1,
    rate_init: np.ndarray | None = None,
    amp_init: np.ndarray | None = None,
    n_restarts: int = 3,
) -> ExpFitResult:
    """Fit an n-exponential dwell-time distribution by MLE.

    Port of fitnexp*.m.

    The model is:
        P(t) = Σ_{i=1}^{n} a_i · λ_i · exp(−λ_i · t)

    with constraint Σ a_i = 1.

    Parameters
    ----------
    dwell_times:
        Array of observed dwell times (seconds > 0).
    n:
        Number of exponential components.
    rate_init:
        Initial rate constants (s⁻¹).  If None, log-spaced between
        1/max(t) and 1/min(t).
    amp_init:
        Initial amplitudes.  If None, uniform (1/n each).
    n_restarts:
        Number of random restarts to avoid local minima.

    Returns
    -------
    ExpFitResult
    """
    t = np.asarray(dwell_times, dtype=np.float64)
    t = t[t > 0]
    N = len(t)

    t_min, t_max = float(t.min()), float(t.max())

    if rate_init is None:
        rate_init = np.geomspace(1.0 / t_max, 1.0 / t_min, n)
    if amp_init is None:
        amp_init = np.ones(n) / n

    best_ll = np.inf
    best_result = None

    rng = np.random.default_rng(42)

    for restart in range(n_restarts):
        if restart == 0:
            lam0 = rate_init
            a0 = amp_init
        else:
            lam0 = np.exp(rng.uniform(np.log(1.0 / t_max), np.log(1.0 / t_min), n))
            a0 = rng.dirichlet(np.ones(n))

        # Parameterize: log(rates) and log(raw_amplitudes) — unconstrained
        p0 = np.concatenate([np.log(lam0), np.log(a0)])

        res = minimize(
            _negloglik_nexp, p0, args=(t,),
            method="Nelder-Mead",
            options={"maxiter": 10000, "xatol": 1e-8, "fatol": 1e-8},
        )
        if res.fun < best_ll:
            best_ll = res.fun
            best_result = res

    assert best_result is not None
    params = best_result.x
    lam = np.exp(params[:n])
    raw_a = params[n:]
    a = np.exp(raw_a) / np.sum(np.exp(raw_a))

    ll = float(-best_ll)
    n_params = 2 * n - 1   # rates + (n-1) free amplitudes
    aic = -2 * ll + 2 * n_params
    bic = -2 * ll + n_params * np.log(N)

    # Sort by rate
    order = np.argsort(lam)
    return ExpFitResult(
        rates=lam[order],
        amplitudes=a[order],
        n=n,
        log_likelihood=ll,
        aic=float(aic),
        bic=float(bic),
        n_obs=N,
    )


# ---------------------------------------------------------------------------
# n-gamma MLE
# ---------------------------------------------------------------------------

def _negloglik_ngamma(params: np.ndarray, t: np.ndarray) -> float:
    """Negative log-likelihood for n-gamma mixture."""
    n = len(params) // 3
    k = np.exp(params[:n])        # shape > 0
    theta = np.exp(params[n:2*n]) # scale > 0
    raw_a = params[2*n:]
    a = np.exp(raw_a) / np.sum(np.exp(raw_a))

    log_t = np.log(t)
    pdf = 0.0
    for i in range(n):
        # Gamma pdf: t^(k-1) * exp(-t/theta) / (Gamma(k) * theta^k)
        log_p_i = (
            (k[i] - 1) * log_t
            - t / theta[i]
            - gammaln(k[i])
            - k[i] * np.log(theta[i])
        )
        pdf = pdf + a[i] * np.exp(log_p_i)
    pdf = np.clip(pdf, 1e-300, None)
    return float(-np.sum(np.log(pdf)))


def fit_n_gamma(
    dwell_times: np.ndarray,
    n: int = 1,
    n_restarts: int = 3,
) -> GammaFitResult:
    """Fit an n-gamma dwell-time distribution by MLE.

    Port of ngamdist*.m.

    The model is:
        P(t) = Σ_{i=1}^{n} a_i · Gamma(t; k_i, θ_i)

    Parameters
    ----------
    dwell_times:
        Array of observed dwell times (seconds > 0).
    n:
        Number of gamma components.
    n_restarts:
        Number of random restarts.

    Returns
    -------
    GammaFitResult
    """
    t = np.asarray(dwell_times, dtype=np.float64)
    t = t[t > 0]
    N = len(t)

    t_mean = float(t.mean())
    t_var = float(t.var(ddof=1)) if len(t) > 1 else t_mean ** 2

    rng = np.random.default_rng(99)
    best_ll = np.inf
    best_result = None

    for restart in range(n_restarts):
        if restart == 0:
            # Method of moments initial guess
            k0 = np.full(n, t_mean ** 2 / max(t_var, 1e-12) / n)
            theta0 = np.full(n, t_var / max(t_mean, 1e-12) / n)
            a0 = np.ones(n) / n
        else:
            k0 = rng.uniform(0.5, 5.0, n)
            theta0 = rng.uniform(0.1, t_mean * 2, n)
            a0 = rng.dirichlet(np.ones(n))

        p0 = np.concatenate([np.log(k0), np.log(theta0), np.log(a0)])
        res = minimize(
            _negloglik_ngamma, p0, args=(t,),
            method="Nelder-Mead",
            options={"maxiter": 20000, "xatol": 1e-8, "fatol": 1e-8},
        )
        if res.fun < best_ll:
            best_ll = res.fun
            best_result = res

    assert best_result is not None
    params = best_result.x
    k = np.exp(params[:n])
    theta = np.exp(params[n:2*n])
    raw_a = params[2*n:]
    a = np.exp(raw_a) / np.sum(np.exp(raw_a))

    ll = float(-best_ll)
    n_params = 3 * n - 1
    aic = -2 * ll + 2 * n_params
    bic = -2 * ll + n_params * np.log(N)

    order = np.argsort(k * theta)   # sort by mean dwell time
    return GammaFitResult(
        shapes=k[order],
        scales=theta[order],
        amplitudes=a[order],
        n=n,
        log_likelihood=ll,
        aic=float(aic),
        bic=float(bic),
        n_obs=N,
    )


# ---------------------------------------------------------------------------
# Dwell-time extraction from step data
# ---------------------------------------------------------------------------

def extract_dwell_times(
    step_positions: np.ndarray,
    time: np.ndarray,
) -> np.ndarray:
    """Extract dwell times between consecutive steps.

    Parameters
    ----------
    step_positions:
        Integer indices of step positions (from KVResult.step_positions).
    time:
        Full time axis (seconds).

    Returns
    -------
    np.ndarray
        Dwell times in seconds (length = len(step_positions) + 1).
    """
    if len(step_positions) == 0:
        return np.array([float(time[-1] - time[0])])
    t_steps = time[step_positions]
    t_edges = np.concatenate([[time[0]], t_steps, [time[-1]]])
    return np.diff(t_edges)
