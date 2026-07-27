"""Synthetic RNAP + molecular-ruler traces, for checking the ruler analysis.

The teaching dataset in `data/Datos Curso Biophysal` contains tether pulls and
two-state hopping, not ruler transcription traces, so there is nothing in it
with a known ruler geometry to validate `ruler.py` against. This module
generates traces whose true geometry is known by construction: an RNAP that
sits at the stall site, transcribes through `nrep` repeats pausing at each
lattice site, and then either crosses the nucleosome or arrests in it.

The trajectory is generated in bp, converted to extension in nm through the
same extensible-WLC the real pipeline inverts, and given Gaussian noise — so a
synthetic trace enters the analysis at exactly the point a processed real trace
does, as a (time, force, extension) triple.
"""

from __future__ import annotations

import numpy as np
from ruler import KT_PN_NM, P_DNA_NM, RISE_NM_PER_BP, S_DNA_PN, RulerAlignOptions

from salafleezers.analysis.wlc import xwlc_extension


def simulate_trace(
    opts: RulerAlignOptions | None = None,
    *,
    force_pn: float = 10.0,
    fs: float = 200.0,
    velocity_bp_s: float = 12.0,
    ruler_pause_s: float = 1.5,
    nuc_pause_s: float = 4.0,
    stall_s: float = 3.0,
    noise_nm: float = 3.0,
    will_cross: bool = True,
    tether_bp: float = 3000.0,
    rng: np.random.Generator | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (time_s, force_pn, extension_nm) for one simulated trace.

    *tether_bp* is the DNA already between the beads at the stall site; the
    transcribed length is added to it, as in the real experiment where the
    polymerase pays out template as it moves.
    """
    opts = opts or RulerAlignOptions()
    rng = rng or np.random.default_rng(0)

    dt = 1.0 / fs
    segments: list[np.ndarray] = [np.full(int(stall_s * fs), 0.0)]
    pos = 0.0

    def translocate(to_bp: float) -> None:
        nonlocal pos
        n = max(1, int(abs(to_bp - pos) / velocity_bp_s * fs))
        segments.append(np.linspace(pos, to_bp, n, endpoint=False))
        pos = to_bp

    def dwell(seconds: float) -> None:
        segments.append(np.full(max(1, int(seconds * fs)), pos))

    # Ruler: translocate to each lattice pause and sit there.
    for target in opts.expected_pauses_bp:
        translocate(float(target))
        dwell(rng.exponential(ruler_pause_s))

    # Nucleosome: entry pause, then either crossing or arrest.
    translocate(float(opts.ruler_end_bp))
    dwell(rng.exponential(nuc_pause_s))
    if will_cross:
        for frac in (0.3, 0.6, 1.0):
            translocate(opts.ruler_end_bp + frac * opts.nuc_length_bp)
            dwell(rng.exponential(nuc_pause_s))
        translocate(opts.cross_bp + 120.0)
        dwell(5.0)
    else:
        translocate(opts.ruler_end_bp + 0.4 * opts.nuc_length_bp)
        dwell(25.0)

    bp = np.concatenate(segments)
    time = np.arange(len(bp)) * dt
    force = np.full(len(bp), force_pn)

    lc_nm = (tether_bp + bp) * RISE_NM_PER_BP
    extension = np.array([
        xwlc_extension(force_pn, Lc=lc, P=P_DNA_NM, S=S_DNA_PN, kT=KT_PN_NM)[0]
        for lc in lc_nm
    ])
    extension += rng.normal(0.0, noise_nm, size=len(extension))
    return time, force, extension


def simulate_condition(
    n_traces: int,
    cross_fraction: float = 0.6,
    opts: RulerAlignOptions | None = None,
    seed: int = 0,
    **kwargs,
) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Simulate one experimental condition — a set of traces, some crossing."""
    rng = np.random.default_rng(seed)
    return [
        simulate_trace(opts, will_cross=(i < round(cross_fraction * n_traces)),
                       rng=rng, **kwargs)
        for i in range(n_traces)
    ]
