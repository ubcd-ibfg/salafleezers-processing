"""Run the whole RNAP nucleosome-crossing workflow end to end.

Reproduces the analysis half of the MATLAB how-to — `procFranp2` alignment,
`procFranp3` per-condition analysis, `ezFactPlot` residence-time histograms and
`procFran_PFVv2` pause-free velocities — over a set of conditions.

Two input modes:

*   ``--conditions DIR`` reads processed traces from a directory of
    per-condition subfolders, exactly the layout the how-to asks for::

        Boltz V1/
          a Just Ruler/    ForceExtension260625_103.h5  ...
          ab No nuc/       ...
          b Nuc/           ...

    The leading letters order the conditions; the rest is the condition name.

*   ``--synthetic`` simulates two conditions with known ruler geometry instead,
    which is how to check the analysis itself when no ruler data is at hand.

Usage
-----
    uv run python examples/rnap_nuc_crossing/run_analysis.py --synthetic
    uv run python examples/rnap_nuc_crossing/run_analysis.py --conditions "Boltz V1"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from ruler import (
    AlignResult,
    RulerAlignOptions,
    align_to_ruler,
    contour_bp,
    crossed,
    pfv_by_region,
    residence_time_histogram,
)

# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_processed(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Read (time, force, extension) from one `sfz process` output file."""
    if path.suffix == ".h5":
        import h5py
        with h5py.File(path, "r") as f:
            return (np.asarray(f["time"]), np.asarray(f["force"]),
                    np.asarray(f["extension"]))
    if path.suffix == ".npz":
        d = np.load(path)
        return d["time"], d["force"], d["extension"]
    if path.suffix == ".mat":
        from scipy.io import loadmat
        d = loadmat(path)
        return (d["time"].ravel(), d["force"].ravel(), d["extension"].ravel())
    raise ValueError(f"unsupported file type: {path.suffix}")


def load_conditions(root: Path) -> dict[str, list[tuple]]:
    """Load every condition subfolder of *root*, in alphabetical order."""
    conditions: dict[str, list[tuple]] = {}
    for sub in sorted(p for p in root.iterdir() if p.is_dir()):
        traces = []
        for f in sorted(sub.glob("*.h5")) + sorted(sub.glob("*.npz")) + \
                sorted(sub.glob("*.mat")):
            try:
                traces.append(load_processed(f))
            except Exception as exc:
                print(f"  {f.name}: skipped ({exc})", file=sys.stderr)
        if traces:
            conditions[sub.name] = traces
    return conditions


def synthetic_conditions(opts: RulerAlignOptions) -> dict[str, list[tuple]]:
    from synth import simulate_condition
    return {
        "a Just Ruler": simulate_condition(8, cross_fraction=1.0, opts=opts, seed=1,
                                           velocity_bp_s=20.0, ruler_pause_s=6.0,
                                           nuc_pause_s=2.0),
        "b Nuc": simulate_condition(10, cross_fraction=0.5, opts=opts, seed=2,
                                    velocity_bp_s=20.0, ruler_pause_s=6.0,
                                    nuc_pause_s=15.0),
    }


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyse_condition(
    name: str,
    traces: list[tuple],
    opts: RulerAlignOptions,
) -> list[AlignResult]:
    """Convert to contour length and align every trace of one condition."""
    results = []
    for i, (time, force, extension) in enumerate(traces):
        bp = contour_bp(force, extension)
        r = align_to_ruler(time, bp, opts)
        results.append(r)
        status = (f"scale={r.scale:.3f} pauses={r.n_matched} R={r.resultant:.2f} "
                  f"rms={r.rms_residual_bp:.1f}bp max={r.max_bp:.0f}bp "
                  f"{'CROSSED' if crossed(r, opts) else 'stalled'}") if r.ok \
            else f"not aligned ({r.reason})"
        print(f"  [{name}] trace {i:2d}: {status}")
    return results


def report(name: str, results: list[AlignResult], opts: RulerAlignOptions) -> None:
    aligned = [r for r in results if r.ok]
    crossers = [r for r in aligned if crossed(r, opts)]
    print(f"\n{name}")
    print(f"  aligned          : {len(aligned)}/{len(results)}")
    if not aligned:
        return
    print(f"  crossed nucleosome: {len(crossers)}/{len(aligned)} "
          f"({100 * len(crossers) / len(aligned):.0f}%)")

    pfvs = {r: [] for r in ("ruler (naked DNA)", "nucleosome")}
    pause_frac = {r: [] for r in pfvs}
    for r in aligned:
        for p in pfv_by_region(r, opts):
            if np.isfinite(p.velocity_bp_s):
                pfvs[p.region].append(p.velocity_bp_s)
                pause_frac[p.region].append(p.pause_fraction)
    for region, vals in pfvs.items():
        if vals:
            print(f"  pause-free velocity, {region:18s}: {np.median(vals):6.2f} bp/s "
                  f" (paused {100 * np.median(pause_frac[region]):.0f}% of the time, "
                  f"n={len(vals)} traces)")

    rth = residence_time_histogram(results, bin_bp=10.0,
                                   range_bp=(0.0, opts.cross_bp + 200), opts=opts)
    ruler = (rth.centers_bp >= opts.start) & (rth.centers_bp < opts.ruler_end_bp)
    nuc = (rth.centers_bp >= opts.ruler_end_bp) & (rth.centers_bp < opts.cross_bp)
    print(f"  residence time, ruler region     : {rth.mean_s[ruler].sum():6.1f} s")
    print(f"  residence time, nucleosome region: {rth.mean_s[nuc].sum():6.1f} s")


def save_rth_plot(
    per_condition: dict[str, list[AlignResult]],
    opts: RulerAlignOptions,
    out: Path,
    only_crossed: bool = True,
) -> None:
    """Save the residence-time histogram figure — the `ezFactPlot` equivalent."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax_rth, ax_ccdf) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    for name, results in per_condition.items():
        rth = residence_time_histogram(results, bin_bp=10.0,
                                       range_bp=(0.0, opts.cross_bp + 200),
                                       only_crossed=only_crossed, opts=opts)
        if rth.n_traces == 0:
            continue
        label = f"{name} (n={rth.n_traces})"
        ax_rth.plot(rth.centers_bp, rth.mean_s, lw=1.2, label=label)
        ax_rth.fill_between(rth.centers_bp, rth.mean_s - rth.sem_s,
                            rth.mean_s + rth.sem_s, alpha=0.25)
        ax_ccdf.plot(rth.centers_bp, rth.ccdf, lw=1.2, label=label)

    for ax in (ax_rth, ax_ccdf):
        ax.axvspan(opts.start, opts.ruler_end_bp, color="0.9", zorder=0)
        ax.axvspan(opts.ruler_end_bp, opts.cross_bp, color="orange",
                   alpha=0.15, zorder=0)
        for x in opts.expected_pauses_bp:
            ax.axvline(x, color="0.7", lw=0.5, ls=":", zorder=0)
        ax.legend(fontsize=8)

    ax_rth.set_ylabel("residence time (s / 10 bp)")
    ax_rth.set_title("Residence-time histogram — grey = ruler, orange = nucleosome")
    ax_ccdf.set_ylabel("fraction remaining")
    ax_ccdf.set_xlabel("position from stall site (bp)")
    ax_ccdf.set_title("CCDF")
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    print(f"\nwrote {out}")


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--conditions", type=Path,
                     help="folder of per-condition subfolders of processed traces")
    src.add_argument("--synthetic", action="store_true",
                     help="simulate two conditions with known ruler geometry")
    ap.add_argument("--start", type=int, default=350,
                    help="stall site to first repeat, bp")
    ap.add_argument("--nrep", type=int, default=8, help="number of ruler repeats")
    ap.add_argument("--per", type=int, default=64, help="repeat length, bp")
    ap.add_argument("--pauloc", type=int, default=59,
                    help="pause position in repeat, bp")
    ap.add_argument("--plot", type=Path, help="write the residence-time figure here")
    ap.add_argument("--all-traces", action="store_true",
                    help="include non-crossing traces (default: crossers only)")
    args = ap.parse_args()

    opts = RulerAlignOptions(start=args.start, nrep=args.nrep,
                             per=args.per, pauloc=args.pauloc)
    print(f"Ruler: {opts.nrep} x {opts.per} bp starting {opts.start} bp from the stall "
          f"site, pause at +{opts.pauloc}")
    print(f"Expected pauses (bp): {opts.expected_pauses_bp}")
    print(f"Nucleosome at {opts.ruler_end_bp:.0f} bp; crossed means reaching "
          f"{opts.cross_bp:.0f} bp\n")

    if args.synthetic:
        conditions = synthetic_conditions(opts)
    else:
        if not args.conditions.is_dir():
            print(f"not a directory: {args.conditions}", file=sys.stderr)
            return 1
        conditions = load_conditions(args.conditions)
        if not conditions:
            print(f"no condition subfolders with traces under {args.conditions}",
                  file=sys.stderr)
            return 1

    per_condition = {name: analyse_condition(name, traces, opts)
                     for name, traces in conditions.items()}
    for name, results in per_condition.items():
        report(name, results, opts)

    if args.plot:
        save_rth_plot(per_condition, opts, args.plot, only_crossed=not args.all_traces)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
