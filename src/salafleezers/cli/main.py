"""Command-line interface for the SalaFleezer processing pipeline.

Entry point registered as ``sfz`` in pyproject.toml.

Sub-commands:
  sfz inspect   <dat_file>   — print header metadata
  sfz calibrate <dat_file>   — Lorentzian calibration
  sfz process   <txt_file>   — batch-process a set of data files
  sfz stepfind  <data_file>  — Kalafut-Visscher or HMM step detection
  sfz wlc-fit   <data_file>  — extensible WLC fit to F-x curve
  sfz velocity  <data_file>  — velocity distribution from step data
  sfz pwd       <data_file>  — pairwise-distance histogram
  sfz gui                    — launch the web GUI (requires [gui] extra)
"""

from __future__ import annotations

import json
import sys
import time
import tomllib
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional

import numpy as np
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint


class _SaveFormat(str, Enum):
    hdf5 = "hdf5"
    npz = "npz"
    mat = "mat"


class _Algorithm(str, Enum):
    kv = "kv"
    hmm = "hmm"


class _WLCMethod(str, Enum):
    basic = "basic"
    marko_siggia = "marko_siggia"
    bouchiat = "bouchiat"

from salafleezers.constants import (
    BEAD_RADIUS_NM,
    CAL_FMIN_HZ,
    CAL_N_ALIAS,
    CAL_NBIN,
)
from salafleezers.processing.pipeline import ProcessingOptions

app = typer.Typer(
    name="sfz",
    help="SalaFleezer optical tweezers data processing tool.",
    add_completion=True,
    rich_markup_mode="markdown",
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True, style="bold red")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    """Load sfz.toml from the current directory or any parent."""
    for d in [Path.cwd(), *Path.cwd().parents]:
        cfg = d / "sfz.toml"
        if cfg.exists():
            with open(cfg, "rb") as f:
                return tomllib.load(f)
    return {}


def _cfg(key: str, default):
    """Return value from sfz.toml [defaults] section, or *default*."""
    return _load_config().get("defaults", {}).get(key, default)


def _resolve(cli_val, cfg_key: str, default):
    """Three-tier precedence: CLI flag > sfz.toml > built-in default."""
    if cli_val is not None:
        return cli_val
    return _cfg(cfg_key, default)


def _make_opts(
    ra_a: float | None,
    ra_b: float | None,
    fmin: float | None,
    fmax: float | None,
    n_bin: int | None,
    n_alias: int | None,
    no_normalize: bool,
    save_format: str,
    verbose: bool,
) -> ProcessingOptions:
    return ProcessingOptions(
        ra_a=_resolve(ra_a, "ra_a", BEAD_RADIUS_NM),
        ra_b=_resolve(ra_b, "ra_b", BEAD_RADIUS_NM),
        f_min=_resolve(fmin, "fmin", CAL_FMIN_HZ),
        f_max=fmax,
        n_bin=_resolve(n_bin, "n_bin", CAL_NBIN),
        n_alias=_resolve(n_alias, "n_alias", CAL_N_ALIAS),
        normalize=not no_normalize,
        save_format=save_format,
        verbose=verbose,
    )


# ---------------------------------------------------------------------------
# Shared option types
# ---------------------------------------------------------------------------

_OPT_RA_A = Annotated[Optional[float], typer.Option(
    "--ra-a", help=f"Bead radius for trap A (nm) [default: {BEAD_RADIUS_NM}]"
)]
_OPT_RA_B = Annotated[Optional[float], typer.Option(
    "--ra-b", help=f"Bead radius for trap B (nm) [default: {BEAD_RADIUS_NM}]"
)]
_OPT_FMIN = Annotated[Optional[float], typer.Option(
    "--fmin", help=f"Calibration fit lower frequency (Hz) [default: {CAL_FMIN_HZ}]"
)]
_OPT_FMAX = Annotated[Optional[float], typer.Option(
    "--fmax", help="Calibration fit upper frequency (Hz); default = Nyquist"
)]
_OPT_NBIN = Annotated[Optional[int], typer.Option(
    "--n-bin", help=f"Points per spectral bin [default: {CAL_NBIN}]"
)]
_OPT_NALIAS = Annotated[Optional[int], typer.Option(
    "--n-alias", help=f"Lorentzian aliasing order [default: {CAL_N_ALIAS}]"
)]


# ---------------------------------------------------------------------------
# sfz inspect
# ---------------------------------------------------------------------------

@app.command("inspect")
def inspect(
    dat_file: Annotated[Path, typer.Argument(help=".dat file to inspect")],
    json_out: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
    """Print the header metadata of a *.dat* file."""
    from salafleezers.io.reader import read_header

    if not dat_file.exists():
        err_console.print(f"File not found: {dat_file}")
        raise typer.Exit(1)

    meta, cmt, _ = read_header(dat_file)

    display = {k: v for k, v in meta.items() if k != "hdr"}
    if cmt.strip():
        display["comment"] = cmt.strip()
    # Convert numpy types to plain Python for JSON
    display = {k: (v.tolist() if hasattr(v, "tolist") else v) for k, v in display.items()}

    if json_out:
        rprint(json.dumps({"file": str(dat_file), "metadata": display}, indent=2))
        return

    table = Table(title=f"[bold]{dat_file.name}[/bold]", show_header=True)
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value")
    for k, v in display.items():
        if k == "initMHz":
            v = f"[{', '.join(f'{x:.2f}' for x in (v if hasattr(v, '__iter__') else [v]))}]"
        table.add_row(str(k), str(v))
    console.print(table)


# ---------------------------------------------------------------------------
# sfz calibrate
# ---------------------------------------------------------------------------

@app.command("calibrate")
def calibrate(
    dat_file: Annotated[Path, typer.Argument(help=".dat file to calibrate")],
    plot: Annotated[bool, typer.Option("--plot", help="Show power spectrum plot")] = False,
    json_out: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    ra_a: _OPT_RA_A = None,
    ra_b: _OPT_RA_B = None,
    fmin: _OPT_FMIN = None,
    fmax: _OPT_FMAX = None,
    n_bin: _OPT_NBIN = None,
    n_alias: _OPT_NALIAS = None,
    no_normalize: Annotated[bool, typer.Option("--no-normalize", help="Skip QPD sum normalization")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
):
    """Calibrate a single *.dat* file (power spectrum + Lorentzian fit)."""
    from salafleezers.calibration.fit import calibrate as _cal
    from salafleezers.io.reader import read_dat

    if not dat_file.exists():
        err_console.print(f"File not found: {dat_file}")
        raise typer.Exit(1)

    opts = _make_opts(ra_a, ra_b, fmin, fmax, n_bin, n_alias,
                      no_normalize, "hdf5", verbose)
    dat = read_dat(dat_file, skip_fl=True)
    fs = float(dat.meta["Fs"])

    axes = [("AX", "AS"), ("BX", "BS"), ("AY", "AS"), ("BY", "BS")]
    results: dict = {}

    with console.status(f"Calibrating [bold]{dat_file.name}[/bold]  (Fs = {fs:.0f} Hz)…"):
        for det, sum_ch in axes:
            if det not in dat.channels:
                continue
            raw = dat.channels[det].astype(float)
            s = dat.channels[sum_ch].astype(float)
            data = (raw / s) if opts.normalize and s.any() else raw
            f_max_eff = opts.f_max or fs / 2
            result = _cal(
                data, fs,
                ra=opts.ra_a if det.startswith("A") else opts.ra_b,
                kt=opts.kt, wv=opts.wv,
                f_min=opts.f_min, f_max=f_max_eff,
                n_bin=opts.n_bin, n_alias=opts.n_alias,
                name=det,
            )
            results[det] = result

    if json_out:
        out = {
            det: {"fc": r.fc, "alpha": r.alpha, "kappa": r.kappa,
                  "D": r.D, "drag": r.drag}
            for det, r in results.items()
        }
        rprint(json.dumps(out, indent=2))
    else:
        table = Table(
            title=f"[bold]{dat_file.name}[/bold]  Fs = {fs:.0f} Hz",
            show_header=True,
        )
        table.add_column("Channel", style="cyan")
        table.add_column("fc (Hz)", justify="right")
        table.add_column("α (nm/V)", justify="right")
        table.add_column("κ (pN/nm)", justify="right")
        for det, r in results.items():
            table.add_row(det, f"{r.fc:.1f}", f"{r.alpha:.2f}", f"{r.kappa:.4f}")
        console.print(table)

    if plot:
        _plot_calibration(results)


def _plot_calibration(results: dict) -> None:
    try:
        import matplotlib.pyplot as plt
        from salafleezers.calibration.lorentzian import lorentzian_pure
    except ImportError:
        err_console.print(
            "matplotlib not installed — add the [gui] extra: "
            "uv sync --extra gui"
        )
        return

    n_axes = len(results)
    fig, axes_arr = plt.subplots(1, n_axes, figsize=(5 * n_axes, 4))
    if n_axes == 1:
        axes_arr = [axes_arr]
    for ax_plot, (det, res) in zip(axes_arr, results.items()):
        ax_plot.loglog(res.F_full, res.P_full, ".", color="0.7", ms=2, label="data")
        f_model = np.geomspace(res.F_fit[0], res.F_fit[-1], 300)
        fs_est = res.F_fit[-1] * 2
        P_model = lorentzian_pure(res.fit_params, f_model, fs_est)
        ax_plot.loglog(f_model, P_model, "r-", lw=1.5,
                       label=f"fit  fc={res.fc:.0f} Hz")
        ax_plot.set_xlabel("Frequency (Hz)")
        ax_plot.set_ylabel("PSD (V²/Hz)")
        ax_plot.set_title(f"{det}  α={res.alpha:.1f} nm/V  κ={res.kappa:.4f} pN/nm")
        ax_plot.legend(fontsize=8)
    plt.tight_layout()
    plt.show()


# ---------------------------------------------------------------------------
# sfz process
# ---------------------------------------------------------------------------

@app.command("process")
def process(
    txt_file: Annotated[Path, typer.Argument(help="Batch .txt file")],
    data_dir: Annotated[Optional[Path], typer.Option("--data-dir", help="Directory containing .dat files")] = None,
    output_dir: Annotated[Optional[Path], typer.Option("--output-dir", help="Output directory")] = None,
    json_out: Annotated[bool, typer.Option("--json", help="Output NDJSON progress events")] = False,
    ra_a: _OPT_RA_A = None,
    ra_b: _OPT_RA_B = None,
    fmin: _OPT_FMIN = None,
    fmax: _OPT_FMAX = None,
    n_bin: _OPT_NBIN = None,
    n_alias: _OPT_NALIAS = None,
    no_normalize: Annotated[bool, typer.Option("--no-normalize")] = False,
    save_format: Annotated[_SaveFormat, typer.Option("--save-format", help="Output file format")] = _SaveFormat.hdf5,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
):
    """Batch-process files listed in a *.txt* batch file.

    **Batch file format** (matches AProcessDataV2.m):

    ```
    Line 1: YYMMDD  (date string, e.g. 230415)
    Line 2+: dat_num  off_num  cal_num  [comment]
    ```
    """
    from salafleezers.processing.pipeline import process_one
    from salafleezers.io.writer import save

    if not txt_file.exists():
        err_console.print(f"File not found: {txt_file}")
        raise typer.Exit(1)

    opts = _make_opts(ra_a, ra_b, fmin, fmax, n_bin, n_alias,
                      no_normalize, save_format, verbose)

    lines = txt_file.read_text().splitlines()
    lines = [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]
    if not lines:
        err_console.print("Batch file is empty.")
        raise typer.Exit(1)

    mmddyy = lines[0].strip()
    triplets: list[tuple[int, int, int, str]] = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 3:
            continue
        triplets.append((
            int(parts[0]), int(parts[1]), int(parts[2]),
            " ".join(parts[3:]) if len(parts) > 3 else "",
        ))

    dat_dir = data_dir or txt_file.parent
    out_dir = output_dir or dat_dir

    if not json_out:
        console.print(
            Panel(
                f"Processing [bold]{len(triplets)}[/bold] file(s) from "
                f"[cyan]{dat_dir}[/cyan] ([yellow]{mmddyy}[/yellow])\n"
                f"Output → [cyan]{out_dir}[/cyan]  format=[green]{opts.save_format}[/green]",
                title="sfz process",
            )
        )

    errors: list[str] = []
    t0 = time.perf_counter()

    for dat_n, off_n, cal_n, comment in triplets:
        stem = f"ForceExtension{mmddyy}_{dat_n:03d}"
        if comment and verbose and not json_out:
            console.print(f"  [dim]{comment}[/dim]")
        try:
            result = process_one(dat_dir, (dat_n, off_n, cal_n), mmddyy, opts)
            saved = save(out_dir / stem, result.to_dict(), fmt=opts.save_format)
            if json_out:
                rprint(json.dumps({"status": "ok", "file": str(saved)}))
            else:
                console.print(f"  [[green]{dat_n:03d}[/green]] → {saved.name}")
        except Exception as exc:
            msg = f"[{dat_n:03d}] {exc}"
            errors.append(msg)
            if json_out:
                rprint(json.dumps({"status": "error", "file": stem, "error": str(exc)}))
            else:
                err_console.print(f"  ERROR {msg}")

    elapsed = time.perf_counter() - t0
    if not json_out:
        status = "[red]with errors[/red]" if errors else "[green]OK[/green]"
        console.print(f"\nDone in {elapsed:.1f}s  {status}")
    if errors:
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# sfz stepfind
# ---------------------------------------------------------------------------

@app.command("stepfind")
def stepfind(
    data_file: Annotated[Path, typer.Argument(help="Processed HDF5/npz file")],
    channel: Annotated[str, typer.Option("--channel", "-c", help="Channel to analyse")] = "extension",
    algorithm: Annotated[_Algorithm, typer.Option("--algorithm", "-a", help="Detection algorithm")] = _Algorithm.kv,
    pen_factor: Annotated[float, typer.Option("--pen-factor", help="Penalty factor (KV)")] = 2.0,
    n_states: Annotated[int, typer.Option("--n-states", help="Number of HMM states")] = 2,
    json_out: Annotated[bool, typer.Option("--json")] = False,
):
    """Detect steps in a processed data file."""
    data_file = _load_processed(data_file)
    x = _get_channel(data_file, channel)
    time_arr = data_file.get("time", np.arange(len(x)))

    if algorithm == "kv":
        from salafleezers.analysis.stepfind.kv import find_steps
        result = find_steps(x, time=time_arr, pen_factor=pen_factor)
        out = {
            "algorithm": "kv",
            "n_steps": result.n_steps,
            "step_positions": result.step_positions.tolist(),
            "step_times": result.step_times.tolist(),
            "levels": result.levels.tolist(),
            "chi2": result.chi2,
        }
    else:
        from salafleezers.analysis.stepfind.hmm import find_steps
        result = find_steps(x, n_states=n_states)
        from salafleezers.analysis.stepfind.hmm import hmm_to_steps
        steps = hmm_to_steps(result)
        out = {
            "algorithm": "hmm",
            "n_states": result.n_states,
            "step_positions": steps.tolist(),
            "means": result.means.tolist(),
            "stds": result.stds.tolist(),
            "log_likelihood": result.log_likelihood,
        }

    if json_out:
        rprint(json.dumps(out, indent=2))
    else:
        _print_stepfind(out, algorithm)


def _print_stepfind(out: dict, algorithm: str) -> None:
    n = out.get("n_steps") or len(out.get("step_positions", []))
    console.print(f"\n[bold]Step detection ({algorithm.upper()})[/bold]: "
                  f"[green]{n}[/green] step(s) found")
    if algorithm == "kv" and out.get("step_times"):
        table = Table()
        table.add_column("#", justify="right", style="cyan")
        table.add_column("Time (s)", justify="right")
        table.add_column("Level before", justify="right")
        table.add_column("Level after", justify="right")
        levels = out["levels"]
        for i, t in enumerate(out["step_times"]):
            table.add_row(str(i + 1), f"{t:.3f}", f"{levels[i]:.2f}", f"{levels[i+1]:.2f}")
        console.print(table)


# ---------------------------------------------------------------------------
# sfz wlc-fit
# ---------------------------------------------------------------------------

@app.command("wlc-fit")
def wlc_fit(
    data_file: Annotated[Path, typer.Argument(help="Processed HDF5/npz file")],
    method: Annotated[_WLCMethod, typer.Option("--method")] = _WLCMethod.basic,
    p0: Annotated[float, typer.Option("--p0", help="Initial persistence length (nm)")] = 50.0,
    s0: Annotated[float, typer.Option("--s0", help="Initial stretch modulus (pN)")] = 900.0,
    json_out: Annotated[bool, typer.Option("--json")] = False,
):
    """Fit a WLC model to a force-extension curve."""
    from salafleezers.analysis.wlc import fit_force_ext

    dat = _load_processed(data_file)
    F = _get_channel(dat, "force")
    x = _get_channel(dat, "extension")

    result = fit_force_ext(F, x, P0=p0, S0=s0, method=method)

    out = {
        "P_nm": result.P,
        "Lc_nm": result.Lc,
        "S_pN": result.S,
        "x_offset_nm": result.x_offset,
        "F_offset_pN": result.F_offset,
        "chi2": result.chi2,
        "method": result.method,
    }

    if json_out:
        rprint(json.dumps(out, indent=2))
    else:
        table = Table(title="WLC Fit Result")
        table.add_column("Parameter", style="cyan")
        table.add_column("Value", justify="right")
        table.add_row("Persistence length P", f"{result.P:.2f} nm")
        table.add_row("Contour length Lc", f"{result.Lc:.1f} nm")
        table.add_row("Stretch modulus S", f"{result.S:.0f} pN")
        table.add_row("Extension offset", f"{result.x_offset:.1f} nm")
        table.add_row("Force offset", f"{result.F_offset:.3f} pN")
        table.add_row("χ² residual", f"{result.chi2:.4f}")
        console.print(table)


# ---------------------------------------------------------------------------
# sfz velocity
# ---------------------------------------------------------------------------

@app.command("velocity")
def velocity(
    data_file: Annotated[Path, typer.Argument(help="Processed HDF5/npz file")],
    channel: Annotated[str, typer.Option("--channel")] = "extension",
    window: Annotated[int, typer.Option("--window", help="SG window (samples)")] = 21,
    polyorder: Annotated[int, typer.Option("--polyorder", help="SG polynomial order")] = 2,
    json_out: Annotated[bool, typer.Option("--json")] = False,
):
    """Compute velocity distribution from a processed data file."""
    from salafleezers.analysis.velocity import savgol_velocity, velocity_histogram

    dat = _load_processed(data_file)
    x = _get_channel(dat, channel)
    t = dat.get("time", np.arange(len(x)) / 1000.0)

    v = savgol_velocity(x, t, window=window, polyorder=polyorder)
    hist = velocity_histogram(v)

    out = {
        "v_centers": hist["v_centers"].tolist(),
        "counts": hist["counts"].tolist(),
        "mean_velocity_nm_s": float(np.mean(v[np.isfinite(v)])),
    }
    if json_out:
        rprint(json.dumps(out, indent=2))
    else:
        console.print(
            f"Mean velocity: [bold]{out['mean_velocity_nm_s']:.1f}[/bold] nm/s  "
            f"({len(v)} points)"
        )


# ---------------------------------------------------------------------------
# sfz pwd
# ---------------------------------------------------------------------------

@app.command("pwd")
def pwd(
    data_file: Annotated[Path, typer.Argument(help="Processed HDF5/npz file")],
    channel: Annotated[str, typer.Option("--channel")] = "extension",
    bins: Annotated[int, typer.Option("--bins")] = 200,
    json_out: Annotated[bool, typer.Option("--json")] = False,
):
    """Compute pairwise-distance histogram to identify step sizes."""
    from salafleezers.analysis.pwd import pairwise_distance

    dat = _load_processed(data_file)
    x = _get_channel(dat, channel)

    result = pairwise_distance(x, bins=bins)

    out = {
        "step_sizes_nm": result.step_sizes.tolist(),
        "peak_heights": result.peak_heights.tolist(),
        "bin_centers": result.bin_centers.tolist(),
        "pwd_counts": result.pwd_counts.tolist(),
    }
    if json_out:
        rprint(json.dumps(out, indent=2))
    else:
        console.print(
            f"\nPWD analysis: [green]{len(result.step_sizes)}[/green] peak(s) found"
        )
        if len(result.step_sizes) > 0:
            table = Table()
            table.add_column("Peak #", style="cyan")
            table.add_column("Step size (nm)", justify="right")
            table.add_column("Height", justify="right")
            for i, (s, h) in enumerate(zip(result.step_sizes, result.peak_heights)):
                table.add_row(str(i + 1), f"{s:.2f}", f"{h:.1f}")
            console.print(table)


# ---------------------------------------------------------------------------
# sfz gui
# ---------------------------------------------------------------------------

def _print_security_posture(
    *, data_root: Path | None, allow_origin: list[str] | None, rate_limit: int | None,
) -> None:
    """Summarize the effective security-relevant config at startup.

    Nothing here is secret (never prints the auth token itself, only
    whether one is configured) -- the point is to make the posture visible
    rather than buried in unset env vars, especially for anyone about to
    run this behind a reverse proxy for a shared lab.
    """
    import os

    auth_on = bool(os.environ.get("SFZ_AUTH_TOKEN"))
    max_body = os.environ.get("SFZ_MAX_BODY_BYTES")
    max_sessions = os.environ.get("SFZ_MAX_SESSIONS")
    session_ttl = os.environ.get("SFZ_SESSION_TTL_SECONDS")

    table = Table(title="[bold]Security posture[/bold]", show_header=False)
    table.add_column("Setting", style="cyan", no_wrap=True)
    table.add_column("Value")

    table.add_row(
        "Auth",
        "[green]bearer token required[/green]" if auth_on
        else "[yellow]disabled (local-only)[/yellow]",
    )
    table.add_row(
        "File-open data root",
        f"[green]{data_root}[/green]" if data_root is not None
        else "[yellow]unrestricted (any server-readable path)[/yellow]",
    )
    table.add_row(
        "CORS origins",
        ", ".join(allow_origin) if allow_origin else "built-in localhost defaults",
    )
    table.add_row(
        "Rate limit",
        f"{rate_limit} req/min per client" if rate_limit else "disabled",
    )
    table.add_row("Max request body", f"{max_body} bytes" if max_body else "50 MB (default)")
    table.add_row(
        "Session cap / TTL",
        f"{max_sessions or 50} sessions / {session_ttl or '14400'}s",
    )
    console.print(table)

    if not auth_on and (allow_origin or data_root or rate_limit):
        console.print(
            "[yellow]Note:[/yellow] auth is disabled -- these settings only matter "
            "once SFZ_AUTH_TOKEN is also set for a shared deployment.\n"
        )


@app.command("gui")
def gui(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8765,
    no_browser: Annotated[bool, typer.Option("--no-browser")] = False,
    data_root: Annotated[
        Optional[Path],
        typer.Option(
            "--data-root",
            help="Confine /api/files/open to this directory tree. "
                 "Unset = unrestricted (fine for local single-user use).",
        ),
    ] = None,
    allow_origin: Annotated[
        Optional[list[str]],
        typer.Option(
            "--allow-origin",
            help="CORS origin to allow (repeatable). Unset = built-in "
                 "localhost/127.0.0.1 defaults.",
        ),
    ] = None,
    rate_limit: Annotated[
        Optional[int],
        typer.Option(
            "--rate-limit",
            help="Max requests per client IP per minute. Unset = unlimited.",
        ),
    ] = None,
    log_level: Annotated[
        str, typer.Option("--log-level", help="Python logging level.")
    ] = "warning",
):
    """Launch the interactive web GUI (requires `sfz[gui]` extra).

    Auth is controlled by the ``SFZ_AUTH_TOKEN`` env var (not a CLI flag,
    so the token never appears in shell history or ``ps`` output). See
    ``--data-root``/``--allow-origin``/``--rate-limit`` for hardening a
    shared-server deployment.
    """
    import logging
    import os

    logging.basicConfig(
        level=log_level.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    try:
        from salafleezers.web.app import create_app  # type: ignore[import]
    except ImportError:
        err_console.print(
            "[bold red]GUI dependencies not installed.[/bold red]\n"
            "Install with:  [green]uv sync --extra gui[/green]"
        )
        raise typer.Exit(1)

    import uvicorn  # type: ignore[import]
    import webbrowser

    if data_root is not None:
        os.environ["SFZ_DATA_ROOT"] = str(data_root)
    if rate_limit is not None:
        os.environ["SFZ_RATE_LIMIT_PER_MINUTE"] = str(rate_limit)

    _print_security_posture(
        data_root=data_root, allow_origin=allow_origin, rate_limit=rate_limit
    )

    web_app = create_app(allow_origins=allow_origin)
    url = f"http://{host}:{port}"
    if not no_browser:
        webbrowser.open(url)
    console.print(f"[bold]sfz gui[/bold]  listening on [link={url}]{url}[/link]")
    uvicorn.run(web_app, host=host, port=port, log_level=log_level)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_processed(path: Path) -> dict:
    """Load a processed HDF5 or npz file into a plain dict of arrays."""
    if not path.exists():
        err_console.print(f"File not found: {path}")
        raise typer.Exit(1)

    suffix = path.suffix.lower()
    if suffix in (".h5", ".hdf5", ".hdf"):
        import h5py
        with h5py.File(path, "r") as f:
            return {k: np.array(v) for k, v in f.items()}
    elif suffix == ".npz":
        return dict(np.load(path, allow_pickle=False))
    else:
        err_console.print(f"Unsupported format: {suffix}")
        raise typer.Exit(1)


def _get_channel(dat: dict, name: str) -> np.ndarray:
    """Retrieve a named channel from a loaded data dict."""
    aliases = {
        "extension": ["extension", "Extension", "ext"],
        "force": ["force", "Force", "F"],
        "time": ["time", "Time", "t"],
    }
    candidates = aliases.get(name, [name])
    for key in candidates:
        if key in dat:
            return np.asarray(dat[key], dtype=np.float64)
    err_console.print(
        f"Channel '{name}' not found.  Available: {list(dat.keys())}"
    )
    raise typer.Exit(1)
