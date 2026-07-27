"""Session state, split into a durable document and an evictable array cache.

A Session holds everything needed to reproduce a GUI workspace. It is
deliberately split in two:

  * **Durable document** -- ``file_refs`` (where each file's bytes live),
    ``file_summaries`` (cheap metadata), crops, and cached analysis results.
    Fully serializable, and the only thing that has to survive.
  * **Array cache** -- the parsed numpy arrays, held in a module-level
    :class:`ArrayCache` bounded by *bytes* rather than session count. Pure
    derived state: evicting it is never destructive, because any
    :class:`FileRef` can be re-resolved and re-parsed on the next access.

That split is what makes the app hostable. Previously a ``file_id`` was a key
into a per-process dict of raw arrays, so a restart lost every loaded file, the
session TTL destroyed work, and two uvicorn workers would have been two
disjoint session universes. Now the arrays are a cache in front of durable
per-user storage, so rehydration is the normal path rather than a special
"reload" route.

Still process-local: ``session_manager`` is an in-memory
:class:`SessionStore`. Swapping in a Redis/Postgres implementation behind that
Protocol -- plus passing the app to uvicorn as an import string -- is what
would make ``--workers`` safe. See the architecture notes in the plan.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from pathlib import Path
from typing import Any, Protocol

import numpy as np

logger = logging.getLogger(__name__)

# Sessions hold references and cached results, not raw arrays, so these caps
# bound bookkeeping rather than memory. Memory is bounded separately by
# ArrayCache's byte budget.
_DEFAULT_MAX_SESSIONS = 50
_DEFAULT_TTL_SECONDS = 4 * 3600.0

# Total bytes of parsed trace arrays held across all sessions. A single .dat
# expands to roughly 4 bytes/sample/channel as float32, so a handful of large
# traces can run to a few GB -- this is the knob that actually keeps the
# process from growing without bound.
_DEFAULT_MAX_CACHE_BYTES = 4 * 1024 * 1024 * 1024   # 4 GB


def _configured_max_sessions() -> int:
    return int(os.environ.get("SFZ_MAX_SESSIONS") or _DEFAULT_MAX_SESSIONS)


def _configured_ttl_seconds() -> float | None:
    raw = os.environ.get("SFZ_SESSION_TTL_SECONDS")
    if raw is None:
        return _DEFAULT_TTL_SECONDS
    if raw == "" or float(raw) <= 0:
        return None   # explicitly disabled
    return float(raw)


def _configured_max_cache_bytes() -> int:
    return int(os.environ.get("SFZ_MAX_CACHE_BYTES") or _DEFAULT_MAX_CACHE_BYTES)


# ---------------------------------------------------------------------------
# Durable file references
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FileRef:
    """A durable, re-resolvable pointer to one file's bytes.

    ``kind="dataset"`` references a file in the caller's upload workspace
    (see web/workspace.py) and is confined to it -- the portable form, and the
    only one that makes sense when client and server don't share a filesystem.
    ``kind="path"`` is a server-filesystem path, kept for session reload and
    CLI/scripted callers.
    """
    kind: str                          # "dataset" | "path"
    path: str | None = None
    dataset_id: str | None = None
    relative_path: str | None = None

    def resolve(self, user_id: str) -> Path:
        """Resolve to a concrete filesystem path for *user_id*."""
        if self.kind == "dataset":
            from salafleezers.web.workspace import workspace_store
            assert self.dataset_id is not None and self.relative_path is not None
            return workspace_store.resolve_file_path(
                user_id, self.dataset_id, self.relative_path
            )
        if self.kind == "path":
            assert self.path is not None
            return Path(self.path)
        raise ValueError(f"Unknown FileRef kind: {self.kind!r}")

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "path": self.path,
            "dataset_id": self.dataset_id,
            "relative_path": self.relative_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FileRef":
        return cls(
            kind=data["kind"],
            path=data.get("path"),
            dataset_id=data.get("dataset_id"),
            relative_path=data.get("relative_path"),
        )


@dataclass
class FileSummary:
    """Cheap metadata about a loaded file, available without its arrays.

    Lets listing/metadata routes answer without forcing a rehydrate -- which
    matters once arrays are an evictable cache rather than always resident.
    """
    file_id: str
    filename: str
    n_samples: int
    sampling_rate_hz: float
    duration_s: float
    channels: list[str]
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id,
            "filename": self.filename,
            "n_samples": self.n_samples,
            "sampling_rate_hz": self.sampling_rate_hz,
            "duration_s": self.duration_s,
            "channels": list(self.channels),
            "meta": {k: str(v) for k, v in self.meta.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FileSummary":
        return cls(
            file_id=data["file_id"],
            filename=data["filename"],
            n_samples=data["n_samples"],
            sampling_rate_hz=data["sampling_rate_hz"],
            duration_s=data.get("duration_s", 0.0),
            channels=list(data.get("channels", [])),
            meta=data.get("meta", {}),
        )


@dataclass
class LoadedFile:
    """One parsed file's arrays. Cached, derived state -- never authoritative."""
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

    def nbytes(self) -> int:
        """Approximate resident size, including memoized float64 casts."""
        total = self.time.nbytes + sum(a.nbytes for a in self.channels.values())
        total += sum(a.nbytes for a in self._channel64_cache.values())
        if "time64" in self.__dict__:
            total += self.__dict__["time64"].nbytes
        return total

    def summary(self) -> FileSummary:
        return FileSummary(
            file_id=self.file_id,
            filename=self.filename,
            n_samples=self.n_samples,
            sampling_rate_hz=self.sampling_rate_hz,
            duration_s=(
                float(self.time[-1] - self.time[0]) if len(self.time) > 1 else 0.0
            ),
            channels=list(self.channels.keys()),
            meta=self.meta,
        )


# ---------------------------------------------------------------------------
# Byte-bounded array cache
# ---------------------------------------------------------------------------

class ArrayCache:
    """Process-wide LRU cache of parsed arrays, bounded by total bytes.

    Bounding by bytes rather than by entry or session count is the point: one
    session with a 2 GB trace and fifty sessions with small ones are very
    different memory profiles, and only a byte budget distinguishes them.
    Eviction is always safe -- every entry can be rebuilt from its
    :class:`FileRef`.
    """

    def __init__(self, max_bytes: int | None = None) -> None:
        self.max_bytes = max_bytes if max_bytes is not None else _configured_max_cache_bytes()
        self._entries: OrderedDict[tuple[str, str], LoadedFile] = OrderedDict()

    @property
    def current_bytes(self) -> int:
        return sum(f.nbytes() for f in self._entries.values())

    def get(self, session_id: str, file_id: str) -> LoadedFile | None:
        key = (session_id, file_id)
        entry = self._entries.get(key)
        if entry is not None:
            self._entries.move_to_end(key)
        return entry

    def put(self, session_id: str, file_id: str, loaded: LoadedFile) -> None:
        key = (session_id, file_id)
        self._entries[key] = loaded
        self._entries.move_to_end(key)
        self._evict_to_budget()

    def discard(self, session_id: str, file_id: str) -> None:
        self._entries.pop((session_id, file_id), None)

    def discard_session(self, session_id: str) -> None:
        for key in [k for k in self._entries if k[0] == session_id]:
            del self._entries[key]

    def _evict_to_budget(self) -> None:
        # Always keep the most-recently-used entry even if it alone exceeds the
        # budget: evicting it would make the request that just loaded it fail,
        # and a single trace larger than the cap is a sizing problem to report,
        # not a reason to thrash.
        while len(self._entries) > 1 and self.current_bytes > self.max_bytes:
            evicted_key, _ = self._entries.popitem(last=False)
            logger.debug("ArrayCache evicted %s to stay under budget", evicted_key)


array_cache = ArrayCache()


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

@dataclass
class Session:
    """Full workspace state for one user session.

    ``file_refs``/``file_summaries``/``crops``/``*_results`` are the durable
    document. Arrays are fetched through :meth:`get_file`, which rehydrates
    from the ref on a cache miss.
    """
    session_id: str
    created_at: datetime
    user_id: str = "local"
    last_accessed: datetime = field(default_factory=datetime.now)
    file_refs: dict[str, FileRef] = field(default_factory=dict)
    file_summaries: dict[str, FileSummary] = field(default_factory=dict)
    crops: dict[str, tuple[float, float]] = field(default_factory=dict)
    # Cached analysis results (keyed by arbitrary result_id)
    step_results: dict[str, Any] = field(default_factory=dict)
    wlc_results: dict[str, Any] = field(default_factory=dict)
    velocity_results: dict[str, Any] = field(default_factory=dict)
    pwd_results: dict[str, Any] = field(default_factory=dict)
    kinetics_results: dict[str, Any] = field(default_factory=dict)
    kde_results: dict[str, Any] = field(default_factory=dict)

    # -- files ------------------------------------------------------------

    @property
    def file_ids(self) -> list[str]:
        return list(self.file_refs.keys())

    def add_file(self, file_id: str, ref: FileRef, loaded: LoadedFile) -> None:
        """Register a newly parsed file: durable ref + summary, arrays cached."""
        self.file_refs[file_id] = ref
        self.file_summaries[file_id] = loaded.summary()
        array_cache.put(self.session_id, file_id, loaded)

    def get_file(self, file_id: str) -> LoadedFile | None:
        """Return a file's arrays, rehydrating from its ref on a cache miss.

        Returns ``None`` if the file isn't part of this session, or if its
        bytes can no longer be read (deleted dataset, moved path) -- callers
        surface that as a 404 rather than a 500, since a vanished source is a
        normal condition once storage outlives the process.
        """
        ref = self.file_refs.get(file_id)
        if ref is None:
            return None

        cached = array_cache.get(self.session_id, file_id)
        if cached is not None:
            return cached

        try:
            loaded = self._load_from_ref(file_id, ref)
        except Exception:
            logger.warning(
                "Failed to rehydrate file %r in session %r", file_id, self.session_id,
                exc_info=True,
            )
            return None

        array_cache.put(self.session_id, file_id, loaded)
        return loaded

    def _load_from_ref(self, file_id: str, ref: FileRef) -> LoadedFile:
        from salafleezers.web.io import estimate_sampling_rate, load_file

        path = ref.resolve(self.user_id)
        channels, time, meta, filename = load_file(path)
        return LoadedFile(
            file_id=file_id,
            filename=filename,
            path=str(path),
            n_samples=len(time),
            sampling_rate_hz=estimate_sampling_rate(time),
            channels=channels,
            time=time,
            meta=meta,
        )

    def remove_file(self, file_id: str) -> None:
        self.file_refs.pop(file_id, None)
        self.file_summaries.pop(file_id, None)
        self.crops.pop(file_id, None)
        array_cache.discard(self.session_id, file_id)

    # -- persistence ------------------------------------------------------

    def to_document(self) -> dict:
        """Serialize the durable half of this session."""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "file_refs": {fid: r.to_dict() for fid, r in self.file_refs.items()},
            "file_summaries": {
                fid: s.to_dict() for fid, s in self.file_summaries.items()
            },
            "crops": {fid: list(c) for fid, c in self.crops.items()},
            "step_results": self.step_results,
            "wlc_results": self.wlc_results,
            "velocity_results": self.velocity_results,
            "pwd_results": self.pwd_results,
            "kinetics_results": self.kinetics_results,
            "kde_results": self.kde_results,
        }

    @classmethod
    def from_document(cls, data: dict, user_id: str) -> "Session":
        refs = {
            fid: FileRef.from_dict(r) for fid, r in data.get("file_refs", {}).items()
        }
        # Sessions saved before file_refs existed stored a flat {file_id: path}
        # map; read them as path-kind refs so old saves still load.
        for fid, path_str in data.get("file_paths", {}).items():
            refs.setdefault(fid, FileRef(kind="path", path=path_str))

        return cls(
            session_id=data["session_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            user_id=user_id,
            file_refs=refs,
            file_summaries={
                fid: FileSummary.from_dict(s)
                for fid, s in data.get("file_summaries", {}).items()
            },
            crops={
                fid: (float(c[0]), float(c[1]))
                for fid, c in data.get("crops", {}).items()
            },
            step_results=data.get("step_results", {}),
            wlc_results=data.get("wlc_results", {}),
            velocity_results=data.get("velocity_results", {}),
            pwd_results=data.get("pwd_results", {}),
            kinetics_results=data.get("kinetics_results", {}),
            kde_results=data.get("kde_results", {}),
        )


# ---------------------------------------------------------------------------
# Session store
# ---------------------------------------------------------------------------

class SessionStore(Protocol):
    """Structural interface for where live sessions are kept.

    Declared so a shared implementation (Redis, Postgres) can replace the
    in-memory one without touching route logic -- the change that, together
    with passing the app to uvicorn as an import string, would make
    ``--workers`` safe. Mirrors the intent of
    :class:`salafleezers.web.storage.StorageBackend`.
    """

    def create(self, user_id: str = ...) -> Session: ...
    def get(self, session_id: str) -> Session: ...
    def get_owned(self, session_id: str, user_id: str) -> Session: ...
    def list_ids(self, user_id: str | None = ...) -> list[str]: ...
    def delete(self, session_id: str, user_id: str | None = ...) -> None: ...
    def restore(self, session: Session) -> None: ...


_UNSET = object()   # distinguishes "use env-configured default" from an explicit None


class SessionManager:
    """In-memory :class:`SessionStore` implementation (process-local)."""

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

    def _drop(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        array_cache.discard_session(session_id)

    def _evict_expired(self) -> None:
        if self.ttl_seconds is None:
            return
        now = datetime.now()
        expired = [
            sid for sid, s in self._sessions.items()
            if (now - s.last_accessed).total_seconds() > self.ttl_seconds
        ]
        for sid in expired:
            self._drop(sid)

    def _evict_lru_if_full(self) -> None:
        if self.max_sessions is None:
            return
        while len(self._sessions) >= self.max_sessions:
            oldest_sid = min(
                self._sessions, key=lambda sid: self._sessions[sid].last_accessed
            )
            self._drop(oldest_sid)

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
        self._drop(session_id)

    def restore(self, session: Session) -> None:
        """Register a :class:`Session` reconstructed from disk (e.g. reload)."""
        self._sessions[session.session_id] = session


# Module-level singleton shared by all routers
session_manager = SessionManager()
