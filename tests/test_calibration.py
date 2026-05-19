"""Tests for calibration modules — power spectrum, Lorentzian models, fitting."""

from __future__ import annotations

import numpy as np
import pytest

from salafleezers.calibration.fit import calibrate, lorentz_guess
from salafleezers.calibration.lorentzian import lorentzian_pure
from salafleezers.calibration.power_spectrum import (
    bin_spectrum,
    compute_power_spectrum,
    select_fit_range,
)


class TestPowerSpectrum:
    def test_output_lengths_match(self):
        data = np.random.default_rng(0).normal(0, 1, 1024)
        F, P = compute_power_spectrum(data, fs=62500.0)
        assert len(F) == len(P)
        assert len(F) > 0

    def test_dc_removed(self):
        data = np.ones(1024)  # DC signal
        F, P = compute_power_spectrum(data, fs=62500.0)
        # F should not contain 0
        assert F[0] > 0

    def test_one_sided(self):
        n = 1024
        fs = 62500.0
        data = np.random.default_rng(1).normal(0, 1, n)
        F, P = compute_power_spectrum(data, fs)
        # All frequencies should be < Nyquist
        assert F[-1] < fs / 2 + 1e-6

    def test_bin_spectrum_reduces_length(self):
        F, P = compute_power_spectrum(np.random.randn(10000), fs=62500.0)
        Fb, Pb = bin_spectrum(F, P, n_bin=100)
        assert len(Fb) == len(Pb)
        assert len(Fb) < len(F)

    def test_select_fit_range(self):
        F = np.linspace(10, 30000, 500)
        P = np.ones(500)
        Ff, Pf = select_fit_range(F, P, f_min=100, f_max=20000)
        assert Ff.min() > 100
        assert Ff.max() < 20000


class TestLorentzian:
    def test_pure_lorentzian_shape(self):
        f = np.linspace(100, 30000, 200)
        S = lorentzian_pure([1000.0, 1e-4], f, fs=62500.0)
        assert S.shape == f.shape
        assert np.all(S > 0)

    def test_pure_lorentzian_peak_at_fc(self):
        """Lorentzian should be highest near fc (without aliasing dominating)."""
        fc = 1000.0
        f = np.linspace(1, 5000, 1000)
        S = lorentzian_pure([fc, 1e-4], f, fs=62500.0, n_alias=0)
        peak_f = f[np.argmax(S)]
        # Peak should be at the lowest frequency (since PSD is monotone-decaying for f>0)
        assert peak_f < fc

    def test_pure_lorentzian_decay(self):
        """For f >> fc, PSD should decrease."""
        S = lorentzian_pure([1000.0, 1e-4],
                             np.array([100.0, 10000.0, 30000.0]),
                             fs=62500.0, n_alias=0)
        assert S[0] > S[1] > S[2]


class TestFitting:
    def test_lorentz_guess_rough(self):
        """lorentz_guess should return positive fc and D."""
        rng = np.random.default_rng(5)
        Fb = np.linspace(100, 10000, 200)
        fc_true, D_true = 1500.0, 5e-5
        Pb = lorentzian_pure([fc_true, D_true], Fb, fs=62500.0)
        fc_g, D_g = lorentz_guess(Fb, Pb)
        assert fc_g > 0
        assert D_g > 0

    def test_calibrate_recovers_parameters(self, lorentzian_spectrum):
        """Full calibration on synthetic OU process should recover fc within 20%."""
        x, fs, fc_true, D_true = lorentzian_spectrum
        result = calibrate(x, fs, f_min=100.0, f_max=20000.0, n_alias=0)
        # fc should be within 20% of true value (wide tolerance for short data)
        assert abs(result.fc - fc_true) / fc_true < 0.20
        assert result.alpha > 0
        assert result.kappa > 0

    def test_calibration_result_fields(self, lorentzian_spectrum):
        x, fs, _, _ = lorentzian_spectrum
        result = calibrate(x, fs, f_min=100.0)
        for attr in ("fc", "D", "alpha", "kappa", "drag", "D_theory",
                     "fit_params", "F_fit", "P_fit", "F_full", "P_full"):
            assert hasattr(result, attr)
