"""Tests for the storage backend abstraction and auth stub (Phase 6)."""

from __future__ import annotations

import numpy as np
import pytest

from salafleezers.web.storage import LocalFilesystemStore, UserScopedStore


@pytest.fixture
def backend(tmp_path):
    return LocalFilesystemStore(root=tmp_path)


class TestLocalFilesystemStore:
    def test_save_load_roundtrip(self, backend):
        backend.save_session("abc", {"foo": "bar"})
        assert backend.load_session("abc") == {"foo": "bar"}

    def test_load_missing_raises(self, backend):
        with pytest.raises(FileNotFoundError):
            backend.load_session("nonexistent")

    def test_list_sessions_flat(self, backend):
        backend.save_session("s1", {})
        backend.save_session("s2", {})
        assert sorted(backend.list_sessions()) == ["s1", "s2"]

    def test_list_sessions_nested(self, backend):
        # Simulates what UserScopedStore writes: "<user_id>/<session_id>"
        backend.save_session("alice/s1", {})
        backend.save_session("bob/s2", {})
        assert sorted(backend.list_sessions()) == ["alice/s1", "bob/s2"]

    def test_delete_session(self, backend):
        backend.save_session("abc", {})
        backend.delete_session("abc")
        with pytest.raises(FileNotFoundError):
            backend.load_session("abc")

    def test_save_load_arrays_roundtrip(self, backend):
        arr = np.arange(10, dtype=np.float64)
        backend.save_arrays("abc", "traces", {"x": arr})
        loaded = backend.load_arrays("abc", "traces")
        np.testing.assert_array_equal(loaded["x"], arr)


class TestUserScopedStore:
    def test_namespaces_by_user(self, backend):
        alice = UserScopedStore(backend, "alice")
        bob = UserScopedStore(backend, "bob")

        alice.save_session("s1", {"owner": "alice"})
        bob.save_session("s1", {"owner": "bob"})

        # Same session_id "s1", different users -> no collision.
        assert alice.load_session("s1") == {"owner": "alice"}
        assert bob.load_session("s1") == {"owner": "bob"}

    def test_list_sessions_scoped_to_user(self, backend):
        alice = UserScopedStore(backend, "alice")
        bob = UserScopedStore(backend, "bob")
        alice.save_session("s1", {})
        alice.save_session("s2", {})
        bob.save_session("s1", {})

        assert sorted(alice.list_sessions()) == ["s1", "s2"]
        assert bob.list_sessions() == ["s1"]

    def test_delete_only_affects_own_namespace(self, backend):
        alice = UserScopedStore(backend, "alice")
        bob = UserScopedStore(backend, "bob")
        alice.save_session("s1", {})
        bob.save_session("s1", {})

        alice.delete_session("s1")

        with pytest.raises(FileNotFoundError):
            alice.load_session("s1")
        assert bob.load_session("s1") == {}

    def test_arrays_namespaced_by_user(self, backend):
        alice = UserScopedStore(backend, "alice")
        bob = UserScopedStore(backend, "bob")
        alice.save_arrays("s1", "traces", {"x": np.array([1.0])})
        bob.save_arrays("s1", "traces", {"x": np.array([2.0])})

        assert alice.load_arrays("s1", "traces")["x"][0] == 1.0
        assert bob.load_arrays("s1", "traces")["x"][0] == 2.0
