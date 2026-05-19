"""Tests for io/reader.py — binary .dat file parsing."""

from __future__ import annotations

import numpy as np
import pytest

from salafleezers.constants import INT16_TO_VOLT
from salafleezers.io.reader import DatFile, read_dat, read_header


class TestReadHeader:
    def test_returns_meta_dict(self, dat_path):
        meta, cmt, offset = read_header(dat_path)
        assert isinstance(meta, dict)
        assert "Fsamp" in meta
        assert "nChannels" in meta
        assert "channelID" in meta
        assert "extraData" in meta

    def test_version_field(self, dat_path):
        meta, _, _ = read_header(dat_path)
        assert meta["filever"] >= 9

    def test_comment_string(self, dat_path):
        _, cmt, _ = read_header(dat_path)
        assert "synthetic" in cmt

    def test_raises_on_old_version(self, tmp_path):
        from tests.conftest import make_dat_file
        bad = make_dat_file(tmp_path / "old.dat", version=8.0)
        with pytest.raises(ValueError, match="version"):
            read_header(bad)


class TestReadDat:
    def test_returns_dat_file(self, dat_path):
        dat = read_dat(dat_path)
        assert isinstance(dat, DatFile)

    def test_channel_names_present(self, dat_path):
        dat = read_dat(dat_path)
        # chnid=2 → must include AX, BX, AY, BY, AS, BS
        for ch in ("AX", "BX", "AY", "BY", "AS", "BS"):
            assert ch in dat.channels, f"Missing channel {ch}"

    def test_volt_conversion(self, tmp_path):
        """Raw int16 values should be divided by 3276.7."""
        from tests.conftest import make_dat_file
        n_ch, n_s = 13, 64
        # All channels = 3276 (≈ 1 V after conversion)
        raw = np.full((n_ch, n_s), 3276, dtype=np.int16)
        dat_p = make_dat_file(tmp_path / "v.dat", n_samples=n_s,
                               n_channels=n_ch, channel_data=raw)
        dat = read_dat(dat_p)
        ax = dat.channels["AX"]
        np.testing.assert_allclose(ax, 3276 * INT16_TO_VOLT, rtol=1e-4)

    def test_time_axis_length(self, dat_path):
        dat = read_dat(dat_path)
        for ch_arr in dat.channels.values():
            assert len(dat.time) == len(ch_arr)

    def test_time_starts_at_dt_over_2(self, dat_path):
        dat = read_dat(dat_path)
        dt = float(dat.meta["Fsamp"])
        np.testing.assert_allclose(dat.time[0], dt / 2, rtol=1e-4)

    def test_fl_sidecar_read(self, dat_with_fl):
        dat_p, _ = dat_with_fl
        dat = read_dat(dat_p)
        assert dat.apd1 is not None
        assert dat.apd2 is not None
        assert len(dat.apd1) > 0

    def test_pos_sidecar_read(self, dat_with_pos):
        dat_p, _ = dat_with_pos
        dat = read_dat(dat_p)
        assert dat.t1f is not None
        assert dat.t2f is not None
        # Synthetic values: T1=60 MHz, T2=70 MHz
        np.testing.assert_allclose(dat.t1f, 60.0, rtol=1e-3)
        np.testing.assert_allclose(dat.t2f, 70.0, rtol=1e-3)

    def test_no_fl_when_extra_data_is_0(self, dat_path):
        dat = read_dat(dat_path)
        assert dat.apd1 is None
        assert dat.apd2 is None

    def test_skip_fl_flag(self, dat_with_fl):
        dat_p, _ = dat_with_fl
        dat = read_dat(dat_p, skip_fl=True)
        assert dat.apd1 is None
