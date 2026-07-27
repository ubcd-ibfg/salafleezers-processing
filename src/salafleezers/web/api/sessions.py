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

from fastapi import APIRouter, Depends, HTTPException

from salafleezers.web.auth import Principal, get_current_principal
from salafleezers.web.schemas import SessionInfo
from salafleezers.web.sessions import Session, session_manager
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
        n_files=len(session.file_refs),
        file_ids=session.file_ids,
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

    try:
        path = _store_for(principal).save_session(session_id, s.to_document())
    except InvalidSegmentError:
        raise HTTPException(status_code=400, detail="Invalid session id")
    return {"saved_to": str(path)}


@router.post("/load/{session_id}")
def load_session(
    session_id: str, principal: Principal = Depends(get_current_principal)
):
    """Reload a previously saved session from disk.

    Restores the durable document only -- arrays rehydrate lazily on first
    access (see ``Session.get_file``), so loading a session with 700 files is
    a cheap operation rather than a multi-minute re-parse. Refs whose bytes
    have vanished are reported as ``n_files_unavailable`` instead of being
    silently dropped, which is what the previous eager reload did.
    """
    try:
        state = _store_for(principal).load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Saved session not found on disk")
    except InvalidSegmentError:
        raise HTTPException(status_code=400, detail="Invalid session id")

    s = Session.from_document(state, user_id=principal.user_id)
    session_manager.restore(s)

    unavailable = []
    for fid, ref in s.file_refs.items():
        try:
            if not ref.resolve(s.user_id).exists():
                unavailable.append(fid)
        except Exception:
            logger.warning(
                "Unresolvable file ref %r in session %r", fid, session_id, exc_info=True
            )
            unavailable.append(fid)

    return {
        "loaded": session_id,
        "n_files": len(s.file_refs),
        "n_files_unavailable": len(unavailable),
        "unavailable_file_ids": unavailable,
    }
