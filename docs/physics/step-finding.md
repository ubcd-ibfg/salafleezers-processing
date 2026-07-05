# Step-finding theory

Detecting discrete steps in a noisy extension (or force) trace — e.g. a molecular motor taking
discrete mechanical steps, or a polymerase adding nucleotides — is the core measurement most of
this instrument exists to make. Two algorithms are implemented,
`salafleezers.analysis.stepfind.{kv,hmm}`.

## Kalafut-Visscher (KV)

Port of `AFindStepsV5.m` / `BatchKV.m`. Reference: Kalafut & Visscher,
*Comput. Phys. Commun.* **179**, 716-723 (2008).

The idea: model the trace as a piecewise-constant staircase, and greedily decide whether adding
another step is justified by how much it reduces the fit's residual sum of squares
(\(\chi^2\), called "QE" — quadratic error — in the original code), penalized by model
complexity (a Schwarz/Bayesian Information Criterion, SIC/BIC):

1. **Greedy insertion** — for every existing segment, try every possible split point; take the
   split that most reduces total \(\chi^2\) across all segments. Accept it only if the
   improvement exceeds a penalty term. Repeat until no split clears the penalty.
2. **Counter-fit (pruning)** — after insertion converges, try removing each existing step;
   remove it if doing so increases \(\chi^2\) by less than a (separate) counter-penalty. This
   catches steps that were only locally justified during greedy insertion but aren't globally.

Both passes repeat until nothing changes.

### The penalty — two different parameterizations

This is the one place where the Python port's numerics **don't directly correspond** to
MATLAB's, even though the algorithm is the same — worth understanding if you're translating a
`pen_factor` you're used to from one implementation to the other (see
[Testing & golden files](../developer/testing-golden-files.md) for how this was discovered and
what was actually validated).

**MATLAB** (`AFindStepsV5.m`) derives a *relative* threshold on the fractional decrease in QE.
Starting from the SIC criterion \((k+2)p + \log n + n\log(QE/n)\), comparing a fit with \(i\)
vs. \(i+1\) steps simplifies (since only the QE term differs materially) to accepting a step
when:
\[
\frac{\Delta QE}{QE_i} < P = e^{-p/n} - 1
\]
where \(p\) is the raw penalty (`single(k)` in MATLAB means "\(k\times\) the default",
default \(p=\ln(n)\)) and \(n\) is the segment length.

**Python** (`stepfind/kv.py::find_steps`) instead uses an *absolute* threshold directly on
\(\chi^2\) improvement:
\[
\text{penalty} = \text{pen\_factor} \cdot \sigma^2 \cdot \ln N
\]
where \(\sigma^2 = \text{var(data)}\) and \(N\) is the full trace length — a fixed BIC-like
penalty rather than one that rescales per-segment with the current fit residual.

Both are legitimate SIC/BIC-flavored penalties for the same algorithm, but `pen_factor=2.0` in
Python is **not** numerically equivalent to `single(2)` in MATLAB. If you're trying to match a
specific MATLAB analysis's step count, don't assume the same number carries over — tune it
empirically against your data instead.

## HMM (Hidden Markov Model)

Port of `fitViterbi*.m` / `findStepHMM*.m`. Models the trace as \(K\) discrete states, each
emitting a Gaussian signal \(p(x\mid\text{state}=k) = \mathcal{N}(x;\mu_k,\sigma_k)\), with
transitions between states governed by a \(K\times K\) transition matrix. Unlike KV (which
discovers the number of steps automatically), HMM requires you to specify \(K\) (`--n-states`)
up front.

`stepfind/hmm.py` implements the Viterbi algorithm from scratch in pure NumPy (no `hmmlearn`
dependency) to find the single most likely state sequence given the observed data and model —
the standard dynamic-programming decoder, computed in log-space for numerical stability. This
is decoding only (given a model, find the best state path); the transition matrix and per-state
means/variances themselves are estimated separately before decoding (see the module for the
current initialization strategy, which can be seeded from a KV result so the HMM refines an
existing step-find rather than discovering structure from scratch).

## Which to use

KV is the default, and is what's golden-tested against real MATLAB output. HMM is useful when
you have a strong prior on the number of states (e.g. a system with a known number of discrete
conformations) and want the noise model to be explicit rather than emergent from the greedy
penalty. Both are exposed identically through the CLI (`sfz stepfind --algorithm kv|hmm`) and
the GUI's step-find controls.
