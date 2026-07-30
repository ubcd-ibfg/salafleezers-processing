"""Durable per-user upload workspace.

Gives browser-uploaded files and folders a home on disk so a user can drag
data into the GUI without ever typing a server filesystem path. A "dataset"
is one drop (a folder or a batch of loose files). Files are written one at a
time as they arrive, then "finalized": classified into openable traces,
attached sidecars, batch descriptors, and skipped files, with each trace's
sidecar-completeness checked against its ``.dat`` header (see io/reader.py) --
turning the reader's silent ``warnings.warn`` on a missing ``_pos``/``_fl``
sidecar into something the UI can show *before* the user opens the file.

Layout:
  ~/.salafleezers/uploads/<user_id>/<dataset_id>/manifest.json
  ~/.salafleezers/uploads/<user_id>/<dataset_id>/files/<relative_path>
"""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Protocol

from salafleezers.web.storage import InvalidSegmentError, _safe_name, _safe_segment

_DEFAULT_ROOT = Path.home() / ".salafleezers" / "uploads"

_DEFAULT_MAX_UPLOAD_BYTES = 1024 * 1024 * 1024           # 1 GB per file
_DEFAULT_MAX_WORKSPACE_BYTES = 20 * 1024 * 1024 * 1024   # 20 GB per user

# Sidecars are only ever a raw-.dat convention (see io/reader.py) -- .h5/.npz
# outputs are single self-contained files.
_SIDECAR_SUFFIXES = ("_pos", "_fl", "_grn")
_TRACE_EXTENSIONS = {".dat", ".h5", ".hdf5", ".hdf", ".npz"}
_BATCH_EXTENSIONS = {".txt"}


class UploadTooLargeError(ValueError):
    """Raised mid-stream when an upload exceeds the per-file byte cap."""

    def __init__(self, cap: int) -> None:
        super().__init__(f"Upload exceeds max size of {cap} bytes")
        self.cap = cap


class WorkspaceQuotaError(ValueError):
    """Raised when a user's total upload usage would exceed their quota."""

    def __init__(self, cap: int) -> None:
        super().__init__(f"Workspace quota exceeded (limit {cap} bytes)")
        self.cap = cap


def max_upload_bytes() -> int:
    return int(os.environ.get("SFZ_MAX_UPLOAD_BYTES") or _DEFAULT_MAX_UPLOAD_BYTES)


def max_workspace_bytes() -> int:
    return int(os.environ.get("SFZ_MAX_WORKSPACE_BYTES") or _DEFAULT_MAX_WORKSPACE_BYTES)


def _safe_relpath(raw: str) -> str:
    """Validate and normalize a browser-supplied relative path.

    Folder uploads send paths like ``260625/260625_001.dat`` via
    ``webkitRelativePath`` -- legitimate, unlike the bare single-segment
    names :func:`salafleezers.web.storage._safe_name` expects. This rejects
    absolute paths, drive letters, backslash separators, and ``..``
    components in any position, then returns a normalized POSIX-style
    relative path. Every join in this module routes through here before
    ``_safe_segment`` re-checks containment.
    """
    if not raw:
        raise InvalidSegmentError("Empty relative_path")
    normalized = raw.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[a-zA-Z]:", normalized):
        raise InvalidSegmentError(f"Absolute relative_path: {raw!r}")
    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise InvalidSegmentError(f"Invalid relative_path: {raw!r}")
    return "/".join(parts)


@dataclass
class UploadEntry:
    relative_path: str
    size_bytes: int
    kind: str                                  # "trace" | "sidecar" | "batch" | "skipped"
    parent: str | None = None                  # sidecar: relative_path of its trace
    sidecars: list[str] = field(default_factory=list)          # trace: attached sidecars
    missing_sidecars: list[str] = field(default_factory=list)  # trace: expected but absent
    warning: str | None = None
    datatype: int | None = None                # .dat header field 5: 1 = calibration file


@dataclass
class Dataset:
    dataset_id: str
    user_id: str
    name: str
    created_at: str
    finalized: bool = False
    entries: list[UploadEntry] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(e.size_bytes for e in self.entries)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Dataset":
        entries = [UploadEntry(**e) for e in data.get("entries", [])]
        return cls(
            dataset_id=data["dataset_id"],
            user_id=data["user_id"],
            name=data["name"],
            created_at=data["created_at"],
            finalized=data.get("finalized", False),
            entries=entries,
        )


class WorkspaceBackend(Protocol):
    """Structural interface for where uploaded bytes live.

    Declared alongside the local implementation so an object-store backend
    (S3/MinIO -- the natural choice once the app is hosted rather than run on
    the user's own machine) can be dropped in without touching routes.
    Mirrors the intent of :class:`salafleezers.web.storage.StorageBackend`.

    ``resolve_file_path`` is the one method that assumes a filesystem: an
    object-store implementation would materialize to a local cache path,
    since the ``.dat`` reader needs seekable sibling files for its
    ``_pos``/``_fl``/``_grn`` sidecars.
    """

    def create_dataset(self, user_id: str, name: str) -> "Dataset": ...
    def receive_file(
        self, user_id: str, dataset_id: str, relative_path: str, chunks: Iterable[bytes]
    ) -> int: ...
    def finalize_dataset(self, user_id: str, dataset_id: str) -> "Dataset": ...
    def get_dataset(self, user_id: str, dataset_id: str) -> "Dataset": ...
    def list_datasets(self, user_id: str) -> list["Dataset"]: ...
    def delete_dataset(self, user_id: str, dataset_id: str) -> None: ...
    def delete_entry(self, user_id: str, dataset_id: str, relative_path: str) -> "Dataset": ...
    def resolve_file_path(
        self, user_id: str, dataset_id: str, relative_path: str
    ) -> Path: ...
    def usage_bytes(self, user_id: str) -> int: ...


class WorkspaceStore:
    """Local-filesystem :class:`WorkspaceBackend` implementation."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else _DEFAULT_ROOT
        self.root.mkdir(parents=True, exist_ok=True)

    # -- paths ------------------------------------------------------------

    def _dataset_dir(self, user_id: str, dataset_id: str) -> Path:
        return _safe_segment(self.root, user_id, _safe_name(dataset_id))

    def _manifest_path(self, user_id: str, dataset_id: str) -> Path:
        return self._dataset_dir(user_id, dataset_id) / "manifest.json"

    def _files_dir(self, user_id: str, dataset_id: str) -> Path:
        return self._dataset_dir(user_id, dataset_id) / "files"

    def resolve_file_path(self, user_id: str, dataset_id: str, relative_path: str) -> Path:
        """Resolve an uploaded file's path, confined to its dataset's ``files/`` dir."""
        rel = _safe_relpath(relative_path)
        return _safe_segment(self._files_dir(user_id, dataset_id), *rel.split("/"))

    # -- quota --------------------------------------------------------------

    def usage_bytes(self, user_id: str) -> int:
        user_dir = _safe_segment(self.root, user_id)
        if not user_dir.exists():
            return 0
        return sum(p.stat().st_size for p in user_dir.rglob("*") if p.is_file())

    # -- lifecycle ------------------------------------------------------------

    def create_dataset(self, user_id: str, name: str) -> Dataset:
        dataset_id = str(uuid.uuid4())
        self._files_dir(user_id, dataset_id).mkdir(parents=True, exist_ok=True)
        ds = Dataset(
            dataset_id=dataset_id,
            user_id=user_id,
            name=name or "Untitled",
            created_at=datetime.now().isoformat(),
        )
        self._write_manifest(ds)
        return ds

    def receive_file(
        self, user_id: str, dataset_id: str, relative_path: str, chunks: Iterable[bytes],
    ) -> int:
        """Stream *chunks* to disk under quota, returning bytes written.

        Enforces ``SFZ_MAX_UPLOAD_BYTES`` while writing -- not from a
        client-reported ``Content-Length``, which can lie -- and both the
        per-file cap and the total workspace quota delete the partial file
        on overrun rather than leaving debris behind.
        """
        dest = self.resolve_file_path(user_id, dataset_id, relative_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        per_file_cap = max_upload_bytes()
        workspace_cap = max_workspace_bytes()
        existing_usage = self.usage_bytes(user_id)

        written = 0
        try:
            with open(dest, "wb") as f:
                for chunk in chunks:
                    written += len(chunk)
                    if written > per_file_cap:
                        raise UploadTooLargeError(per_file_cap)
                    if existing_usage + written > workspace_cap:
                        raise WorkspaceQuotaError(workspace_cap)
                    f.write(chunk)
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
        return written

    def finalize_dataset(self, user_id: str, dataset_id: str) -> Dataset:
        """Classify every uploaded file and persist the manifest."""
        current = self.get_dataset(user_id, dataset_id)
        files_dir = self._files_dir(user_id, dataset_id)
        entries: dict[str, UploadEntry] = {}

        for p in sorted(files_dir.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(files_dir).as_posix()
            entries[rel] = UploadEntry(relative_path=rel, size_bytes=p.stat().st_size, kind="skipped")

        stems: dict[str, str] = {}   # "<dir>/<stem>" (or "<stem>" at top level) -> trace relative_path
        for rel, entry in entries.items():
            suffix = Path(rel).suffix.lower()
            stem = Path(rel).stem
            parent_dir = Path(rel).parent.as_posix()
            if suffix in _BATCH_EXTENSIONS:
                entry.kind = "batch"
            elif suffix == ".dat" and stem.endswith(_SIDECAR_SUFFIXES):
                entry.kind = "sidecar"
            elif suffix in _TRACE_EXTENSIONS:
                entry.kind = "trace"
                key = stem if parent_dir == "." else f"{parent_dir}/{stem}"
                stems[key] = rel

        for rel, entry in entries.items():
            if entry.kind != "sidecar":
                continue
            stem = Path(rel).stem
            parent_dir = Path(rel).parent.as_posix()
            for sfx in _SIDECAR_SUFFIXES:
                if stem.endswith(sfx):
                    base_stem = stem[: -len(sfx)]
                    key = base_stem if parent_dir == "." else f"{parent_dir}/{base_stem}"
                    trace_rel = stems.get(key)
                    if trace_rel is not None:
                        entry.parent = trace_rel
                        entries[trace_rel].sidecars.append(rel)
                    break

        for rel, entry in entries.items():
            if entry.kind == "trace" and rel.lower().endswith(".dat"):
                self._check_sidecar_completeness(files_dir / rel, entry)

        ds = Dataset(
            dataset_id=dataset_id,
            user_id=user_id,
            name=current.name,
            created_at=current.created_at,
            finalized=True,
            entries=sorted(entries.values(), key=lambda e: e.relative_path),
        )
        self._write_manifest(ds)
        return ds

    @staticmethod
    def _check_sidecar_completeness(path: Path, entry: UploadEntry) -> None:
        try:
            from salafleezers.io.reader import read_header
            meta, _cmt, _offset = read_header(path)
        except Exception:
            return   # unreadable/corrupt header -- opening the file will surface this

        raw_datatype = meta.get("datatype")
        entry.datatype = int(raw_datatype) if raw_datatype is not None else None

        extra = meta.get("extraData", 0)
        expected = []
        if extra in (2, 3):
            expected.append("_pos")
        if extra in (1, 3):
            expected.append("_fl")
        if not expected:
            return

        have = set()
        for s in entry.sidecars:
            s_stem = Path(s).stem
            for sfx in _SIDECAR_SUFFIXES:
                if s_stem.endswith(sfx):
                    have.add(sfx)
                    break

        missing = [sfx for sfx in expected if sfx not in have]
        entry.missing_sidecars = missing
        if missing:
            stem = Path(path).stem
            names = ", ".join(f"{stem}{m}.dat" for m in missing)
            entry.warning = (
                f"Expected sidecar file(s) {names} not found in this upload -- "
                "re-drop the whole folder, not just this file."
            )

    def get_dataset(self, user_id: str, dataset_id: str) -> Dataset:
        manifest_path = self._manifest_path(user_id, dataset_id)
        if not manifest_path.exists():
            raise FileNotFoundError(f"Dataset '{dataset_id}' not found")
        with open(manifest_path) as f:
            return Dataset.from_dict(json.load(f))

    def list_datasets(self, user_id: str) -> list[Dataset]:
        user_dir = _safe_segment(self.root, user_id)
        if not user_dir.exists():
            return []
        out = []
        for manifest_path in sorted(user_dir.glob("*/manifest.json")):
            with open(manifest_path) as f:
                out.append(Dataset.from_dict(json.load(f)))
        return out

    def delete_dataset(self, user_id: str, dataset_id: str) -> None:
        path = self._dataset_dir(user_id, dataset_id)
        if path.exists():
            shutil.rmtree(path)

    def delete_entry(self, user_id: str, dataset_id: str, relative_path: str) -> Dataset:
        """Delete one uploaded file or an entire subfolder, then re-finalize.

        A trace's sidecars are looked up from the current manifest and deleted
        alongside it -- otherwise a lone ``_pos``/``_fl`` file becomes
        invisible dead weight, since the UI only ever lists ``kind == "trace"``
        entries. Re-finalizing afterward (rather than patching the manifest by
        hand) keeps entries/sidecar-links/``missing_sidecars`` derived from
        what's actually left on disk, the same as after any upload.
        """
        path = self.resolve_file_path(user_id, dataset_id, relative_path)

        if path.is_dir():
            shutil.rmtree(path)
        elif path.is_file():
            current = self.get_dataset(user_id, dataset_id)
            entry = next((e for e in current.entries if e.relative_path == relative_path), None)
            if entry is not None and entry.kind == "trace":
                for sidecar_rel in entry.sidecars:
                    self.resolve_file_path(user_id, dataset_id, sidecar_rel).unlink(missing_ok=True)
            path.unlink()
        else:
            raise FileNotFoundError(f"'{relative_path}' not found in dataset '{dataset_id}'")

        return self.finalize_dataset(user_id, dataset_id)

    def _write_manifest(self, ds: Dataset) -> None:
        path = self._manifest_path(ds.user_id, ds.dataset_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(ds.to_dict(), f, indent=2)


# Module-level singleton, mirroring session_manager / the sessions.py _backend pattern.
workspace_store = WorkspaceStore()
