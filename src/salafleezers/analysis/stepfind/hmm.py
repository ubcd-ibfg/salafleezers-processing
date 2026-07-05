"""Gaussian-emission HMM + Viterbi step detection.

Port of DataGUIs/StepFind_HMM/fitViterbi*.m and findStepHMM*.m.

The model
---------
K discrete states, each emitting a Gaussian signal:
    p(x | state=k) = N(x; mu_k, sigma_k)

Transitions are modelled by a K×K transition matrix.  Viterbi decoding
finds the most likely state sequence for the observed data.

The initial state means can be seeded from a KV result so that the HMM
refines rather than rediscovers the step structure.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm as scipy_norm


@dataclass
class HMMResult:
    """Result of Gaussian-emission HMM + Viterbi decoding."""
    states: np.ndarray        # state sequence (length N, integer labels)
    means: np.ndarray         # Gaussian mean for each state (length K)
    stds: np.ndarray          # Gaussian std dev for each state (length K)
    transition_matrix: np.ndarray  # K×K transition probability matrix
    log_likelihood: float
    n_states: int


# ---------------------------------------------------------------------------
# Viterbi decoder (pure NumPy, no hmmlearn dependency)
# ---------------------------------------------------------------------------

def _viterbi(
    data: np.ndarray,
    means: np.ndarray,
    stds: np.ndarray,
    A: np.ndarray,
    pi: np.ndarray,
) -> tuple[np.ndarray, float]:
    """Viterbi algorithm for Gaussian-emission HMM.

    Parameters
    ----------
    data:   (N,) observation sequence
    means:  (K,) Gaussian means
    stds:   (K,) Gaussian standard deviations (must be > 0)
    A:      (K, K) row-stochastic transition matrix
    pi:     (K,) initial state probabilities

    Returns
    -------
    path:   (N,) integer state sequence
    log_p:  log probability of the optimal path
    """
    N = len(data)
    K = len(means)
    log_A = np.log(np.clip(A, 1e-300, None))
    log_pi = np.log(np.clip(pi, 1e-300, None))

    # log emission probabilities: (N, K)
    log_emit = np.column_stack([
        scipy_norm.logpdf(data, loc=means[k], scale=max(stds[k], 1e-12))
        for k in range(K)
    ])

    # Viterbi DP tables
    log_delta = np.empty((N, K))
    psi = np.zeros((N, K), dtype=int)

    log_delta[0] = log_pi + log_emit[0]

    for t in range(1, N):
        # (K,K) matrix: log_delta[t-1, j] + log_A[j, k]
        trans_val = log_delta[t - 1, :, None] + log_A   # (K, K)
        psi[t] = np.argmax(trans_val, axis=0)
        log_delta[t] = trans_val[psi[t], np.arange(K)] + log_emit[t]

    # Backtrack
    path = np.empty(N, dtype=int)
    path[-1] = int(np.argmax(log_delta[-1]))
    for t in range(N - 2, -1, -1):
        path[t] = psi[t + 1, path[t + 1]]

    return path, float(np.max(log_delta[-1]))


# ---------------------------------------------------------------------------
# Baum-Welch EM for parameter estimation
# ---------------------------------------------------------------------------

def _baum_welch(
    data: np.ndarray,
    K: int,
    means_init: np.ndarray,
    stds_init: np.ndarray,
    max_iter: int = 100,
    tol: float = 1e-4,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Baum-Welch EM for Gaussian-emission HMM.

    Returns (means, stds, A, pi) after convergence.
    """
    N = len(data)
    means = means_init.copy()
    stds = np.maximum(stds_init.copy(), 1e-6)
    # Uniform transition and initial probabilities
    A = np.full((K, K), 1.0 / K)
    pi = np.full(K, 1.0 / K)

    prev_ll = -np.inf

    for _ in range(max_iter):
        # --- Forward pass ---
        log_emit = np.column_stack([
            scipy_norm.logpdf(data, loc=means[k], scale=stds[k])
            for k in range(K)
        ])   # (N, K)

        # alpha in log-space
        log_alpha = np.empty((N, K))
        log_alpha[0] = np.log(pi) + log_emit[0]
        for t in range(1, N):
            log_alpha[t] = (
                np.logaddexp.reduce(
                    log_alpha[t - 1, :, None] + np.log(A), axis=0
                )
                + log_emit[t]
            )

        # --- Backward pass ---
        log_beta = np.zeros((N, K))
        for t in range(N - 2, -1, -1):
            log_beta[t] = np.logaddexp.reduce(
                np.log(A) + log_emit[t + 1] + log_beta[t + 1], axis=1
            )

        # --- Posteriors ---
        log_gamma = log_alpha + log_beta
        log_gamma -= np.logaddexp.reduce(log_gamma, axis=1, keepdims=True)
        gamma = np.exp(log_gamma)   # (N, K)

        # --- Transition posteriors (ξ) ---
        xi = np.zeros((K, K))
        for t in range(N - 1):
            num = (
                log_alpha[t, :, None]
                + np.log(A)
                + log_emit[t + 1]
                + log_beta[t + 1]
            )
            xi += np.exp(num - np.logaddexp.reduce(num.ravel()))

        # --- M-step ---
        pi = gamma[0] / gamma[0].sum()
        A = xi / xi.sum(axis=1, keepdims=True).clip(1e-300)

        n_k = gamma.sum(axis=0)
        means = (gamma * data[:, None]).sum(axis=0) / n_k.clip(1e-300)
        stds = np.sqrt(
            (gamma * (data[:, None] - means) ** 2).sum(axis=0) / n_k.clip(1e-300)
        ).clip(1e-6)

        ll = float(np.logaddexp.reduce(log_alpha[-1]))
        if abs(ll - prev_ll) < tol:
            break
        prev_ll = ll

    return means, stds, A, pi


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_steps(
    data: np.ndarray,
    n_states: int = 2,
    time: np.ndarray | None = None,
    means_init: np.ndarray | None = None,
    stds_init: np.ndarray | None = None,
    max_em_iter: int = 100,
    em_tol: float = 1e-4,
) -> HMMResult:
    """Detect steps using a Gaussian-emission HMM + Viterbi decoding.

    Parameters
    ----------
    data:
        1-D time series.
    n_states:
        Number of discrete states (≥ 2).
    time:
        Optional time axis (not used for detection, stored for reference).
    means_init:
        Initial state means.  If None, uses K evenly-spaced quantiles of data.
    stds_init:
        Initial state standard deviations.  If None, uses global std / K.
    max_em_iter:
        Maximum Baum-Welch iterations.
    em_tol:
        Log-likelihood convergence tolerance.

    Returns
    -------
    HMMResult
    """
    data = np.asarray(data, dtype=np.float64)
    K = n_states

    if means_init is None:
        quantiles = np.linspace(0.1, 0.9, K)
        means_init = np.quantile(data, quantiles)
    means_init = np.asarray(means_init, dtype=np.float64)

    if stds_init is None:
        stds_init = np.full(K, np.std(data, ddof=1) / K)
    stds_init = np.asarray(stds_init, dtype=np.float64)

    means, stds, A, pi = _baum_welch(
        data, K, means_init, stds_init, max_em_iter, em_tol
    )

    states, log_p = _viterbi(data, means, stds, A, pi)

    return HMMResult(
        states=states,
        means=means,
        stds=stds,
        transition_matrix=A,
        log_likelihood=log_p,
        n_states=K,
    )


def hmm_to_steps(result: HMMResult) -> np.ndarray:
    """Extract step positions (transition indices) from an HMMResult."""
    diff = np.diff(result.states)
    return np.where(diff != 0)[0] + 1
