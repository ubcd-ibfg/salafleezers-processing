"""Session CRUD routes.

POST   /api/sessions           → create a new empty session
GET    /api/sessions           → list all in-memory sessions
GET    /api/sessions/{id}      → session info
DELETE /api/sessions/{id}      → remove from memory
POST   /api/sessions/{id}/save → persist to disk
POST   /api/sessions/load/{id} → restore from disk
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from salafleezers.web.auth import Principal, get_current_principal
from salafleezers.web.schemas import SessionInfo
from salafleezers.web.sessions import Session, LoadedFile, session_manager
from salafleezers.web.storage import (
    InvalidSegmentError,
    LocalFilesystemStore,
    UserScopedStore,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
_backend = LocalFilesystemStore()


def _store_for(principal: Principal) -> UserScopedStore:
    """Scope disk storage to the calling principal (see web/auth.py).

    In the local-first default (no SFZ_AUTH_TOKEN configured), every caller
    resolves to the same anonymous principal, so this behaves exactly like
    using a single shared LocalFilesystemStore -- the namespacing only
    matters once shared-server / multi-user auth is turned on.
    """
    return UserScopedStore(_backend, principal.user_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _info(session: Session) -> SessionInfo:
    return SessionInfo(
        session_id=session.session_id,
        created_at=session.created_at.isoformat(),
        n_files=len(session.files),
        file_ids=list(session.files.keys()),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", response_model=SessionInfo, status_code=201)
def create_session(principal: Principal = Depends(get_current_principal)):
    """Create a new empty session and return its ID."""
    return _info(session_manager.create(user_id=principal.user_id))


@router.get("", response_model=list[SessionInfo])
def list_sessions(principal: Principal = Depends(get_current_principal)):
    """List all in-memory sessions owned by the calling principal."""
    return [
        _info(session_manager.get(sid))
        for sid in session_manager.list_ids(user_id=principal.user_id)
    ]


@router.get("/{session_id}", response_model=SessionInfo)
def get_session(
    session_id: str, principal: Principal = Depends(get_current_principal)
):
    try:
        return _info(session_manager.get_owned(session_id, principal.user_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


@router.delete("/{session_id}")
def delete_session(
    session_id: str, principal: Principal = Depends(get_current_principal)
):
    session_manager.delete(session_id, user_id=principal.user_id)
    return {"deleted": session_id}


@router.post("/{session_id}/save")
def save_session(
    session_id: str, principal: Principal = Depends(get_current_principal)
):
    """Persist a session's metadata and results to disk."""
    try:
        s = session_manager.get_owned(session_id, principal.user_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    state = {
        "session_id": s.session_id,
        "created_at": s.created_at.isoformat(),
        "file_paths": {fid: f.path for fid, f in s.files.items()},
        "step_results": s.step_results,
        "wlc_results": s.wlc_results,
        "velocity_results": s.velocity_results,
        "pwd_results": s.pwd_results,
        "kinetics_results": s.kinetics_results,
        "kde_results": s.kde_results,
    }
    try:
        path = _store_for(principal).save_session(session_id, state)
    except InvalidSegmentError:
        raise HTTPException(status_code=400, detail="Invalid session id")
    return {"saved_to": str(path)}


@router.post("/load/{session_id}")
def load_session(
    session_id: str, principal: Principal = Depends(get_current_principal)
):
    """Reload a previously saved session from disk, re-parsing file arrays."""
    try:
        state = _store_for(principal).load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Saved session not found on disk")
    except InvalidSegmentError:
        raise HTTPException(status_code=400, detail="Invalid session id")

    s = Session(
        session_id=state["session_id"],
        created_at=datetime.fromisoformat(state["created_at"]),
        user_id=principal.user_id,
        step_results=state.get("step_results", {}),
        wlc_results=state.get("wlc_results", {}),
        velocity_results=state.get("velocity_results", {}),
        pwd_results=state.get("pwd_results", {}),
        kinetics_results=state.get("kinetics_results", {}),
        kde_results=state.get("kde_results", {}),
    )
    session_manager.restore(s)

    from salafleezers.web.io import estimate_sampling_rate, load_file

    reloaded = 0
    for fid, path_str in state.get("file_paths", {}).items():
        p = Path(path_str)
        if not p.exists():
            continue
        try:
            channels, time, meta, filename = load_file(p)
            s.files[fid] = LoadedFile(
                file_id=fid,
                filename=filename,
                path=path_str,
                n_samples=len(time),
                sampling_rate_hz=estimate_sampling_rate(time),
                channels=channels,
                time=time,
                meta=meta,
            )
            reloaded += 1
        except Exception:
            logger.warning(
                "Failed to reload file %r for session %r", path_str, session_id,
                exc_info=True,
            )

    return {"loaded": session_id, "n_files_reloaded": reloaded}
