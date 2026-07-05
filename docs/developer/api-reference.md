# API reference

## REST + WebSocket (live)

`sfz gui` serves interactive OpenAPI docs alongside the app itself — the authoritative,
always-up-to-date reference for every request/response schema, generated directly from the
FastAPI app's pydantic models:

- **Swagger UI**: `http://127.0.0.1:8765/api/docs`
- **ReDoc**: `http://127.0.0.1:8765/api/redoc`
- **Raw OpenAPI JSON**: `http://127.0.0.1:8765/api/openapi.json`

The WebSocket protocol (`/ws/session/{id}`) isn't part of OpenAPI (it doesn't cover WebSockets);
its message types are documented in the module docstring of `web/ws/session.py`.

## Python library

The pure analysis functions are what both the CLI and the web API call into — see
[Architecture](architecture.md) for why that matters. Their docstrings (NumPy style) are the
primary reference; below are the modules most worth knowing about.

### Analysis modules

::: salafleezers.analysis.filters
    options:
      members: [window_filter, smooth, bilateral_filter]

::: salafleezers.analysis.wlc
    options:
      members: [xwlc_extension, xwlc_force, fit_force_ext]

::: salafleezers.analysis.stepfind.kv
    options:
      members: [find_steps]

::: salafleezers.analysis.stepfind.hmm
    options:
      members: [find_steps]

::: salafleezers.analysis.velocity
    options:
      members: [step_velocities, savgol_velocity, velocity_histogram]

::: salafleezers.analysis.pwd
    options:
      members: [pairwise_distance]

::: salafleezers.analysis.kinetics
    options:
      members: [fit_n_exponential, fit_n_gamma, extract_dwell_times]

::: salafleezers.analysis.stats
    options:
      members: [kde, violin_data, msd_fft, weighted_histogram]

### Web layer

::: salafleezers.web.storage
    options:
      members: [StorageBackend, LocalFilesystemStore, UserScopedStore]

::: salafleezers.web.auth
    options:
      members: [Principal, get_current_principal]
