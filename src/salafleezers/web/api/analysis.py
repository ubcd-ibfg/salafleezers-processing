"""Analysis endpoints — thin wrappers around Phase 2 pure-NumPy modules.

POST /api/stepfind       → KV or HMM step detection
POST /api/wlc/fit        → extensible WLC fitting
POST /api/velocity       → Savitzky-Golay velocity distribution
POST /api/pwd            → pairwise-distance histogram
POST /api/kinetics/fit   → exponential / gamma dwell-time fit
POST /api/kde            → kernel density estimation
POST /api/violin         → distribution comparison across files
POST /api/msd            → mean-squared displacement
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException

from salafleezers.web.schemas import (
    KDERequest,
    KDEResult,
    KineticsRequest,
    KineticsResult,
    MSDRequest,
    MSDResult,
    PWDRequest,
    PWDResult,
    StepFindRequest,
    StepFindResult,
    VelocityRequest,
    VelocityResult,
    ViolinGroup,
    ViolinRequest,
    ViolinResult,
    WLCFitRequest,
    WLCFitResult,
)
from salafleezers.web.sessions import LoadedFile, Session, session_manager

router = APIRouter(prefix="/api", tags=["analysis"])


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _get_session(session_id: str) -> Session:
    try:
        return session_manager.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


def _get_file(session: Session, file_id: str) -> LoadedFile:
    f = session.files.get(file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="File not found in session")
    return f


def _resolve_channel(f: LoadedFile, channel: str) -> np.ndarray:
    for name in (channel, channel.lower(), channel.upper()):
        if name in f.channels:
            return f.channels[name].astype(np.float64)
    raise HTTPException(status_code=404, detail=f"Channel '{channel}' not found")


def _crop_if_requested(data: np.ndarray, time: np.ndarray,
                        t_start, t_end) -> tuple[np.ndarray, np.ndarray]:
    if t_start is None and t_end is None:
        return data, time
    from salafleezers.analysis.crop import crop
    t0 = t_start if t_start is not None else float(time[0])
    t1 = t_end if t_end is not None else float(time[-1])
    return crop(data, time, t0, t1)


# ---------------------------------------------------------------------------
# Step detection
# ---------------------------------------------------------------------------

@router.post("/stepfind", response_model=StepFindResult, status_code=201)
async def run_stepfind(request: StepFindRequest):
    """Detect steps using the Kalafut-Visscher (KV) or Baum-Welch HMM algorithm."""
    session = _get_session(request.session_id)
    f = _get_file(session, request.file_id)

    data = _resolve_channel(f, request.channel)
    time = f.time.astype(np.float64)
    data, time = _crop_if_requested(data, time, request.t_start, request.t_end)

    if request.algorithm == "kv":
        from salafleezers.analysis.stepfind.kv import find_steps
        r = find_steps(data, time=time, pen_factor=request.pen_factor)
        result_id = f"{request.file_id}_stepfind_kv"
        out = StepFindResult(
            session_id=request.session_id,
            file_id=request.file_id,
            result_id=result_id,
            algorithm="kv",
            n_steps=r.n_steps,
            step_positions=r.step_positions.tolist(),
            step_times=r.step_times.tolist(),
            levels=r.levels.tolist(),
            chi2=float(r.chi2),
        )

    elif request.algorithm == "hmm":
        from salafleezers.analysis.stepfind.hmm import find_steps, hmm_to_steps
        r = find_steps(data, n_states=request.n_states)
        steps = hmm_to_steps(r)
        step_times = time[steps].tolist() if len(steps) > 0 else []
        result_id = f"{request.file_id}_stepfind_hmm"
        out = StepFindResult(
            session_id=request.session_id,
            file_id=request.file_id,
            result_id=result_id,
            algorithm="hmm",
            n_steps=len(steps),
            step_positions=steps.tolist(),
            step_times=step_times,
            levels=r.means.tolist(),
        )

    else:
        raise HTTPException(status_code=422, detail=f"Unknown algorithm '{request.algorithm}'")

    session.step_results[out.result_id] = out.model_dump()
    return out


# ---------------------------------------------------------------------------
# WLC fitting
# ---------------------------------------------------------------------------

@router.post("/wlc/fit", response_model=WLCFitResult, status_code=201)
async def run_wlc_fit(request: WLCFitRequest):
    """Fit an extensible WLC model to a force-extension curve."""
    from salafleezers.analysis.wlc import fit_force_ext, xwlc_extension

    session = _get_session(request.session_id)
    f = _get_file(session, request.file_id)
    time = f.time.astype(np.float64)

    F = _resolve_channel(f, request.F_channel)
    x = _resolve_channel(f, request.x_channel)
    F, _ = _crop_if_requested(F, time, request.t_start, request.t_end)
    x, _ = _crop_if_requested(x, time, request.t_start, request.t_end)

    try:
        r = fit_force_ext(F, x, P0=request.P0, S0=request.S0,
                          method=request.method, fit_offsets=request.fit_offsets)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"WLC fit failed: {exc}")

    F_model = np.linspace(max(float(F.min()), 0.1), float(F.max()), 200)
    x_model = xwlc_extension(F_model, r.Lc, r.P, r.S, method=request.method)

    result_id = f"{request.file_id}_wlc"
    out = WLCFitResult(
        session_id=request.session_id,
        file_id=request.file_id,
        P_nm=r.P,
        Lc_nm=r.Lc,
        S_pN=r.S,
        x_offset_nm=r.x_offset,
        F_offset_pN=r.F_offset,
        chi2=r.chi2,
        method=r.method,
        F_model=F_model.tolist(),
        x_model=x_model.tolist(),
    )
    session.wlc_results[result_id] = out.model_dump()
    return out


# ---------------------------------------------------------------------------
# Velocity
# ---------------------------------------------------------------------------

@router.post("/velocity", response_model=VelocityResult, status_code=201)
async def run_velocity(request: VelocityRequest):
    """Compute a velocity distribution via Savitzky-Golay differentiation."""
    from salafleezers.analysis.velocity import savgol_velocity, velocity_histogram

    session = _get_session(request.session_id)
    f = _get_file(session, request.file_id)
    data = _resolve_channel(f, request.channel)
    time = f.time.astype(np.float64)

    vel = savgol_velocity(data, time, window=request.window, polyorder=request.polyorder)
    hist = velocity_histogram(vel)

    out = VelocityResult(
        session_id=request.session_id,
        file_id=request.file_id,
        v_centers=hist["v_centers"].tolist(),
        counts=hist["counts"].tolist(),
        mean_velocity_nm_s=float(np.nanmean(np.abs(vel))),
    )
    session.velocity_results[request.file_id] = out.model_dump()
    return out


# ---------------------------------------------------------------------------
# Pairwise distance
# ---------------------------------------------------------------------------

@router.post("/pwd", response_model=PWDResult, status_code=201)
async def run_pwd(request: PWDRequest):
    """Compute a pairwise-distance histogram."""
    from salafleezers.analysis.pwd import pairwise_distance

    session = _get_session(request.session_id)
    f = _get_file(session, request.file_id)
    data = _resolve_channel(f, request.channel)
    time = f.time.astype(np.float64)
    data, time = _crop_if_requested(data, time, request.t_start, request.t_end)

    try:
        r = pairwise_distance(data, bins=request.bins)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"PWD failed: {exc}")

    out = PWDResult(
        session_id=request.session_id,
        file_id=request.file_id,
        bin_centers=r.bin_centers.tolist(),
        pwd_counts=r.pwd_counts.tolist(),
        step_sizes=r.step_sizes.tolist(),
        peak_heights=r.peak_heights.tolist(),
    )
    session.pwd_results[request.file_id] = out.model_dump()
    return out


# ---------------------------------------------------------------------------
# Kinetics
# ---------------------------------------------------------------------------

@router.post("/kinetics/fit", response_model=KineticsResult, status_code=201)
async def run_kinetics(request: KineticsRequest):
    """Fit a dwell-time distribution to exponential or gamma mixtures."""
    # Obtain dwell times
    if request.dwell_times is not None:
        dwell_times = np.asarray(request.dwell_times, dtype=np.float64)
    elif request.step_result_id is not None:
        session = _get_session(request.session_id)
        step_res = session.step_results.get(request.step_result_id)
        if step_res is None:
            raise HTTPException(status_code=404, detail="Step result not found")
        from salafleezers.analysis.kinetics import extract_dwell_times
        f = _get_file(session, request.file_id)
        steps = np.array(step_res["step_positions"], dtype=np.intp)
        dwell_times = extract_dwell_times(steps, f.time.astype(np.float64))
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide either 'dwell_times' or 'step_result_id'",
        )

    dwell_times = dwell_times[dwell_times > 0]
    if len(dwell_times) < 2:
        raise HTTPException(status_code=422, detail="Not enough dwell times to fit")

    session = _get_session(request.session_id)

    if request.model == "exponential":
        from salafleezers.analysis.kinetics import fit_n_exponential
        r = fit_n_exponential(dwell_times, n=request.n_components,
                              n_restarts=request.n_restarts)
        out = KineticsResult(
            session_id=request.session_id,
            file_id=request.file_id,
            model="exponential",
            n_components=request.n_components,
            rates=r.rates.tolist(),
            amplitudes=r.amplitudes.tolist(),
            log_likelihood=r.log_likelihood,
            aic=r.aic,
            bic=r.bic,
        )

    elif request.model == "gamma":
        from salafleezers.analysis.kinetics import fit_n_gamma
        r = fit_n_gamma(dwell_times, n=request.n_components,
                        n_restarts=request.n_restarts)
        out = KineticsResult(
            session_id=request.session_id,
            file_id=request.file_id,
            model="gamma",
            n_components=request.n_components,
            shapes=r.shapes.tolist(),
            scales=r.scales.tolist(),
            amplitudes=r.amplitudes.tolist(),
            log_likelihood=r.log_likelihood,
            aic=r.aic,
            bic=r.bic,
        )

    else:
        raise HTTPException(status_code=422, detail=f"Unknown model '{request.model}'")

    session.kinetics_results[request.file_id] = out.model_dump()
    return out


# ---------------------------------------------------------------------------
# Kernel density estimation
# ---------------------------------------------------------------------------

@router.post("/kde", response_model=KDEResult, status_code=201)
async def run_kde(request: KDERequest):
    """Estimate a kernel density for one channel (port of kdf.m)."""
    from salafleezers.analysis.stats import kde

    session = _get_session(request.session_id)
    f = _get_file(session, request.file_id)
    data = _resolve_channel(f, request.channel)
    time = f.time.astype(np.float64)
    data, _ = _crop_if_requested(data, time, request.t_start, request.t_end)

    try:
        r = kde(data, n_points=request.n_points, bandwidth=request.bandwidth)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"KDE failed: {exc}")

    out = KDEResult(
        session_id=request.session_id,
        file_id=request.file_id,
        x=r.x.tolist(),
        density=r.density.tolist(),
        bandwidth=r.bandwidth,
    )
    session.kde_results[request.file_id] = out.model_dump()
    return out


# ---------------------------------------------------------------------------
# Distribution comparison (violin.m)
# ---------------------------------------------------------------------------

@router.post("/violin", response_model=ViolinResult, status_code=201)
async def run_violin(request: ViolinRequest):
    """Compare one channel's distribution across multiple loaded files."""
    from salafleezers.analysis.stats import violin_data

    session = _get_session(request.session_id)
    if not request.file_ids:
        raise HTTPException(status_code=422, detail="Provide at least one file_id")

    groups: dict[str, np.ndarray] = {}
    for fid in request.file_ids:
        f = _get_file(session, fid)
        groups[f.filename] = _resolve_channel(f, request.channel)

    try:
        result = violin_data(groups, bandwidth=request.bandwidth)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Violin failed: {exc}")

    return ViolinResult(
        session_id=request.session_id,
        channel=request.channel,
        groups=[
            ViolinGroup(
                label=label,
                x=v.x.tolist(),
                density=v.density.tolist(),
                median=v.median,
                quartile_25=v.quartile_25,
                quartile_75=v.quartile_75,
                whisker_lo=v.whisker_lo,
                whisker_hi=v.whisker_hi,
                n=v.n,
            )
            for label, v in result.items()
        ],
    )


# ---------------------------------------------------------------------------
# Mean-squared displacement
# ---------------------------------------------------------------------------

@router.post("/msd", response_model=MSDResult, status_code=201)
async def run_msd(request: MSDRequest):
    """Mean-squared displacement via FFT cross-correlation (port of msd*.m)."""
    from salafleezers.analysis.stats import msd_fft

    session = _get_session(request.session_id)
    f = _get_file(session, request.file_id)
    data = _resolve_channel(f, request.channel)
    time = f.time.astype(np.float64)
    data, time = _crop_if_requested(data, time, request.t_start, request.t_end)

    if len(data) < 2:
        raise HTTPException(status_code=422, detail="Not enough samples for MSD")

    lags, msd = msd_fft(data, max_lag=request.max_lag)
    dt = float(time[1] - time[0]) if len(time) > 1 else 1.0

    return MSDResult(
        session_id=request.session_id,
        file_id=request.file_id,
        lags_s=(lags * dt).tolist(),
        msd=msd.tolist(),
    )
