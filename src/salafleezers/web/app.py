"""FastAPI application factory.

Usage:
    from salafleezers.web.app import create_app
    import uvicorn
    uvicorn.run(create_app(), host="127.0.0.1", port=8765)

The factory pattern lets tests instantiate the app without side effects and
lets the CLI pass runtime configuration (CORS origins, SPA path, etc.).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from salafleezers.web.api import analysis, files, sessions, traces
from salafleezers.web.ws.session import handle_session_ws

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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins if allow_origins is not None else _DEFAULT_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # REST routers
    app.include_router(sessions.router)
    app.include_router(files.router)
    app.include_router(traces.router)
    app.include_router(analysis.router)

    # WebSocket
    @app.websocket("/ws/session/{session_id}")
    async def ws_session(websocket: WebSocket, session_id: str) -> None:
        await handle_session_ws(websocket, session_id)

    # Health check
    @app.get("/api/health", tags=["meta"])
    async def health() -> dict:
        return {"status": "ok", "version": "0.2.0"}

    # SPA static files (Phase 4+)
    if serve_spa and _SPA_DIR.exists():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(_SPA_DIR), html=True), name="spa")

    return app
