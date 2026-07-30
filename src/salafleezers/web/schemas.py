"""Pydantic schemas shared by the REST API, WebSocket protocol, and CLI.

This is the single canonical data model: a .mat/.h5 trace, an API payload,
and a GUI session are all the same shape.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from salafleezers.constants import (
    BEAD_RADIUS_NM,
    CAL_FMIN_HZ,
    CAL_N_ALIAS,
    CAL_NBIN,
    CONV_TRAP_X_NM_PER_MHZ,
    KT_24C,
    WATER_VISC_24C,
)


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
    """Open a file either by server path or by reference to an uploaded dataset.

    ``path`` is a server-filesystem path -- used by session reload
    (``POST /api/sessions/load/{id}``) and available to CLI/scripted callers,
    but no longer exposed as a UI affordance. ``dataset_id``+``relative_path``
    reference a file inside the caller's upload workspace (see workspace.py)
    and are always confined there regardless of ``SFZ_DATA_ROOT`` -- that's
    what lets uploads work with zero server-side configuration.
    """
    path: str | None = None
    dataset_id: str | None = None
    relative_path: str | None = None
    session_id: str | None = None   # if None → create a new session

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "FileOpenRequest":
        has_path = self.path is not None
        has_dataset = self.dataset_id is not None or self.relative_path is not None
        if has_path == has_dataset:
            raise ValueError(
                "Provide exactly one of 'path' or ('dataset_id' + 'relative_path')"
            )
        if has_dataset and (self.dataset_id is None or self.relative_path is None):
            raise ValueError("'dataset_id' and 'relative_path' must be provided together")
        return self


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
    n_states: int = Field(default=2, ge=2, le=20)   # HMM number of states
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
    # The range this result was computed over. ``step_positions`` index into
    # the *cropped* array, so any downstream consumer (velocity method="steps",
    # kinetics dwell times) must re-apply the same crop before indexing a time
    # axis -- otherwise the positions silently refer to the wrong samples.
    t_start: float | None = None
    t_end: float | None = None


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
    window: int = Field(default=21, ge=3, le=100_001)
    polyorder: int = Field(default=2, ge=0, le=10)
    step_result_id: str | None = None
    t_start: float | None = None
    t_end: float | None = None


class VelocityResult(BaseModel):
    session_id: str
    file_id: str
    result_id: str
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
    bins: int = Field(default=200, ge=2, le=20_000)
    t_start: float | None = None
    t_end: float | None = None


class PWDResult(BaseModel):
    session_id: str
    file_id: str
    result_id: str
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
    dwell_times: list[float] | None = Field(
        default=None, max_length=1_000_000
    )   # provide inline OR reference a step result
    step_result_id: str | None = None
    model: str = "exponential"               # "exponential" | "gamma"
    n_components: int = Field(default=1, ge=1, le=10)
    n_restarts: int = Field(default=3, ge=1, le=50)


class KineticsResult(BaseModel):
    session_id: str
    file_id: str
    result_id: str
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
    n_points: int = Field(default=512, ge=2, le=20_000)
    bandwidth: float | str = "scott"
    t_start: float | None = None
    t_end: float | None = None


class KDEResult(BaseModel):
    session_id: str
    file_id: str
    result_id: str
    x: list[float]
    density: list[float]
    bandwidth: float


# ---------------------------------------------------------------------------
# Distribution comparison (violin.m)
# ---------------------------------------------------------------------------

class ViolinRequest(BaseModel):
    session_id: str
    file_ids: list[str] = Field(min_length=1, max_length=200)   # one violin per file
    channel: str = "extension"
    bandwidth: float | str = "scott"
    t_start: float | None = None
    t_end: float | None = None


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
    max_lag: int | None = Field(default=None, ge=1, le=1_000_000)
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


# ---------------------------------------------------------------------------
# Uploads (browser-side data intake — see web/workspace.py)
# ---------------------------------------------------------------------------

class DatasetCreateRequest(BaseModel):
    name: str = "Untitled"


class UploadEntryOut(BaseModel):
    relative_path: str
    size_bytes: int
    kind: str                       # "trace" | "sidecar" | "batch" | "skipped"
    parent: str | None = None
    sidecars: list[str] = Field(default_factory=list)
    missing_sidecars: list[str] = Field(default_factory=list)
    warning: str | None = None
    datatype: int | None = None     # .dat header field 5: 1 = calibration file


class DatasetOut(BaseModel):
    dataset_id: str
    name: str
    created_at: str
    finalized: bool
    total_bytes: int
    entries: list[UploadEntryOut]


class UploadedFileOut(BaseModel):
    relative_path: str
    size_bytes: int


# ---------------------------------------------------------------------------
# Calibration & processing (Lorentzian power-spectrum fit -> force/extension)
# ---------------------------------------------------------------------------

class CalibrationRequest(BaseModel):
    session_id: str
    file_id: str                     # a calibration .dat already opened in the session
    bead_radius_a_nm: float = Field(default=BEAD_RADIUS_NM, gt=0, le=100_000)
    bead_radius_b_nm: float = Field(default=BEAD_RADIUS_NM, gt=0, le=100_000)
    f_min_hz: float = Field(default=CAL_FMIN_HZ, ge=0)
    f_max_hz: float | None = Field(default=None, gt=0)      # None -> Nyquist
    n_bin: int = Field(default=CAL_NBIN, ge=1, le=1_000_000)
    n_alias: int = Field(default=CAL_N_ALIAS, ge=0, le=100)  # bounds the (2n+1, len(f)) alloc
    normalize: bool = True
    kt_pn_nm: float = Field(default=KT_24C, gt=0)
    water_viscosity: float = Field(default=WATER_VISC_24C, gt=0)


class CalibrationAxisResult(BaseModel):
    detector: str                    # "AX" | "BX" | "AY" | "BY"
    fc_hz: float
    alpha_nm_v: float
    kappa_pn_nm: float
    D_v2_hz: float
    drag_pn_s_nm: float
    D_theory_nm2_s: float
    chi2: float
    converged: bool
    f_binned: list[float]            # full binned PSD -- for plotting
    psd_binned: list[float]
    f_model: list[float]             # fitted Lorentzian, evaluated over the fit range
    psd_model: list[float]
    f_fit_min: float                 # so the plot can shade the fit window
    f_fit_max: float


class CalibrationResultOut(BaseModel):
    session_id: str
    file_id: str
    result_id: str
    sampling_rate_hz: float
    axes: list[CalibrationAxisResult]
    skipped: list[str]               # detectors absent from this file


class DatasetFileRef(BaseModel):
    dataset_id: str
    relative_path: str


class ProcessRunRequest(BaseModel):
    session_id: str
    data: DatasetFileRef
    offset: DatasetFileRef | None = None            # None -> zero offset
    calibration: DatasetFileRef | None = None        # fit fresh from this .dat ...
    calibration_result_id: str | None = None         # ... or replay a cached fit
    bead_radius_a_nm: float = Field(default=BEAD_RADIUS_NM, gt=0, le=100_000)
    bead_radius_b_nm: float = Field(default=BEAD_RADIUS_NM, gt=0, le=100_000)
    ext_offset_nm: float = 0.0
    conv_trap_x_nm_per_mhz: float = Field(default=CONV_TRAP_X_NM_PER_MHZ, gt=0)
    normalize: bool = True
    # Calibration-fit knobs, honoured only when `calibration` is given.
    f_min_hz: float = Field(default=CAL_FMIN_HZ, ge=0)
    f_max_hz: float | None = Field(default=None, gt=0)
    n_bin: int = Field(default=CAL_NBIN, ge=1, le=1_000_000)
    n_alias: int = Field(default=CAL_N_ALIAS, ge=0, le=100)
    save_format: str = "hdf5"                        # "hdf5" | "npz"
    output_name: str | None = None

    @model_validator(mode="after")
    def _exactly_one_calibration(self) -> "ProcessRunRequest":
        has_dat = self.calibration is not None
        has_cached = self.calibration_result_id is not None
        if has_dat == has_cached:
            raise ValueError(
                "Provide exactly one of 'calibration' (a .dat to fit) or "
                "'calibration_result_id' (a previously computed fit)"
            )
        return self


class ProcessRunResult(BaseModel):
    session_id: str
    dataset_id: str
    relative_path: str
    preview: TracePreview            # already opened into the session
    calibration: CalibrationResultOut
    warnings: list[str]              # e.g. missing _pos -> extension unreliable
