"""Tests for the FastAPI web backend (Phase 3).

Uses FastAPI's synchronous TestClient (backed by httpx).
No actual file I/O is needed for most tests — we inject numpy data
directly into the in-memory SessionManager.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

# Import the app factory + internals we'll manipulate in tests
from salafleezers.web.app import create_app
from salafleezers.web.sessions import LoadedFile, Session, session_manager

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    return create_app(serve_spa=False)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def synthetic_session():
    """Inject a session with synthetic data directly into the SessionManager."""
    rng = np.random.default_rng(42)
    N = 10_000
    t = np.linspace(0, 10, N, dtype=np.float32)
    # Staircase extension trace — five 8-nm steps
    extension = np.zeros(N, dtype=np.float32)
    for i, start in enumerate(range(1000, 9000, 2000)):
        extension[start:] += 8.0
    extension += rng.standard_normal(N).astype(np.float32) * 0.5

    force = rng.uniform(5.0, 25.0, N).astype(np.float32)

    file_id = str(uuid.uuid4())
    session = Session(
        session_id=str(uuid.uuid4()),
        created_at=datetime.now(),
        files={
            file_id: LoadedFile(
                file_id=file_id,
                filename="test.npz",
                path="/tmp/test.npz",
                n_samples=N,
                sampling_rate_hz=1000.0,
                channels={"extension": extension, "force": force},
                time=t,
                meta={"fs": 1000},
            )
        },
    )
    session_manager._sessions[session.session_id] = session
    yield session, file_id
    # Clean up
    session_manager._sessions.pop(session.session_id, None)


# ---------------------------------------------------------------------------
# Health + meta
# ---------------------------------------------------------------------------

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_openapi_json(client):
    r = client.get("/api/openapi.json")
    assert r.status_code == 200
    assert "paths" in r.json()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def test_create_session(client):
    r = client.post("/api/sessions")
    assert r.status_code == 201
    body = r.json()
    assert "session_id" in body
    assert body["n_files"] == 0


def test_list_sessions(client):
    client.post("/api/sessions")
    r = client.get("/api/sessions")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_session(client):
    created = client.post("/api/sessions").json()
    sid = created["session_id"]
    r = client.get(f"/api/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["session_id"] == sid


def test_get_session_not_found(client):
    r = client.get("/api/sessions/nonexistent-id")
    assert r.status_code == 404


def test_delete_session(client):
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.delete(f"/api/sessions/{sid}")
    assert r.status_code == 200
    assert client.get(f"/api/sessions/{sid}").status_code == 404


# ---------------------------------------------------------------------------
# Save / load (disk persistence, auth stub)
# ---------------------------------------------------------------------------

def test_save_and_load_session_anonymous(client):
    """No SFZ_AUTH_TOKEN configured -> save/load work with no auth header."""
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.post(f"/api/sessions/{sid}/save")
    assert r.status_code == 200
    assert "saved_to" in r.json()

    r = client.post(f"/api/sessions/load/{sid}")
    assert r.status_code == 200
    assert r.json()["loaded"] == sid


def test_save_session_requires_token_when_configured(client, monkeypatch):
    monkeypatch.setenv("SFZ_AUTH_TOKEN", "s3cret")
    sid = client.post("/api/sessions").json()["session_id"]

    r = client.post(f"/api/sessions/{sid}/save")
    assert r.status_code == 401

    r = client.post(
        f"/api/sessions/{sid}/save", headers={"Authorization": "Bearer wrong"}
    )
    assert r.status_code == 401

    r = client.post(
        f"/api/sessions/{sid}/save", headers={"Authorization": "Bearer s3cret"}
    )
    assert r.status_code == 200


def test_empty_string_token_treated_as_unset(client, monkeypatch):
    """Docker Compose's `${SFZ_AUTH_TOKEN:-}` sets an empty string, not unset."""
    monkeypatch.setenv("SFZ_AUTH_TOKEN", "")
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.post(f"/api/sessions/{sid}/save")
    assert r.status_code == 200


def test_saved_sessions_are_namespaced_per_principal(client, monkeypatch, tmp_path):
    """Two different principals saving the same session_id shouldn't collide."""
    from salafleezers.web.api import sessions as sessions_module

    monkeypatch.setattr(
        sessions_module, "_backend",
        sessions_module.LocalFilesystemStore(root=tmp_path),
    )

    sid = client.post("/api/sessions").json()["session_id"]
    client.post(f"/api/sessions/{sid}/save")  # anonymous principal

    monkeypatch.setenv("SFZ_AUTH_TOKEN", "s3cret")
    r = client.post(
        f"/api/sessions/{sid}/save", headers={"Authorization": "Bearer s3cret"}
    )
    assert r.status_code == 200

    saved_dirs = sorted(p.name for p in tmp_path.iterdir())
    assert saved_dirs == ["local", "shared"]


# ---------------------------------------------------------------------------
# Files — open (uses a real temp .npz file)
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_npz(tmp_path):
    N = 500
    t = np.linspace(0, 1, N, dtype=np.float32)
    ext = np.zeros(N, dtype=np.float32)
    np.savez(tmp_path / "data.npz", time=t, extension=ext, force=np.ones(N, dtype=np.float32))
    return tmp_path / "data.npz"


def test_open_file_creates_session(client, tmp_npz):
    r = client.post("/api/files/open", json={"path": str(tmp_npz)})
    assert r.status_code == 201
    body = r.json()
    assert "file_id" in body
    assert "session_id" in body
    assert body["n_original"] == 500
    assert "extension" in body["channels"]
    assert body["decimate_factor"] >= 1


def test_open_file_into_existing_session(client, tmp_npz):
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.post("/api/files/open", json={"path": str(tmp_npz), "session_id": sid})
    assert r.status_code == 201
    assert r.json()["session_id"] == sid


def test_open_file_not_found(client):
    r = client.post("/api/files/open", json={"path": "/no/such/file.npz"})
    assert r.status_code == 404


def test_file_info(client, tmp_npz, synthetic_session):
    session, file_id = synthetic_session
    r = client.get(f"/api/files/{file_id}/info",
                   params={"session_id": session.session_id})
    assert r.status_code == 200
    body = r.json()
    assert body["file_id"] == file_id
    assert body["n_samples"] == 10_000
    assert "extension" in body["channels"]


# ---------------------------------------------------------------------------
# Traces — server-side decimation
# ---------------------------------------------------------------------------

def test_get_trace_default(client, synthetic_session):
    session, file_id = synthetic_session
    r = client.get(f"/api/traces/{file_id}",
                   params={"session_id": session.session_id, "channel": "extension"})
    assert r.status_code == 200
    body = r.json()
    assert body["channel"] == "extension"
    assert len(body["time"]) == len(body["data"])
    assert body["n_original"] == 10_000


def test_get_trace_with_decimate(client, synthetic_session):
    session, file_id = synthetic_session
    r = client.get(f"/api/traces/{file_id}",
                   params={"session_id": session.session_id,
                            "channel": "extension", "decimate": 500})
    assert r.status_code == 200
    body = r.json()
    assert len(body["time"]) == 10_000 // 500 + (1 if 10_000 % 500 else 0)


def test_get_trace_with_time_crop(client, synthetic_session):
    session, file_id = synthetic_session
    r = client.get(f"/api/traces/{file_id}",
                   params={"session_id": session.session_id,
                            "channel": "extension",
                            "t_start": 0.0, "t_end": 5.0, "decimate": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["t_end"] <= 5.01   # allow floating-point slop


def test_get_trace_channel_not_found(client, synthetic_session):
    session, file_id = synthetic_session
    r = client.get(f"/api/traces/{file_id}",
                   params={"session_id": session.session_id, "channel": "nonexistent"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Step detection
# ---------------------------------------------------------------------------

def test_stepfind_kv(client, synthetic_session):
    session, file_id = synthetic_session
    r = client.post("/api/stepfind", json={
        "session_id": session.session_id,
        "file_id": file_id,
        "channel": "extension",
        "algorithm": "kv",
        "pen_factor": 2.0,
    })
    assert r.status_code == 201
    body = r.json()
    assert body["algorithm"] == "kv"
    assert isinstance(body["n_steps"], int)
    assert isinstance(body["levels"], list)
    assert body["n_steps"] == len(body["step_positions"])


def test_stepfind_hmm(client, synthetic_session):
    session, file_id = synthetic_session
    r = client.post("/api/stepfind", json={
        "session_id": session.session_id,
        "file_id": file_id,
        "channel": "extension",
        "algorithm": "hmm",
        "n_states": 3,
    })
    assert r.status_code == 201
    body = r.json()
    assert body["algorithm"] == "hmm"
    assert len(body["levels"]) == 3


def test_stepfind_cached_in_session(client, synthetic_session):
    session, file_id = synthetic_session
    client.post("/api/stepfind", json={
        "session_id": session.session_id,
        "file_id": file_id,
        "channel": "extension",
        "algorithm": "kv",
    })
    assert any("kv" in k for k in session.step_results)


def test_stepfind_bad_algorithm(client, synthetic_session):
    session, file_id = synthetic_session
    r = client.post("/api/stepfind", json={
        "session_id": session.session_id,
        "file_id": file_id,
        "algorithm": "bad",
    })
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# WLC fitting
# ---------------------------------------------------------------------------

@pytest.fixture
def wlc_session():
    """Session with a synthetic force-extension dataset."""
    from salafleezers.analysis.wlc import xwlc_extension
    rng = np.random.default_rng(7)
    F = np.linspace(1.0, 40.0, 300, dtype=np.float64)
    x = xwlc_extension(F, Lc=1200.0, P=50.0, S=900.0) + rng.standard_normal(300) * 0.5
    N = len(F)
    t = np.arange(N, dtype=np.float32)

    file_id = str(uuid.uuid4())
    session = Session(
        session_id=str(uuid.uuid4()),
        created_at=datetime.now(),
        files={
            file_id: LoadedFile(
                file_id=file_id,
                filename="wlc.npz",
                path="/tmp/wlc.npz",
                n_samples=N,
                sampling_rate_hz=1.0,
                channels={
                    "force": F.astype(np.float32),
                    "extension": x.astype(np.float32),
                },
                time=t,
                meta={},
            )
        },
    )
    session_manager._sessions[session.session_id] = session
    yield session, file_id
    session_manager._sessions.pop(session.session_id, None)


def test_wlc_fit(client, wlc_session):
    session, file_id = wlc_session
    r = client.post("/api/wlc/fit", json={
        "session_id": session.session_id,
        "file_id": file_id,
        "method": "basic",
        "P0": 50.0,
        "S0": 900.0,
        "fit_offsets": False,
    })
    assert r.status_code == 201
    body = r.json()
    assert 20 < body["P_nm"] < 100
    assert 800 < body["Lc_nm"] < 2000
    assert len(body["F_model"]) == 200
    assert len(body["x_model"]) == 200


# ---------------------------------------------------------------------------
# Velocity
# ---------------------------------------------------------------------------

def test_velocity(client, synthetic_session):
    session, file_id = synthetic_session
    r = client.post("/api/velocity", json={
        "session_id": session.session_id,
        "file_id": file_id,
        "channel": "extension",
        "window": 21,
    })
    assert r.status_code == 201
    body = r.json()
    assert isinstance(body["v_centers"], list)
    assert isinstance(body["counts"], list)
    assert len(body["v_centers"]) == len(body["counts"])


# ---------------------------------------------------------------------------
# Pairwise distance
# ---------------------------------------------------------------------------

def test_pwd(client, synthetic_session):
    session, file_id = synthetic_session
    r = client.post("/api/pwd", json={
        "session_id": session.session_id,
        "file_id": file_id,
        "channel": "extension",
        "bins": 100,
    })
    assert r.status_code == 201
    body = r.json()
    assert len(body["bin_centers"]) == 100
    assert len(body["pwd_counts"]) == 100


# ---------------------------------------------------------------------------
# Kinetics
# ---------------------------------------------------------------------------

def test_kinetics_inline_dwell_times(client, synthetic_session):
    session, file_id = synthetic_session
    rng = np.random.default_rng(0)
    dwell_times = rng.exponential(scale=0.5, size=200).tolist()
    r = client.post("/api/kinetics/fit", json={
        "session_id": session.session_id,
        "file_id": file_id,
        "dwell_times": dwell_times,
        "model": "exponential",
        "n_components": 1,
    })
    assert r.status_code == 201
    body = r.json()
    assert body["model"] == "exponential"
    assert len(body["rates"]) == 1
    # Rate should be close to 1/0.5 = 2 s⁻¹
    assert 0.5 < body["rates"][0] < 5.0


def test_kde(client, synthetic_session):
    session, file_id = synthetic_session
    r = client.post("/api/kde", json={
        "session_id": session.session_id,
        "file_id": file_id,
        "channel": "extension",
        "n_points": 128,
    })
    assert r.status_code == 201
    body = r.json()
    assert len(body["x"]) == 128
    assert len(body["density"]) == 128
    assert body["bandwidth"] > 0


def test_violin(client, synthetic_session):
    session, file_id = synthetic_session
    r = client.post("/api/violin", json={
        "session_id": session.session_id,
        "file_ids": [file_id],
        "channel": "extension",
    })
    assert r.status_code == 201
    body = r.json()
    assert len(body["groups"]) == 1
    g = body["groups"][0]
    assert g["label"] == "test.npz"
    assert g["n"] == 10_000
    assert len(g["x"]) == len(g["density"])


def test_violin_missing_files(client, synthetic_session):
    session, _ = synthetic_session
    r = client.post("/api/violin", json={
        "session_id": session.session_id,
        "file_ids": [],
        "channel": "extension",
    })
    assert r.status_code == 422


def test_msd(client, synthetic_session):
    session, file_id = synthetic_session
    r = client.post("/api/msd", json={
        "session_id": session.session_id,
        "file_id": file_id,
        "channel": "extension",
        "max_lag": 100,
    })
    assert r.status_code == 201
    body = r.json()
    assert len(body["lags_s"]) == 101
    assert len(body["msd"]) == 101
    assert body["msd"][0] == pytest.approx(0.0, abs=1e-6)


def test_kinetics_missing_input(client, synthetic_session):
    session, file_id = synthetic_session
    r = client.post("/api/kinetics/fit", json={
        "session_id": session.session_id,
        "file_id": file_id,
        "model": "exponential",
    })
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

def test_ws_ping(client, synthetic_session):
    session, _ = synthetic_session
    with client.websocket_connect(f"/ws/session/{session.session_id}") as ws:
        ws.send_json({"type": "ping"})
        data = ws.receive_json()
        assert data["type"] == "pong"


def test_ws_bad_session(client):
    with client.websocket_connect("/ws/session/nonexistent-id") as ws:
        data = ws.receive_json()
        assert data["type"] == "error"
        assert "not found" in data["detail"].lower()


def test_ws_filter(client, synthetic_session):
    session, file_id = synthetic_session
    with client.websocket_connect(f"/ws/session/{session.session_id}") as ws:
        ws.send_json({
            "type": "filter",
            "file_id": file_id,
            "channel": "extension",
            "half_width": 10,
            "decimate": 200,
        })
        data = ws.receive_json()
        assert data["type"] == "trace"
        assert data["channel"] == "extension"
        assert len(data["time"]) > 0


def test_ws_measure(client, synthetic_session):
    session, file_id = synthetic_session
    with client.websocket_connect(f"/ws/session/{session.session_id}") as ws:
        ws.send_json({
            "type": "measure",
            "file_id": file_id,
            "channel": "extension",
            "t_start": 1.0,
            "t_end": 3.0,
        })
        data = ws.receive_json()
        assert data["type"] == "measurement"
        assert "mean" in data
        assert "std" in data


def test_ws_crop(client, synthetic_session):
    session, file_id = synthetic_session
    with client.websocket_connect(f"/ws/session/{session.session_id}") as ws:
        ws.send_json({
            "type": "crop",
            "file_id": file_id,
            "t_start": 2.0,
            "t_end": 8.0,
            "channels": ["extension"],
            "decimate": 100,
        })
        data = ws.receive_json()
        assert data["type"] == "crop_ack"
        assert "extension" in data["channels"]
        # Crop bounds should be stored in session
        assert file_id in session.crops


def test_ws_unknown_message_type(client, synthetic_session):
    session, _ = synthetic_session
    with client.websocket_connect(f"/ws/session/{session.session_id}") as ws:
        ws.send_json({"type": "nonexistent_command"})
        data = ws.receive_json()
        assert data["type"] == "error"


def test_ws_invalid_json(client, synthetic_session):
    session, _ = synthetic_session
    with client.websocket_connect(f"/ws/session/{session.session_id}") as ws:
        ws.send_text("not json {{")
        data = ws.receive_json()
        assert data["type"] == "error"
