"""Molecular-ruler alignment and nucleosome-crossing analysis.

Python equivalent of the `Misc/PolRepeats/Fran` stage of BLabOTMatlab —
`procFranp2` (alignment), `procFranp3` (per-condition analysis), `ezFactPlot`
(residence-time histogram) and `procFran_PFVv2` (pause-free velocity).

Everything numerical here is built on `salafleezers.analysis`; this module only
adds the ruler-specific geometry, which the port does not cover.

The experiment
--------------
An RNAP elongation complex is stalled at a defined site. Downstream of it the
template carries a *molecular ruler*: `nrep` tandem copies of a `per`-bp repeat,
each containing a strong pause site at position `pauloc` within the repeat, with
the first repeat starting `start` bp past the stall site. Because the pause
lattice has a known, exact period, the pauses give an internal length standard:
fitting the observed pause spacing to `per` calibrates the trace's bp axis and
locates the stall site as bp 0. Past the ruler sits the nucleosome, and the
question is whether — and how fast — the polymerase crosses it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from salafleezers.analysis.filters import decimate_trace
from salafleezers.analysis.stepfind.kv import find_steps

# DNA elastic parameters, matching the MATLAB DataOptsPopup "XWLC (P, S, kT, h)"
# field documented in the how-to as [50 900 4.14 .34].
P_DNA_NM = 50.0        # persistence length, nm
S_DNA_PN = 900.0       # stretch modulus, pN
KT_PN_NM = 4.14        # thermal energy, pN*nm
RISE_NM_PER_BP = 0.34  # B-DNA rise, nm/bp


# ---------------------------------------------------------------------------
# Contour-length conversion  ("Convert to Contour" in DataOptsPopup)
# ---------------------------------------------------------------------------

def contour_bp(
    force: np.ndarray,
    extension: np.ndarray,
    p: float = P_DNA_NM,
    s: float = S_DNA_PN,
    kt: float = KT_PN_NM,
    rise: float = RISE_NM_PER_BP,
    min_force_pn: float = 0.1,
) -> np.ndarray:
    """Convert a force/extension trace to contour length in base pairs.

    Inverts the Odijk extensible-WLC used by
    :func:`salafleezers.analysis.wlc.xwlc_extension` (``method="basic"``)::

        x = Lc * (1 - 0.5*sqrt(kT/(P*F)) + F/S)   =>   Lc = x / (...)

    so the returned trace is in template bp rather than bead-to-bead nm, which
    removes the force-dependent stretching of the tether. Samples below
    *min_force_pn* are returned as NaN: the WLC diverges at zero force and the
    conversion is meaningless there.
    """
    force = np.asarray(force, dtype=np.float64)
    extension = np.asarray(extension, dtype=np.float64)

    with np.errstate(divide="ignore", invalid="ignore"):
        factor = 1.0 - 0.5 * np.sqrt(kt / (p * force)) + force / s
        lc_nm = extension / factor

    bad = (force < min_force_pn) | ~np.isfinite(lc_nm) | (factor <= 0)
    lc_nm = np.where(bad, np.nan, lc_nm)
    return lc_nm / rise


# ---------------------------------------------------------------------------
# Ruler alignment options  (the MATLAB `rAopts` struct)
# ---------------------------------------------------------------------------

@dataclass
class RulerAlignOptions:
    """Ruler geometry and detection settings.

    The four geometry fields carry the same names and default values as the
    MATLAB `rAopts` struct in the how-to.
    """

    # --- Geometry (rAopts) ---
    start: int = 350     # stall site -> first repeat, bp
    nrep: int = 8        # number of repeats
    per: int = 64        # repeat length, bp
    pauloc: int = 59     # pause position within a repeat, bp

    # --- Trace preparation ---
    decimate: int = 20            # block-average factor applied before stepfinding
    pen_factor: float = 2.0       # KV penalty (see sfz stepfind --pen-factor)
    min_step_pts: int = 3

    # --- Pause detection ---
    min_pause_s: float = 0.5      # absolute floor on a pause dwell
    pause_dwell_factor: float = 2.5   # ...and this many times the median plateau dwell
    lattice_tol_bp: float = 12.0  # max residual for a pause to be called on-lattice
    min_pauses: int = 4           # fewer matched pauses than this = alignment failed

    # --- Scale search (bp-axis calibration error the lattice fit corrects) ---
    scale_range: tuple[float, float] = (0.85, 1.20)
    scale_step: float = 2e-4
    # reject fits this unconvincing (0 = scattered, 1 = perfect)
    min_resultant: float = 0.5

    # --- Nucleosome region ---
    nuc_length_bp: int = 147      # nucleosomal DNA; crossing means clearing this
    cross_margin_bp: float = 10.0

    @property
    def ruler_start_bp(self) -> float:
        """First ruler pause, in bp downstream of the stall site."""
        return self.start + self.pauloc

    @property
    def ruler_end_bp(self) -> float:
        """End of the ruler / entry into the nucleosome, bp."""
        return self.start + self.nrep * self.per

    @property
    def expected_pauses_bp(self) -> np.ndarray:
        """The `nrep` expected ruler pause positions, bp from the stall site."""
        return self.ruler_start_bp + self.per * np.arange(self.nrep)

    @property
    def cross_bp(self) -> float:
        """Position a trace must reach to count as having crossed the nucleosome."""
        return self.ruler_end_bp + self.nuc_length_bp + self.cross_margin_bp


# ---------------------------------------------------------------------------
# Plateau detection
# ---------------------------------------------------------------------------

@dataclass
class Plateaus:
    """Step-finding result reduced to plateau level / start / duration."""
    levels: np.ndarray      # bp
    t_start: np.ndarray     # s
    t_end: np.ndarray       # s
    dwell: np.ndarray       # s

    def pauses(self, min_dwell_s: float, dwell_factor: float = 0.0) -> Plateaus:
        """Plateaus long enough to be pauses rather than translocation.

        Step-finding carves the translocation ramps between pauses into short
        plateaus too, and those outnumber the real pauses. An absolute dwell
        floor alone can't separate them, because how long a ramp plateau lasts
        depends on the transcription rate of that particular trace. So a pause
        must also last *dwell_factor* times the median plateau dwell of its own
        trace, which adapts to the trace's own rate.
        """
        if self.dwell.size == 0:
            return self
        threshold = min_dwell_s
        if dwell_factor > 0:
            threshold = max(threshold, dwell_factor * float(np.median(self.dwell)))
        keep = self.dwell >= threshold
        return Plateaus(self.levels[keep], self.t_start[keep],
                        self.t_end[keep], self.dwell[keep])


def _noise_scaled_pen_factor(data: np.ndarray, pen_factor: float) -> float:
    """Rescale the KV penalty so it is set by the noise, not the signal range.

    `find_steps` builds its acceptance threshold as
    ``pen_factor * var(data) * ln(N)``. On a transcription trace `var(data)` is
    dominated by the several-hundred-bp rise across the ruler, not by the noise,
    so the default `pen_factor=2` demands enormous steps and finds only a
    handful. Estimating the sample-to-sample noise from the first difference
    (``var(diff)/2``, which is insensitive to any slow trend) and rescaling
    makes the effective threshold ``pen_factor * sigma_noise**2 * ln(N)``, which
    is what the Kalafut-Visscher criterion is meant to be.
    """
    total_var = float(np.var(data, ddof=1))
    if total_var <= 0:
        return pen_factor
    noise_var = float(np.var(np.diff(data))) / 2.0
    return pen_factor * max(noise_var, 1e-12) / total_var


def find_plateaus(time: np.ndarray, bp: np.ndarray,
                  opts: RulerAlignOptions) -> Plateaus:
    """Block-average, run Kalafut-Visscher step-finding, return the plateaus."""
    finite = np.isfinite(bp)
    time, bp = np.asarray(time, float)[finite], np.asarray(bp, float)[finite]
    if len(bp) < 2 * opts.min_step_pts:
        empty = np.array([])
        return Plateaus(empty, empty, empty, empty)

    if opts.decimate > 1:
        bp = decimate_trace(bp, opts.decimate)
        time = decimate_trace(time, opts.decimate)

    pen = _noise_scaled_pen_factor(bp, opts.pen_factor)
    kv = find_steps(bp, time=time, pen_factor=pen, min_step_pts=opts.min_step_pts)

    edges = np.concatenate([[0], kv.step_positions, [len(bp)]])
    t_start = time[edges[:-1]]
    t_end = time[np.minimum(edges[1:], len(time) - 1)]
    return Plateaus(kv.levels, t_start, t_end, t_end - t_start)


# ---------------------------------------------------------------------------
# Alignment  (procFranp2)
# ---------------------------------------------------------------------------

@dataclass
class AlignResult:
    """Outcome of aligning one trace to the ruler lattice."""
    ok: bool
    scale: float = 1.0            # multiplicative correction to the bp axis
    offset: float = 0.0           # additive shift, applied after scaling
    n_matched: int = 0            # ruler pauses found on-lattice
    resultant: float = np.nan     # lattice-fit quality, 0 (scattered) to 1 (perfect)
    rms_residual_bp: float = np.nan
    reason: str = ""
    time: np.ndarray = field(default_factory=lambda: np.array([]))
    bp: np.ndarray = field(default_factory=lambda: np.array([]))  # aligned trace
    pause_bp: np.ndarray = field(default_factory=lambda: np.array([]))
    pause_dwell_s: np.ndarray = field(default_factory=lambda: np.array([]))

    @property
    def max_bp(self) -> float:
        return float(np.nanmax(self.bp)) if self.bp.size else np.nan


def _lattice_fit(
    levels: np.ndarray,
    weights: np.ndarray,
    period: float,
    scale_range: tuple[float, float],
    scale_step: float,
) -> tuple[float, float, float]:
    """Find the bp-axis scale that makes the pause levels most periodic.

    For a trial scale *a*, how well the scaled levels fall on a lattice of
    spacing *period* is measured by the circular resultant

        R(a) = | sum_j w_j * exp(2*pi*i * a*x_j / period) | / sum_j w_j

    which is 1 when every level sits at the same phase and near 0 when the
    phases are scattered. Maximising R over *a* is a weighted periodogram: it
    uses all the pauses at once, so a handful of spurious plateaus picked up
    from the translocation ramps cannot pull the fit off the way a spacing
    median can. The phase of the resultant at the best scale gives the
    sub-repeat offset for free.

    Returns (scale, phase_bp, resultant).
    """
    scales = np.arange(scale_range[0], scale_range[1] + scale_step, scale_step)
    w = weights / weights.sum()
    # (n_scales, n_levels) phasors
    phasors = np.exp(2j * np.pi * np.outer(scales, levels) / period)
    resultant = phasors @ w
    best = int(np.argmax(np.abs(resultant)))
    scale = float(scales[best])
    phase = float((np.angle(resultant[best]) % (2 * np.pi)) * period / (2 * np.pi))
    return scale, phase, float(np.abs(resultant[best]))


def align_to_ruler(
    time: np.ndarray,
    bp: np.ndarray,
    opts: RulerAlignOptions | None = None,
) -> AlignResult:
    """Align one contour-length trace to the molecular-ruler lattice.

    Equivalent of the alignment `procFranp2` performs. Three stages:

    1. **Scale.** The ruler pauses are known to be exactly `per` bp apart, so
       the scale factor that makes the measured pause levels most periodic is
       the one that calibrates the bp axis (see :func:`_lattice_fit`). This
       absorbs error in the WLC parameters and in the trap calibration, both of
       which stretch the bp axis multiplicatively.
    2. **Phase.** The same fit gives the position of the lattice modulo `per`,
       which pins the pauses onto their known positions to sub-repeat precision.
    3. **Repeat number.** Phase alone leaves the offset ambiguous by whole
       repeats. That is resolved by requiring the trace's first plateau — the
       stall site, where the polymerase sits before transcription starts — to
       land at bp 0.

    Returns an :class:`AlignResult`; check ``.ok`` before using it, since a
    trace with too few resolvable ruler pauses cannot be aligned.
    """
    opts = opts or RulerAlignOptions()
    plateaus = find_plateaus(time, bp, opts)
    pauses = plateaus.pauses(opts.min_pause_s, opts.pause_dwell_factor)

    if len(pauses.levels) < opts.min_pauses:
        return AlignResult(
            ok=False,
            reason=f"only {len(pauses.levels)} pauses detected "
                   f"(need {opts.min_pauses})")

    order = np.argsort(pauses.levels)
    levels = pauses.levels[order]
    dwell = pauses.dwell[order]
    raw_baseline = float(plateaus.levels[0])

    # --- 1 & 2. scale and phase from the lattice fit, weighted by dwell time ---
    # Only the ruler pauses are periodic. Pauses inside the nucleosome are not,
    # and on a trace that crosses they can outnumber the ruler pauses and bias
    # the fit. Which pauses are in the ruler is only known once the trace is
    # aligned, so fit on everything first, then refit on the pauses that first
    # pass placed inside the ruler, and repeat.
    fit_mask = np.ones(len(levels), dtype=bool)
    scale = 1.0
    offset = 0.0
    resultant = np.nan
    for _ in range(3):
        if fit_mask.sum() < opts.min_pauses:
            break
        scale, phase, resultant = _lattice_fit(
            levels[fit_mask], dwell[fit_mask], opts.per,
            opts.scale_range, opts.scale_step)

        # --- 3. resolve the whole-repeat ambiguity against the stall site ---
        baseline = raw_baseline * scale
        n_rep = round((baseline - phase + opts.ruler_start_bp) / opts.per)
        offset = opts.ruler_start_bp - phase - opts.per * n_rep

        in_ruler = levels * scale + offset
        next_mask = ((in_ruler > -opts.per)
                     & (in_ruler < opts.ruler_end_bp + opts.per / 2))
        if next_mask.sum() < opts.min_pauses or np.array_equal(next_mask, fit_mask):
            break
        fit_mask = next_mask

    # A trace with no ruler in it still yields a best-fit scale, so the fit has
    # to be able to say no. Two things give a spurious fit away: a resultant
    # near zero (the pauses were not periodic at any scale), and a scale that
    # ran into the end of the search range instead of settling inside it.
    if not np.isfinite(resultant) or resultant < opts.min_resultant:
        return AlignResult(ok=False, reason=f"pauses are not periodic "
                                            f"(lattice resultant {resultant:.2f} < "
                                            f"{opts.min_resultant})")
    edge = 2 * opts.scale_step
    if scale <= opts.scale_range[0] + edge or scale >= opts.scale_range[1] - edge:
        return AlignResult(ok=False, reason=f"scale {scale:.3f} hit the edge of the "
                                            f"search range {opts.scale_range}")

    aligned_pauses = levels * scale + offset
    residual = ((aligned_pauses - opts.ruler_start_bp + opts.per / 2) % opts.per
                - opts.per / 2)
    matched = np.abs(residual) < opts.lattice_tol_bp
    matched &= ((aligned_pauses > -opts.per)
                & (aligned_pauses < opts.ruler_end_bp + opts.per))

    if matched.sum() < opts.min_pauses:
        return AlignResult(ok=False, reason=f"only {int(matched.sum())} pauses landed "
                                            f"on the lattice")

    finite = np.isfinite(np.asarray(bp, float))
    return AlignResult(
        ok=True,
        scale=scale,
        offset=offset,
        n_matched=int(matched.sum()),
        resultant=resultant,
        rms_residual_bp=float(np.sqrt(np.mean(residual[matched] ** 2))),
        time=np.asarray(time, float)[finite],
        bp=np.asarray(bp, float)[finite] * scale + offset,
        pause_bp=aligned_pauses,
        pause_dwell_s=pauses.dwell[order],
    )


def crossed(result: AlignResult, opts: RulerAlignOptions | None = None) -> bool:
    """True if the trace ran past the nucleosome (the MATLAB `tfc` flag)."""
    opts = opts or RulerAlignOptions()
    return bool(result.ok and result.max_bp >= opts.cross_bp)


# ---------------------------------------------------------------------------
# Residence-time histogram  (ezFactPlot)
# ---------------------------------------------------------------------------

@dataclass
class RTH:
    """Residence-time histogram for one condition."""
    centers_bp: np.ndarray
    mean_s: np.ndarray       # mean residence time per bin, s/bp-bin
    sem_s: np.ndarray        # standard error across traces
    n_traces: int

    @property
    def ccdf(self) -> np.ndarray:
        """Fraction of traces still going at or past each bin (survival curve)."""
        total = self.mean_s.sum()
        if total <= 0:
            return np.zeros_like(self.mean_s)
        return 1.0 - np.cumsum(self.mean_s) / total


def residence_time_histogram(
    results: list[AlignResult],
    bin_bp: float = 1.0,
    range_bp: tuple[float, float] = (0.0, 1200.0),
    only_crossed: bool = False,
    opts: RulerAlignOptions | None = None,
) -> RTH:
    """Time spent per bp bin, averaged over the traces of one condition.

    This is what `ezFactPlot` plots: each trace contributes a histogram of its
    own dwell time against position, and the condition's curve is the mean over
    traces, with the spread reported as a standard error. `only_crossed`
    reproduces `struct('onlycross', 1)` — restricting to traces that made it
    past the nucleosome, so the average isn't dominated by traces that stalled.
    """
    opts = opts or RulerAlignOptions()
    edges = np.arange(range_bp[0], range_bp[1] + bin_bp, bin_bp)
    centers = (edges[:-1] + edges[1:]) / 2

    per_trace = []
    for r in results:
        if not r.ok or (only_crossed and not crossed(r, opts)):
            continue
        dt = np.diff(r.time, prepend=r.time[0])
        counts, _ = np.histogram(r.bp, bins=edges, weights=dt)
        per_trace.append(counts)

    if not per_trace:
        zeros = np.zeros_like(centers)
        return RTH(centers, zeros, zeros, 0)

    stacked = np.vstack(per_trace)
    mean = stacked.mean(axis=0)
    sem = stacked.std(axis=0, ddof=1) / np.sqrt(len(stacked)) if len(stacked) > 1 \
        else np.zeros_like(mean)
    return RTH(centers, mean, sem, len(stacked))


# ---------------------------------------------------------------------------
# Pause-free velocity  (procFran_PFVv2)
# ---------------------------------------------------------------------------

@dataclass
class PFV:
    """Pause-free velocity over one region of the template."""
    region: str
    velocity_bp_s: float     # distance / time spent translocating
    distance_bp: float
    total_s: float
    paused_s: float
    n_pauses: int

    @property
    def pause_fraction(self) -> float:
        return self.paused_s / self.total_s if self.total_s > 0 else np.nan


def pause_free_velocity(
    result: AlignResult,
    region_bp: tuple[float, float],
    opts: RulerAlignOptions | None = None,
    label: str = "",
) -> PFV:
    """Translocation velocity across a template region, excluding pauses.

    Pause-free velocity is the distance covered divided by the time spent
    actually moving::

        v_pf = distance / (total time - time paused)

    Note this is deliberately *not*
    :func:`salafleezers.analysis.velocity.step_velocities`, which divides each
    step's rise by the dwell at the level it arrives on — that folds the pause
    that follows a step into that step's velocity, which is the opposite of
    what "pause-free" means. Pauses here are the long plateaus that
    :meth:`Plateaus.pauses` identifies, the same ones the ruler alignment uses.

    The how-to reads two numbers off `procFran_PFVv2`: the ruler region (naked
    DNA) and the nucleosome region.
    """
    opts = opts or RulerAlignOptions()
    label = label or f"{region_bp[0]:.0f}-{region_bp[1]:.0f} bp"
    nan_result = PFV(label, np.nan, np.nan, np.nan, np.nan, 0)

    if not result.ok:
        return nan_result

    mask = (result.bp >= region_bp[0]) & (result.bp <= region_bp[1])
    if mask.sum() < 10 * opts.min_step_pts:
        return nan_result

    t, bp = result.time[mask], result.bp[mask]
    total = float(t[-1] - t[0])
    if total <= 0:
        return nan_result

    plateaus = find_plateaus(t, bp, opts)
    if plateaus.levels.size < 2:
        return nan_result
    pauses = plateaus.pauses(opts.min_pause_s, opts.pause_dwell_factor)

    distance = float(plateaus.levels[-1] - plateaus.levels[0])
    paused = float(pauses.dwell.sum())
    moving = total - paused
    if moving <= 0 or distance <= 0:
        return PFV(label, np.nan, distance, total, paused, len(pauses.levels))
    return PFV(label, distance / moving, distance, total, paused, len(pauses.levels))


def pfv_by_region(
    result: AlignResult,
    opts: RulerAlignOptions | None = None,
    **kwargs,
) -> list[PFV]:
    """Pause-free velocity on the ruler (naked DNA) and nucleosome regions."""
    opts = opts or RulerAlignOptions()
    return [
        pause_free_velocity(result, (opts.start, opts.ruler_end_bp), opts,
                            label="ruler (naked DNA)", **kwargs),
        pause_free_velocity(result, (opts.ruler_end_bp, opts.cross_bp), opts,
                            label="nucleosome", **kwargs),
    ]
