"""Command-line interface for the SalaFleezer processing pipeline.

Replaces DataOptsPopup.m (GUI) and AProcessDataV2.m (batch runner).

Entry point registered as ``sfz`` in pyproject.toml.

Sub-commands:
  sfz process  <txt_file>   — batch-process a set of data files
  sfz calibrate <dat_file>  — calibrate one file and optionally plot
  sfz inspect  <dat_file>   — print header metadata
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from salafleezers.constants import (
    BEAD_RADIUS_NM,
    CAL_FMIN_HZ,
    CAL_N_ALIAS,
    CAL_NBIN,
)
from salafleezers.processing.pipeline import ProcessingOptions


# ---------------------------------------------------------------------------
# Shared options
# ---------------------------------------------------------------------------

def _common_cal_options(fn):
    """Decorator that adds shared calibration options to a click command."""
    fn = click.option("--ra-a", default=BEAD_RADIUS_NM, show_default=True,
                      help="Bead radius for trap A (nm)")(fn)
    fn = click.option("--ra-b", default=BEAD_RADIUS_NM, show_default=True,
                      help="Bead radius for trap B (nm)")(fn)
    fn = click.option("--fmin", default=CAL_FMIN_HZ, show_default=True,
                      help="Calibration fit lower frequency (Hz)")(fn)
    fn = click.option("--fmax", default=None, type=float,
                      help="Calibration fit upper frequency (Hz); default = Nyquist")(fn)
    fn = click.option("--n-bin", default=CAL_NBIN, show_default=True,
                      help="Points per spectral bin")(fn)
    fn = click.option("--n-alias", default=CAL_N_ALIAS, show_default=True,
                      help="Lorentzian aliasing order")(fn)
    fn = click.option("--no-normalize", is_flag=True, default=False,
                      help="Skip QPD sum normalization")(fn)
    fn = click.option("--save-format",
                      type=click.Choice(["hdf5", "npz", "mat"]), default="hdf5",
                      show_default=True, help="Output file format")(fn)
    fn = click.option("--verbose", is_flag=True, default=False,
                      help="Print progress and calibration values")(fn)
    return fn


def _make_opts(**kwargs) -> ProcessingOptions:
    return ProcessingOptions(
        ra_a=kwargs.get("ra_a", BEAD_RADIUS_NM),
        ra_b=kwargs.get("ra_b", BEAD_RADIUS_NM),
        f_min=kwargs.get("fmin", CAL_FMIN_HZ),
        f_max=kwargs.get("fmax"),
        n_bin=kwargs.get("n_bin", CAL_NBIN),
        n_alias=kwargs.get("n_alias", CAL_N_ALIAS),
        normalize=not kwargs.get("no_normalize", False),
        save_format=kwargs.get("save_format", "hdf5"),
        verbose=kwargs.get("verbose", False),
    )


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option()
def cli():
    """SalaFleezer optical tweezers data processing tool."""


# ---------------------------------------------------------------------------
# sfz inspect
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("dat_file", type=click.Path(exists=True))
def inspect(dat_file: str):
    """Print the header metadata of a .dat file."""
    from salafleezers.io.reader import read_header

    path = Path(dat_file)
    meta, cmt, _ = read_header(path)

    click.echo(f"\nFile: {path.name}")
    click.echo("-" * 40)
    for k, v in meta.items():
        if k == "hdr":
            continue  # skip raw header array
        click.echo(f"  {k:20s}: {v}")
    if cmt.strip():
        click.echo(f"  {'comment':20s}: {cmt.strip()}")
    click.echo()


# ---------------------------------------------------------------------------
# sfz calibrate
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("dat_file", type=click.Path(exists=True))
@click.option("--plot", is_flag=True, default=False,
              help="Show power spectrum and Lorentzian fit")
@_common_cal_options
def calibrate_cmd(dat_file: str, plot: bool, **kwargs):
    """Calibrate a single .dat file (power spectrum + Lorentzian fit)."""
    from salafleezers.calibration.fit import calibrate as _cal
    from salafleezers.calibration.power_spectrum import compute_power_spectrum, bin_spectrum
    from salafleezers.io.reader import read_dat

    opts = _make_opts(**kwargs)
    path = Path(dat_file)
    dat = read_dat(path, skip_fl=True)
    fs = float(dat.meta["Fs"])

    click.echo(f"\nCalibrating {path.name}  (Fs = {fs:.0f} Hz)")
    click.echo("-" * 50)

    axes = [("AX", "AS"), ("BX", "BS"), ("AY", "AS"), ("BY", "BS")]
    results = {}
    for det, sum_ch in axes:
        if det not in dat.channels:
            continue
        raw = dat.channels[det].astype(float)
        s = dat.channels[sum_ch].astype(float)
        data = (raw / s) if opts.normalize and s.any() else raw

        f_max = opts.f_max or fs / 2
        result = _cal(data, fs,
                      ra=opts.ra_a if det.startswith("A") else opts.ra_b,
                      kt=opts.kt, wv=opts.wv,
                      f_min=opts.f_min, f_max=f_max,
                      n_bin=opts.n_bin, n_alias=opts.n_alias,
                      name=det)
        results[det] = result
        click.echo(f"  {det}: fc = {result.fc:8.1f} Hz  |  alpha = {result.alpha:8.2f} nm/V  |  kappa = {result.kappa:.4f} pN/nm")

    if plot:
        _plot_calibration(results)


def _plot_calibration(results: dict):
    import matplotlib.pyplot as plt
    from salafleezers.calibration.lorentzian import lorentzian_pure
    import numpy as np

    n_axes = len(results)
    fig, axes_arr = plt.subplots(1, n_axes, figsize=(5 * n_axes, 4))
    if n_axes == 1:
        axes_arr = [axes_arr]

    for ax_plot, (det, res) in zip(axes_arr, results.items()):
        ax_plot.loglog(res.F_full, res.P_full, ".", color="0.7", ms=2, label="data")
        f_model = np.geomspace(res.F_fit[0], res.F_fit[-1], 300)
        fs_est = res.F_fit[-1] * 2
        P_model = lorentzian_pure(res.fit_params, f_model, fs_est)
        ax_plot.loglog(f_model, P_model, "r-", lw=1.5, label=f"fit  fc={res.fc:.0f} Hz")
        ax_plot.set_xlabel("Frequency (Hz)")
        ax_plot.set_ylabel("PSD (V²/Hz)")
        ax_plot.set_title(f"{det}  α={res.alpha:.1f} nm/V  κ={res.kappa:.4f} pN/nm")
        ax_plot.legend(fontsize=8)

    plt.tight_layout()
    plt.show()


# ---------------------------------------------------------------------------
# sfz process
# ---------------------------------------------------------------------------

@cli.command(name="process")
@click.argument("txt_file", type=click.Path(exists=True))
@click.option("--data-dir", default=None, type=click.Path(),
              help="Directory containing .dat files (default: same as txt_file)")
@click.option("--output-dir", default=None, type=click.Path(),
              help="Output directory (default: same as data-dir)")
@_common_cal_options
def process_cmd(txt_file: str, data_dir: str | None, output_dir: str | None, **kwargs):
    """Batch-process files listed in a txt batch file.

    TXT FILE FORMAT (matches AProcessDataV2.m):

    \b
    Line 1: YYMMDD  (date string, e.g. 230415)
    Line 2+: dat_num  off_num  cal_num  [comment]
    """
    from salafleezers.processing.pipeline import process_one
    from salafleezers.io.writer import save

    opts = _make_opts(**kwargs)
    txt_path = Path(txt_file)

    # Parse batch file
    lines = txt_path.read_text().splitlines()
    lines = [l.strip() for l in lines if l.strip() and not l.startswith("#")]
    if not lines:
        click.echo("Batch file is empty.", err=True)
        sys.exit(1)

    mmddyy = lines[0].strip()
    triplets: list[tuple[int, int, int, str]] = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 3:
            continue
        dat_n, off_n, cal_n = int(parts[0]), int(parts[1]), int(parts[2])
        comment = " ".join(parts[3:]) if len(parts) > 3 else ""
        triplets.append((dat_n, off_n, cal_n, comment))

    dat_dir = Path(data_dir) if data_dir else txt_path.parent
    out_dir = Path(output_dir) if output_dir else dat_dir

    click.echo(f"Processing {len(triplets)} file(s) from {dat_dir} ({mmddyy})")
    click.echo(f"Output → {out_dir}  format={opts.save_format}")

    for dat_n, off_n, cal_n, comment in triplets:
        if comment and opts.verbose:
            click.echo(f"\n--- {comment} ---")
        try:
            result = process_one(dat_dir, (dat_n, off_n, cal_n), mmddyy, opts)
            stem = f"ForceExtension{mmddyy}_{dat_n:03d}"
            saved = save(out_dir / stem, result.to_dict(), fmt=opts.save_format)
            click.echo(f"  [{dat_n:03d}] → {saved.name}")
        except Exception as exc:
            click.echo(f"  [{dat_n:03d}] ERROR: {exc}", err=True)

    click.echo("Done.")
