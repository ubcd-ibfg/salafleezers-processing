"""Calibration and processing endpoints.

POST /api/calibrate   → Lorentzian power-spectrum fit on all four QPD axes
                        of a calibration .dat already opened in a session
POST /api/process     → apply a calibration to a data + offset .dat pair,
                        producing a force/extension trace written into the
                        data file's own uploaded dataset and opened into
                        the session -- GUI parity with one `sfz process`
                        batch line
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

import numpy as np
from fastapi import APIRouter, Depends, HTTPException

from salafleezers.web.api._common import _analysis_slot, _get_file, _get_session
from salafleezers.web.api.files import _open_into_session
from salafleezers.web.auth import Principal, get_current_principal
from salafleezers.web.schemas import (
    CalibrationAxisResult,
    CalibrationRequest,
    CalibrationResultOut,
    DatasetFileRef,
    ProcessRunRequest,
    ProcessRunResult,
)
from salafleezers.web.sessions import FileRef
from salafleezers.web.storage import InvalidSegmentError
from salafleezers.web.workspace import (
    UploadTooLargeError,
    WorkspaceQuotaError,
    workspace_store,
)

if TYPE_CHECKING:
    from salafleezers.calibration.fit import CalibrationResult

router = APIRouter(prefix="/api", tags=["calibration"])

# A full-resolution PSD response is bounded by n_bin, not sample count -- but
# a caller could still request a very small n_bin against a long trace, so
# cap what actually crosses the wire (and lands in session.json on save).
_MAX_PSD_POINTS = 4000

# Raw .dat triplets run ~200-400 MB each in memory (see AxisCalibration /
# process_from_dats docs); this bounds total bytes read from disk before any
# of that allocation happens, distinct from SFZ_MAX_STEPFIND_SAMPLES which is
# far below a raw acquisition's sample count.
_DEFAULT_MAX_PROCESS_BYTES = 500 * 1024 * 1024

_DATNAME_RE = re.compile(r"^(\d{6})_(\d{3})$")
_CHUNK_SIZE = 1024 * 1024


def _max_process_bytes() -> int:
    return int(os.environ.get("SFZ_MAX_PROCESS_BYTES") or _DEFAULT_MAX_PROCESS_BYTES)


def _iter_chunks(fileobj: BinaryIO, chunk_size: int = _CHUNK_SIZE) -> Iterator[bytes]:
    while True:
        chunk = fileobj.read(chunk_size)
        if not chunk:
            break
        yield chunk


def _decimate_for_plot(arr: np.ndarray) -> np.ndarray:
    if len(arr) <= _MAX_PSD_POINTS:
        return arr
    step = -(-len(arr) // _MAX_PSD_POINTS)  # ceil division
    return arr[::step]


def _axis_result(c: CalibrationResult, fs: float, n_alias: int) -> CalibrationAxisResult:
    from salafleezers.calibration.lorentzian import lorentzian_pure

    f_model = np.geomspace(float(c.F_fit[0]), float(c.F_fit[-1]), 300)
    psd_model = lorentzian_pure(c.fit_params, f_model, fs, n_alias)
    return CalibrationAxisResult(
        detector=c.name,
        fc_hz=c.fc,
        alpha_nm_v=c.alpha,
        kappa_pn_nm=c.kappa,
        D_v2_hz=c.D,
        drag_pn_s_nm=c.drag,
        D_theory_nm2_s=c.D_theory,
        chi2=c.chi2,
        converged=c.converged,
        f_binned=_decimate_for_plot(c.F_full).tolist(),
        psd_binned=_decimate_for_plot(c.P_full).tolist(),
        f_model=f_model.tolist(),
        psd_model=psd_model.tolist(),
        f_fit_min=float(c.F_fit[0]),
        f_fit_max=float(c.F_fit[-1]),
    )


def _default_output_name(data_relative_path: str) -> str:
    """Mirror the CLI's ``ForceExtension{mmddyy}_{num:03d}`` naming where it applies."""
    stem = Path(data_relative_path).stem
    m = _DATNAME_RE.match(stem)
    if m:
        mmddyy, num = m.groups()
        return f"ForceExtension{mmddyy}_{num}"
    return f"{stem}_processed"


def _resolve_dataset_ref(ref: DatasetFileRef, user_id: str) -> Path:
    try:
        path = workspace_store.resolve_file_path(user_id, ref.dataset_id, ref.relative_path)
    except InvalidSegmentError:
        raise HTTPException(status_code=400, detail="Invalid dataset reference")
    if not path.exists():
        raise HTTPException(
            status_code=404, detail=f"File not found in dataset: {ref.relative_path}"
        )
    return path


@router.post("/calibrate", response_model=CalibrationResultOut, status_code=201)
def run_calibration(
    request: CalibrationRequest, principal: Principal = Depends(get_current_principal)
):
    """Fit Lorentzian power spectra on every QPD axis present in an opened calibration file."""
    from salafleezers.calibration.fit import calibrate
    from salafleezers.processing.pipeline import _DET_AXES

    session = _get_session(request.session_id, principal)
    f = _get_file(session, request.file_id)
    fs = float(f.meta["Fs"]) if "Fs" in f.meta else f.sampling_rate_hz
    f_max = request.f_max_hz if request.f_max_hz is not None else fs / 2

    axes: list[CalibrationAxisResult] = []
    skipped: list[str] = []

    with _analysis_slot(principal.user_id):
        for det, sum_ch in _DET_AXES:
            if det not in f.channels or sum_ch not in f.channels:
                skipped.append(det)
                continue

            raw = f.resolve_channel64(det)
            s = f.resolve_channel64(sum_ch)
            if request.normalize:
                with np.errstate(divide="ignore", invalid="ignore"):
                    data = np.where(s != 0, raw / s, 0.0)
            else:
                data = raw

            try:
                c = calibrate(
                    data,
                    fs,
                    ra=request.bead_radius_a_nm if det.startswith("A") else request.bead_radius_b_nm,
                    kt=request.kt_pn_nm,
                    wv=request.water_viscosity,
                    f_min=request.f_min_hz,
                    f_max=f_max,
                    n_bin=request.n_bin,
                    n_alias=request.n_alias,
                    name=det,
                )
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"Calibration failed for {det}: {exc}")

            axes.append(_axis_result(c, fs, request.n_alias))

    result_id = f"{request.file_id}_calibration"
    out = CalibrationResultOut(
        session_id=request.session_id,
        file_id=request.file_id,
        result_id=result_id,
        sampling_rate_hz=fs,
        axes=axes,
        skipped=skipped,
    )
    session.calibration_results[result_id] = out.model_dump()
    return out


@router.post("/process", response_model=ProcessRunResult, status_code=201)
def run_processing(
    request: ProcessRunRequest, principal: Principal = Depends(get_current_principal)
):
    """Apply a calibration to a data+offset pair, producing a force/extension trace.

    Writes the result into the data file's own uploaded dataset under
    ``processed/`` and opens it into the session, so it appears in the
    Trace Viewer exactly like any other uploaded file.
    """
    from salafleezers.io.reader import read_dat
    from salafleezers.io.writer import save as save_processed
    from salafleezers.processing.pipeline import (
        _DET_AXES,
        AxisCalibration,
        ProcessingOptions,
        _calibrate_file,
        _to_axis_calibrations,
        process_from_dats,
    )

    session = _get_session(request.session_id, principal)

    data_path = _resolve_dataset_ref(request.data, principal.user_id)
    offset_path = _resolve_dataset_ref(request.offset, principal.user_id) if request.offset else None
    cal_path = _resolve_dataset_ref(request.calibration, principal.user_id) if request.calibration else None

    total_bytes = data_path.stat().st_size
    total_bytes += offset_path.stat().st_size if offset_path is not None else 0
    total_bytes += cal_path.stat().st_size if cal_path is not None else 0
    limit = _max_process_bytes()
    if total_bytes > limit:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Selected files total {total_bytes:,} bytes, exceeding the "
                f"{limit:,}-byte processing limit."
            ),
        )

    ext_map = {"hdf5": ".h5", "npz": ".npz"}
    if request.save_format not in ext_map:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported save_format {request.save_format!r}; choose 'hdf5' or 'npz'",
        )

    with _analysis_slot(principal.user_id):
        opts = ProcessingOptions(
            ra_a=request.bead_radius_a_nm,
            ra_b=request.bead_radius_b_nm,
            conv_trap_x=request.conv_trap_x_nm_per_mhz,
            ext_offset=request.ext_offset_nm,
            f_min=request.f_min_hz,
            f_max=request.f_max_hz,
            n_bin=request.n_bin,
            n_alias=request.n_alias,
            normalize=request.normalize,
            save_format=request.save_format,
        )

        if cal_path is not None:
            cal_dat = read_dat(cal_path, skip_fl=True)
            try:
                cal_full = _calibrate_file(cal_dat, opts)
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"Calibration failed: {exc}")
            cal_fs = float(cal_dat.meta["Fs"])
            del cal_dat

            axes_out = [_axis_result(c, cal_fs, request.n_alias) for c in cal_full.values()]
            skipped = [det for det, _ in _DET_AXES if det not in cal_full]
            calibration_out = CalibrationResultOut(
                session_id=request.session_id,
                file_id=request.calibration.relative_path,
                result_id=f"process_{Path(request.data.relative_path).stem}_calibration",
                sampling_rate_hz=cal_fs,
                axes=axes_out,
                skipped=skipped,
            )
            cal = _to_axis_calibrations(cal_full)
        else:
            cached = session.calibration_results.get(request.calibration_result_id)
            if cached is None:
                raise HTTPException(
                    status_code=404, detail="Calibration result not found in session"
                )
            calibration_out = CalibrationResultOut(**cached)
            cal = {
                a["detector"]: AxisCalibration(
                    alpha=a["alpha_nm_v"], kappa=a["kappa_pn_nm"], fc=a["fc_hz"]
                )
                for a in cached["axes"]
            }

        try:
            raw_off = read_dat(offset_path, skip_fl=True) if offset_path is not None else None
            raw_dat = read_dat(data_path, skip_fl=True)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        warnings: list[str] = []
        if raw_dat.t1f is None or raw_dat.t2f is None:
            warnings.append(
                "No trap-position (_pos) sidecar was found for the data file -- extension "
                "is not physically meaningful without it (trap separation defaults to "
                "zero). Force is unaffected. Re-upload the whole folder to include the "
                "sidecar."
            )

        result = process_from_dats(raw_dat, raw_off, cal, opts)
        del raw_off

        output_name = request.output_name or _default_output_name(request.data.relative_path)
        with tempfile.TemporaryDirectory() as tmp_dir:
            written_path = save_processed(
                Path(tmp_dir) / output_name, result.to_dict(), fmt=opts.save_format
            )
            dest_relative = f"processed/{written_path.name}"
            try:
                with open(written_path, "rb") as fh:
                    workspace_store.receive_file(
                        principal.user_id, request.data.dataset_id, dest_relative,
                        _iter_chunks(fh),
                    )
            except InvalidSegmentError:
                raise HTTPException(status_code=400, detail="Invalid output path")
            except (UploadTooLargeError, WorkspaceQuotaError) as exc:
                raise HTTPException(status_code=413, detail=str(exc))

        workspace_store.finalize_dataset(principal.user_id, request.data.dataset_id)

        ref = FileRef(
            kind="dataset", dataset_id=request.data.dataset_id, relative_path=dest_relative
        )
        out_path = ref.resolve(principal.user_id)
        preview = _open_into_session(session, ref, out_path)

    return ProcessRunResult(
        session_id=session.session_id,
        dataset_id=request.data.dataset_id,
        relative_path=dest_relative,
        preview=preview,
        calibration=calibration_out,
        warnings=warnings,
    )
