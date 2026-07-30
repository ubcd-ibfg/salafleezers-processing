"""Main processing pipeline — port of ProcessOneDataV2.m + tsprocess.m.

Orchestrates the full SalaFleezer data reduction:
  calibrate → load offset → load data → normalize → force/extension
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import numpy as np

from salafleezers.calibration.fit import CalibrationResult, calibrate
from salafleezers.constants import (
    BEAD_RADIUS_NM,
    CAL_FMIN_HZ,
    CAL_N_ALIAS,
    CAL_NBIN,
    CONV_TRAP_X_NM_PER_MHZ,
    DAT_FILENAME_FORMAT,
    KT_24C,
    WATER_VISC_24C,
)
from salafleezers.io.reader import DatFile, read_dat
from salafleezers.processing.normalize import apply_offset, normalize_by_sum
from salafleezers.utils.signal import window_filter


# ---------------------------------------------------------------------------
# Options dataclass
# ---------------------------------------------------------------------------

@dataclass
class ProcessingOptions:
    """All processing options for one SalaFleezer data set.

    Replaces the struct returned by DataOptsPopup.m.
    """
    # Bead radii (nm)
    ra_a: float = BEAD_RADIUS_NM
    ra_b: float = BEAD_RADIUS_NM

    # Trap geometry
    conv_trap_x: float = CONV_TRAP_X_NM_PER_MHZ   # nm per MHz
    ext_offset: float = 0.0                          # nm subtracted from extension

    # Calibration options
    f_min: float = CAL_FMIN_HZ
    f_max: float | None = None   # None → Nyquist
    n_bin: int = CAL_NBIN
    n_alias: int = CAL_N_ALIAS
    kt: float = KT_24C
    wv: float = WATER_VISC_24C

    # Normalization
    normalize: bool = True

    # Output
    save_format: str = "hdf5"   # "hdf5", "npz", or "mat"
    verbose: bool = False


# ---------------------------------------------------------------------------
# Per-detector calibration helper
# ---------------------------------------------------------------------------

_DET_AXES = [("AX", "AS"), ("BX", "BS"), ("AY", "AS"), ("BY", "BS")]


@dataclass(frozen=True)
class AxisCalibration:
    """The calibration numbers the force/extension math and ``to_dict`` need.

    A deliberately lighter counterpart to :class:`CalibrationResult` — no
    spectrum arrays — so a caller replaying a calibration fit that only has
    the JSON-serialized scalar fields (e.g. from a cached web session result)
    doesn't have to fabricate dummy arrays to satisfy a full
    ``CalibrationResult``. ``fc`` is carried through only so saved output
    keeps the ``cal_{axis}_fc`` field documented in ``data-formats.md``.
    """
    alpha: float   # nm/V
    kappa: float   # pN/nm
    fc: float = 0.0  # Hz


def _to_axis_calibrations(
    cal: dict[str, CalibrationResult],
) -> dict[str, AxisCalibration]:
    return {
        name: AxisCalibration(alpha=c.alpha, kappa=c.kappa, fc=c.fc)
        for name, c in cal.items()
    }


def _calibrate_file(
    cal_dat: DatFile,
    opts: ProcessingOptions,
) -> dict[str, CalibrationResult]:
    """Run Lorentzian calibration on all four QPD axes from a cal file.

    Mirrors ACalibrateV2.m → tscalibrate.m for SalaFleezer.

    Parameters
    ----------
    cal_dat : DatFile
        Parsed calibration .dat file.
    opts : ProcessingOptions

    Returns
    -------
    dict mapping detector name → CalibrationResult (keys: AX, BX, AY, BY)
    """
    fs = float(cal_dat.meta["Fs"])
    results: dict[str, CalibrationResult] = {}

    for det, sum_ch in _DET_AXES:
        if det not in cal_dat.channels or sum_ch not in cal_dat.channels:
            continue

        raw = cal_dat.channels[det].astype(np.float64)
        s = cal_dat.channels[sum_ch].astype(np.float64)

        # Normalize by sum for calibration (if requested)
        if opts.normalize:
            with np.errstate(divide="ignore", invalid="ignore"):
                data = np.where(s != 0, raw / s, 0.0)
        else:
            data = raw

        f_max = opts.f_max if opts.f_max is not None else fs / 2
        results[det] = calibrate(
            data,
            fs,
            ra=opts.ra_a if det.startswith("A") else opts.ra_b,
            kt=opts.kt,
            wv=opts.wv,
            f_min=opts.f_min,
            f_max=f_max,
            n_bin=opts.n_bin,
            n_alias=opts.n_alias,
            name=det,
        )

    return results


# ---------------------------------------------------------------------------
# Offset preparation helper
# ---------------------------------------------------------------------------

def _prepare_offset(off_dat: DatFile) -> DatFile:
    """Downsample an offset file to ~100×2 points (timeshared convention).

    The MATLAB code in ProcessOneDataV2.m uses:
        npul = 2  (for Meitner / Avogadro / SalaFleezer)
        npts = 100 * npul
        navg = floor(len(AS) / npts)
        off.field = windowFilter(@mean, rawoff.field(1:round(end/npul)), [], navg)

    We replicate this with window_filter(fn="mean", decimate=navg).
    """
    npul = 2
    n_raw = len(off_dat.channels.get("AS", next(iter(off_dat.channels.values()))))
    npts = 100 * npul
    navg = max(1, n_raw // npts)

    downsampled_channels: dict[str, np.ndarray] = {}
    # Use only the first half of the offset (one sweep direction)
    half = round(n_raw / npul)

    channels_to_use = ["AX", "AY", "AS", "BX", "BY", "BS"]
    for ch in channels_to_use:
        if ch not in off_dat.channels:
            continue
        sig = off_dat.channels[ch][:half].astype(np.float64)
        downsampled_channels[ch] = window_filter(sig, fn="mean", decimate=navg)

    # Compute TX from DDS positions if available
    if off_dat.t1f is not None and off_dat.t2f is not None:
        t1 = off_dat.t1f[:half]
        t2 = off_dat.t2f[:half]
        tx_raw = (t2 - t1) * CONV_TRAP_X_NM_PER_MHZ
        downsampled_channels["TX"] = window_filter(tx_raw.astype(np.float64), fn="mean", decimate=navg)
    else:
        # No trap positions: create a dummy TX spanning the data range (one point)
        downsampled_channels["TX"] = np.array([0.0, 1e9])
        for ch in channels_to_use:
            if ch in downsampled_channels:
                downsampled_channels[ch] = np.array(
                    [np.mean(downsampled_channels[ch])] * 2
                )

    # Build a minimal DatFile proxy
    proxy = DatFile(
        meta=off_dat.meta,
        channels=downsampled_channels,
        time=np.arange(len(downsampled_channels.get("AS", [0]))) * float(off_dat.meta["Fsamp"]),
    )
    return proxy


# ---------------------------------------------------------------------------
# Processed data container
# ---------------------------------------------------------------------------

@dataclass
class ProcessedData:
    """Output of the full SalaFleezer processing pipeline."""
    time: np.ndarray          # seconds
    force: np.ndarray         # pN (differential, hypot of X and Y)
    extension: np.ndarray     # nm
    force_ax: np.ndarray      # pN (trap A, X axis)
    force_bx: np.ndarray      # pN (trap B, X axis)
    force_ay: np.ndarray      # pN (trap A, Y axis)
    force_by: np.ndarray      # pN (trap B, Y axis)
    cal: dict[str, AxisCalibration]
    meta: dict
    opts: ProcessingOptions
    # Optional fluorescence
    apd1: np.ndarray | None = None
    apd2: np.ndarray | None = None
    apd_time: np.ndarray | None = None

    def to_dict(self) -> dict:
        """Flatten to a dict suitable for saving."""
        d: dict = {
            "time": self.time,
            "force": self.force,
            "extension": self.extension,
            "forceAX": self.force_ax,
            "forceBX": self.force_bx,
            "forceAY": self.force_ay,
            "forceBY": self.force_by,
        }
        if self.apd1 is not None:
            d["APD1"] = self.apd1
            d["APD2"] = self.apd2
            d["APDT"] = self.apd_time
        # Calibration summary
        for name, c in self.cal.items():
            d[f"cal_{name}_fc"] = np.float64(c.fc)
            d[f"cal_{name}_alpha"] = np.float64(c.alpha)
            d[f"cal_{name}_kappa"] = np.float64(c.kappa)
        return d


# ---------------------------------------------------------------------------
# Core single-file processor
# ---------------------------------------------------------------------------

def process_from_dats(
    raw_dat: DatFile,
    raw_off: DatFile | None,
    cal: Mapping[str, AxisCalibration],
    opts: ProcessingOptions,
) -> ProcessedData:
    """Turn a data / offset / calibration triplet already in memory into force+extension.

    This is the filename-free core of :func:`process_one`: everything about
    resolving numbered ``.dat`` filenames on disk lives in the caller, so any
    source of ``DatFile``s (a batch directory, or files uploaded through the
    web GUI with arbitrary names) can drive the same physics.

    Parameters
    ----------
    raw_dat : DatFile
        The data file to process (read with ``skip_fl=True`` unless
        fluorescence channels are wanted in the output).
    raw_off : DatFile or None
        The offset file (bead-interaction baseline). ``None`` means "no
        offset available" -- a constant zero offset is subtracted instead of
        raising, since force is still meaningful without one.
    cal : mapping of detector name -> AxisCalibration
        Per-axis ``alpha``/``kappa`` (and optionally ``fc``), e.g. from
        :func:`_calibrate_file` via :func:`_to_axis_calibrations`, or
        replayed from a previously computed fit.
    opts : ProcessingOptions

    Returns
    -------
    ProcessedData
    """
    # 1. Offset
    if raw_off is not None:
        off = _prepare_offset(raw_off)
    else:
        off = DatFile(meta={}, channels={"TX": np.array([0.0, 1e9])}, time=np.array([0.0, 1e9]))

    # Compute trap-delta TX for data file
    if raw_dat.t1f is not None and raw_dat.t2f is not None:
        dat_tx = ((raw_dat.t2f - raw_dat.t1f) * CONV_TRAP_X_NM_PER_MHZ).astype(np.float64)
    else:
        dat_tx = np.zeros(len(raw_dat.time), dtype=np.float64)

    off_tx = off.channels["TX"].astype(np.float64)

    # TY: timeshared instruments fix TY = 0
    dat_ty = np.zeros_like(dat_tx)

    # 2. Normalise + offset-subtract each detector; compute forces
    def _process_det(det: str, sum_ch: str) -> tuple[np.ndarray, np.ndarray]:
        """Return (corrected_signal_V, force_pN)."""
        if det not in raw_dat.channels or sum_ch not in raw_dat.channels:
            zeros = np.zeros(len(raw_dat.time), dtype=np.float64)
            return zeros, zeros
        if opts.normalize:
            sig = apply_offset(
                data_signal=raw_dat.channels[det].astype(np.float64),
                data_sum=raw_dat.channels[sum_ch].astype(np.float64),
                data_td=dat_tx,
                off_signal=off.channels[det].astype(np.float64) if det in off.channels else np.zeros(2),
                off_sum=off.channels[sum_ch].astype(np.float64) if sum_ch in off.channels else np.ones(2),
                off_td=off_tx,
            )
        else:
            norm_off = off.channels[det].astype(np.float64) if det in off.channels else np.zeros(2)
            off_sum = off.channels[sum_ch].astype(np.float64) if sum_ch in off.channels else np.ones(2)
            from scipy.interpolate import interp1d
            med = float(np.nanmedian(norm_off / off_sum))
            interp = interp1d(off_tx, norm_off, kind="linear",
                              bounds_error=False, fill_value=med)
            sig = raw_dat.channels[det].astype(np.float64) - interp(dat_tx)

        c = cal.get(det)
        force = sig * (c.alpha * c.kappa) if c is not None else np.zeros_like(sig)
        return sig, force.astype(np.float64)

    sig_ax, force_ax = _process_det("AX", "AS")
    sig_bx, force_bx = _process_det("BX", "BS")
    sig_ay, force_ay = _process_det("AY", "AS")
    sig_by, force_by = _process_det("BY", "BS")

    # 3. Extension: hypot(TX + α_AX·AX - α_BX·BX, TY + α_AY·AY - α_BY·BY) - r_A - r_B - offset
    a_ax = cal["AX"].alpha if "AX" in cal else 0.0
    a_bx = cal["BX"].alpha if "BX" in cal else 0.0
    a_ay = cal["AY"].alpha if "AY" in cal else 0.0
    a_by = cal["BY"].alpha if "BY" in cal else 0.0

    extension = (
        np.hypot(
            dat_tx + a_ax * sig_ax - a_bx * sig_bx,
            dat_ty + a_ay * sig_ay - a_by * sig_by,
        )
        - opts.ra_a - opts.ra_b - opts.ext_offset
    )

    # 4. Total differential force
    force = np.hypot(
        (force_bx - force_ax) / 2,
        (force_by - force_ay) / 2,
    )

    # 5. Time axis from data file sampling frequency
    fs = float(raw_dat.meta["Fs"])
    n = len(extension)
    time_axis = np.arange(n, dtype=np.float32) / fs

    return ProcessedData(
        time=time_axis,
        force=force.astype(np.float32),
        extension=extension.astype(np.float32),
        force_ax=force_ax.astype(np.float32),
        force_bx=force_bx.astype(np.float32),
        force_ay=force_ay.astype(np.float32),
        force_by=force_by.astype(np.float32),
        cal=dict(cal),
        meta=raw_dat.meta,
        opts=opts,
        apd1=raw_dat.apd1,
        apd2=raw_dat.apd2,
        apd_time=raw_dat.apd_time,
    )


def process_one(
    path: str | Path,
    nums: tuple[int, int, int],
    mmddyy: str,
    opts: ProcessingOptions | None = None,
) -> ProcessedData:
    """Process one data / offset / calibration file triplet.

    Mirrors ``ProcessOneDataV2(path, inNums, inOpts)`` in MATLAB.

    Parameters
    ----------
    path : str or Path
        Directory containing the .dat files.
    nums : (dat_num, off_num, cal_num)
        File number triplet (e.g. (1, 2, 3)).
    mmddyy : str
        Date string prefix, e.g. ``"230415"``.
    opts : ProcessingOptions or None
        Processing options.  Defaults to SalaFleezer defaults.

    Returns
    -------
    ProcessedData
    """
    if opts is None:
        opts = ProcessingOptions()

    path = Path(path)
    dat_num, off_num, cal_num = nums

    def fn(n: int) -> Path:
        return path / DAT_FILENAME_FORMAT.format(mmddyy=mmddyy, num=n)

    if opts.verbose:
        print(f"[sfz] Processing {mmddyy}_{dat_num:03d} | off={off_num} | cal={cal_num}")

    t0 = time.perf_counter()

    # 1. Calibrate
    cal_dat = read_dat(fn(cal_num), skip_fl=True)
    cal = _calibrate_file(cal_dat, opts)
    if opts.verbose:
        for k, v in cal.items():
            print(f"  cal {k}: fc={v.fc:.1f} Hz  alpha={v.alpha:.1f} nm/V  kappa={v.kappa:.4f} pN/nm")
    del cal_dat

    # 2. Offset
    raw_off = read_dat(fn(off_num), skip_fl=True)

    # 3. Data
    raw_dat = read_dat(fn(dat_num))

    result = process_from_dats(raw_dat, raw_off, _to_axis_calibrations(cal), opts)
    del raw_off

    if opts.verbose:
        elapsed = time.perf_counter() - t0
        print(f"  Done in {elapsed:.2f}s  |  n={len(result.time)} pts")

    return result


# ---------------------------------------------------------------------------
# Batch processor (mirrors tsprocess.m / AProcessDataV2.m)
# ---------------------------------------------------------------------------

def process_batch(
    path: str | Path,
    mmddyy: str,
    triplets: list[tuple[int, int, int]],
    opts: ProcessingOptions | None = None,
    output_dir: str | Path | None = None,
) -> list[ProcessedData]:
    """Process a list of file-number triplets in a directory.

    Parameters
    ----------
    path : directory containing .dat files.
    mmddyy : date string (e.g. "230415").
    triplets : list of (dat, off, cal) number tuples.
    opts : processing options.
    output_dir : if given, save results here; else same as *path*.

    Returns
    -------
    list of ProcessedData
    """
    from salafleezers.io.writer import save

    path = Path(path)
    out_dir = Path(output_dir) if output_dir else path
    results = []

    for dat_num, off_num, cal_num in triplets:
        result = process_one(path, (dat_num, off_num, cal_num), mmddyy, opts)
        results.append(result)
        # Save
        stem = f"ForceExtension{mmddyy}_{dat_num:03d}"
        out_path = out_dir / stem
        fmt = opts.save_format if opts else "hdf5"
        saved = save(out_path, result.to_dict(), fmt=fmt)
        if opts and opts.verbose:
            print(f"  Saved → {saved}")

    return results
