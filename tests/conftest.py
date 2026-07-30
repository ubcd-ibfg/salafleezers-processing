"""Pytest fixtures: synthetic .dat file generators for round-trip testing.

All files are written in the big-endian binary format that SalaFleezer
produces, matching the layout documented in timeshareread.m.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Low-level binary helpers
# ---------------------------------------------------------------------------

def _pack_f8(v: float) -> bytes:
    return struct.pack(">d", v)


def _pack_f8_array(arr) -> bytes:
    return np.asarray(arr, dtype=">f8").tobytes()


def _pack_i2_array(arr) -> bytes:
    return np.asarray(arr, dtype=">i2").tobytes()


def _pack_u4_array(arr) -> bytes:
    return np.asarray(arr, dtype=">u4").tobytes()


def _pack_u8_array(arr) -> bytes:
    return np.asarray(arr, dtype=">u8").tobytes()


# ---------------------------------------------------------------------------
# Synthetic .dat file builder
# ---------------------------------------------------------------------------

def make_lorentzian_channel_data(
    n_ch: int,
    n_samples: int,
    fs: float = 62500.0,
    fc: float = 1000.0,
    seed: int = 42,
) -> np.ndarray:
    """Generate synthetic channel data with channel 0 (AY) having Lorentzian PSD.

    The calibration channels (AX, BX, etc.) need a Lorentzian spectrum to
    allow the optimizer to converge.  All channels get the same OU signal
    scaled to int16 range.
    """
    rng = np.random.default_rng(seed)
    dt = 1.0 / fs
    gamma_dt = 2 * np.pi * fc * dt
    # D chosen so the OU process's stationary std is ~3000 int16 units
    # (std = sqrt(D/(2*pi*fc)) * 3276.7). Anything much smaller and the
    # signal is swamped by int16 quantization noise -- calibrate() then
    # fits the quantization floor instead of the true corner frequency,
    # recovering a wildly wrong fc despite converging "successfully".
    D = 5625.0
    noise = rng.normal(0, np.sqrt(2 * D * dt), n_samples)
    x = np.zeros(n_samples)
    for i in range(1, n_samples):
        x[i] = x[i - 1] * np.exp(-gamma_dt) + noise[i]

    # Convert to int16 (multiply by 3276.7 to invert the reader's division)
    x_int16 = np.clip(x * 3276.7, -32767, 32767).astype(np.int16)
    # Replicate across channels; sum channels (AS, BS) get a constant > 0
    data = np.zeros((n_ch, n_samples), dtype=np.int16)
    for ch in range(n_ch):
        if ch in (2, 5):   # AS and BS (sum channels) — constant ~1V
            data[ch] = np.full(n_samples, 3277, dtype=np.int16)
        else:
            data[ch] = x_int16
    return data


def make_dat_file(
    path: Path,
    *,
    fs: float = 62500.0,
    n_samples: int = 1024,
    n_channels: int = 13,
    channel_id: int = 2,        # SalaFleezer default
    data_type: int = 0,         # regular data
    version: float = 9.0,
    init_mhz: list | None = None,
    extra_data: int = 0,        # 0=none, 1=fl, 2=pos, 3=both
    channel_data: np.ndarray | None = None,
    comment: str = "synthetic test file",
) -> Path:
    """Write a minimal synthetic .dat file in SalaFleezer big-endian format."""
    if init_mhz is None:
        init_mhz = [60.0, 70.0, 80.0, 90.0, 0.0, 0.0]

    # Build header array (13 values minimum)
    fs_raw = fs * 3         # raw sample rate (before averaging)
    dt = 1.0 / fs           # sample interval (decimated)
    hdr = [
        version,            # [0] filever
        fs_raw,             # [1] Fsampraw
        dt,                 # [2] Fsamp  (=1/fs, the decimated interval)
        float(n_channels),  # [3] nChannels
        float(channel_id),  # [4] channelID
        float(data_type),   # [5] datatype
        *init_mhz,          # [6:12] initMHz
        float(extra_data),  # [12] extraData
    ]

    cmt_bytes = comment.encode("latin-1")

    # Build data: [n_channels, n_samples] as int16
    if channel_data is None:
        rng = np.random.default_rng(42)
        channel_data = rng.integers(-1000, 1000, size=(n_channels, n_samples), dtype=np.int16)
    # Data in MATLAB column-major order → flat: iterate over columns then rows
    # In Python row-major: reshape to (n_channels, n_samples) and tobytes gives row-major
    # To match MATLAB's reshape(data, nch, []) we need Fortran order on write
    data_flat = np.asfortranarray(channel_data).ravel(order="F").astype(np.int16)

    buf = bytearray()
    buf += _pack_f8(len(hdr))          # hdrlen
    buf += _pack_f8_array(hdr)         # hdr
    buf += _pack_f8(len(cmt_bytes))    # cmtlen
    buf += cmt_bytes                   # cmt
    buf += data_flat.astype(">i2").tobytes()  # QPD data

    path.write_bytes(bytes(buf))
    return path


def make_fl_sidecar(path: Path, *, n_samples: int = 1024, apd_dt: float = 1e-4) -> Path:
    """Write a synthetic _fl sidecar file (2-APD)."""
    flhdr = [apd_dt, 1.0]   # apddt, NSampPerStep (no nAPD → 2-APD mode)
    rng = np.random.default_rng(7)
    counts = rng.integers(0, 1000, size=2 * n_samples, dtype=np.uint32)

    buf = bytearray()
    buf += _pack_f8(len(flhdr))
    buf += _pack_f8_array(flhdr)
    buf += _pack_u4_array(counts)

    path.write_bytes(bytes(buf))
    return path


def make_pos_sidecar(path: Path, *, n_samples: int = 1024) -> Path:
    """Write a synthetic _pos sidecar file (2 traps × n_samples)."""
    # Dummy header (all zeros, poshdrlen=0)
    mhz_to_uint64 = lambda mhz: int(mhz / (49.152 * 6) * 2**48)
    t1_vals = np.full(n_samples, mhz_to_uint64(60.0), dtype=np.uint64)
    t2_vals = np.full(n_samples, mhz_to_uint64(70.0), dtype=np.uint64)
    # Interleaved [T1, T2, T1, T2, ...] (column-major Fortran order)
    interleaved = np.empty(2 * n_samples, dtype=np.uint64)
    interleaved[0::2] = t1_vals
    interleaved[1::2] = t2_vals

    buf = bytearray()
    buf += _pack_f8(0)   # poshdrlen = 0
    buf += _pack_u8_array(interleaved)

    path.write_bytes(bytes(buf))
    return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def dat_path(tmp_path) -> Path:
    """A minimal synthetic .dat file (no sidecars)."""
    return make_dat_file(tmp_path / "230415_001.dat", n_samples=512)


@pytest.fixture
def dat_with_fl(tmp_path) -> tuple[Path, Path]:
    """A .dat file + matching _fl sidecar."""
    dat = make_dat_file(
        tmp_path / "230415_001.dat",
        n_samples=512,
        extra_data=1,
    )
    fl = make_fl_sidecar(tmp_path / "230415_001_fl.dat", n_samples=512)
    return dat, fl


@pytest.fixture
def dat_with_pos(tmp_path) -> tuple[Path, Path]:
    """A .dat file + matching _pos sidecar."""
    dat = make_dat_file(
        tmp_path / "230415_001.dat",
        n_samples=512,
        extra_data=2,
    )
    pos = make_pos_sidecar(tmp_path / "230415_001_pos.dat", n_samples=512)
    return dat, pos


@pytest.fixture
def lorentzian_spectrum():
    """Synthetic Lorentzian PSD with known fc=1000 Hz, D=1e-4 V²·Hz."""
    rng = np.random.default_rng(0)
    fs = 62500.0
    fc_true = 1000.0
    D_true = 1e-4

    N = 100_000
    dt = 1.0 / fs
    t = np.arange(N) * dt
    # Ornstein-Uhlenbeck process with fc = k/gamma, D = kT/gamma
    gamma_dt = 2 * np.pi * fc_true * dt
    noise = rng.normal(0, np.sqrt(2 * D_true * dt), N)
    x = np.zeros(N)
    for i in range(1, N):
        x[i] = x[i - 1] * np.exp(-gamma_dt) + noise[i]

    return x, fs, fc_true, D_true
