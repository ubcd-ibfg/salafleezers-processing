# Step-finding theory

Detecting discrete steps in a noisy extension (or force) trace — e.g. a molecular motor taking
discrete mechanical steps, or a polymerase adding nucleotides — is the core measurement most of
this instrument exists to make. Two algorithms are implemented,
`salafleezers.analysis.stepfind.{kv,hmm}`.

## Kalafut-Visscher (KV)

Reference: Kalafut & Visscher, *Comput. Phys. Commun.* **179**, 716-723 (2008).

The idea: model the trace as a piecewise-constant staircase, and greedily decide whether adding
another step is justified by how much it reduces the fit's residual sum of squares
($\chi^2$, called "QE" — quadratic error — in the original code), penalized by model
complexity (a Schwarz/Bayesian Information Criterion, SIC/BIC):

1. **Greedy insertion** — for every existing segment, try every possible split point; take the
   split that most reduces total $\chi^2$ across all segments. Accept it only if the
   improvement exceeds a penalty term. Repeat until no split clears the penalty.
2. **Counter-fit (pruning)** — after insertion converges, try removing each existing step;
   remove it if doing so increases $\chi^2$ by less than a (separate) counter-penalty. This
   catches steps that were only locally justified during greedy insertion but aren't globally.

Both passes repeat until nothing changes.

### The penalty

`stepfind/kv.py::find_steps` uses an *absolute* threshold directly on $\chi^2$ improvement — a
fixed BIC-like penalty term:

$$
\text{penalty} = \text{pen\_factor} \cdot \sigma^2 \cdot \ln N
$$

where $\sigma^2 = \text{var(data)}$ and $N$ is the full trace length. A split is accepted
only if it reduces total $\chi^2$ by more than this penalty; `pen_factor` (default 2.0) is the
knob that trades sensitivity (more, smaller steps found) against false positives — tune it
empirically against your data.

## HMM (Hidden Markov Model)

Models the trace as $K$ discrete states, each
emitting a Gaussian signal $p(x\mid\text{state}=k) = \mathcal{N}(x;\mu_k,\sigma_k)$, with
transitions between states governed by a $K\times K$ transition matrix. Unlike KV (which
discovers the number of steps automatically), HMM requires you to specify $K$ (`--n-states`)
up front.

`stepfind/hmm.py` implements the Viterbi algorithm from scratch in pure NumPy (no `hmmlearn`
dependency) to find the single most likely state sequence given the observed data and model —
the standard dynamic-programming decoder, computed in log-space for numerical stability. This
is decoding only (given a model, find the best state path); the transition matrix and per-state
means/variances themselves are estimated separately before decoding (see the module for the
current initialization strategy, which can be seeded from a KV result so the HMM refines an
existing step-find rather than discovering structure from scratch).

## Which to use

KV is the default, and is what's golden-tested against an independently computed reference. HMM is useful when
you have a strong prior on the number of states (e.g. a system with a known number of discrete
conformations) and want the noise model to be explicit rather than emergent from the greedy
penalty. Both are exposed identically through the CLI (`sfz stepfind --algorithm kv|hmm`) and
the GUI's step-find controls.
