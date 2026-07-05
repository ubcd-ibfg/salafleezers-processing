"""Unit tests for the analysis modules.

These tests use synthetic data to verify algorithmic correctness without
requiring the MATLAB golden fixtures (which are tested separately under
tests/golden/).
"""

from __future__ import annotations

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# analysis.filters
# ---------------------------------------------------------------------------

class TestFilters:
    def test_smooth_constant(self):
        from salafleezers.analysis.filters import smooth
        data = np.ones(100)
        out = smooth(data, 11)
        np.testing.assert_allclose(out, 1.0, atol=1e-10)

    def test_window_filter_mean_block(self):
        from salafleezers.analysis.filters import window_filter
        data = np.arange(12, dtype=float)
        out = window_filter(data, fn="mean", decimate=4)
        expected = np.array([1.5, 5.5, 9.5])
        np.testing.assert_allclose(out, expected, atol=1e-10)

    def test_window_filter_sliding_mean(self):
        from salafleezers.analysis.filters import window_filter
        data = np.ones(50)
        out = window_filter(data, fn="mean", half_width=5)
        np.testing.assert_allclose(out, 1.0, atol=1e-10)

    def test_bilateral_edge_preserving(self):
        from salafleezers.analysis.filters import bilateral_filter
        # Step function: bilateral filter should preserve the step
        data = np.concatenate([np.zeros(50), np.ones(50)]) * 10.0
        out = bilateral_filter(data, spatial_sigma=3.0, intensity_sigma=1.0)
        # Left region should remain near 0, right near 10
        assert float(np.mean(out[:40])) < 1.0
        assert float(np.mean(out[60:])) > 9.0

    def test_backward_compat_import(self):
        """utils.signal still works after the re-export."""
        from salafleezers.utils.signal import window_filter, smooth
        data = np.ones(20)
        assert len(smooth(data, 5)) == 20


# ---------------------------------------------------------------------------
# analysis.crop
# ---------------------------------------------------------------------------

class TestCrop:
    def test_crop_basic(self):
        from salafleezers.analysis.crop import crop
        t = np.linspace(0, 1, 100)
        x = np.random.default_rng(0).standard_normal(100)
        xc, tc = crop(x, t, 0.2, 0.8)
        assert tc[0] >= 0.2
        assert tc[-1] <= 0.8
        assert len(xc) == len(tc)

    def test_trim(self):
        from salafleezers.analysis.crop import trim
        data = np.arange(10, dtype=float)
        assert list(trim(data, 2)) == [2, 3, 4, 5, 6, 7]

    def test_measure(self):
        from salafleezers.analysis.crop import measure
        t = np.linspace(0, 1, 1001)
        x = np.sin(2 * np.pi * t)
        m = measure(x, t, 0.0, 1.0)
        assert m["n_pts"] > 0
        assert abs(m["mean"]) < 0.01   # mean of sin over full cycle ≈ 0

    def test_segment_means(self):
        from salafleezers.analysis.crop import segment_means
        data = np.array([1.0] * 10 + [3.0] * 10)
        steps = np.array([10])
        means = segment_means(data, steps)
        np.testing.assert_allclose(means, [1.0, 3.0])


# ---------------------------------------------------------------------------
# analysis.wlc
# ---------------------------------------------------------------------------

class TestWLC:
    def test_basic_extension_increases_with_force(self):
        from salafleezers.analysis.wlc import xwlc_extension
        F = np.array([1.0, 5.0, 10.0, 20.0])
        x = xwlc_extension(F, Lc=1000.0, P=50.0, S=900.0)
        assert np.all(np.diff(x) > 0), "Extension should increase with force"

    def test_extension_below_contour_length(self):
        from salafleezers.analysis.wlc import xwlc_extension
        F = np.linspace(0.1, 50.0, 100)
        x = xwlc_extension(F, Lc=1000.0, P=50.0, S=900.0)
        assert np.all(x < 1200.0), "Extension should not far exceed Lc"

    def test_bouchiat_consistent_with_basic(self):
        from salafleezers.analysis.wlc import xwlc_extension
        F = np.array([5.0, 10.0, 20.0])
        x_basic = xwlc_extension(F, Lc=1000.0, P=50.0, S=900.0, method="basic")
        x_bouchiat = xwlc_extension(F, Lc=1000.0, P=50.0, S=900.0, method="bouchiat")
        # Should agree within ~5% at moderate forces
        np.testing.assert_allclose(x_bouchiat, x_basic, rtol=0.05)

    def test_fit_recovers_params(self):
        from salafleezers.analysis.wlc import xwlc_extension, fit_force_ext
        P_true, Lc_true, S_true = 50.0, 800.0, 900.0
        F = np.linspace(1.0, 40.0, 50)
        # Low noise, no offsets: ensures stable P-Lc recovery
        x = xwlc_extension(F, Lc=Lc_true, P=P_true, S=S_true) + \
            np.random.default_rng(7).normal(0, 0.5, len(F))
        result = fit_force_ext(
            F, x, P0=55.0, Lc0=850.0, S0=950.0, method="basic", fit_offsets=False
        )
        assert abs(result.P - P_true) / P_true < 0.2, f"P: {result.P:.1f} vs {P_true}"
        assert abs(result.Lc - Lc_true) / Lc_true < 0.05, f"Lc: {result.Lc:.1f} vs {Lc_true}"


# ---------------------------------------------------------------------------
# analysis.stepfind.kv
# ---------------------------------------------------------------------------

class TestKVStepFind:
    def _make_step_data(self, levels, n_per=200, noise=0.5, seed=42):
        rng = np.random.default_rng(seed)
        x = np.concatenate([
            rng.normal(lv, noise, n_per) for lv in levels
        ])
        t = np.arange(len(x)) / 1000.0
        return x, t

    def test_detects_single_step(self):
        from salafleezers.analysis.stepfind.kv import find_steps
        x, t = self._make_step_data([0.0, 10.0])
        result = find_steps(x, t, pen_factor=2.0)
        assert result.n_steps >= 1, "Should detect at least one step"
        # Step should be near the middle
        mid = len(x) // 2
        assert any(abs(int(p) - mid) < 50 for p in result.step_positions), \
            f"Step position {result.step_positions} not near middle {mid}"

    def test_detects_multiple_steps(self):
        from salafleezers.analysis.stepfind.kv import find_steps
        x, t = self._make_step_data([0, 8, 4, 12], n_per=300)
        result = find_steps(x, t, pen_factor=2.0)
        assert result.n_steps >= 3, f"Expected ≥3 steps, got {result.n_steps}"

    def test_flat_trace_no_steps(self):
        from salafleezers.analysis.stepfind.kv import find_steps
        rng = np.random.default_rng(99)
        x = rng.normal(5.0, 0.5, 500)
        result = find_steps(x, pen_factor=2.0)
        assert result.n_steps == 0, f"Expected 0 steps on flat trace, got {result.n_steps}"

    def test_levels_close_to_true(self):
        from salafleezers.analysis.stepfind.kv import find_steps
        true_levels = [0.0, 10.0]
        x, t = self._make_step_data(true_levels, n_per=500, noise=0.3)
        result = find_steps(x, t, pen_factor=2.0)
        np.testing.assert_allclose(
            sorted(result.levels), sorted(true_levels), atol=1.0
        )


# ---------------------------------------------------------------------------
# analysis.stepfind.hmm
# ---------------------------------------------------------------------------

class TestHMMStepFind:
    def test_basic_two_state(self):
        from salafleezers.analysis.stepfind.hmm import find_steps
        rng = np.random.default_rng(5)
        x = np.concatenate([rng.normal(0, 0.5, 200), rng.normal(10, 0.5, 200)])
        result = find_steps(x, n_states=2)
        assert result.n_states == 2
        assert len(result.states) == len(x)
        # Means should bracket the true levels
        means_sorted = sorted(result.means)
        assert means_sorted[0] < 3.0 and means_sorted[1] > 7.0

    def test_hmm_to_steps(self):
        from salafleezers.analysis.stepfind.hmm import find_steps, hmm_to_steps
        rng = np.random.default_rng(10)
        x = np.concatenate([rng.normal(0, 0.5, 100), rng.normal(5, 0.5, 100)])
        result = find_steps(x, n_states=2)
        steps = hmm_to_steps(result)
        assert len(steps) >= 1


# ---------------------------------------------------------------------------
# analysis.velocity
# ---------------------------------------------------------------------------

class TestVelocity:
    def test_savgol_constant_velocity(self):
        from salafleezers.analysis.velocity import savgol_velocity
        t = np.linspace(0, 1, 1001)
        x = 100.0 * t   # constant velocity 100 nm/s
        v = savgol_velocity(x, t, window=11, polyorder=2)
        # Interior should be ~100 nm/s
        np.testing.assert_allclose(v[50:-50], 100.0, rtol=0.01)

    def test_velocity_histogram_shape(self):
        from salafleezers.analysis.velocity import velocity_histogram
        v = np.random.default_rng(0).normal(0, 10, 1000)
        hist = velocity_histogram(v, n_bins=50)
        assert len(hist["counts"]) == 50
        assert len(hist["v_centers"]) == 50


# ---------------------------------------------------------------------------
# analysis.pwd
# ---------------------------------------------------------------------------

class TestPWD:
    def test_single_step_size_detected(self):
        from salafleezers.analysis.pwd import pairwise_distance
        rng = np.random.default_rng(3)
        # Trace with one dominant step size of 8 nm
        levels = np.tile([0.0, 8.0], 50)
        x = levels + rng.normal(0, 0.3, len(levels))
        result = pairwise_distance(x, bins=100)
        # Should have a peak near 8 nm
        assert len(result.step_sizes) > 0
        assert any(abs(s - 8.0) < 2.0 for s in result.step_sizes), \
            f"No peak near 8 nm, got peaks at: {result.step_sizes}"


# ---------------------------------------------------------------------------
# analysis.kinetics
# ---------------------------------------------------------------------------

class TestKinetics:
    def test_single_exponential_fit(self):
        from salafleezers.analysis.kinetics import fit_n_exponential
        rng = np.random.default_rng(0)
        rate_true = 2.0   # s⁻¹
        t = rng.exponential(1.0 / rate_true, 500)
        result = fit_n_exponential(t, n=1)
        assert abs(result.rates[0] - rate_true) / rate_true < 0.2, \
            f"Rate {result.rates[0]:.3f} differs from true {rate_true}"

    def test_extract_dwell_times(self):
        from salafleezers.analysis.kinetics import extract_dwell_times
        time = np.linspace(0, 1, 1000)
        steps = np.array([200, 500, 800])
        dwells = extract_dwell_times(steps, time)
        assert len(dwells) == 4
        np.testing.assert_allclose(np.sum(dwells), time[-1] - time[0], rtol=1e-3)


# ---------------------------------------------------------------------------
# analysis.stats
# ---------------------------------------------------------------------------

class TestStats:
    def test_kde_integrates_to_one(self):
        from salafleezers.analysis.stats import kde
        rng = np.random.default_rng(0)
        data = rng.normal(0, 1, 1000)
        result = kde(data, n_points=1024)
        dx = result.x[1] - result.x[0]
        integral = float(np.sum(result.density) * dx)
        assert abs(integral - 1.0) < 0.01, f"KDE integral = {integral:.4f}"

    def test_msd_fft_brownian(self):
        from salafleezers.analysis.stats import msd_fft
        rng = np.random.default_rng(42)
        dt = 1e-4
        D = 1e4    # nm²/s
        n = 10000
        x = np.cumsum(rng.normal(0, np.sqrt(2 * D * dt), n))
        lags, msd = msd_fft(x, max_lag=500)
        t = lags * dt
        # MSD should be ~2Dt for small lags
        slope = float(np.polyfit(t[1:20], msd[1:20], 1)[0])
        assert abs(slope - 2 * D) / (2 * D) < 0.2, \
            f"MSD slope {slope:.0f} differs from 2D = {2*D:.0f}"

    def test_violin_data_keys(self):
        from salafleezers.analysis.stats import violin_data
        rng = np.random.default_rng(0)
        groups = {"A": rng.normal(0, 1, 100), "B": rng.normal(5, 1, 100)}
        vd = violin_data(groups)
        assert "A" in vd and "B" in vd
        assert vd["A"].median < vd["B"].median
