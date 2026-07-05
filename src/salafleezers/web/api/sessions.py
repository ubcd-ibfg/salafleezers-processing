"""Session CRUD routes.

POST   /api/sessions           → create a new empty session
GET    /api/sessions           → list all in-memory sessions
GET    /api/sessions/{id}      → session info
DELETE /api/sessions/{id}      → remove from memory
POST   /api/sessions/{id}/save → persist to disk
POST   /api/sessions/load/{id} → restore from disk
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException

from salafleezers.web.schemas import SessionInfo
from salafleezers.web.sessions import Session, LoadedFile, session_manager
from salafleezers.web.storage import LocalFilesystemStore

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
_store = LocalFilesystemStore()


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
async def create_session():
    """Create a new empty session and return its ID."""
    return _info(session_manager.create())


@router.get("", response_model=list[SessionInfo])
async def list_sessions():
    """List all in-memory sessions."""
    return [_info(session_manager.get(sid)) for sid in session_manager.list_ids()]


@router.get("/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str):
    try:
        return _info(session_manager.get(session_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    session_manager.delete(session_id)
    return {"deleted": session_id}


@router.post("/{session_id}/save")
async def save_session(session_id: str):
    """Persist a session's metadata and results to disk."""
    try:
        s = session_manager.get(session_id)
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
    }
    path = _store.save_session(session_id, state)
    return {"saved_to": str(path)}


@router.post("/load/{session_id}")
async def load_session(session_id: str):
    """Reload a previously saved session from disk, re-parsing file arrays."""
    try:
        state = _store.load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Saved session not found on disk")

    s = Session(
        session_id=state["session_id"],
        created_at=datetime.fromisoformat(state["created_at"]),
        step_results=state.get("step_results", {}),
        wlc_results=state.get("wlc_results", {}),
        velocity_results=state.get("velocity_results", {}),
        pwd_results=state.get("pwd_results", {}),
        kinetics_results=state.get("kinetics_results", {}),
    )
    session_manager._sessions[s.session_id] = s

    from salafleezers.web.io import load_file

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
                sampling_rate_hz=float(1.0 / (time[1] - time[0])) if len(time) > 1 else 1.0,
                channels=channels,
                time=time,
                meta=meta,
            )
            reloaded += 1
        except Exception:
            pass

    return {"loaded": session_id, "n_files_reloaded": reloaded}
