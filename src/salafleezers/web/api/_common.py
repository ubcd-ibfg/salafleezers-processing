"""Shared helpers for the compute endpoints (analysis, calibration, processing).

Not a router itself -- ``analysis.py`` re-exports these names for backward
compatibility (existing imports and tests reference them via
``salafleezers.web.api.analysis``), and ``calibration.py`` imports them
directly from here.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager

import numpy as np
from fastapi import HTTPException

from salafleezers.web.auth import Principal
from salafleezers.web.sessions import LoadedFile, Session, session_manager

# ---------------------------------------------------------------------------
# Resource guards
# ---------------------------------------------------------------------------
#
# Analysis runs synchronously inside the request (there is no job queue), so
# nothing here is free: a client that hangs up does NOT stop the computation.
# Two guards keep that from turning into accidental denial-of-service on a
# shared server, and they matter more than a client-side "cancel" button:
#
#   1. A hard input-size cap, because Kalafut-Visscher is worst-case O(N^2)
#      (see analysis/stepfind/kv.py) -- a full-resolution 62.5 kHz trace is
#      minutes of CPU, and the honest answer is to refuse and tell the caller
#      to narrow the range rather than accept and stall.
#   2. A per-principal concurrency cap, so one user can't occupy every
#      threadpool slot and make the app unresponsive for everyone else.

_DEFAULT_MAX_STEPFIND_SAMPLES = 2_000_000
_DEFAULT_MAX_CONCURRENT_PER_USER = 2


def _max_stepfind_samples() -> int:
    return int(
        os.environ.get("SFZ_MAX_STEPFIND_SAMPLES") or _DEFAULT_MAX_STEPFIND_SAMPLES
    )


def _max_concurrent_per_user() -> int:
    return int(
        os.environ.get("SFZ_MAX_CONCURRENT_ANALYSES") or _DEFAULT_MAX_CONCURRENT_PER_USER
    )


_slots_lock = threading.Lock()
_slots: dict[str, threading.Semaphore] = {}


@contextmanager
def _analysis_slot(user_id: str):
    """Limit how many analyses one principal can run at once.

    Returns 429 rather than queueing: the caller is a UI that should say "one
    at a time", and an unbounded queue would just move the stall.
    """
    with _slots_lock:
        sem = _slots.get(user_id)
        if sem is None:
            sem = threading.Semaphore(_max_concurrent_per_user())
            _slots[user_id] = sem

    if not sem.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail="Too many analyses already running for this user; wait for one to finish",
        )
    try:
        yield
    finally:
        sem.release()


def _guard_sample_count(n: int, limit: int, what: str) -> None:
    if n > limit:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{what} over {n:,} samples exceeds the {limit:,}-sample limit. "
                "Zoom in or apply a crop to narrow the analysis range."
            ),
        )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _get_session(session_id: str, principal: Principal) -> Session:
    try:
        return session_manager.get_owned(session_id, principal.user_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


def _get_file(session: Session, file_id: str) -> LoadedFile:
    """Fetch a file's arrays, rehydrating from its durable ref on a cache miss."""
    f = session.get_file(file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="File not found in session")
    return f


def _resolve_channel(f: LoadedFile, channel: str) -> np.ndarray:
    resolved = f.resolve_channel64(channel)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Channel '{channel}' not found")
    return resolved


def _crop_if_requested(data: np.ndarray, time: np.ndarray,
                        t_start, t_end) -> tuple[np.ndarray, np.ndarray]:
    if t_start is None and t_end is None:
        return data, time
    from salafleezers.analysis.crop import crop
    t0 = t_start if t_start is not None else float(time[0])
    t1 = t_end if t_end is not None else float(time[-1])
    return crop(data, time, t0, t1)
