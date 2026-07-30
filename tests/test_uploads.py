"""Tests for browser-side data intake: workspace.py + api/uploads.py.

Covers the workspace store directly (path safety, quota enforcement,
sidecar-completeness classification) and the HTTP surface end to end,
including that uploaded datasets are opened through the same
``/api/files/open`` route as server paths and are isolated per principal.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from salafleezers.web.app import create_app
from salafleezers.web.storage import InvalidSegmentError
from salafleezers.web.workspace import (
    UploadTooLargeError,
    WorkspaceQuotaError,
    WorkspaceStore,
    _safe_relpath,
)

from tests.conftest import make_dat_file, make_fl_sidecar, make_pos_sidecar


# ---------------------------------------------------------------------------
# _safe_relpath
# ---------------------------------------------------------------------------

class TestSafeRelpath:
    def test_accepts_nested_path(self):
        assert _safe_relpath("260625/260625_001.dat") == "260625/260625_001.dat"

    def test_normalizes_backslashes(self):
        assert _safe_relpath("260625\\260625_001.dat") == "260625/260625_001.dat"

    def test_strips_dot_components(self):
        assert _safe_relpath("a/./b.dat") == "a/b.dat"

    @pytest.mark.parametrize("bad", [
        "",
        ".",
        "..",
        "../evil.dat",
        "a/../../b.dat",
        "/etc/passwd",
        "C:\\evil.dat",
        "C:/evil.dat",
    ])
    def test_rejects_unsafe_paths(self, bad):
        with pytest.raises(InvalidSegmentError):
            _safe_relpath(bad)


# ---------------------------------------------------------------------------
# WorkspaceStore (direct, no HTTP)
# ---------------------------------------------------------------------------

class TestWorkspaceStoreUnit:
    @pytest.fixture
    def store(self, tmp_path) -> WorkspaceStore:
        return WorkspaceStore(root=tmp_path / "uploads")

    def test_create_and_get_dataset(self, store):
        ds = store.create_dataset("local", "My Data")
        fetched = store.get_dataset("local", ds.dataset_id)
        assert fetched.name == "My Data"
        assert fetched.finalized is False

    def test_receive_file_roundtrip(self, store):
        ds = store.create_dataset("local", "ds")
        written = store.receive_file("local", ds.dataset_id, "a.dat", [b"hello", b"world"])
        assert written == 10
        path = store.resolve_file_path("local", ds.dataset_id, "a.dat")
        assert path.read_bytes() == b"helloworld"

    def test_receive_file_nested_relative_path(self, store):
        ds = store.create_dataset("local", "ds")
        store.receive_file("local", ds.dataset_id, "260625/a.dat", [b"x"])
        path = store.resolve_file_path("local", ds.dataset_id, "260625/a.dat")
        assert path.exists()
        assert path.parent.name == "260625"

    def test_receive_file_rejects_traversal(self, store):
        ds = store.create_dataset("local", "ds")
        with pytest.raises(InvalidSegmentError):
            store.receive_file("local", ds.dataset_id, "../evil.dat", [b"x"])

    def test_receive_file_over_per_file_cap_deletes_partial(self, store, monkeypatch):
        monkeypatch.setenv("SFZ_MAX_UPLOAD_BYTES", "5")
        ds = store.create_dataset("local", "ds")
        with pytest.raises(UploadTooLargeError):
            store.receive_file("local", ds.dataset_id, "big.dat", [b"x" * 10])
        path = store.resolve_file_path("local", ds.dataset_id, "big.dat")
        assert not path.exists()

    def test_receive_file_over_workspace_quota_deletes_partial(self, store, monkeypatch):
        ds = store.create_dataset("local", "ds")
        # usage_bytes() includes manifest.json overhead, so size the quota
        # relative to the baseline rather than an arbitrary small constant.
        baseline = store.usage_bytes("local")
        monkeypatch.setenv("SFZ_MAX_WORKSPACE_BYTES", str(baseline + 10))

        store.receive_file("local", ds.dataset_id, "first.dat", [b"x" * 5])
        with pytest.raises(WorkspaceQuotaError):
            store.receive_file("local", ds.dataset_id, "second.dat", [b"x" * 20])
        path = store.resolve_file_path("local", ds.dataset_id, "second.dat")
        assert not path.exists()
        # The first file, already under quota, is untouched.
        assert store.resolve_file_path("local", ds.dataset_id, "first.dat").exists()

    def test_finalize_classifies_trace_sidecar_batch_skipped(self, store, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dat = make_dat_file(src / "260625_001.dat", n_samples=64, extra_data=2)
        pos = make_pos_sidecar(src / "260625_001_pos.dat", n_samples=64)

        ds = store.create_dataset("local", "ds")
        store.receive_file("local", ds.dataset_id, "260625_001.dat", [dat.read_bytes()])
        store.receive_file("local", ds.dataset_id, "260625_001_pos.dat", [pos.read_bytes()])
        store.receive_file("local", ds.dataset_id, "260625.txt", [b"260625\n103 102 73\n"])
        store.receive_file("local", ds.dataset_id, "260625_001.fig", [b"not a real fig"])

        result = store.finalize_dataset("local", ds.dataset_id)
        entries = {e.relative_path: e for e in result.entries}

        assert entries["260625_001.dat"].kind == "trace"
        assert entries["260625_001.dat"].sidecars == ["260625_001_pos.dat"]
        assert entries["260625_001.dat"].missing_sidecars == []
        assert entries["260625_001_pos.dat"].kind == "sidecar"
        assert entries["260625_001_pos.dat"].parent == "260625_001.dat"
        assert entries["260625.txt"].kind == "batch"
        assert entries["260625_001.fig"].kind == "skipped"

    def test_finalize_warns_on_missing_expected_sidecar(self, store, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        # extra_data=1 means the header expects a _fl sidecar.
        dat = make_dat_file(src / "a.dat", n_samples=32, extra_data=1)

        ds = store.create_dataset("local", "ds")
        store.receive_file("local", ds.dataset_id, "a.dat", [dat.read_bytes()])
        result = store.finalize_dataset("local", ds.dataset_id)

        entry = result.entries[0]
        assert entry.kind == "trace"
        assert entry.missing_sidecars == ["_fl"]
        assert entry.warning is not None
        assert "re-drop the whole folder" in entry.warning

    def test_finalize_no_warning_when_sidecar_present(self, store, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dat = make_dat_file(src / "a.dat", n_samples=32, extra_data=1)
        fl = make_fl_sidecar(src / "a_fl.dat", n_samples=32)

        ds = store.create_dataset("local", "ds")
        store.receive_file("local", ds.dataset_id, "a.dat", [dat.read_bytes()])
        store.receive_file("local", ds.dataset_id, "a_fl.dat", [fl.read_bytes()])
        result = store.finalize_dataset("local", ds.dataset_id)

        trace = next(e for e in result.entries if e.relative_path == "a.dat")
        assert trace.missing_sidecars == []
        assert trace.warning is None

    def test_delete_dataset_removes_directory(self, store):
        ds = store.create_dataset("local", "ds")
        store.receive_file("local", ds.dataset_id, "a.dat", [b"x"])
        store.delete_dataset("local", ds.dataset_id)
        with pytest.raises(FileNotFoundError):
            store.get_dataset("local", ds.dataset_id)

    def test_delete_entry_removes_single_file(self, store):
        ds = store.create_dataset("local", "ds")
        store.receive_file("local", ds.dataset_id, "a.npz", [b"x" * 10])
        store.receive_file("local", ds.dataset_id, "b.npz", [b"y" * 5])
        store.finalize_dataset("local", ds.dataset_id)

        result = store.delete_entry("local", ds.dataset_id, "a.npz")

        assert {e.relative_path for e in result.entries} == {"b.npz"}
        assert result.total_bytes == 5
        assert not store.resolve_file_path("local", ds.dataset_id, "a.npz").exists()

    def test_delete_entry_cascades_to_sidecars(self, store, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dat = make_dat_file(src / "a.dat", n_samples=32, extra_data=2)
        pos = make_pos_sidecar(src / "a_pos.dat", n_samples=32)

        ds = store.create_dataset("local", "ds")
        store.receive_file("local", ds.dataset_id, "a.dat", [dat.read_bytes()])
        store.receive_file("local", ds.dataset_id, "a_pos.dat", [pos.read_bytes()])
        store.finalize_dataset("local", ds.dataset_id)

        result = store.delete_entry("local", ds.dataset_id, "a.dat")

        assert result.entries == []
        assert not store.resolve_file_path("local", ds.dataset_id, "a.dat").exists()
        assert not store.resolve_file_path("local", ds.dataset_id, "a_pos.dat").exists()

    def test_delete_entry_removes_subfolder(self, store):
        ds = store.create_dataset("local", "ds")
        store.receive_file("local", ds.dataset_id, "260625/a.dat", [b"x"])
        store.receive_file("local", ds.dataset_id, "260625/b.dat", [b"y"])
        store.receive_file("local", ds.dataset_id, "270625/c.dat", [b"z"])
        store.finalize_dataset("local", ds.dataset_id)

        result = store.delete_entry("local", ds.dataset_id, "260625")

        assert {e.relative_path for e in result.entries} == {"270625/c.dat"}
        assert not store.resolve_file_path("local", ds.dataset_id, "260625/a.dat").parent.exists()
        assert store.resolve_file_path("local", ds.dataset_id, "270625/c.dat").exists()

    def test_delete_entry_missing_path_raises(self, store):
        ds = store.create_dataset("local", "ds")
        with pytest.raises(FileNotFoundError):
            store.delete_entry("local", ds.dataset_id, "nope.dat")

    @pytest.mark.parametrize("bad", ["../evil.dat", "/etc/passwd", "a/../../b.dat"])
    def test_delete_entry_rejects_traversal(self, store, bad):
        ds = store.create_dataset("local", "ds")
        with pytest.raises(InvalidSegmentError):
            store.delete_entry("local", ds.dataset_id, bad)

    def test_list_datasets_scoped_by_user(self, store):
        store.create_dataset("alice", "a")
        store.create_dataset("bob", "b")
        assert len(store.list_datasets("alice")) == 1
        assert len(store.list_datasets("bob")) == 1
        assert store.list_datasets("alice")[0].name == "a"


# ---------------------------------------------------------------------------
# HTTP surface — /api/uploads + /api/files/open
# ---------------------------------------------------------------------------

@pytest.fixture
def upload_store(tmp_path, monkeypatch):
    """Point every module that touches the upload workspace at a temp root.

    ``api/uploads.py`` imported ``workspace_store`` by value, and
    ``sessions.FileRef.resolve`` re-imports the module attribute on every
    call -- both need patching so a test never touches the real
    ``~/.salafleezers``.
    """
    store = WorkspaceStore(root=tmp_path / "uploads")
    monkeypatch.setattr("salafleezers.web.workspace.workspace_store", store)
    monkeypatch.setattr("salafleezers.web.api.uploads.workspace_store", store)
    return store


@pytest.fixture
def app():
    return create_app(serve_spa=False)


@pytest.fixture
def client(app, upload_store):
    return TestClient(app)


def _upload(client, dataset_id, relative_path, content: bytes, **kwargs):
    return client.post(
        f"/api/uploads/{dataset_id}/files",
        data={"relative_path": relative_path},
        files={"file": (relative_path.rsplit("/", 1)[-1], io.BytesIO(content))},
        **kwargs,
    )


class TestUploadsAPI:
    def test_create_upload_finalize_list_roundtrip(self, client):
        r = client.post("/api/uploads", json={"name": "260625"})
        assert r.status_code == 201
        dataset_id = r.json()["dataset_id"]

        r = _upload(client, dataset_id, "a.npz", b"x" * 20)
        assert r.status_code == 201
        assert r.json() == {"relative_path": "a.npz", "size_bytes": 20}

        r = client.post(f"/api/uploads/{dataset_id}/finalize")
        assert r.status_code == 200
        body = r.json()
        assert body["finalized"] is True
        assert body["total_bytes"] == 20

        r = client.get("/api/uploads")
        assert len(r.json()) == 1
        assert r.json()[0]["dataset_id"] == dataset_id

    def test_upload_rejects_missing_dataset(self, client):
        r = _upload(client, "does-not-exist", "a.dat", b"x")
        assert r.status_code == 404

    @pytest.mark.parametrize("bad_path", [
        "../evil.dat", "/etc/passwd", "a/../../b.dat", "C:\\evil.dat",
    ])
    def test_upload_rejects_path_traversal(self, client, bad_path):
        dataset_id = client.post("/api/uploads", json={"name": "ds"}).json()["dataset_id"]
        r = _upload(client, dataset_id, bad_path, b"x")
        assert r.status_code == 400

    def test_upload_over_per_file_cap_rejected_and_no_partial_left(
        self, client, monkeypatch, upload_store
    ):
        monkeypatch.setenv("SFZ_MAX_UPLOAD_BYTES", "10")
        dataset_id = client.post("/api/uploads", json={"name": "ds"}).json()["dataset_id"]
        r = _upload(client, dataset_id, "big.dat", b"x" * 1000)
        assert r.status_code == 413
        path = upload_store.resolve_file_path("local", dataset_id, "big.dat")
        assert not path.exists()

    def test_upload_over_workspace_quota_rejected(self, client, monkeypatch, upload_store):
        dataset_id = client.post("/api/uploads", json={"name": "ds"}).json()["dataset_id"]
        baseline = upload_store.usage_bytes("local")
        monkeypatch.setenv("SFZ_MAX_WORKSPACE_BYTES", str(baseline + 60))

        r = _upload(client, dataset_id, "first.dat", b"x" * 50)
        assert r.status_code == 201
        r = _upload(client, dataset_id, "second.dat", b"x" * 80)
        assert r.status_code == 413

    def test_delete_dataset(self, client, upload_store):
        dataset_id = client.post("/api/uploads", json={"name": "ds"}).json()["dataset_id"]
        _upload(client, dataset_id, "a.dat", b"x")
        r = client.delete(f"/api/uploads/{dataset_id}")
        assert r.status_code == 200
        r = client.get(f"/api/uploads/{dataset_id}")
        assert r.status_code == 404

    def test_delete_entry_removes_file(self, client, upload_store):
        dataset_id = client.post("/api/uploads", json={"name": "ds"}).json()["dataset_id"]
        _upload(client, dataset_id, "a.npz", b"x" * 10)
        _upload(client, dataset_id, "b.npz", b"y" * 5)
        client.post(f"/api/uploads/{dataset_id}/finalize")

        r = client.delete(f"/api/uploads/{dataset_id}/entries/a.npz")
        assert r.status_code == 200
        body = r.json()
        assert {e["relative_path"] for e in body["entries"]} == {"b.npz"}
        assert body["total_bytes"] == 5

    def test_delete_entry_removes_subfolder(self, client, upload_store):
        dataset_id = client.post("/api/uploads", json={"name": "ds"}).json()["dataset_id"]
        _upload(client, dataset_id, "260625/a.dat", b"x")
        _upload(client, dataset_id, "270625/b.dat", b"y")
        client.post(f"/api/uploads/{dataset_id}/finalize")

        r = client.delete(f"/api/uploads/{dataset_id}/entries/260625")
        assert r.status_code == 200
        assert {e["relative_path"] for e in r.json()["entries"]} == {"270625/b.dat"}

    def test_delete_entry_missing_returns_404(self, client, upload_store):
        dataset_id = client.post("/api/uploads", json={"name": "ds"}).json()["dataset_id"]
        r = client.delete(f"/api/uploads/{dataset_id}/entries/nope.dat")
        assert r.status_code == 404

    @pytest.mark.parametrize("bad_path", ["%2e%2e%2Fevil.dat", "a/%2e%2e%2F%2e%2e%2Fb.dat"])
    def test_delete_entry_rejects_path_traversal(self, client, upload_store, bad_path):
        """Percent-encoded ``..`` segments -- plain ``../`` in the URL is
        normalized away by the HTTP client itself before the request is even
        sent, so it never reaches the server's own path-safety check. This
        confirms that check still rejects traversal that does arrive intact.
        """
        dataset_id = client.post("/api/uploads", json={"name": "ds"}).json()["dataset_id"]
        r = client.delete(f"/api/uploads/{dataset_id}/entries/{bad_path}")
        assert r.status_code == 400

    def test_delete_entry_isolated_between_principals(self, client, monkeypatch, upload_store):
        monkeypatch.setenv("SFZ_TRUSTED_USER_HEADER", "X-Test-User")
        alice = {"X-Test-User": "alice"}
        bob = {"X-Test-User": "bob"}

        dataset_id = client.post(
            "/api/uploads", json={"name": "ds"}, headers=alice
        ).json()["dataset_id"]
        _upload(client, dataset_id, "a.dat", b"x", headers=alice)
        client.post(f"/api/uploads/{dataset_id}/finalize", headers=alice)

        r = client.delete(f"/api/uploads/{dataset_id}/entries/a.dat", headers=bob)
        assert r.status_code == 404

        r = client.get(f"/api/uploads/{dataset_id}", headers=alice)
        assert len(r.json()["entries"]) == 1

    def test_datasets_isolated_between_principals(self, client, monkeypatch):
        monkeypatch.setenv("SFZ_TRUSTED_USER_HEADER", "X-Test-User")
        alice = {"X-Test-User": "alice"}
        bob = {"X-Test-User": "bob"}

        dataset_id = client.post(
            "/api/uploads", json={"name": "alice-data"}, headers=alice
        ).json()["dataset_id"]

        r = client.get(f"/api/uploads/{dataset_id}", headers=bob)
        assert r.status_code == 404

        assert client.get("/api/uploads", headers=bob).json() == []
        assert len(client.get("/api/uploads", headers=alice).json()) == 1

    def test_missing_identity_header_rejected_when_configured(self, client, monkeypatch):
        monkeypatch.setenv("SFZ_TRUSTED_USER_HEADER", "X-Test-User")
        r = client.get("/api/uploads")
        assert r.status_code == 401

    def test_untrusted_header_ignored_when_not_configured(self, client):
        """A client can't claim an identity the deployer didn't ask for."""
        r = client.post(
            "/api/uploads", json={"name": "ds"}, headers={"X-Test-User": "attacker"}
        )
        assert r.status_code == 201
        # Visible to the default anonymous principal, since the header was ignored.
        assert len(client.get("/api/uploads").json()) == 1


class TestOpenUploadedFile:
    def test_open_requires_exactly_one_source(self, client):
        assert client.post("/api/files/open", json={}).status_code == 422
        assert client.post("/api/files/open", json={
            "path": "/a", "dataset_id": "x", "relative_path": "y",
        }).status_code == 422

    def test_open_single_file_upload(self, client):
        dataset_id = client.post("/api/uploads", json={"name": "ds"}).json()["dataset_id"]
        import numpy as np
        buf = io.BytesIO()
        np.savez(buf, time=np.linspace(0, 1, 10, dtype=np.float32),
                  extension=np.zeros(10, dtype=np.float32))
        _upload(client, dataset_id, "trace.npz", buf.getvalue())
        client.post(f"/api/uploads/{dataset_id}/finalize")

        r = client.post("/api/files/open", json={
            "dataset_id": dataset_id, "relative_path": "trace.npz",
        })
        assert r.status_code == 201
        assert r.json()["filename"] == "trace.npz"

    def test_open_missing_upload_returns_404(self, client):
        dataset_id = client.post("/api/uploads", json={"name": "ds"}).json()["dataset_id"]
        r = client.post("/api/files/open", json={
            "dataset_id": dataset_id, "relative_path": "nope.npz",
        })
        assert r.status_code == 404

    def test_folder_upload_preserves_sidecar_and_opens_with_trap_position(
        self, client, tmp_path
    ):
        """Uploading a .dat + its _pos sidecar under the same relative folder
        keeps them siblings on disk, so opening the trace still resolves
        trap-position data -- the reason folder upload matters, not just a
        single-file convenience.
        """
        src = tmp_path / "src"
        src.mkdir()
        dat = make_dat_file(src / "260625_001.dat", n_samples=64, extra_data=2)
        pos = make_pos_sidecar(src / "260625_001_pos.dat", n_samples=64)

        dataset_id = client.post("/api/uploads", json={"name": "260625"}).json()["dataset_id"]
        assert _upload(client, dataset_id, "260625/260625_001.dat", dat.read_bytes()).status_code == 201
        assert _upload(client, dataset_id, "260625/260625_001_pos.dat", pos.read_bytes()).status_code == 201

        finalized = client.post(f"/api/uploads/{dataset_id}/finalize").json()
        entries = {e["relative_path"]: e for e in finalized["entries"]}
        trace = entries["260625/260625_001.dat"]
        assert trace["kind"] == "trace"
        assert trace["sidecars"] == ["260625/260625_001_pos.dat"]
        assert trace["missing_sidecars"] == []

        r = client.post("/api/files/open", json={
            "dataset_id": dataset_id, "relative_path": "260625/260625_001.dat",
        })
        assert r.status_code == 201
        file_id, session_id = r.json()["file_id"], r.json()["session_id"]

        info = client.get(
            f"/api/files/{file_id}/info", params={"session_id": session_id}
        ).json()
        assert "TX0" in info["meta"]
