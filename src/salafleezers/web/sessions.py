"""In-memory session state.

A Session holds everything needed to reproduce a GUI workspace:
  - loaded files (numpy arrays, metadata)
  - crop boundaries
  - cached analysis results (step detection, WLC fits, …)

Sessions are keyed by UUID.  The SessionManager is a module-level singleton
so the FastAPI app and all routers share the same state.
For multi-worker / multi-server deployment, swap in a Redis-backed store
without changing any business logic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np


@dataclass
class LoadedFile:
    """One parsed file held in a session."""
    file_id: str
    filename: str
    path: str
    n_samples: int
    sampling_rate_hz: float
    channels: dict[str, np.ndarray]   # float32 arrays
    time: np.ndarray                   # float32, seconds
    meta: dict[str, Any]


@dataclass
class Session:
    """Full workspace state for one user session."""
    session_id: str
    created_at: datetime
    files: dict[str, LoadedFile] = field(default_factory=dict)
    crops: dict[str, tuple[float, float]] = field(default_factory=dict)
    # Cached analysis results (keyed by arbitrary result_id)
    step_results: dict[str, Any] = field(default_factory=dict)
    wlc_results: dict[str, Any] = field(default_factory=dict)
    velocity_results: dict[str, Any] = field(default_factory=dict)
    pwd_results: dict[str, Any] = field(default_factory=dict)
    kinetics_results: dict[str, Any] = field(default_factory=dict)


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        sid = str(uuid.uuid4())
        s = Session(session_id=sid, created_at=datetime.now())
        self._sessions[sid] = s
        return s

    def get(self, session_id: str) -> Session:
        s = self._sessions.get(session_id)
        if s is None:
            raise KeyError(f"Session '{session_id}' not found")
        return s

    def list_ids(self) -> list[str]:
        return list(self._sessions.keys())

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


# Module-level singleton shared by all routers
session_manager = SessionManager()
