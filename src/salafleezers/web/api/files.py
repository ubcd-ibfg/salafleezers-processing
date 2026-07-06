"""File-open routes.

POST /api/files/open            → parse file into session, return preview
GET  /api/files/{file_id}/info  → metadata for a loaded file
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from salafleezers.web.auth import Principal, get_current_principal
from salafleezers.web.io import estimate_sampling_rate, load_file
from salafleezers.web.schemas import FileOpenRequest, TraceMetadata, TracePreview
from salafleezers.web.sessions import LoadedFile, session_manager

router = APIRouter(prefix="/api/files", tags=["files"])

_PREVIEW_POINTS = 2000   # target number of points for the initial render


def _resolve_data_path(raw_path: str) -> Path:
    """Resolve a client-supplied file path, confining it to ``SFZ_DATA_ROOT``.

    Local-first default (``SFZ_DATA_ROOT`` unset): no restriction -- this is
    a single-user desktop tool and the client is trusted to supply any path
    a native file picker would return. Setting ``SFZ_DATA_ROOT`` (required
    for shared-server deployments, i.e. whenever ``SFZ_AUTH_TOKEN`` is also
    set) confines every open to that directory tree, resolving symlinks and
    ``..`` so a caller can't read arbitrary files on the host.
    """
    root = os.environ.get("SFZ_DATA_ROOT") or None
    path = Path(raw_path).expanduser().resolve()
    if root is not None:
        root_resolved = Path(root).resolve()
        if path != root_resolved and not path.is_relative_to(root_resolved):
            raise HTTPException(status_code=403, detail="Path outside data root")
    return path


@router.post("/open", response_model=TracePreview, status_code=201)
def open_file(
    request: FileOpenRequest, principal: Principal = Depends(get_current_principal)
):
    """Parse a file on the server filesystem into a session.

    Creates a new session if ``session_id`` is not provided.
    Returns a decimated preview of every channel.
    """
    path = _resolve_data_path(request.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    if request.session_id:
        try:
            session = session_manager.get_owned(request.session_id, principal.user_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        session = session_manager.create(user_id=principal.user_id)

    try:
        channels, time, meta, filename = load_file(path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    n_samples = len(time)
    fs = estimate_sampling_rate(time)

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
def get_file_info(
    file_id: str,
    session_id: str,
    principal: Principal = Depends(get_current_principal),
):
    """Return metadata for a loaded file without returning any array data."""
    try:
        session = session_manager.get_owned(session_id, principal.user_id)
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
