"""Trace-data route.

GET /api/traces/{file_id}?session_id=…&channel=…&decimate=…&t_start=…&t_end=…

Server-side decimation keeps payloads small even for multi-million-point traces.
The frontend requests higher-resolution chunks as the user zooms in.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from salafleezers.web.auth import Principal, get_current_principal
from salafleezers.web.schemas import TraceSegment
from salafleezers.web.sessions import session_manager

router = APIRouter(prefix="/api/traces", tags=["traces"])


@router.get("/{file_id}", response_model=TraceSegment)
def get_trace(
    file_id: str,
    session_id: str,
    channel: str = Query("force"),
    decimate: int = Query(100, ge=1, le=100_000),
    t_start: float | None = Query(None),
    t_end: float | None = Query(None),
    principal: Principal = Depends(get_current_principal),
):
    """Return a (decimated) segment of one channel.

    **Adaptive decimate workflow**: request with ``decimate=1`` only for
    small visible windows; use ``decimate=N`` for the full-trace overview.
    """
    try:
        session = session_manager.get_owned(session_id, principal.user_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    f = session.get_file(file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="File not found in session")

    data = f.resolve_channel64(channel)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Channel '{channel}' not found")

    time = f.time64

    # Crop
    if t_start is not None or t_end is not None:
        from salafleezers.analysis.crop import crop
        t0 = t_start if t_start is not None else float(time[0])
        t1 = t_end if t_end is not None else float(time[-1])
        data, time = crop(data, time, t0, t1)

    n_original = len(time)
    return TraceSegment(
        file_id=file_id,
        channel=channel,
        time=time[::decimate].tolist(),
        data=data[::decimate].tolist(),
        n_original=n_original,
        decimate_factor=decimate,
        t_start=float(time[0]) if n_original else 0.0,
        t_end=float(time[-1]) if n_original else 0.0,
    )
