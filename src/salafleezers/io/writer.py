"""Output writers for processed SalaFleezer data.

Replaces MATLAB's ``save(..., '-v7.3')`` in ProcessOneDataV2.m.
Primary format: HDF5 via h5py (portable, hierarchical, compressible).
Compat format: .mat via scipy.io.savemat for downstream MATLAB users.
Lightweight format: .npz (numpy) for quick local storage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np


def save_hdf5(path: str | Path, data: dict[str, Any], *, compress: bool = True) -> None:
    """Save a dict of arrays/scalars/sub-dicts to an HDF5 file.

    Parameters
    ----------
    path : str or Path
        Output file path (usually ``ForceExtension<stem>.h5``).
    data : dict
        Flat or nested dict.  Arrays are stored as datasets; plain Python
        scalars and strings are stored as attributes of the root group.
    compress : bool
        Apply gzip compression (level 4) to float/int datasets.
    """
    import h5py

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as f:
        _write_group(f, data, compress=compress)


def _write_group(group: Any, data: dict[str, Any], *, compress: bool) -> None:
    import h5py

    for key, value in data.items():
        if isinstance(value, dict):
            sub = group.require_group(key)
            _write_group(sub, value, compress=compress)
        elif isinstance(value, np.ndarray):
            kwargs: dict[str, Any] = {}
            if compress and value.dtype.kind in ("f", "i", "u") and value.size > 1:
                kwargs = {"compression": "gzip", "compression_opts": 4}
            group.create_dataset(key, data=value, **kwargs)
        elif isinstance(value, (int, float, bool, np.integer, np.floating)):
            group.attrs[key] = value
        elif isinstance(value, str):
            group.attrs[key] = value
        elif value is None:
            pass
        else:
            # Try converting unknown types to array
            try:
                arr = np.asarray(value)
                group.create_dataset(key, data=arr)
            except Exception:
                group.attrs[key] = str(value)


def save_npz(path: str | Path, data: dict[str, Any]) -> None:
    """Save flat dict of arrays to a compressed .npz file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {k: np.asarray(v) for k, v in data.items() if v is not None}
    np.savez_compressed(path, **arrays)


def save_mat(path: str | Path, data: dict[str, Any]) -> None:
    """Save to MATLAB .mat format (v5, compatible with MATLAB ≥ R2006a).

    Nested dicts become MATLAB structs.
    """
    from scipy.io import savemat

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    savemat(str(path), data, do_compression=True)


def save(
    path: str | Path,
    data: dict[str, Any],
    fmt: str = "hdf5",
) -> Path:
    """Save processed data to the requested format.

    Parameters
    ----------
    path : str or Path
        Output path (extension will be adjusted to match *fmt* if needed).
    data : dict
        Data to save.
    fmt : str
        One of ``"hdf5"``, ``"npz"``, or ``"mat"``.

    Returns
    -------
    Path
        Actual path written.
    """
    path = Path(path)
    ext_map = {"hdf5": ".h5", "npz": ".npz", "mat": ".mat"}
    if fmt not in ext_map:
        raise ValueError(f"Unknown format {fmt!r}. Choose from {list(ext_map)}")

    # Replace extension if it doesn't match
    if path.suffix != ext_map[fmt]:
        path = path.with_suffix(ext_map[fmt])

    if fmt == "hdf5":
        save_hdf5(path, data)
    elif fmt == "npz":
        save_npz(path, data)
    else:
        save_mat(path, data)

    return path
