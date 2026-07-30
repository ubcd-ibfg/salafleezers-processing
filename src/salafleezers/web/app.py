"""FastAPI application factory.

Usage:
    from salafleezers.web.app import create_app
    import uvicorn
    uvicorn.run(create_app(), host="127.0.0.1", port=8765)

The factory pattern lets tests instantiate the app without side effects and
lets the CLI pass runtime configuration (CORS origins, SPA path, etc.).
"""

from __future__ import annotations

import os
import time
from collections import deque
from pathlib import Path

from fastapi import Depends, FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse

from salafleezers.web.api import analysis, calibration, files, sessions, traces, uploads
from salafleezers.web.auth import (
    ANONYMOUS_USER_ID,
    Principal,
    auth_required,
    consume_ticket,
    get_current_principal,
    issue_ticket,
)
from salafleezers.web.workspace import max_upload_bytes
from salafleezers.web.ws.session import handle_session_ws

_DEFAULT_MAX_BODY_BYTES = 50 * 1024 * 1024   # 50 MB

# File uploads are streamed straight to disk under their own per-file cap
# (SFZ_MAX_UPLOAD_BYTES, enforced while writing in workspace.receive_file), so
# the JSON-oriented body limit must not apply to them -- a 200 MB trace is a
# normal upload but an absurd JSON payload.
_UPLOAD_PATH_MARKER = "/api/uploads/"


class _BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized request bodies before they're buffered/parsed.

    Pydantic validation (and any request.json() call) only runs after the
    whole body has already been read into memory, so a size cap has to sit
    in front of that -- otherwise a single request with an enormous JSON
    array (e.g. millions of ``dwell_times``) can exhaust memory regardless
    of the field-level bounds on the parsed model.

    File-upload routes are exempted from this cap and bounded by
    ``SFZ_MAX_UPLOAD_BYTES`` instead, enforced mid-stream rather than from the
    client-reported ``Content-Length`` (which can lie).
    """

    def __init__(self, app, max_bytes: int) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        is_upload = path.startswith(_UPLOAD_PATH_MARKER) and path.endswith("/files")
        limit = max_upload_bytes() if is_upload else self.max_bytes

        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > limit:
                    return PlainTextResponse("Request body too large", status_code=413)
            except ValueError:
                pass
        return await call_next(request)


class _RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory sliding-window rate limit, per client IP.

    Local-first default (no ``SFZ_RATE_LIMIT_PER_MINUTE``) leaves this
    disabled entirely -- a single local user shouldn't be throttled against
    themselves. For a shared-server deployment it caps how many requests
    any one client can make per rolling 60s window.

    Per-process only: each worker holds its own counters, so this isn't a
    substitute for a shared store (Redis, etc.) in a multi-worker/multi-host
    deployment -- a reasonable trade-off for the single-process small-lab
    deployments this app targets.
    """

    _WINDOW_SECONDS = 60.0

    def __init__(self, app, requests_per_minute: int) -> None:
        super().__init__(app)
        self.limit = requests_per_minute
        self._hits: dict[str, deque[float]] = {}

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()

        hits = self._hits.get(client_ip)
        if hits is not None:
            while hits and now - hits[0] > self._WINDOW_SECONDS:
                hits.popleft()
            if not hits:
                # Evict stale keys so a long-running process doesn't
                # accumulate one deque per distinct client forever.
                del self._hits[client_ip]
                hits = None

        if hits is not None and len(hits) >= self.limit:
            return PlainTextResponse("Rate limit exceeded", status_code=429)

        self._hits.setdefault(client_ip, deque()).append(now)
        return await call_next(request)


def _find_spa_dir() -> Path:
    """Locate the built Svelte SPA.

    Checks the installed-package location first (``force-include``d into the
    wheel at build time), then falls back to the source-tree ``frontend/dist``
    for `uv run` / editable-install development.
    """
    installed = Path(__file__).parent / "frontend_dist"
    if installed.exists():
        return installed
    return Path(__file__).parent.parent.parent.parent / "frontend" / "dist"


_SPA_DIR = _find_spa_dir()


def resolve_frontend_base_path() -> str:
    """Read ``FRONTEND_BASE_PATH`` from the environment, normalized.

    Returns ``""`` for the default root deployment, or ``"/segment"`` (single
    leading slash, no trailing slash) otherwise. The frontend build reads the
    same variable (see ``frontend/vite.config.ts``) so the SPA's baked-in
    asset/API/WS URLs line up with wherever the backend mounts itself.
    """
    raw = os.environ.get("FRONTEND_BASE_PATH")
    if not raw:
        return ""
    trimmed = raw.strip("/")
    return f"/{trimmed}" if trimmed else ""


_DEFAULT_ORIGINS = [
    "http://localhost:5173",   # Vite dev server
    "http://localhost:4173",   # Vite preview
    "http://127.0.0.1:5173",
    "http://127.0.0.1:4173",
    "http://localhost:8765",   # production port
    "http://127.0.0.1:8765",
]


def create_app(
    *,
    allow_origins: list[str] | None = None,
    serve_spa: bool = True,
) -> FastAPI:
    """Return a configured FastAPI instance.

    Parameters
    ----------
    allow_origins:
        CORS allowed origins.  Defaults to localhost + 127.0.0.1 on the
        standard Vite and production ports.
    serve_spa:
        Mount the built Svelte SPA at ``/`` when ``frontend/dist`` exists.
        Set to ``False`` during tests or when running the Vite dev server.
    """
    app = FastAPI(
        title="SalaFleezer GUI API",
        description=(
            "REST + WebSocket API for interactive optical tweezers analysis.\n\n"
            "OpenAPI docs: `/api/docs`  •  ReDoc: `/api/redoc`"
        ),
        version="0.2.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    origins = allow_origins if allow_origins is not None else _DEFAULT_ORIGINS

    if "*" in origins:
        # With allow_credentials=True, Starlette's CORSMiddleware reflects the
        # request's Origin header back verbatim instead of sending a literal
        # "*" (browsers reject credentialed "*" responses) -- so "*" here
        # doesn't mean "any origin, no credentials", it silently means "any
        # origin, WITH credentials". That's very unlikely to be what a
        # deployer intended, so fail fast instead of allowing it quietly.
        raise ValueError(
            "allow_origins=['*'] combined with credentialed CORS allows any "
            "origin full authenticated access; pass an explicit origin list."
        )

    max_body_bytes = int(
        os.environ.get("SFZ_MAX_BODY_BYTES") or _DEFAULT_MAX_BODY_BYTES
    )
    app.add_middleware(_BodySizeLimitMiddleware, max_bytes=max_body_bytes)

    rate_limit = os.environ.get("SFZ_RATE_LIMIT_PER_MINUTE")
    if rate_limit:
        app.add_middleware(_RateLimitMiddleware, requests_per_minute=int(rate_limit))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # REST routers
    app.include_router(sessions.router)
    app.include_router(files.router)
    app.include_router(uploads.router)
    app.include_router(traces.router)
    app.include_router(analysis.router)
    app.include_router(calibration.router)

    @app.post("/api/ws-ticket", tags=["meta"])
    async def ws_ticket(
        principal: Principal = Depends(get_current_principal),
    ) -> dict:
        """Mint a short-lived single-use ticket for the session WebSocket.

        Browsers cannot set an ``Authorization`` header on a WebSocket
        handshake, so the socket is authenticated with a ticket obtained from
        this (header-authenticated) endpoint instead of a long-lived token in
        the query string.
        """
        ticket, ttl = issue_ticket(principal.user_id)
        return {"ticket": ticket, "expires_in": ttl}

    # WebSocket
    @app.websocket("/ws/session/{session_id}")
    async def ws_session(
        websocket: WebSocket,
        session_id: str,
        ticket: str | None = None,
    ) -> None:
        if auth_required():
            user_id = consume_ticket(ticket) if ticket else None
            if user_id is None:
                await websocket.close(code=4401)
                return
        else:
            # Local-first default: no auth configured, so no ticket needed.
            user_id = ANONYMOUS_USER_ID

        await handle_session_ws(
            websocket, session_id, user_id, allowed_origins=origins
        )

    # Health check
    @app.get("/api/health", tags=["meta"])
    async def health() -> dict:
        """Health plus the handful of capabilities the SPA needs at boot."""
        return {
            "status": "ok",
            "version": "0.2.0",
            "auth_required": auth_required(),
            "max_upload_bytes": max_upload_bytes(),
        }

    # SPA static files (Phase 4+)
    if serve_spa and _SPA_DIR.exists():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(_SPA_DIR), html=True), name="spa")

    base_path = resolve_frontend_base_path()
    if not base_path:
        return app

    # Serve everything (SPA, /api, /ws) under a path prefix instead of at the
    # domain root -- for a deployment reachable at e.g.
    # https://lab.example.org/salafleezer/ behind a reverse proxy that
    # forwards the path through unstripped. Starlette's Mount forwards both
    # HTTP and WebSocket scopes and adjusts root_path as it goes, so
    # FastAPI's own URL generation (OpenAPI, docs) stays correct without any
    # extra bookkeeping here.
    outer = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    outer.mount(base_path, app)

    @outer.get("/", include_in_schema=False)
    async def _redirect_to_base_path() -> RedirectResponse:
        return RedirectResponse(url=f"{base_path}/")

    return outer
