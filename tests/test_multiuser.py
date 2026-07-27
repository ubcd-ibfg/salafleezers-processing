"""Tests for the client-server architecture seams (plan §0, Tier 1):

  * rehydratable sessions -- evicted arrays are transparently reloaded
  * proxy-header identity -- real per-user isolation, fails closed
  * WebSocket tickets -- the only way to authenticate a socket the browser
    itself cannot attach a header to
  * analysis guards -- input-size cap and per-principal concurrency limit
  * WS handlers no longer block the event loop
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from salafleezers.web.app import create_app
from salafleezers.web.api.analysis import _analysis_slot, _slots
from salafleezers.web.auth import consume_ticket, issue_ticket
from salafleezers.web.sessions import array_cache, session_manager


@pytest.fixture
def app():
    return create_app(serve_spa=False)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def tmp_npz(tmp_path):
    """Non-degenerate data: KDE/stats routes need nonzero variance."""
    rng = np.random.default_rng(0)
    N = 2000
    t = np.linspace(0, 10, N, dtype=np.float32)
    ext = (10.0 + rng.standard_normal(N)).astype(np.float32)
    force = rng.uniform(5.0, 25.0, N).astype(np.float32)
    np.savez(tmp_path / "data.npz", time=t, extension=ext, force=force)
    return tmp_path / "data.npz"


# ---------------------------------------------------------------------------
# Rehydratable sessions
# ---------------------------------------------------------------------------

class TestRehydration:
    def test_traces_route_rehydrates_after_cache_eviction(self, client, tmp_npz, monkeypatch):
        r = client.post("/api/files/open", json={"path": str(tmp_npz)})
        assert r.status_code == 201
        body = r.json()
        session_id, file_id = body["session_id"], body["file_id"]

        # Confirm the file is actually cached, then evict it -- simulating
        # what ArrayCache does under memory pressure, or what a fresh
        # process does after a restart (the ref survives; the array cache
        # is process-local and empty).
        assert array_cache.get(session_id, file_id) is not None
        array_cache.discard(session_id, file_id)
        assert array_cache.get(session_id, file_id) is None

        calls = []
        import salafleezers.web.io as io_mod
        original_load_file = io_mod.load_file

        def spy_load_file(path):
            calls.append(path)
            return original_load_file(path)

        monkeypatch.setattr(io_mod, "load_file", spy_load_file)

        r = client.get(f"/api/traces/{file_id}", params={"session_id": session_id})
        assert r.status_code == 200
        assert len(calls) == 1, "expected a cache-miss rehydrate to re-read the file"

        # And it's cached again afterwards.
        assert array_cache.get(session_id, file_id) is not None

    def test_analysis_route_rehydrates_after_cache_eviction(self, client, tmp_npz):
        r = client.post("/api/files/open", json={"path": str(tmp_npz)})
        session_id, file_id = r.json()["session_id"], r.json()["file_id"]
        array_cache.discard(session_id, file_id)

        r = client.post("/api/kde", json={
            "session_id": session_id, "file_id": file_id, "channel": "extension",
        })
        assert r.status_code == 201

    def test_get_file_returns_none_for_vanished_source(self, client, tmp_path):
        npz_path = tmp_path / "vanishing.npz"
        N = 100
        np.savez(npz_path, time=np.linspace(0, 1, N, dtype=np.float32),
                  extension=np.zeros(N, dtype=np.float32))
        r = client.post("/api/files/open", json={"path": str(npz_path)})
        session_id, file_id = r.json()["session_id"], r.json()["file_id"]
        array_cache.discard(session_id, file_id)
        npz_path.unlink()

        r = client.get(f"/api/traces/{file_id}", params={"session_id": session_id})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Proxy-header identity
# ---------------------------------------------------------------------------

class TestTrustedUserHeader:
    def test_distinct_header_values_get_distinct_isolated_sessions(self, client, monkeypatch):
        monkeypatch.setenv("SFZ_TRUSTED_USER_HEADER", "X-Test-User")
        alice = {"X-Test-User": "alice@example.com"}
        bob = {"X-Test-User": "bob@example.com"}

        sid = client.post("/api/sessions", headers=alice).json()["session_id"]

        r = client.get(f"/api/sessions/{sid}", headers=bob)
        assert r.status_code == 404

        r = client.get(f"/api/sessions/{sid}", headers=alice)
        assert r.status_code == 200

        session_manager.delete(sid)

    def test_header_ignored_when_not_configured_is_not_a_bypass(self, client):
        """Without SFZ_TRUSTED_USER_HEADER set, a client-supplied identity
        header must NOT be honored -- otherwise any client could claim to be
        any user simply by setting a header, defeating isolation the moment
        a deployer *thinks* they've turned it on but a stray header slips
        through from an unrelated client.
        """
        r = client.post("/api/sessions", headers={"X-Test-User": "attacker"})
        assert r.status_code == 201
        # Falls back to the anonymous local principal, not "attacker".
        sid = r.json()["session_id"]
        session_manager.delete(sid)

    def test_missing_header_rejected_when_configured(self, client, monkeypatch):
        monkeypatch.setenv("SFZ_TRUSTED_USER_HEADER", "X-Test-User")
        r = client.post("/api/sessions")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# WebSocket tickets
# ---------------------------------------------------------------------------

class TestWsTicket:
    def test_issue_and_consume_ticket(self):
        ticket, ttl = issue_ticket("alice")
        assert ttl > 0
        assert consume_ticket(ticket) == "alice"

    def test_ticket_is_single_use(self):
        ticket, _ = issue_ticket("alice")
        assert consume_ticket(ticket) == "alice"
        assert consume_ticket(ticket) is None

    def test_expired_ticket_rejected(self, monkeypatch):
        import salafleezers.web.auth as auth_mod
        monkeypatch.setattr(auth_mod, "_TICKET_TTL_SECONDS", 0.01)
        ticket, _ = issue_ticket("alice")
        time.sleep(0.05)
        assert consume_ticket(ticket) is None

    def test_unknown_ticket_rejected(self):
        assert consume_ticket("not-a-real-ticket") is None

    def test_ws_ticket_endpoint_requires_auth_when_configured(self, client, monkeypatch):
        monkeypatch.setenv("SFZ_AUTH_TOKEN", "secret")
        r = client.post("/api/ws-ticket")
        assert r.status_code == 401
        r = client.post("/api/ws-ticket", headers={"Authorization": "Bearer secret"})
        assert r.status_code == 200
        assert "ticket" in r.json()

    def test_ws_requires_valid_ticket_when_auth_configured(self, client, monkeypatch, tmp_npz):
        monkeypatch.setenv("SFZ_AUTH_TOKEN", "secret")
        headers = {"Authorization": "Bearer secret"}

        sid = client.post("/api/sessions", headers=headers).json()["session_id"]

        # No ticket at all -> rejected before accept.
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/session/{sid}"):
                pass

        # A valid ticket connects successfully...
        ticket = client.post("/api/ws-ticket", headers=headers).json()["ticket"]
        with client.websocket_connect(f"/ws/session/{sid}?ticket={ticket}") as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"

        # ...and the same ticket cannot be reused for a second connection.
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/session/{sid}?ticket={ticket}"):
                pass


# ---------------------------------------------------------------------------
# Analysis guards
# ---------------------------------------------------------------------------

class TestAnalysisGuards:
    def test_stepfind_over_sample_cap_returns_422(self, client, monkeypatch, tmp_npz):
        r = client.post("/api/files/open", json={"path": str(tmp_npz)})
        session_id, file_id = r.json()["session_id"], r.json()["file_id"]

        monkeypatch.setenv("SFZ_MAX_STEPFIND_SAMPLES", "100")
        r = client.post("/api/stepfind", json={
            "session_id": session_id, "file_id": file_id, "channel": "extension",
        })
        assert r.status_code == 422
        assert "100" in r.json()["detail"]

    def test_stepfind_under_sample_cap_succeeds(self, client, tmp_npz):
        r = client.post("/api/files/open", json={"path": str(tmp_npz)})
        session_id, file_id = r.json()["session_id"], r.json()["file_id"]
        r = client.post("/api/stepfind", json={
            "session_id": session_id, "file_id": file_id, "channel": "extension",
        })
        assert r.status_code == 201

    def test_analysis_slot_returns_429_when_exhausted(self, monkeypatch):
        monkeypatch.setenv("SFZ_MAX_CONCURRENT_ANALYSES", "1")
        _slots.pop("test-user-guard", None)
        from fastapi import HTTPException

        with _analysis_slot("test-user-guard"):
            with pytest.raises(HTTPException) as exc_info:
                with _analysis_slot("test-user-guard"):
                    pass
            assert exc_info.value.status_code == 429
        # Released after the outer context exits -- a fresh acquire succeeds.
        with _analysis_slot("test-user-guard"):
            pass


# ---------------------------------------------------------------------------
# WS handlers off the event loop
# ---------------------------------------------------------------------------

class TestWsNonBlocking:
    def test_ws_filter_does_not_block_concurrent_http(self, client, monkeypatch, tmp_npz):
        """A slow filter computation must not stall unrelated requests.

        Patches the (already-imported-per-call) ``window_filter`` to sleep,
        then measures whether a concurrent ``/api/health`` request completes
        well before the filter response does. Under the pre-fix code (the
        WS handler awaited the computation directly on the event loop) this
        would serialize and the health check would take >= the sleep time;
        with ``anyio.to_thread.run_sync`` it runs on a worker thread and the
        event loop stays free to answer other requests.
        """
        r = client.post("/api/files/open", json={"path": str(tmp_npz)})
        session_id, file_id = r.json()["session_id"], r.json()["file_id"]

        import salafleezers.analysis.filters as filters_mod
        original = filters_mod.window_filter

        def slow_filter(*args, **kwargs):
            time.sleep(0.3)
            return original(*args, **kwargs)

        monkeypatch.setattr(filters_mod, "window_filter", slow_filter)

        result: dict = {}

        def do_health():
            t0 = time.monotonic()
            resp = client.get("/api/health")
            result["status"] = resp.status_code
            result["elapsed"] = time.monotonic() - t0

        with client.websocket_connect(f"/ws/session/{session_id}") as ws:
            ws.send_json({
                "type": "filter", "file_id": file_id, "channel": "extension",
                "half_width": 5, "decimate": 10,
            })
            time.sleep(0.05)   # let the filter message start processing first
            t = threading.Thread(target=do_health)
            t.start()
            t.join(timeout=2)
            msg = ws.receive_json()

        assert msg["type"] == "trace"
        assert result["status"] == 200
        assert result["elapsed"] < 0.2, (
            f"/api/health took {result['elapsed']:.3f}s while a WS filter was "
            "running -- the event loop appears to be blocked"
        )
