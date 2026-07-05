"""Pydantic schemas shared by the REST API, WebSocket protocol, and CLI.

This is the single canonical data model: a .mat/.h5 trace, an API payload,
and a GUI session are all the same shape.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

class SessionInfo(BaseModel):
    session_id: str
    created_at: str
    n_files: int
    file_ids: list[str]


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

class FileOpenRequest(BaseModel):
    path: str
    session_id: str | None = None   # if None → create a new session


class TraceMetadata(BaseModel):
    file_id: str
    filename: str
    n_samples: int
    sampling_rate_hz: float
    duration_s: float
    channels: list[str]
    meta: dict[str, Any]


class TracePreview(BaseModel):
    """Initial payload returned when a file is opened.

    Contains a decimated preview of every channel suitable for the
    first render.  Higher-resolution data is fetched lazily via
    GET /api/traces/{file_id}.
    """
    file_id: str
    session_id: str
    time: list[float]
    channels: dict[str, list[float]]
    n_original: int
    decimate_factor: int
    sampling_rate_hz: float
    filename: str


# ---------------------------------------------------------------------------
# Traces
# ---------------------------------------------------------------------------

class TraceSegment(BaseModel):
    """A (decimated) segment of one channel, for viewport-level-of-detail."""
    file_id: str
    channel: str
    time: list[float]
    data: list[float]
    n_original: int
    decimate_factor: int
    t_start: float
    t_end: float


# ---------------------------------------------------------------------------
# Step detection
# ---------------------------------------------------------------------------

class StepFindRequest(BaseModel):
    session_id: str
    file_id: str
    channel: str = "extension"
    algorithm: str = "kv"     # "kv" | "hmm"
    pen_factor: float = 2.0   # KV penalty multiplier
    n_states: int = 2         # HMM number of states
    t_start: float | None = None
    t_end: float | None = None


class StepFindResult(BaseModel):
    session_id: str
    file_id: str
    result_id: str            # key for later reference (e.g. kinetics)
    algorithm: str
    n_steps: int
    step_positions: list[int]
    step_times: list[float]
    levels: list[float]
    chi2: float | None = None


# ---------------------------------------------------------------------------
# WLC fitting
# ---------------------------------------------------------------------------

class WLCFitRequest(BaseModel):
    session_id: str
    file_id: str
    F_channel: str = "force"
    x_channel: str = "extension"
    method: str = "basic"     # "basic" | "marko_siggia" | "bouchiat"
    P0: float = 50.0
    S0: float = 900.0
    fit_offsets: bool = True
    t_start: float | None = None
    t_end: float | None = None


class WLCFitResult(BaseModel):
    session_id: str
    file_id: str
    P_nm: float
    Lc_nm: float
    S_pN: float
    x_offset_nm: float
    F_offset_pN: float
    chi2: float
    method: str
    F_model: list[float]      # model curve for plotting
    x_model: list[float]


# ---------------------------------------------------------------------------
# Velocity
# ---------------------------------------------------------------------------

class VelocityRequest(BaseModel):
    session_id: str
    file_id: str
    channel: str = "extension"
    method: str = "savgol"    # "savgol" | "steps"
    window: int = 21
    polyorder: int = 2
    step_result_id: str | None = None


class VelocityResult(BaseModel):
    session_id: str
    file_id: str
    v_centers: list[float]
    counts: list[int]
    mean_velocity_nm_s: float


# ---------------------------------------------------------------------------
# Pairwise distance
# ---------------------------------------------------------------------------

class PWDRequest(BaseModel):
    session_id: str
    file_id: str
    channel: str = "extension"
    bins: int = 200
    t_start: float | None = None
    t_end: float | None = None


class PWDResult(BaseModel):
    session_id: str
    file_id: str
    bin_centers: list[float]
    pwd_counts: list[float]
    step_sizes: list[float]
    peak_heights: list[float]


# ---------------------------------------------------------------------------
# Kinetics
# ---------------------------------------------------------------------------

class KineticsRequest(BaseModel):
    session_id: str
    file_id: str
    dwell_times: list[float] | None = None   # provide inline OR reference a step result
    step_result_id: str | None = None
    model: str = "exponential"               # "exponential" | "gamma"
    n_components: int = 1
    n_restarts: int = 3


class KineticsResult(BaseModel):
    session_id: str
    file_id: str
    model: str
    n_components: int
    rates: list[float] | None = None
    amplitudes: list[float] | None = None
    shapes: list[float] | None = None
    scales: list[float] | None = None
    log_likelihood: float
    aic: float
    bic: float


# ---------------------------------------------------------------------------
# Kernel density estimation
# ---------------------------------------------------------------------------

class KDERequest(BaseModel):
    session_id: str
    file_id: str
    channel: str = "extension"
    n_points: int = 512
    bandwidth: float | str = "scott"
    t_start: float | None = None
    t_end: float | None = None


class KDEResult(BaseModel):
    session_id: str
    file_id: str
    x: list[float]
    density: list[float]
    bandwidth: float


# ---------------------------------------------------------------------------
# Distribution comparison (violin.m)
# ---------------------------------------------------------------------------

class ViolinRequest(BaseModel):
    session_id: str
    file_ids: list[str]     # one group/violin per file
    channel: str = "extension"
    bandwidth: float | str = "scott"


class ViolinGroup(BaseModel):
    label: str
    x: list[float]
    density: list[float]
    median: float
    quartile_25: float
    quartile_75: float
    whisker_lo: float
    whisker_hi: float
    n: int


class ViolinResult(BaseModel):
    session_id: str
    channel: str
    groups: list[ViolinGroup]


# ---------------------------------------------------------------------------
# Mean-squared displacement (msd*.m)
# ---------------------------------------------------------------------------

class MSDRequest(BaseModel):
    session_id: str
    file_id: str
    channel: str = "extension"
    max_lag: int | None = None
    t_start: float | None = None
    t_end: float | None = None


class MSDResult(BaseModel):
    session_id: str
    file_id: str
    lags_s: list[float]
    msd: list[float]


# ---------------------------------------------------------------------------
# Measurement (WebSocket response)
# ---------------------------------------------------------------------------

class MeasurementResult(BaseModel):
    mean: float
    std: float
    median: float
    min: float
    max: float
    n_pts: int
    t_start: float
    t_end: float
    duration: float
