"""File-loading utilities shared by multiple API routes.

Decouples format-specific parsing from the FastAPI request layer so the
same helper can be called from both ``api/files.py`` (open route) and
``api/sessions.py`` (reload-on-startup).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def load_file(path: Path) -> tuple[dict[str, np.ndarray], np.ndarray, dict, str]:
    """Parse any supported file into ``(channels, time, meta, filename)``.

    Returns
    -------
    channels
        ``{name: float32_array}`` — one entry per data column.
    time
        ``float32`` seconds axis (length N).
    meta
        Scalar metadata dict (all values JSON-serialisable).
    filename
        Basename of the file.

    Raises
    ------
    ValueError
        For unsupported file formats or unreadable files.
    """
    suffix = path.suffix.lower()

    if suffix == ".dat":
        return _load_dat(path)
    if suffix in (".h5", ".hdf5", ".hdf"):
        return _load_hdf5(path)
    if suffix == ".npz":
        return _load_npz(path)

    raise ValueError(f"Unsupported file format: '{suffix}'")


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

def _load_dat(path: Path):
    from salafleezers.io.reader import read_dat

    dat = read_dat(path)
    channels = {k: v.astype(np.float32) for k, v in dat.channels.items()}
    meta = {k: v for k, v in dat.meta.items() if k != "hdr"}
    return channels, dat.time.astype(np.float32), meta, path.name


def _load_hdf5(path: Path):
    import h5py

    channels: dict[str, np.ndarray] = {}
    meta: dict = {}
    time: np.ndarray | None = None

    with h5py.File(path, "r") as f:
        for key in f.keys():
            arr = np.array(f[key])
            if arr.ndim == 1:
                if key == "time":
                    time = arr.astype(np.float32)
                else:
                    channels[key] = arr.astype(np.float32)
        for k, v in f.attrs.items():
            try:
                meta[k] = v.item() if hasattr(v, "item") else str(v)
            except Exception:
                pass

    if time is None:
        n = next((len(v) for v in channels.values()), 0)
        time = np.arange(n, dtype=np.float32)

    return channels, time, meta, path.name


def _load_npz(path: Path):
    data = np.load(path, allow_pickle=False)
    channels: dict[str, np.ndarray] = {}
    time: np.ndarray | None = None

    for key, arr in data.items():
        if arr.ndim != 1:
            continue
        if key == "time":
            time = arr.astype(np.float32)
        else:
            channels[key] = arr.astype(np.float32)

    if time is None:
        n = next((len(v) for v in channels.values()), 0)
        time = np.arange(n, dtype=np.float32)

    return channels, time, {}, path.name
