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
from salafleezers.web.sessions import FileRef, LoadedFile, Session, session_manager

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
    session = Session(session_id=str(uuid.uuid4()), created_at=datetime.now())
    session.add_file(
        file_id,
        FileRef(kind="path", path="/tmp/test.npz"),
        LoadedFile(
            file_id=file_id,
            filename="test.npz",
            path="/tmp/test.npz",
            n_samples=N,
            sampling_rate_hz=1000.0,
            channels={"extension": extension, "force": force},
            time=t,
            meta={"fs": 1000},
        ),
    )
    session_manager._sessions[session.session_id] = session
    yield session, file_id
    # Clean up
    session_manager.delete(session.session_id)


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
# App factory — CORS/body-size guardrails
# ---------------------------------------------------------------------------

def test_wildcard_origin_with_credentials_rejected_at_startup():
    with pytest.raises(ValueError, match="allow_origins"):
        create_app(allow_origins=["*"], serve_spa=False)


def test_no_base_path_by_default():
    """Unset FRONTEND_BASE_PATH must not change routes at all (back-compat)."""
    app = create_app(serve_spa=False)
    client = TestClient(app)
    assert client.get("/api/health").status_code == 200


def test_base_path_mounts_api_under_prefix(monkeypatch):
    monkeypatch.setenv("FRONTEND_BASE_PATH", "/salafleezer")
    client = TestClient(create_app(serve_spa=False))

    r = client.get("/salafleezer/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    # Not reachable at the un-prefixed path once a base path is configured.
    assert client.get("/api/health").status_code == 404


def test_base_path_redirects_root_to_itself(monkeypatch):
    monkeypatch.setenv("FRONTEND_BASE_PATH", "/salafleezer")
    client = TestClient(create_app(serve_spa=False), follow_redirects=False)

    r = client.get("/")
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/salafleezer/"


@pytest.mark.parametrize(
    "raw, expected",
    [("", ""), ("/", ""), ("salafleezer", "/salafleezer"), ("/salafleezer/", "/salafleezer")],
)
def test_resolve_frontend_base_path_normalizes(monkeypatch, raw, expected):
    from salafleezers.web.app import resolve_frontend_base_path

    monkeypatch.setenv("FRONTEND_BASE_PATH", raw)
    assert resolve_frontend_base_path() == expected


def test_oversized_request_body_rejected(monkeypatch):
    monkeypatch.setenv("SFZ_MAX_BODY_BYTES", "100")
    small_limit_client = TestClient(create_app(serve_spa=False))

    r = small_limit_client.post(
        "/api/sessions/does-not-matter/save", content=b"x" * 1000
    )
    assert r.status_code == 413


def test_rate_limit_disabled_by_default():
    """Local-first default: no SFZ_RATE_LIMIT_PER_MINUTE -> unthrottled."""
    unlimited_client = TestClient(create_app(serve_spa=False))
    for _ in range(20):
        r = unlimited_client.get("/api/health")
        assert r.status_code == 200


def test_rate_limit_enforced_when_configured(monkeypatch):
    monkeypatch.setenv("SFZ_RATE_LIMIT_PER_MINUTE", "3")
    limited_client = TestClient(create_app(serve_spa=False))

    statuses = [limited_client.get("/api/health").status_code for _ in range(5)]
    assert statuses[:3] == [200, 200, 200]
    assert 429 in statuses[3:]


def test_rate_limit_is_per_client_ip(monkeypatch):
    monkeypatch.setenv("SFZ_RATE_LIMIT_PER_MINUTE", "1")
    app = create_app(serve_spa=False)

    client_a = TestClient(app, client=("1.2.3.4", 1234))
    client_b = TestClient(app, client=("5.6.7.8", 5678))

    assert client_a.get("/api/health").status_code == 200
    assert client_a.get("/api/health").status_code == 429
    # A different client IP has its own budget.
    assert client_b.get("/api/health").status_code == 200


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
    sid = client.post(
        "/api/sessions", headers={"Authorization": "Bearer s3cret"}
    ).json()["session_id"]

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
    """Each principal's saved sessions land under their own disk namespace."""
    from salafleezers.web.api import sessions as sessions_module

    monkeypatch.setattr(
        sessions_module, "_backend",
        sessions_module.LocalFilesystemStore(root=tmp_path),
    )

    anon_sid = client.post("/api/sessions").json()["session_id"]
    client.post(f"/api/sessions/{anon_sid}/save")  # anonymous principal

    monkeypatch.setenv("SFZ_AUTH_TOKEN", "s3cret")
    shared_headers = {"Authorization": "Bearer s3cret"}
    shared_sid = client.post(
        "/api/sessions", headers=shared_headers
    ).json()["session_id"]
    r = client.post(f"/api/sessions/{shared_sid}/save", headers=shared_headers)
    assert r.status_code == 200

    saved_dirs = sorted(p.name for p in tmp_path.iterdir())
    assert saved_dirs == ["local", "shared"]


def test_principal_cannot_save_another_principals_session(client, monkeypatch):
    """A session created by one principal isn't readable/writable by another."""
    anon_sid = client.post("/api/sessions").json()["session_id"]

    monkeypatch.setenv("SFZ_AUTH_TOKEN", "s3cret")
    r = client.post(
        f"/api/sessions/{anon_sid}/save",
        headers={"Authorization": "Bearer s3cret"},
    )
    assert r.status_code == 404


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


def test_open_file_confined_to_data_root(client, monkeypatch, tmp_npz, tmp_path):
    """SFZ_DATA_ROOT confines /api/files/open to a directory tree."""
    other_dir = tmp_path.parent / f"{tmp_path.name}-outside"
    other_dir.mkdir()
    outside_file = other_dir / "outside.npz"
    N = 10
    t = np.linspace(0, 1, N, dtype=np.float32)
    np.savez(outside_file, time=t, extension=np.zeros(N, dtype=np.float32))

    monkeypatch.setenv("SFZ_DATA_ROOT", str(tmp_path))

    r = client.post("/api/files/open", json={"path": str(tmp_npz)})
    assert r.status_code == 201

    r = client.post("/api/files/open", json={"path": str(outside_file)})
    assert r.status_code == 403

    traversal_path = tmp_path / ".." / f"{tmp_path.name}-outside" / "outside.npz"
    r = client.post("/api/files/open", json={"path": str(traversal_path)})
    assert r.status_code == 403


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
    session = Session(session_id=str(uuid.uuid4()), created_at=datetime.now())
    session.add_file(
        file_id,
        FileRef(kind="path", path="/tmp/wlc.npz"),
        LoadedFile(
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
        ),
    )
    session_manager._sessions[session.session_id] = session
    yield session, file_id
    session_manager.delete(session.session_id)


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


def test_velocity_steps_method(client, synthetic_session):
    """method='steps' derives velocity from a cached stepfind result."""
    session, file_id = synthetic_session
    step_r = client.post("/api/stepfind", json={
        "session_id": session.session_id,
        "file_id": file_id,
        "channel": "extension",
        "algorithm": "kv",
    })
    result_id = step_r.json()["result_id"]

    r = client.post("/api/velocity", json={
        "session_id": session.session_id,
        "file_id": file_id,
        "method": "steps",
        "step_result_id": result_id,
    })
    assert r.status_code == 201
    body = r.json()
    assert isinstance(body["v_centers"], list)
    assert isinstance(body["counts"], list)


def test_velocity_steps_method_requires_step_result_id(client, synthetic_session):
    session, file_id = synthetic_session
    r = client.post("/api/velocity", json={
        "session_id": session.session_id,
        "file_id": file_id,
        "method": "steps",
    })
    assert r.status_code == 422


def test_velocity_unknown_method(client, synthetic_session):
    session, file_id = synthetic_session
    r = client.post("/api/velocity", json={
        "session_id": session.session_id,
        "file_id": file_id,
        "method": "bogus",
    })
    assert r.status_code == 422


def test_velocity_results_from_different_methods_do_not_collide(client, synthetic_session):
    """Regression: results used to be cached under bare file_id, so running
    'savgol' then 'steps' on the same file silently overwrote the first."""
    session, file_id = synthetic_session
    step_r = client.post("/api/stepfind", json={
        "session_id": session.session_id,
        "file_id": file_id,
        "channel": "extension",
        "algorithm": "kv",
    })
    step_result_id = step_r.json()["result_id"]

    savgol_r = client.post("/api/velocity", json={
        "session_id": session.session_id,
        "file_id": file_id,
        "method": "savgol",
    })
    steps_r = client.post("/api/velocity", json={
        "session_id": session.session_id,
        "file_id": file_id,
        "method": "steps",
        "step_result_id": step_result_id,
    })

    assert savgol_r.json()["result_id"] != steps_r.json()["result_id"]
    assert len(session.velocity_results) == 2


def test_velocity_honors_crop_range(client, synthetic_session):
    """Regression: VelocityRequest previously had no t_start/t_end fields at
    all, so zooming into a region and running Velocity silently answered
    over the whole trace while its PWD/KDE/MSD neighbours honoured the crop."""
    session, file_id = synthetic_session
    full = client.post("/api/velocity", json={
        "session_id": session.session_id, "file_id": file_id, "channel": "extension",
    }).json()
    cropped = client.post("/api/velocity", json={
        "session_id": session.session_id, "file_id": file_id, "channel": "extension",
        "t_start": 0.0, "t_end": 2.0,
    }).json()
    assert sum(cropped["counts"]) < sum(full["counts"])


def test_step_positions_align_with_cropped_time_downstream(client, synthetic_session):
    """Regression: step_positions index into the array the step-find ran on.
    velocity(method='steps') and kinetics used the session's FULL time axis
    to look them up regardless of what range the antecedent step-find used --
    silently attributing every step to the wrong timestamp whenever that
    step-find was itself cropped. This reconstructs what the "steps" branch
    computes internally and checks it reproduces the step-find's own
    (correctly-cropped) step_times exactly.
    """
    from salafleezers.analysis.crop import crop as crop_fn

    session, file_id = synthetic_session
    t_start, t_end = 2.0, 8.0
    step_r = client.post("/api/stepfind", json={
        "session_id": session.session_id, "file_id": file_id,
        "channel": "extension", "algorithm": "kv",
        "t_start": t_start, "t_end": t_end,
    })
    body = step_r.json()
    assert body["t_start"] == t_start and body["t_end"] == t_end

    # Matches synthetic_session's own construction (see fixture above).
    full_time = np.linspace(0, 10, 10_000, dtype=np.float32).astype(np.float64)
    _, expected_cropped_time = crop_fn(full_time, full_time, t_start, t_end)

    reconstructed = expected_cropped_time[np.array(body["step_positions"], dtype=np.intp)]
    np.testing.assert_allclose(reconstructed, body["step_times"], rtol=1e-5)

    # And the downstream "steps" velocity/kinetics consumers must not error
    # when fed a cropped step result.
    r = client.post("/api/velocity", json={
        "session_id": session.session_id, "file_id": file_id,
        "method": "steps", "step_result_id": body["result_id"],
    })
    assert r.status_code == 201
    assert np.isfinite(r.json()["mean_velocity_nm_s"])


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


def test_violin_honors_crop_range(client, synthetic_session):
    """Regression: ViolinRequest previously had no t_start/t_end fields, so
    this was the other analysis endpoint (with Velocity) that silently used
    a different data range than its PWD/KDE/MSD neighbours."""
    session, file_id = synthetic_session
    full = client.post("/api/violin", json={
        "session_id": session.session_id, "file_ids": [file_id], "channel": "extension",
    }).json()
    cropped = client.post("/api/violin", json={
        "session_id": session.session_id, "file_ids": [file_id], "channel": "extension",
        "t_start": 0.0, "t_end": 2.0,
    }).json()
    assert full["groups"][0]["n"] == 10_000
    # t spans [0, 10] over 10,000 samples, so [0, 2] is ~2,000 samples.
    assert 1_500 < cropped["groups"][0]["n"] < 2_500


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


def test_ws_rejects_disallowed_origin(client, synthetic_session):
    """A page on an origin outside the CORS allowlist can't open the socket.

    WebSocket handshakes bypass CORSMiddleware entirely, so this check has
    to happen in the handler itself -- otherwise any website could ride a
    victim's browser to this local server (cross-site WebSocket hijack).
    """
    from starlette.websockets import WebSocketDisconnect

    session, _ = synthetic_session
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/ws/session/{session.session_id}",
            headers={"origin": "https://evil.example.com"},
        ):
            pass


def test_ws_allows_configured_origin(client, synthetic_session):
    session, _ = synthetic_session
    with client.websocket_connect(
        f"/ws/session/{session.session_id}",
        headers={"origin": "http://localhost:5173"},
    ) as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"


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
