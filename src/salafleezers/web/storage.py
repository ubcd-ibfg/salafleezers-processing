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

import numpy as np


_DEFAULT_ROOT = Path.home() / ".salafleezers" / "sessions"


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
        path.parent.mkdir(exist_ok=True)
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
        return [d.name for d in self.root.iterdir() if d.is_dir()
                and (d / "session.json").exists()]

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
        path.parent.mkdir(exist_ok=True)
        np.savez_compressed(path, **arrays)
        return path

    def load_arrays(self, session_id: str, name: str) -> dict[str, np.ndarray]:
        path = self.root / session_id / f"{name}.npz"
        if not path.exists():
            raise FileNotFoundError(f"Array store '{name}' not found for session '{session_id}'")
        return dict(np.load(path))
