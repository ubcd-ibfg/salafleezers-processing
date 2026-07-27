"""Tests for the RNAP nucleosome-crossing example (examples/rnap_nuc_crossing).

The ruler analysis has no real ruler data to check against in this repo, so it
is validated against synthetic traces whose geometry is known by construction:
alignment must recover the lattice it was built from, and must refuse traces
that have no lattice in them at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

EXAMPLE_DIR = Path(__file__).resolve().parents[1] / "examples" / "rnap_nuc_crossing"
sys.path.insert(0, str(EXAMPLE_DIR))

ruler = pytest.importorskip("ruler")
synth = pytest.importorskip("synth")

SIM = dict(velocity_bp_s=20.0, ruler_pause_s=6.0, nuc_pause_s=15.0)


@pytest.fixture
def opts() -> ruler.RulerAlignOptions:
    return ruler.RulerAlignOptions()


def test_contour_conversion_round_trips(opts):
    """contour_bp must invert the WLC that xwlc_extension applies."""
    from salafleezers.analysis.wlc import xwlc_extension

    true_bp = np.array([1000.0, 2000.0, 3000.0])
    force = np.full(3, 10.0)
    ext = np.array([
        xwlc_extension(10.0, Lc=bp * ruler.RISE_NM_PER_BP, P=ruler.P_DNA_NM,
                       S=ruler.S_DNA_PN, kT=ruler.KT_PN_NM)[0]
        for bp in true_bp
    ])
    assert ruler.contour_bp(force, ext) == pytest.approx(true_bp, rel=1e-9)


def test_contour_conversion_nans_below_min_force():
    bp = ruler.contour_bp(np.array([0.0, 0.05, 10.0]), np.array([100.0, 100.0, 100.0]))
    assert np.isnan(bp[:2]).all()
    assert np.isfinite(bp[2])


def test_ruler_geometry_matches_howto(opts):
    """The rAopts defaults documented in the how-to."""
    assert (opts.start, opts.nrep, opts.per, opts.pauloc) == (350, 8, 64, 59)
    assert opts.ruler_end_bp == 350 + 8 * 64
    assert len(opts.expected_pauses_bp) == 8
    assert np.all(np.diff(opts.expected_pauses_bp) == 64)


@pytest.mark.parametrize("seed", range(6))
def test_alignment_recovers_the_lattice(opts, seed):
    """Aligned ruler pauses must land on the known lattice."""
    time, force, ext = synth.simulate_trace(
        opts, rng=np.random.default_rng(seed), will_cross=(seed % 2 == 0), **SIM)
    result = ruler.align_to_ruler(time, ruler.contour_bp(force, ext), opts)

    assert result.ok, result.reason
    assert result.n_matched >= opts.min_pauses
    assert result.resultant > 0.8
    # Ruler pauses fall within a few bp of the lattice they were built from.
    assert result.rms_residual_bp < opts.lattice_tol_bp
    # The bp axis is recovered to within a few percent.
    assert result.scale == pytest.approx(1.0, abs=0.05)


@pytest.mark.parametrize("seed", range(6))
def test_crossing_classification(opts, seed):
    will_cross = seed % 2 == 0
    time, force, ext = synth.simulate_trace(
        opts, rng=np.random.default_rng(seed), will_cross=will_cross, **SIM)
    result = ruler.align_to_ruler(time, ruler.contour_bp(force, ext), opts)
    assert result.ok, result.reason
    assert ruler.crossed(result, opts) is will_cross


def test_alignment_rejects_a_trace_with_no_ruler(opts):
    """A pure random walk has no lattice; the fit has to say so."""
    rng = np.random.default_rng(0)
    time = np.arange(20000) / 200.0
    bp = 3000 + np.cumsum(rng.normal(0, 2.0, 20000))
    result = ruler.align_to_ruler(time, bp, opts)
    assert not result.ok
    assert result.reason


def test_alignment_rejects_a_pure_ramp(opts):
    """Steady translocation with no pauses cannot be aligned either."""
    time = np.arange(20000) / 200.0
    bp = 3000 + np.linspace(0, 1000, 20000)
    result = ruler.align_to_ruler(time, bp, opts)
    assert not result.ok


def test_pause_free_velocity_recovers_the_simulated_rate(opts):
    """PFV over the ruler must return the rate the trace was built with."""
    time, force, ext = synth.simulate_trace(
        opts, rng=np.random.default_rng(3), will_cross=True, **SIM)
    result = ruler.align_to_ruler(time, ruler.contour_bp(force, ext), opts)
    assert result.ok, result.reason

    pfv = ruler.pause_free_velocity(result, (opts.start, opts.ruler_end_bp), opts)
    assert pfv.velocity_bp_s == pytest.approx(SIM["velocity_bp_s"], rel=0.25)
    # Most of the ruler is spent paused, not moving.
    assert 0.4 < pfv.pause_fraction < 0.95


def test_residence_time_histogram_peaks_at_the_ruler_pauses(opts):
    """The RTH must show a peak at each expected pause position."""
    traces = synth.simulate_condition(6, cross_fraction=1.0, opts=opts, seed=7, **SIM)
    results = [ruler.align_to_ruler(t, ruler.contour_bp(f, x), opts)
               for t, f, x in traces]
    assert all(r.ok for r in results)

    rth = ruler.residence_time_histogram(results, bin_bp=8.0,
                                         range_bp=(0.0, opts.cross_bp + 200), opts=opts)
    assert rth.n_traces == 6

    # Residence time at each expected pause beats the local background.
    background = np.median(rth.mean_s[rth.mean_s > 0])
    for expected in opts.expected_pauses_bp:
        near = np.abs(rth.centers_bp - expected) <= 12
        assert rth.mean_s[near].max() > 2 * background, f"no peak at {expected} bp"


def test_residence_time_histogram_only_crossed_filter(opts):
    traces = synth.simulate_condition(8, cross_fraction=0.5, opts=opts, seed=11, **SIM)
    results = [ruler.align_to_ruler(t, ruler.contour_bp(f, x), opts)
               for t, f, x in traces]
    all_rth = ruler.residence_time_histogram(results, opts=opts)
    crossed_rth = ruler.residence_time_histogram(results, only_crossed=True, opts=opts)
    assert crossed_rth.n_traces < all_rth.n_traces
    assert crossed_rth.n_traces == sum(ruler.crossed(r, opts) for r in results)
