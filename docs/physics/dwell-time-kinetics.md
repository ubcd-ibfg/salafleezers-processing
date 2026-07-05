# Dwell-time kinetics

Implemented in `salafleezers.analysis.kinetics`, port of `fitnexp*.m` / `ngamdist*.m` /
`phage_dwelldist.m`.

## Why fit a distribution instead of just averaging

A dwell time is how long a system stays in one state before transitioning (e.g. time between
steps from [step-finding](step-finding.md)). If a process is a single memoryless (Poisson)
event with rate \(\lambda\), dwell times follow an exponential distribution
\(P(t) = \lambda e^{-\lambda t}\), whose mean is \(1/\lambda\) — so far so simple. But most real
mechanochemical cycles involve multiple hidden sub-steps (e.g. ATP binding, hydrolysis, product
release for a motor protein), which shows up as **not** a single exponential — the actual rate
constants and how many distinguishable kinetic states exist are exactly what a mixture fit
recovers that a plain mean/histogram can't.

## n-exponential model

\[
P(t) = \sum_{i=1}^{n} a_i\,\lambda_i\, e^{-\lambda_i t}, \qquad \sum_i a_i = 1
\]

\(n=1\) is a simple Poisson process; \(n\ge2\) is a mixture of \(n\) distinguishable rate
processes with fractional weights \(a_i\). Fit by maximum likelihood
(`fit_n_exponential` / `_negloglik_nexp`) — `scipy.optimize.minimize` on the negative
log-likelihood, parameterized in an unconstrained space (log-rates so \(\lambda_i>0\) always;
softmax over the amplitude parameters so \(\sum a_i=1\) always) so the optimizer never needs
explicit bound/constraint handling. Multiple random restarts (`n_restarts`, default 3) guard
against the optimizer landing in a poor local optimum, which mixture-model likelihoods are
prone to (there's also a trivial symmetry — permuting the \(n\) components gives the same
likelihood — the fit sorts components by rate afterward so results are directly comparable
across calls).

## n-gamma model

\[
P(t) = \sum_{i=1}^{n} a_i\,\text{Gamma}(t;\,k_i,\,\theta_i), \qquad \sum_i a_i = 1
\]

A Gamma distribution with integer shape \(k\) is exactly the waiting time for \(k\) sequential
Poisson sub-events — so an n-gamma fit is a natural model when you suspect each "step" you're
timing is actually \(k\) unresolved sub-steps happening back-to-back (e.g. \(k\) nucleotide
additions per observed mechanical step). The shape parameter \(k_i\) coming out of the fit close
to an integer is itself evidence for that many hidden sub-states; \(k=1\) recovers the
exponential case. Fit the same way as n-exponential — MLE via `scipy.optimize.minimize`, using
`scipy.special.gammaln` for a numerically stable log-Gamma-function term in the likelihood.

## Model selection

Both fits report log-likelihood, AIC, and BIC, so you can compare e.g. `n=1` vs. `n=2`
exponential components (or exponential vs. gamma) without just picking whichever fits your
prior expectation — a higher \(n\) will *always* fit the data at least as well by construction
(more free parameters), so AIC/BIC's penalty for extra parameters is what actually tells you
whether the added component is justified rather than overfitting noise.

## Getting dwell times

Unlike the other analyses, kinetics fitting isn't (yet) exposed as its own `sfz` CLI
subcommand — only through the web API (`POST /api/kinetics/fit`) and the GUI's Dwell-times
panel, which derive dwell times as the differences between consecutive step times from a KV/HMM
step-find result you've already run in the same session (`extract_dwell_times` diffs the
step-time array), or accept a list of dwell times directly if you have them from another
source. The underlying `fit_n_exponential`/`fit_n_gamma` functions are plain library calls, so
scripting a `sfz`-style CLI wrapper for them would be a small, self-contained addition — see
[Adding an analysis module](../developer/adding-analysis-module.md).
