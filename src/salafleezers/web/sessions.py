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

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from typing import Any

import numpy as np

# Sessions hold full-resolution numpy arrays and are never explicitly closed
# by the client, so without a cap the process grows without bound as files
# are opened. Configurable via env for shared-server deployments; local-first
# single-user use is unlikely to ever hit either default.
_DEFAULT_MAX_SESSIONS = 50
_DEFAULT_TTL_SECONDS = 4 * 3600.0


def _configured_max_sessions() -> int:
    return int(os.environ.get("SFZ_MAX_SESSIONS") or _DEFAULT_MAX_SESSIONS)


def _configured_ttl_seconds() -> float | None:
    raw = os.environ.get("SFZ_SESSION_TTL_SECONDS")
    if raw is None:
        return _DEFAULT_TTL_SECONDS
    if raw == "" or float(raw) <= 0:
        return None   # explicitly disabled
    return float(raw)


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
    _channel64_cache: dict[str, np.ndarray] = field(
        default_factory=dict, repr=False, compare=False
    )

    @cached_property
    def time64(self) -> np.ndarray:
        """float64 cast of ``time``, computed once and reused.

        Every analysis route needs float64 for stable numerics, but a trace
        can be tens of millions of samples -- re-casting the full time axis
        on every HTTP/WS call for read-only data that never changes after
        load was a repeated, avoidable O(n) allocation.
        """
        return self.time.astype(np.float64)

    def resolve_channel64(self, channel: str) -> np.ndarray | None:
        """Look up *channel* (case-insensitively) and cache its float64 cast.

        Returns ``None`` if no channel matches any of ``channel``,
        ``channel.lower()``, ``channel.upper()`` -- callers decide how to
        surface that (404 vs. WS error message).
        """
        cached = self._channel64_cache.get(channel)
        if cached is not None:
            return cached
        for name in (channel, channel.lower(), channel.upper()):
            if name in self.channels:
                result = self.channels[name].astype(np.float64)
                self._channel64_cache[channel] = result
                return result
        return None


@dataclass
class Session:
    """Full workspace state for one user session."""
    session_id: str
    created_at: datetime
    user_id: str = "local"
    last_accessed: datetime = field(default_factory=datetime.now)
    files: dict[str, LoadedFile] = field(default_factory=dict)
    crops: dict[str, tuple[float, float]] = field(default_factory=dict)
    # Cached analysis results (keyed by arbitrary result_id)
    step_results: dict[str, Any] = field(default_factory=dict)
    wlc_results: dict[str, Any] = field(default_factory=dict)
    velocity_results: dict[str, Any] = field(default_factory=dict)
    pwd_results: dict[str, Any] = field(default_factory=dict)
    kinetics_results: dict[str, Any] = field(default_factory=dict)
    kde_results: dict[str, Any] = field(default_factory=dict)


_UNSET = object()   # distinguishes "use env-configured default" from an explicit None


class SessionManager:
    def __init__(
        self,
        max_sessions: int | None = _UNSET,  # type: ignore[assignment]
        ttl_seconds: float | None = _UNSET,  # type: ignore[assignment]
    ) -> None:
        """Create a session manager.

        ``max_sessions``/``ttl_seconds`` left unset fall back to the
        ``SFZ_MAX_SESSIONS``/``SFZ_SESSION_TTL_SECONDS`` env vars (or their
        defaults). Pass ``None`` explicitly to disable that limit -- distinct
        from leaving the parameter unset, since ``None`` is also a valid
        "disabled" value.
        """
        self._sessions: dict[str, Session] = {}
        self.max_sessions = (
            _configured_max_sessions() if max_sessions is _UNSET else max_sessions
        )
        self.ttl_seconds = (
            _configured_ttl_seconds() if ttl_seconds is _UNSET else ttl_seconds
        )

    def _evict_expired(self) -> None:
        if self.ttl_seconds is None:
            return
        now = datetime.now()
        expired = [
            sid for sid, s in self._sessions.items()
            if (now - s.last_accessed).total_seconds() > self.ttl_seconds
        ]
        for sid in expired:
            self._sessions.pop(sid, None)

    def _evict_lru_if_full(self) -> None:
        if self.max_sessions is None:
            return
        while len(self._sessions) >= self.max_sessions:
            oldest_sid = min(
                self._sessions, key=lambda sid: self._sessions[sid].last_accessed
            )
            self._sessions.pop(oldest_sid, None)

    def create(self, user_id: str = "local") -> Session:
        self._evict_expired()
        self._evict_lru_if_full()
        sid = str(uuid.uuid4())
        s = Session(session_id=sid, created_at=datetime.now(), user_id=user_id)
        self._sessions[sid] = s
        return s

    def get(self, session_id: str) -> Session:
        s = self._sessions.get(session_id)
        if s is None:
            raise KeyError(f"Session '{session_id}' not found")
        s.last_accessed = datetime.now()
        return s

    def get_owned(self, session_id: str, user_id: str) -> Session:
        """Fetch a session, raising ``KeyError`` if another principal owns it.

        Sessions are shared process-wide state (see module docstring), so
        without this check any caller could read or mutate any other
        principal's in-memory workspace once a shared-server deployment
        (``SFZ_AUTH_TOKEN``) has more than one principal in play.
        """
        s = self.get(session_id)
        if s.user_id != user_id:
            raise KeyError(f"Session '{session_id}' not found")
        return s

    def list_ids(self, user_id: str | None = None) -> list[str]:
        if user_id is None:
            return list(self._sessions.keys())
        return [sid for sid, s in self._sessions.items() if s.user_id == user_id]

    def delete(self, session_id: str, user_id: str | None = None) -> None:
        if user_id is not None:
            s = self._sessions.get(session_id)
            if s is None or s.user_id != user_id:
                return
        self._sessions.pop(session_id, None)

    def restore(self, session: Session) -> None:
        """Register a :class:`Session` reconstructed from disk (e.g. reload)."""
        self._sessions[session.session_id] = session


# Module-level singleton shared by all routers
session_manager = SessionManager()
