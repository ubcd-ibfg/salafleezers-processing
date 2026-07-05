"""File-open routes.

POST /api/files/open            → parse file into session, return preview
GET  /api/files/{file_id}/info  → metadata for a loaded file
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException

from salafleezers.web.io import load_file
from salafleezers.web.schemas import FileOpenRequest, TraceMetadata, TracePreview
from salafleezers.web.sessions import LoadedFile, session_manager

router = APIRouter(prefix="/api/files", tags=["files"])

_PREVIEW_POINTS = 2000   # target number of points for the initial render


@router.post("/open", response_model=TracePreview, status_code=201)
async def open_file(request: FileOpenRequest):
    """Parse a file on the server filesystem into a session.

    Creates a new session if ``session_id`` is not provided.
    Returns a decimated preview of every channel.
    """
    path = Path(request.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    if request.session_id:
        try:
            session = session_manager.get(request.session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        session = session_manager.create()

    try:
        channels, time, meta, filename = load_file(path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    n_samples = len(time)
    fs = float(1.0 / (time[1] - time[0])) if n_samples > 1 else 1.0

    file_id = str(uuid.uuid4())
    session.files[file_id] = LoadedFile(
        file_id=file_id,
        filename=filename,
        path=str(path),
        n_samples=n_samples,
        sampling_rate_hz=fs,
        channels=channels,
        time=time,
        meta=meta,
    )

    decimate = max(1, n_samples // _PREVIEW_POINTS)
    return TracePreview(
        file_id=file_id,
        session_id=session.session_id,
        time=time[::decimate].tolist(),
        channels={k: v[::decimate].tolist() for k, v in channels.items()},
        n_original=n_samples,
        decimate_factor=decimate,
        sampling_rate_hz=fs,
        filename=filename,
    )


@router.get("/{file_id}/info", response_model=TraceMetadata)
async def get_file_info(file_id: str, session_id: str):
    """Return metadata for a loaded file without returning any array data."""
    try:
        session = session_manager.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    f = session.files.get(file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="File not found in session")

    return TraceMetadata(
        file_id=file_id,
        filename=f.filename,
        n_samples=f.n_samples,
        sampling_rate_hz=f.sampling_rate_hz,
        duration_s=float(f.time[-1] - f.time[0]) if len(f.time) > 1 else 0.0,
        channels=list(f.channels.keys()),
        meta={k: str(v) for k, v in f.meta.items()},
    )
