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
from fastapi import APIRouter, Depends, HTTPException

from salafleezers.web.api._common import (
    _analysis_slot,
    _crop_if_requested,
    _get_file,
    _get_session,
    _guard_sample_count,
    _max_concurrent_per_user,
    _max_stepfind_samples,
    _resolve_channel,
    _slots,
    _slots_lock,
)
from salafleezers.web.auth import Principal, get_current_principal
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

router = APIRouter(prefix="/api", tags=["analysis"])

# Resource guards and shared helpers (_analysis_slot, _guard_sample_count,
# _get_session, _get_file, _resolve_channel, _crop_if_requested, plus the
# _slots/_slots_lock/_max_* internals) now live in _common.py, shared with
# web/api/calibration.py -- imported above and re-exported here so existing
# imports of these names from `salafleezers.web.api.analysis` keep working.


# ---------------------------------------------------------------------------
# Step detection
# ---------------------------------------------------------------------------

@router.post("/stepfind", response_model=StepFindResult, status_code=201)
def run_stepfind(
    request: StepFindRequest, principal: Principal = Depends(get_current_principal)
):
    """Detect steps using the Kalafut-Visscher (KV) or Baum-Welch HMM algorithm."""
    session = _get_session(request.session_id, principal)
    f = _get_file(session, request.file_id)

    data = _resolve_channel(f, request.channel)
    time = f.time64
    data, time = _crop_if_requested(data, time, request.t_start, request.t_end)
    _guard_sample_count(len(data), _max_stepfind_samples(), "Step detection")

    with _analysis_slot(principal.user_id):
        if request.algorithm == "kv":
            from salafleezers.analysis.stepfind.kv import find_steps
            try:
                r = find_steps(data, time=time, pen_factor=request.pen_factor)
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"KV step-find failed: {exc}")
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
                t_start=request.t_start,
                t_end=request.t_end,
            )

        elif request.algorithm == "hmm":
            from salafleezers.analysis.stepfind.hmm import find_steps, hmm_to_steps
            try:
                r = find_steps(data, n_states=request.n_states)
                steps = hmm_to_steps(r)
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"HMM step-find failed: {exc}")
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
                t_start=request.t_start,
                t_end=request.t_end,
            )

        else:
            raise HTTPException(
                status_code=422, detail=f"Unknown algorithm '{request.algorithm}'"
            )

    session.step_results[out.result_id] = out.model_dump()
    return out


# ---------------------------------------------------------------------------
# WLC fitting
# ---------------------------------------------------------------------------

@router.post("/wlc/fit", response_model=WLCFitResult, status_code=201)
def run_wlc_fit(
    request: WLCFitRequest, principal: Principal = Depends(get_current_principal)
):
    """Fit an extensible WLC model to a force-extension curve."""
    from salafleezers.analysis.wlc import fit_force_ext, xwlc_extension

    session = _get_session(request.session_id, principal)
    f = _get_file(session, request.file_id)
    time = f.time64

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
def run_velocity(
    request: VelocityRequest, principal: Principal = Depends(get_current_principal)
):
    """Compute a velocity distribution: Savitzky-Golay derivative or step levels."""
    from salafleezers.analysis.velocity import velocity_histogram

    session = _get_session(request.session_id, principal)
    f = _get_file(session, request.file_id)
    time = f.time64

    if request.method == "savgol":
        from salafleezers.analysis.velocity import savgol_velocity
        data = _resolve_channel(f, request.channel)
        # Honour the caller's analysis range, as every other endpoint does.
        # Without this, zooming into a region and clicking through the analysis
        # tabs gave this one panel an answer computed over the whole trace,
        # with nothing on screen indicating the mismatch.
        data, time = _crop_if_requested(data, time, request.t_start, request.t_end)
        try:
            vel = savgol_velocity(data, time, window=request.window,
                                  polyorder=request.polyorder)
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail=f"Savgol velocity failed: {exc}"
            )
        mean_v = float(np.nanmean(np.abs(vel)))

    elif request.method == "steps":
        from types import SimpleNamespace
        from salafleezers.analysis.velocity import step_velocities

        if request.step_result_id is None:
            raise HTTPException(
                status_code=422, detail="'step_result_id' required for method='steps'"
            )
        step_res = session.step_results.get(request.step_result_id)
        if step_res is None:
            raise HTTPException(status_code=404, detail="Step result not found")

        # step_positions index into the array the step-find ran on, so re-apply
        # that result's own crop before indexing -- using the full time axis
        # here silently attributed each step to the wrong timestamp.
        _, step_time = _crop_if_requested(
            time, time, step_res.get("t_start"), step_res.get("t_end")
        )
        kv_like = SimpleNamespace(
            step_positions=np.array(step_res["step_positions"], dtype=np.intp),
            levels=np.array(step_res["levels"], dtype=np.float64),
        )
        try:
            r = step_velocities(kv_like, step_time)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Step velocity failed: {exc}")
        vel = r.velocities
        mean_v = r.mean_velocity

    else:
        raise HTTPException(
            status_code=422, detail=f"Unknown method '{request.method}'"
        )

    if len(vel) == 0 or not np.any(np.isfinite(vel)):
        raise HTTPException(status_code=422, detail="No velocity samples computed")

    hist = velocity_histogram(vel)
    result_id = f"{request.file_id}_velocity_{request.method}"
    out = VelocityResult(
        session_id=request.session_id,
        file_id=request.file_id,
        result_id=result_id,
        v_centers=hist["v_centers"].tolist(),
        counts=hist["counts"].tolist(),
        mean_velocity_nm_s=mean_v,
    )
    session.velocity_results[result_id] = out.model_dump()
    return out


# ---------------------------------------------------------------------------
# Pairwise distance
# ---------------------------------------------------------------------------

@router.post("/pwd", response_model=PWDResult, status_code=201)
def run_pwd(
    request: PWDRequest, principal: Principal = Depends(get_current_principal)
):
    """Compute a pairwise-distance histogram."""
    from salafleezers.analysis.pwd import pairwise_distance

    session = _get_session(request.session_id, principal)
    f = _get_file(session, request.file_id)
    data = _resolve_channel(f, request.channel)
    time = f.time64
    data, time = _crop_if_requested(data, time, request.t_start, request.t_end)

    try:
        r = pairwise_distance(data, bins=request.bins)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"PWD failed: {exc}")

    result_id = f"{request.file_id}_pwd"
    out = PWDResult(
        session_id=request.session_id,
        file_id=request.file_id,
        result_id=result_id,
        bin_centers=r.bin_centers.tolist(),
        pwd_counts=r.pwd_counts.tolist(),
        step_sizes=r.step_sizes.tolist(),
        peak_heights=r.peak_heights.tolist(),
    )
    session.pwd_results[result_id] = out.model_dump()
    return out


# ---------------------------------------------------------------------------
# Kinetics
# ---------------------------------------------------------------------------

@router.post("/kinetics/fit", response_model=KineticsResult, status_code=201)
def run_kinetics(
    request: KineticsRequest, principal: Principal = Depends(get_current_principal)
):
    """Fit a dwell-time distribution to exponential or gamma mixtures."""
    # Obtain dwell times
    if request.dwell_times is not None:
        dwell_times = np.asarray(request.dwell_times, dtype=np.float64)
    elif request.step_result_id is not None:
        session = _get_session(request.session_id, principal)
        step_res = session.step_results.get(request.step_result_id)
        if step_res is None:
            raise HTTPException(status_code=404, detail="Step result not found")
        from salafleezers.analysis.kinetics import extract_dwell_times
        f = _get_file(session, request.file_id)
        steps = np.array(step_res["step_positions"], dtype=np.intp)
        # Same crop-alignment requirement as velocity method="steps" above.
        _, step_time = _crop_if_requested(
            f.time64, f.time64, step_res.get("t_start"), step_res.get("t_end")
        )
        dwell_times = extract_dwell_times(steps, step_time)
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide either 'dwell_times' or 'step_result_id'",
        )

    dwell_times = dwell_times[dwell_times > 0]
    if len(dwell_times) < 2:
        raise HTTPException(status_code=422, detail="Not enough dwell times to fit")

    session = _get_session(request.session_id, principal)

    result_id = f"{request.file_id}_kinetics_{request.model}"

    if request.model == "exponential":
        from salafleezers.analysis.kinetics import fit_n_exponential
        r = fit_n_exponential(dwell_times, n=request.n_components,
                              n_restarts=request.n_restarts)
        out = KineticsResult(
            session_id=request.session_id,
            file_id=request.file_id,
            result_id=result_id,
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
            result_id=result_id,
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

    session.kinetics_results[result_id] = out.model_dump()
    return out


# ---------------------------------------------------------------------------
# Kernel density estimation
# ---------------------------------------------------------------------------

@router.post("/kde", response_model=KDEResult, status_code=201)
def run_kde(
    request: KDERequest, principal: Principal = Depends(get_current_principal)
):
    """Estimate a kernel density for one channel (port of kdf.m)."""
    from salafleezers.analysis.stats import kde

    session = _get_session(request.session_id, principal)
    f = _get_file(session, request.file_id)
    data = _resolve_channel(f, request.channel)
    time = f.time64
    data, _ = _crop_if_requested(data, time, request.t_start, request.t_end)

    try:
        r = kde(data, n_points=request.n_points, bandwidth=request.bandwidth)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"KDE failed: {exc}")

    result_id = f"{request.file_id}_kde"
    out = KDEResult(
        session_id=request.session_id,
        file_id=request.file_id,
        result_id=result_id,
        x=r.x.tolist(),
        density=r.density.tolist(),
        bandwidth=r.bandwidth,
    )
    session.kde_results[result_id] = out.model_dump()
    return out


# ---------------------------------------------------------------------------
# Distribution comparison (violin.m)
# ---------------------------------------------------------------------------

@router.post("/violin", response_model=ViolinResult, status_code=201)
def run_violin(
    request: ViolinRequest, principal: Principal = Depends(get_current_principal)
):
    """Compare one channel's distribution across multiple loaded files."""
    from salafleezers.analysis.stats import violin_data

    session = _get_session(request.session_id, principal)
    if not request.file_ids:
        raise HTTPException(status_code=422, detail="Provide at least one file_id")

    groups: dict[str, np.ndarray] = {}
    for fid in request.file_ids:
        f = _get_file(session, fid)
        data = _resolve_channel(f, request.channel)
        # Crop per file against its own time axis: files in a comparison can
        # have different sampling rates and durations, so a shared sample
        # index would not describe the same window in each.
        data, _ = _crop_if_requested(data, f.time64, request.t_start, request.t_end)
        groups[f.filename] = data

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
def run_msd(
    request: MSDRequest, principal: Principal = Depends(get_current_principal)
):
    """Mean-squared displacement via FFT cross-correlation (port of msd*.m)."""
    from salafleezers.analysis.stats import msd_fft

    session = _get_session(request.session_id, principal)
    f = _get_file(session, request.file_id)
    data = _resolve_channel(f, request.channel)
    time = f.time64
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
