"""WebSocket handler for real-time session interactions.

Endpoint:  ws /ws/session/{session_id}

The WS connection carries a simple JSON protocol for interactive operations
that would be too slow as HTTP round-trips (filter slider drag, crop-line
drag, live measurement tool).

Client → Server messages
------------------------
{"type": "filter",   "file_id": "…", "channel": "force", "half_width": 5, "decimate": 100}
{"type": "crop",     "file_id": "…", "t_start": 1.0, "t_end": 5.0, "channels": ["force"], "decimate": 100}
{"type": "measure",  "file_id": "…", "channel": "force", "t_start": 2.0, "t_end": 3.0}
{"type": "decimate", "file_id": "…", "channel": "force", "factor": 10, "t_start": …, "t_end": …}
{"type": "ping"}

Server → Client messages
------------------------
{"type": "trace",       "file_id": "…", "channel": "…", "time": […], "data": […]}
{"type": "crop_ack",    "file_id": "…", "t_start": …, "t_end": …, "channels": {…}}
{"type": "measurement", "file_id": "…", "mean": …, "std": …, …}
{"type": "pong"}
{"type": "error",       "detail": "…"}
"""

from __future__ import annotations

import json

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from salafleezers.web.sessions import LoadedFile, Session, session_manager


async def handle_session_ws(
    websocket: WebSocket,
    session_id: str,
    user_id: str = "local",
    allowed_origins: list[str] | None = None,
) -> None:
    """Accept a session WebSocket after an origin check and ownership check.

    WebSocket handshakes aren't covered by ``CORSMiddleware`` (CORS is a
    fetch/XHR-only mechanism), so without this check any web page could open
    a socket to this endpoint and ride the browser's cookies/local network
    access -- a cross-site WebSocket hijack. Non-browser clients typically
    omit the ``Origin`` header entirely, so only a *present but disallowed*
    origin is rejected; this mirrors the CORS allowlist rather than requiring
    Origin on every connection.
    """
    if allowed_origins is not None:
        origin = websocket.headers.get("origin")
        if origin is not None and origin not in allowed_origins:
            await websocket.close(code=4403)
            return

    await websocket.accept()

    try:
        session = session_manager.get_owned(session_id, user_id)
    except KeyError:
        await websocket.send_json({"type": "error", "detail": "Session not found"})
        await websocket.close(code=4004)
        return

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "detail": "Invalid JSON"})
                continue

            msg_type = msg.get("type")
            if msg_type == "filter":
                await _handle_filter(websocket, session, msg)
            elif msg_type == "crop":
                await _handle_crop(websocket, session, msg)
            elif msg_type == "measure":
                await _handle_measure(websocket, session, msg)
            elif msg_type == "decimate":
                await _handle_decimate(websocket, session, msg)
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json(
                    {"type": "error", "detail": f"Unknown message type '{msg_type}'"}
                )
    except WebSocketDisconnect:
        pass


# ---------------------------------------------------------------------------
# Message handlers
# ---------------------------------------------------------------------------

# Unlike the REST schemas (Pydantic-validated), WS messages are raw JSON --
# clamp every client-supplied int here so a malformed/hostile value can't
# reach numpy as an absurd window size or slice step.
_MAX_HALF_WIDTH = 100_000
_MAX_DECIMATE = 1_000_000
_MAX_CHANNELS = 50


def _clamped_int(msg: dict, key: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(msg.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


async def _handle_filter(ws: WebSocket, session: Session, msg: dict) -> None:
    """Apply a sliding-window filter and stream back the decimated result."""
    from salafleezers.analysis.filters import window_filter

    f, ch, err = _get_channel(session, msg)
    if err:
        await ws.send_json({"type": "error", "detail": err})
        return

    half_width = _clamped_int(msg, "half_width", 5, 1, _MAX_HALF_WIDTH)
    decimate = _clamped_int(msg, "decimate", 100, 1, _MAX_DECIMATE)

    filtered = window_filter(ch, fn="mean", half_width=half_width)
    await ws.send_json({
        "type": "trace",
        "file_id": msg.get("file_id"),
        "channel": msg.get("channel"),
        "time": f.time[::decimate].tolist(),
        "data": filtered[::decimate].tolist(),
    })


async def _handle_crop(ws: WebSocket, session: Session, msg: dict) -> None:
    """Store crop bounds and stream back decimated segments for the requested channels."""
    from salafleezers.analysis.crop import crop

    file_id = msg.get("file_id")
    f = session.files.get(file_id)
    if f is None:
        await ws.send_json({"type": "error", "detail": "File not found"})
        return

    t_start = float(msg.get("t_start", f.time[0]))
    t_end = float(msg.get("t_end", f.time[-1]))
    session.crops[file_id] = (t_start, t_end)

    decimate = _clamped_int(msg, "decimate", 100, 1, _MAX_DECIMATE)
    channel_names = msg.get("channels", list(f.channels.keys())[:4])[:_MAX_CHANNELS]

    time64 = f.time64   # resolved once, reused for every requested channel below
    ch_out: dict = {}
    for ch_name in channel_names:
        ch = f.resolve_channel64(ch_name)
        if ch is None:
            continue
        ch_crop, t_crop = crop(ch, time64, t_start, t_end)
        ch_out[ch_name] = {
            "time": t_crop[::decimate].tolist(),
            "data": ch_crop[::decimate].tolist(),
        }

    await ws.send_json({
        "type": "crop_ack",
        "file_id": file_id,
        "t_start": t_start,
        "t_end": t_end,
        "channels": ch_out,
    })


async def _handle_measure(ws: WebSocket, session: Session, msg: dict) -> None:
    """Return statistics over a time region of a channel."""
    from salafleezers.analysis.crop import measure

    f, ch, err = _get_channel(session, msg)
    if err:
        await ws.send_json({"type": "error", "detail": err})
        return

    t_start = msg.get("t_start")
    t_end = msg.get("t_end")
    if t_start is None or t_end is None:
        await ws.send_json({"type": "error", "detail": "'t_start' and 't_end' required"})
        return

    stats = measure(ch, f.time64, float(t_start), float(t_end))
    await ws.send_json({"type": "measurement", "file_id": msg.get("file_id"), **stats})


async def _handle_decimate(ws: WebSocket, session: Session, msg: dict) -> None:
    """Return a decimated viewport segment without filtering."""
    from salafleezers.analysis.crop import crop

    f, ch, err = _get_channel(session, msg)
    if err:
        await ws.send_json({"type": "error", "detail": err})
        return

    factor = _clamped_int(msg, "factor", 100, 1, _MAX_DECIMATE)
    time = f.time64
    data = ch

    t_start = msg.get("t_start")
    t_end = msg.get("t_end")
    if t_start is not None and t_end is not None:
        data, time = crop(data, time, float(t_start), float(t_end))

    await ws.send_json({
        "type": "trace",
        "file_id": msg.get("file_id"),
        "channel": msg.get("channel"),
        "time": time[::factor].tolist(),
        "data": data[::factor].tolist(),
    })


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _get_channel(
    session: Session, msg: dict
) -> tuple[LoadedFile | None, np.ndarray | None, str | None]:
    """Extract and resolve file + channel (float64) from a WS message.

    Returns (file, array, None) on success or (None, None, error_str) on failure.
    """
    file_id = msg.get("file_id")
    channel = msg.get("channel", "force")

    f = session.files.get(file_id)
    if f is None:
        return None, None, "File not found"

    ch = f.resolve_channel64(channel)
    if ch is None:
        return None, None, f"Channel '{channel}' not found"

    return f, ch, None
