"""Local-filesystem session persistence.

Provides the StorageBackend interface so future server-side backends
(S3, database, …) can be dropped in behind the same API.

The local backend stores each session as:
  ~/.salafleezers/sessions/<session_id>/session.json   — serializable state
  ~/.salafleezers/sessions/<session_id>/<name>.npz     — array data
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Protocol

import numpy as np


_DEFAULT_ROOT = Path.home() / ".salafleezers" / "sessions"


class StorageBackend(Protocol):
    """Structural interface implemented by every storage backend.

    Formalizes what was previously an implicit contract on
    ``LocalFilesystemStore`` so a future server-side backend (S3, database, …)
    or a wrapper like :class:`UserScopedStore` can be typed and swapped in
    without touching the routes that use it.
    """

    def save_session(self, session_id: str, state: dict) -> Path: ...
    def load_session(self, session_id: str) -> dict: ...
    def list_sessions(self) -> list[str]: ...
    def delete_session(self, session_id: str) -> None: ...
    def save_arrays(self, session_id: str, name: str, arrays: dict[str, np.ndarray]) -> Path: ...
    def load_arrays(self, session_id: str, name: str) -> dict[str, np.ndarray]: ...


class LocalFilesystemStore:
    """Persist session state and array data to the local filesystem."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else _DEFAULT_ROOT
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Session JSON (serializable state: paths, fit results, metadata)
    # ------------------------------------------------------------------

    def save_session(self, session_id: str, state: dict) -> Path:
        path = self.root / session_id / "session.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f, default=str, indent=2)
        return path

    def load_session(self, session_id: str) -> dict:
        path = self.root / session_id / "session.json"
        if not path.exists():
            raise FileNotFoundError(f"Session '{session_id}' not found on disk")
        with open(path) as f:
            return json.load(f)

    def list_sessions(self) -> list[str]:
        """List every session, by relative path from ``root``.

        Recursive (not a single-level scan) so a nesting wrapper like
        :class:`UserScopedStore` — which stores sessions at
        ``<user_id>/<session_id>`` — composes correctly: the returned
        strings are full ``session.json`` parent paths relative to root
        (e.g. ``"local/abc-123"``), not just top-level directory names.
        """
        return [
            p.parent.relative_to(self.root).as_posix()
            for p in self.root.rglob("session.json")
        ]

    def delete_session(self, session_id: str) -> None:
        path = self.root / session_id
        if path.exists():
            shutil.rmtree(path)

    # ------------------------------------------------------------------
    # Array data (numpy arrays too large for JSON)
    # ------------------------------------------------------------------

    def save_arrays(self, session_id: str, name: str,
                    arrays: dict[str, np.ndarray]) -> Path:
        path = self.root / session_id / f"{name}.npz"
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, **arrays)
        return path

    def load_arrays(self, session_id: str, name: str) -> dict[str, np.ndarray]:
        path = self.root / session_id / f"{name}.npz"
        if not path.exists():
            raise FileNotFoundError(f"Array store '{name}' not found for session '{session_id}'")
        return dict(np.load(path))


class UserScopedStore:
    """Namespaces another :class:`StorageBackend` by user, for isolation.

    Drop-in for a shared-server deployment: each user's sessions live under
    their own ``<user_id>/<session_id>`` subtree, so concurrent users never
    collide with or see each other's sessions — without any change to the
    session/analysis business logic that calls this. In the local-first
    default (single anonymous user), this just adds one constant path
    segment and behaves identically to using the wrapped backend directly.
    """

    def __init__(self, backend: StorageBackend, user_id: str) -> None:
        self._backend = backend
        self._user_id = user_id

    def _scoped(self, session_id: str) -> str:
        return f"{self._user_id}/{session_id}"

    def save_session(self, session_id: str, state: dict) -> Path:
        return self._backend.save_session(self._scoped(session_id), state)

    def load_session(self, session_id: str) -> dict:
        return self._backend.load_session(self._scoped(session_id))

    def list_sessions(self) -> list[str]:
        prefix = f"{self._user_id}/"
        return [
            sid[len(prefix):]
            for sid in self._backend.list_sessions()
            if sid.startswith(prefix)
        ]

    def delete_session(self, session_id: str) -> None:
        self._backend.delete_session(self._scoped(session_id))

    def save_arrays(self, session_id: str, name: str, arrays: dict[str, np.ndarray]) -> Path:
        return self._backend.save_arrays(self._scoped(session_id), name, arrays)

    def load_arrays(self, session_id: str, name: str) -> dict[str, np.ndarray]:
        return self._backend.load_arrays(self._scoped(session_id), name)
