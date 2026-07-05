# syntax=docker/dockerfile:1

# ---- Stage 1: build the Svelte SPA -----------------------------------------
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python runtime ------------------------------------------------
FROM python:3.13-slim AS runtime
RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
# hatchling's force-include check (see pyproject.toml) runs even for
# editable installs, so frontend/dist must exist before `uv sync`.
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist
RUN uv sync --extra gui --no-cache

# Session save/load persists here (see storage.py); mount a volume to
# survive container restarts.
ENV HOME=/root
VOLUME ["/root/.salafleezers"]

EXPOSE 8765

# --no-browser: there's no display in a container. Bind 0.0.0.0 so the
# service is reachable from outside the container network.
CMD ["uv", "run", "sfz", "gui", "--host", "0.0.0.0", "--port", "8765", "--no-browser"]
