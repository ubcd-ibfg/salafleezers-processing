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


async def handle_session_ws(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()

    try:
        session = session_manager.get(session_id)
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

async def _handle_filter(ws: WebSocket, session: Session, msg: dict) -> None:
    """Apply a sliding-window filter and stream back the decimated result."""
    from salafleezers.analysis.filters import window_filter

    f, ch, err = _get_channel(session, msg)
    if err:
        await ws.send_json({"type": "error", "detail": err})
        return

    half_width = max(1, int(msg.get("half_width", 5)))
    decimate = max(1, int(msg.get("decimate", 100)))

    filtered = window_filter(ch.astype(np.float64), fn="mean", half_width=half_width)
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

    decimate = max(1, int(msg.get("decimate", 100)))
    channel_names = msg.get("channels", list(f.channels.keys())[:4])

    ch_out: dict = {}
    for ch_name in channel_names:
        ch = _resolve_channel(f, ch_name)
        if ch is None:
            continue
        ch_crop, t_crop = crop(ch.astype(np.float64), f.time.astype(np.float64),
                                t_start, t_end)
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

    stats = measure(ch.astype(np.float64), f.time.astype(np.float64),
                    float(t_start), float(t_end))
    await ws.send_json({"type": "measurement", "file_id": msg.get("file_id"), **stats})


async def _handle_decimate(ws: WebSocket, session: Session, msg: dict) -> None:
    """Return a decimated viewport segment without filtering."""
    from salafleezers.analysis.crop import crop

    f, ch, err = _get_channel(session, msg)
    if err:
        await ws.send_json({"type": "error", "detail": err})
        return

    factor = max(1, int(msg.get("factor", 100)))
    time = f.time.astype(np.float64)
    data = ch.astype(np.float64)

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

def _resolve_channel(f: LoadedFile, channel: str) -> np.ndarray | None:
    for name in (channel, channel.lower(), channel.upper()):
        if name in f.channels:
            return f.channels[name]
    return None


def _get_channel(
    session: Session, msg: dict
) -> tuple[LoadedFile | None, np.ndarray | None, str | None]:
    """Extract and resolve file + channel from a WS message.

    Returns (file, array, None) on success or (None, None, error_str) on failure.
    """
    file_id = msg.get("file_id")
    channel = msg.get("channel", "force")

    f = session.files.get(file_id)
    if f is None:
        return None, None, "File not found"

    ch = _resolve_channel(f, channel)
    if ch is None:
        return None, None, f"Channel '{channel}' not found"

    return f, ch, None
