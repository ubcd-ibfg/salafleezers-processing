"""Binary .dat file reader for SalaFleezer (timeshared) optical tweezers.

Ports timeshareread.m + timesharereadhdr.m from legacy/BLabOTMatlab/.

File layout (all big-endian):
  float64        hdrlen   — number of header doubles
  float64 × N    hdr      — header fields
  float64        cmtlen   — comment byte count
  char   × M    cmt      — ASCII comment string
  int16  × K    data     — interleaved QPD channels (nch × nsamples)

Associated sidecar files (same stem):
  _fl.dat  — APD fluorescence photon counts (uint32 big-endian)
  _pos.dat — DDS trap frequencies (uint64 big-endian → MHz)
  _grn.dat — green laser status (float64 big-endian, 4 channels)
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from salafleezers.constants import (
    CHANNEL_MAPS,
    CONV_TRAP_X_NM_PER_MHZ,
    INT16_TO_VOLT,
    POS_TO_MHZ,
)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class DatFile:
    """Parsed contents of a SalaFleezer .dat file."""
    meta: dict
    channels: dict[str, np.ndarray]   # float32, volts; keyed by channel name
    time: np.ndarray                   # float32, seconds (centre of sample interval)
    # Optional sidecar data
    apd1: np.ndarray | None = None    # APD 1 photon counts (uint16)
    apd2: np.ndarray | None = None    # APD 2 photon counts (uint16)
    apd_time: np.ndarray | None = None  # APD time axis (float32, s)
    t1f: np.ndarray | None = None     # Trap 1 frequency (float64, MHz)
    t2f: np.ndarray | None = None     # Trap 2 frequency (float64, MHz)
    grn: dict | None = None           # green-laser channels (optional)


# ---------------------------------------------------------------------------
# Header reader
# ---------------------------------------------------------------------------

def read_header(path: Path) -> tuple[dict, str, int]:
    """Read the binary header from a .dat file.

    Returns
    -------
    meta : dict
        Parsed header metadata.
    cmt : str
        Comment string embedded in the file.
    data_offset : int
        Byte offset at which QPD data begins.
    """
    with open(path, "rb") as fid:
        hdrlen = int(np.frombuffer(fid.read(8), dtype=">f8")[0])
        hdr = np.frombuffer(fid.read(hdrlen * 8), dtype=">f8")
        cmtlen = int(np.frombuffer(fid.read(8), dtype=">f8")[0])
        cmt = fid.read(cmtlen).decode("latin-1")
        data_offset = fid.tell()

    ver = hdr[0]
    if ver < 9:
        raise ValueError(
            f"{path.name}: file version {ver:.0f} < 9, not supported"
        )

    dtyp = int(hdr[5])

    # Build meta dict — mirrors the hdrfns/hdrind logic in timeshareread.m
    meta: dict = {
        "filever": hdr[0],
        "Fsampraw": hdr[1],
        "Fsamp": hdr[2],
        "nChannels": int(hdr[3]),
        "channelID": int(hdr[4]),
        "datatype": dtyp,
        "initMHz": hdr[6:12].copy(),
        "extraData": int(hdr[12]),
        "hdr": hdr.copy(),
    }

    if dtyp == 2:  # AOM raster scan
        meta.update({
            "scanDir": hdr[17],
            "scanRange": hdr[18],
            "scanNSteps": hdr[19],
            "scanCycPerStep": hdr[20],
            "scanNScans": hdr[21],
        })
    elif dtyp == 3:  # MCL raster scan
        meta.update({
            "scanIs2D": hdr[13],
            "scanAlongX": hdr[17],
            "scanRangeV": hdr[18],
            "scanNStepsX": hdr[19],
            "scanCycPerStep": hdr[20],
            "scanStepsYorNScans": hdr[21],
            "scanX0": hdr[22],
            "scanY0": hdr[23],
        })
    elif dtyp not in (0, 1):
        warnings.warn(
            f"{path.name}: unknown datatype {dtyp}, scan metadata not parsed"
        )

    return meta, cmt, data_offset


# ---------------------------------------------------------------------------
# Main reader
# ---------------------------------------------------------------------------

def read_dat(path: str | Path, dtype: str = "int16", skip_fl: bool = False) -> DatFile:
    """Read a SalaFleezer .dat file and all available sidecar files.

    Parameters
    ----------
    path : str or Path
        Path to the .dat file.
    dtype : str
        Raw data type: ``"int16"`` (SalaFleezer / Meitner) or
        ``"single"`` / ``"float32"`` (Boltzmann).
    skip_fl : bool
        If True, do not attempt to read the fluorescence sidecar.

    Returns
    -------
    DatFile
        Parsed data with metadata.
    """
    path = Path(path)
    stem = path.stem
    parent = path.parent

    meta, cmt, _ = read_header(path)

    nch = meta["nChannels"]
    dt = float(meta["Fsamp"])          # sample interval in seconds
    fs = 1.0 / dt                      # sampling frequency
    meta["Fs"] = fs
    meta["comment"] = cmt

    # Read raw QPD data
    np_dtype = ">i2" if dtype in ("int16",) else ">f4"
    with open(path, "rb") as fid:
        hdrlen = int(np.frombuffer(fid.read(8), dtype=">f8")[0])
        fid.seek(8 + hdrlen * 8)       # skip header
        cmtlen = int(np.frombuffer(fid.read(8), dtype=">f8")[0])
        fid.seek(cmtlen, 1)            # skip comment
        raw_bytes = fid.read()

    raw = np.frombuffer(raw_bytes, dtype=np_dtype).astype(np.float32)
    nrow = len(raw) // nch
    # MATLAB reshape(data, nch, []) is column-major (Fortran order):
    # on disk layout is [ch0_t0, ch1_t0, …, ch(n-1)_t0, ch0_t1, …]
    # order='F' replicates that → data[ch, t] is correct
    data = raw[: nrow * nch].reshape(nch, nrow, order="F")

    # Convert to volts
    if dtype == "int16":
        data = data * np.float32(INT16_TO_VOLT)

    n_samples = data.shape[1]

    # Build channel dict from channel map
    chnid = meta["channelID"]
    if chnid not in CHANNEL_MAPS:
        raise ValueError(f"{path.name}: unknown channelID {chnid}")

    channels: dict[str, np.ndarray] = {}
    for name, idx, pol in CHANNEL_MAPS[chnid]:
        channels[name] = np.asarray(data[idx] * np.float32(pol), dtype=np.float32)

    # Time axis: centre of each sample interval (dt/2 offset matches timeshareread.m)
    time = (np.arange(n_samples, dtype=np.float32) * np.float32(dt)
            + np.float32(dt / 2))

    dat = DatFile(meta=meta, channels=channels, time=time)

    # --- Trap X separation from DDS frequencies (if positions saved) ---
    # extraData bit 1 (value 2 or 3) means positions were saved
    if meta["extraData"] in (2, 3):
        pos_path = parent / f"{stem}_pos{path.suffix}"
        if pos_path.exists():
            dat.t1f, dat.t2f = _read_pos_sidecar(pos_path)
            # TX from frequency difference (nm)
            meta["TX0"] = (float(dat.t2f[0]) - float(dat.t1f[0])) * CONV_TRAP_X_NM_PER_MHZ
        else:
            warnings.warn(f"Trap position file {pos_path.name} expected but not found")

    # --- Fluorescence sidecar ---
    # extraData bit 0 (value 1 or 3) means fluorescence was saved
    if meta["extraData"] in (1, 3) and not skip_fl:
        fl_path = parent / f"{stem}_fl{path.suffix}"
        if fl_path.exists():
            apd1, apd2, apd_dt = _read_fl_sidecar(fl_path, meta)
            dat.apd1 = apd1
            dat.apd2 = apd2
            # APD time: offset by apddt/4 (matches timeshareread.m)
            n_apd = len(apd1)
            dat.apd_time = (np.arange(n_apd, dtype=np.float32) * np.float32(apd_dt)
                            + np.float32(apd_dt / 4))
        else:
            warnings.warn(f"Fluorescence file {fl_path.name} expected but not found")

    # --- Green laser sidecar (optional, no extraData flag) ---
    grn_path = parent / f"{stem}_grn{path.suffix}"
    if grn_path.exists():
        dat.grn = _read_grn_sidecar(grn_path)

    return dat


# ---------------------------------------------------------------------------
# Sidecar helpers
# ---------------------------------------------------------------------------

def _read_pos_sidecar(pos_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read the _pos sidecar file.  Returns (T1F, T2F) in MHz."""
    with open(pos_path, "rb") as fid:
        poshdrlen = int(np.frombuffer(fid.read(8), dtype=">f8")[0])
        fid.read(poshdrlen * 8)  # skip header (usually all zeros)
        raw = np.frombuffer(fid.read(), dtype=">u8").astype(np.float64)

    # raw uint48 stored in uint64; convert to MHz
    raw = raw * POS_TO_MHZ
    # interleaved [T1, T2, T1, T2, ...]
    posdat = raw.reshape(2, -1, order="F")  # [2, nsamples] column-major like MATLAB
    return posdat[0], posdat[1]


def _read_fl_sidecar(fl_path: Path, meta: dict) -> tuple[np.ndarray, np.ndarray, float]:
    """Read the _fl sidecar file.  Returns (APD1, APD2, apddt)."""
    with open(fl_path, "rb") as fid:
        flhdrlen = int(np.frombuffer(fid.read(8), dtype=">f8")[0])
        flhdr = np.frombuffer(fid.read(flhdrlen * 8), dtype=">f8")
        raw = np.frombuffer(fid.read(), dtype=">u4")  # uint32 big-endian

    apddt = float(flhdr[0])
    meta["apddt"] = apddt
    meta["apdNSampPerStep"] = float(flhdr[1])
    meta["flhdr"] = flhdr.copy()

    n_apd_channels = int(flhdr[2]) if len(flhdr) > 2 else 2

    if any(raw >= 65535):
        warnings.warn(f"Fluorescence values in {fl_path.name} unexpectedly high")
        tmpfl = raw.copy()
    else:
        tmpfl = raw.astype(np.uint16)

    if n_apd_channels == 3:
        # Avogadro: 4 rows [col, APD1, APD2, APD3]
        meta["nAPD"] = 3
        n = 4 * (len(tmpfl) // 4)
        tmpfl = tmpfl[:n].reshape(4, -1, order="F")
        apd1 = tmpfl[1]
        apd2 = tmpfl[2]
    else:
        # SalaFleezer / Meitner: 2 APDs
        n = 2 * (len(tmpfl) // 2)
        tmpfl = tmpfl[:n].reshape(2, -1, order="F")
        apd1 = tmpfl[0]
        apd2 = tmpfl[1]

    return apd1, apd2, apddt


def _read_grn_sidecar(grn_path: Path) -> dict:
    """Read the _grn sidecar file.  Returns dict with green laser channels."""
    with open(grn_path, "rb") as fid:
        nghdr = int(np.frombuffer(fid.read(8), dtype=">f8")[0])
        ghdr = np.frombuffer(fid.read(nghdr * 8), dtype=">f8")
        gdat = np.frombuffer(fid.read(), dtype=">f8")

    gdt = float(ghdr[0])
    gdat = gdat.reshape(4, -1, order="F")  # [4, N] column-major
    n = gdat.shape[1]
    grn_time = np.arange(n, dtype=np.float32) * gdt + gdt / 2
    return {
        "GrnOn": gdat[0].astype(np.float32),
        "GrnCurrPct": gdat[1].astype(np.float32),
        "GrnIntMode": gdat[2].astype(np.float32),
        "GrnPDSum": gdat[3].astype(np.float32),
        "GrnTime": grn_time,
        "gdt": gdt,
    }
