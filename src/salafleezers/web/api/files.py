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
from salafleezers.web.sessions import FileRef, LoadedFile, session_manager
from salafleezers.web.storage import InvalidSegmentError

router = APIRouter(prefix="/api/files", tags=["files"])

_PREVIEW_POINTS = 2000   # target number of points for the initial render


def _resolve_server_path(raw_path: str) -> Path:
    """Resolve a server-filesystem path, confining it to ``SFZ_DATA_ROOT``.

    Local-first default (``SFZ_DATA_ROOT`` unset): no restriction -- this is
    a single-user desktop tool and the client is trusted to supply any path
    a native file picker would return. Setting ``SFZ_DATA_ROOT`` (required
    for shared-server deployments, i.e. whenever ``SFZ_AUTH_TOKEN`` is also
    set) confines every open to that directory tree, resolving symlinks and
    ``..`` so a caller can't read arbitrary files on the host.

    Note that uploaded files (``kind="dataset"`` refs) never come through
    here: they are confined to the caller's own workspace by construction,
    which is why upload works with no server-side configuration at all.
    """
    root = os.environ.get("SFZ_DATA_ROOT") or None
    path = Path(raw_path).expanduser().resolve()
    if root is not None:
        root_resolved = Path(root).resolve()
        if path != root_resolved and not path.is_relative_to(root_resolved):
            raise HTTPException(status_code=403, detail="Path outside data root")
    return path


def _ref_and_path(request: FileOpenRequest, user_id: str) -> tuple[FileRef, Path]:
    """Build the durable ref for this request and resolve it to a path."""
    if request.dataset_id is not None and request.relative_path is not None:
        ref = FileRef(
            kind="dataset",
            dataset_id=request.dataset_id,
            relative_path=request.relative_path,
        )
        try:
            return ref, ref.resolve(user_id)
        except InvalidSegmentError:
            raise HTTPException(status_code=400, detail="Invalid dataset reference")

    assert request.path is not None   # guaranteed by FileOpenRequest's validator
    path = _resolve_server_path(request.path)
    return FileRef(kind="path", path=str(path)), path


def _open_into_session(session, ref: FileRef, path: Path) -> TracePreview:
    """Parse *path* and register it in *session*, returning a decimated preview.

    Shared by ``POST /api/files/open`` and ``POST /api/process`` (which opens
    its freshly written force/extension artifact the same way an uploaded
    file would be opened).
    """
    try:
        channels, time, meta, filename = load_file(path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    n_samples = len(time)
    fs = estimate_sampling_rate(time)

    file_id = str(uuid.uuid4())
    session.add_file(
        file_id,
        ref,
        LoadedFile(
            file_id=file_id,
            filename=filename,
            path=str(path),
            n_samples=n_samples,
            sampling_rate_hz=fs,
            channels=channels,
            time=time,
            meta=meta,
        ),
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


@router.post("/open", response_model=TracePreview, status_code=201)
def open_file(
    request: FileOpenRequest, principal: Principal = Depends(get_current_principal)
):
    """Parse a file into a session, by uploaded-dataset reference or server path.

    Creates a new session if ``session_id`` is not provided.
    Returns a decimated preview of every channel.
    """
    ref, path = _ref_and_path(request, principal.user_id)
    if not path.exists():
        detail = (
            f"File not found in dataset: {request.relative_path}"
            if ref.kind == "dataset" else f"File not found: {path}"
        )
        raise HTTPException(status_code=404, detail=detail)

    if request.session_id:
        try:
            session = session_manager.get_owned(request.session_id, principal.user_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        session = session_manager.create(user_id=principal.user_id)

    return _open_into_session(session, ref, path)


@router.get("/{file_id}/info", response_model=TraceMetadata)
def get_file_info(
    file_id: str,
    session_id: str,
    principal: Principal = Depends(get_current_principal),
):
    """Return metadata for a loaded file without returning any array data.

    Answers from the session's stored summary, so it never forces a
    rehydrate just to report a channel list.
    """
    try:
        session = session_manager.get_owned(session_id, principal.user_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    summary = session.file_summaries.get(file_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="File not found in session")

    return TraceMetadata(
        file_id=file_id,
        filename=summary.filename,
        n_samples=summary.n_samples,
        sampling_rate_hz=summary.sampling_rate_hz,
        duration_s=summary.duration_s,
        channels=list(summary.channels),
        meta={k: str(v) for k, v in summary.meta.items()},
    )
