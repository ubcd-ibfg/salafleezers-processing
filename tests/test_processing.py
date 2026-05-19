"""Tests for processing modules — offset, normalize, and pipeline."""

from __future__ import annotations

import numpy as np
import pytest

from salafleezers.processing.offset import compute_offset
from salafleezers.processing.normalize import normalize_by_sum, apply_offset


class TestNormalizeBySum:
    def test_basic_division(self):
        sig = np.array([1.0, 2.0, 3.0])
        s   = np.array([2.0, 2.0, 2.0])
        out = normalize_by_sum(sig, s)
        np.testing.assert_allclose(out, [0.5, 1.0, 1.5])

    def test_zero_sum_gives_zero(self):
        sig = np.array([1.0, 2.0])
        s   = np.array([0.0, 2.0])
        out = normalize_by_sum(sig, s)
        assert out[0] == 0.0
        assert out[1] == pytest.approx(1.0)


class TestComputeOffset:
    def test_returns_same_length(self):
        td = np.linspace(0, 10, 1000)
        sig = np.sin(td)
        off_ax, off_td = compute_offset(td, sig, bin_size=0.5)
        assert len(off_ax) == len(off_td)

    def test_constant_signal_gives_constant_offset(self):
        td = np.linspace(0, 10, 500)
        sig = np.full(500, 2.5)
        off_ax, _ = compute_offset(td, sig, bin_size=0.2)
        # All bins should give ~2.5
        np.testing.assert_allclose(off_ax, 2.5, atol=0.05)

    def test_no_nans_in_output(self):
        rng = np.random.default_rng(3)
        td = rng.uniform(0, 20, 200)
        sig = rng.normal(0, 1, 200)
        off_ax, off_td = compute_offset(td, sig, bin_size=0.5)
        assert not np.any(np.isnan(off_ax))


class TestApplyOffset:
    def test_removes_constant_offset(self):
        n = 200
        td = np.linspace(0, 10, n)
        data_sig = np.ones(n) * 3.0   # raw signal
        data_sum = np.ones(n) * 2.0   # QPD sum
        # Offset file: same signal/sum → offset = 3/2 = 1.5
        off_sig = np.ones(n) * 3.0
        off_sum = np.ones(n) * 2.0
        off_td  = td

        result = apply_offset(data_sig, data_sum, td, off_sig, off_sum, off_td)
        # normalized data = 3/2 = 1.5; offset = 1.5 → result ≈ 0
        np.testing.assert_allclose(result, 0.0, atol=1e-6)

    def test_extrapolation_uses_median(self):
        """Values outside the offset range should use median fill."""
        n = 100
        off_td  = np.linspace(5, 15, n)
        off_sig = np.ones(n) * 4.0
        off_sum = np.ones(n) * 2.0
        # Data file TD goes outside offset range
        data_td  = np.array([0.0, 10.0, 20.0])
        data_sig = np.ones(3) * 4.0
        data_sum = np.ones(3) * 2.0

        result = apply_offset(data_sig, data_sum, data_td, off_sig, off_sum, off_td)
        # All should be ≈ 0 (normalized - offset = 2 - 2 = 0)
        np.testing.assert_allclose(result, 0.0, atol=1e-6)


class TestPipelineSmoke:
    """Smoke tests for the full pipeline using synthetic .dat files."""

    def test_process_one_runs_without_error(self, tmp_path):
        """process_one should complete on synthetic files without raising."""
        from tests.conftest import make_dat_file, make_lorentzian_channel_data
        from salafleezers.processing.pipeline import ProcessingOptions, process_one

        n_samples = 65536  # enough for calibration to converge
        n_ch = 13
        fs = 62500.0
        # Calibration file needs Lorentzian spectrum; data/offset can be random
        lor_data = make_lorentzian_channel_data(n_ch, n_samples, fs=fs)
        make_dat_file(tmp_path / "230415_003.dat", n_samples=n_samples,
                      n_channels=n_ch, channel_data=lor_data, fs=fs)
        for num in (1, 2):
            make_dat_file(tmp_path / f"230415_{num:03d}.dat",
                          n_samples=n_samples, n_channels=n_ch, fs=fs)

        opts = ProcessingOptions(verbose=False, f_min=100.0, f_max=20000.0)
        result = process_one(tmp_path, (1, 2, 3), "230415", opts)
        assert result is not None
        assert len(result.time) > 0
        assert len(result.force) == len(result.time)
        assert len(result.extension) == len(result.time)

    def test_zero_signal_force_is_near_zero(self, tmp_path):
        """Zero detector signals should produce near-zero force."""
        from tests.conftest import make_dat_file, make_lorentzian_channel_data
        from salafleezers.processing.pipeline import ProcessingOptions, process_one
        import numpy as np

        n_samples = 65536
        n_ch = 13
        fs = 62500.0
        zeros = np.zeros((n_ch, n_samples), dtype=np.int16)
        # Sum channels must be non-zero to allow normalisation
        zeros[2] = 3277   # AS ≈ 1 V
        zeros[5] = 3277   # BS ≈ 1 V
        lor_data = make_lorentzian_channel_data(n_ch, n_samples, fs=fs)
        # data and offset: all-zero QPD signals; cal: Lorentzian
        for num in (1, 2):
            make_dat_file(tmp_path / f"230415_{num:03d}.dat",
                          n_samples=n_samples, n_channels=n_ch,
                          channel_data=zeros, fs=fs)
        make_dat_file(tmp_path / "230415_003.dat", n_samples=n_samples,
                      n_channels=n_ch, channel_data=lor_data, fs=fs)

        result = process_one(tmp_path, (1, 2, 3), "230415",
                             ProcessingOptions(verbose=False,
                                              f_min=100.0, f_max=20000.0))
        np.testing.assert_allclose(result.force, 0.0, atol=1e-6)
