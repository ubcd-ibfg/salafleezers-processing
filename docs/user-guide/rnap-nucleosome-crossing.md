# RNAP nucleosome crossing with a molecular ruler

This walks the RNAP nucleosome-crossing-with-a-molecular-ruler workflow end to end with `sfz`.
It is the longest analysis chain in the lab, so it also doubles as a worked example of using
`sfz` beyond one-file-at-a-time commands.

## The experiment

An RNAP elongation complex is stalled at a defined site (e.g. on a U-less cassette). Downstream
of the stall site the template carries a **molecular ruler**: 8 tandem copies of a 64-bp repeat,
each containing a strong pause site. Past the ruler sits a **nucleosome**. Releasing the stall
lets the polymerase transcribe, and the tether lengthens step by step as it goes.

The ruler is what makes the measurement quantitative. The pause lattice has an exactly known
period, so the pauses act as an internal length standard: fitting the observed pause spacing to
the known 64 bp calibrates each trace's base-pair axis and locates the stall site as bp 0.
Every trace can then be put on a common axis and averaged, and the question — how long does the
polymerase spend in the nucleosome, how fast does it move, and does it get through at all —
becomes answerable across conditions.

## What `sfz` covers and what the example package adds

`sfz` covers the data-reduction half of this workflow completely: raw `.dat` files in, calibrated
force/extension traces out. The ruler-specific analysis half — alignment to the pause lattice,
residence-time histograms, pause-free velocity — has no equivalent in `salafleezers.analysis`,
so this guide ships it as a worked example built on top of the library, in
[`examples/rnap_nuc_crossing/`](#the-example-package).

!!! note "Setup"
    `uv sync` at the repo root is the whole setup — see [Installation](installation.md).

    On a fresh source checkout `uv sync` fails with `Forced include not found:
    frontend/dist`, because `pyproject.toml` embeds the built web GUI into the wheel. Either
    build the frontend (`cd frontend && npm ci && npm run build`) or, if you only want the CLI,
    create the directory so the build has something to include: `mkdir -p frontend/dist`.

---

## 1. Processing options

This workflow's data-reduction step uses:

| Option | Value used here | `sfz` equivalent |
| --- | --- | --- |
| Instrument/protocol | keyed off the file header | implicit — the reader reads `channelID` and the header directly |
| Convert to contour length | on | `contour_bp()` in the example (step 4) |
| Normalize by sum | on | `ProcessingOptions.normalize=True` (the default) |
| Bead radii | `500 nm`, `500 nm` | `--ra-a 500 --ra-b 500` (the default) |
| XWLC (P, S, kT, rise) | `50 nm`, `900 pN`, `4.14 pN·nm`, `0.34 nm/bp` | `contour_bp(p=50, s=900, kt=4.14, rise=0.34)` |
| Extension offset | `50 nm` | `ProcessingOptions(ext_offset=50)` |
| Trap conversion (X) | `133.1416 nm/MHz` | `constants.CONV_TRAP_X_NM_PER_MHZ` |
| Water viscosity | `0.97e-9` | `ProcessingOptions(wv=0.97e-9)` |
| Calibration sample rate | read from the calibration file's header | — |
| Lorentzian filtering | none | the only behaviour implemented |

!!! warning "Two of these are library-only"
    `sfz process` exposes `--ra-a`, `--ra-b`, `--fmin`, `--fmax`, `--n-bin`, `--n-alias`,
    `--no-normalize` and `--save-format`, but **not** `ext_offset` or `wv`. If your experiment
    needs a nonzero extension offset, drive the pipeline from Python instead:

    ```python
    from salafleezers.processing.pipeline import ProcessingOptions, process_batch

    opts = ProcessingOptions(ra_a=500, ra_b=500, ext_offset=50, wv=0.97e-9)
    process_batch("path/to/260625", "260625", [(103, 102, 73)], opts,
                  output_dir="processed/")
    ```

    The trap conversion constant is hard-coded at 133.1416 nm/MHz in `constants.py`. It is not
    currently an option — change the constant if your instrument's trap-position calibration
    differs.

## 2. Folder layout and the batch file

`sfz process` expects a `YYMMDD` folder per acquisition day, containing the `.dat` files and a
`YYMMDD.txt` listing `data offset cal` triplets — see [Batch files](batch-files.md).

Acquisition folders don't ship the `.txt`, and writing one by hand for a day with 180 files is
miserable. Every `.dat` header already records what kind of run it was, so the triplets can be
recovered:

| `datatype` | Meaning | Role |
| --- | --- | --- |
| 0 | regular data | the trace to process |
| 1 | calibration | the `cal` column |
| 2 | AOM raster scan | the `offset` column |
| 3 | MCL raster scan | stage scan — not used here |

`make_batch.py` classifies a folder and pairs each data file with the most recent preceding
offset and calibration run, which is the order the instrument acquires them in:

```bash
uv run python examples/rnap_nuc_crossing/make_batch.py "data/Datos Curso Biophysal/260625"
```

```text
  datatype 0 (data): 8 files
  datatype 1 (cal): 18 files
  datatype 2 (offset): 108 files
  datatype 3 (stage scan): 48 files
wrote 8 triplets -> data/Datos Curso Biophysal/260625/260625.txt
```

Check the result before trusting it — auto-pairing is a good default, not a substitute for the
lab notebook. If a tether was calibrated out of order, fix that line by hand.

## 3. Raw data → force and extension

`sfz process` takes one batch file; a shell loop covers the multi-day case:

```bash
for day in "data/Datos Curso Biophysal"/*/; do
  d=$(basename "$day")
  uv run sfz process "$day/$d.txt" --data-dir "$day" --output-dir processed/
done
```

```text
  [103] → ForceExtension260625_103.h5
  [114] → ForceExtension260625_114.h5
  ...
Done in 2.2s  OK
```

Output is one HDF5 file per trace, holding `time`, `force`, `extension` and the calibration
constants. Pass `--save-format mat` if you have downstream MATLAB scripts that need that format.

Before going further, look at a few traces — `sfz gui`, or `sfz inspect` and `sfz stepfind` for
a quick headless check. A trace that lost its tether is much easier to spot now than after
averaging.

## 4. Organise by condition

Sort the processed files into one folder per condition, named `[letters] [name]`, where the
leading letters set the plotting order:

```text
Boltz V1/
  a Just Ruler/
    ForceExtension260625_103.h5
    ForceExtension260625_114.h5
  ab No nuc/
    ...
  b Nuc/
    ...
```

## 5. Ruler geometry

The ruler's geometry is described by a small dataclass:

```python
from ruler import RulerAlignOptions

opts = RulerAlignOptions(
    start=350,    # stall site → first repeat, bp
    nrep=8,       # number of repeats
    per=64,       # repeat length, bp
    pauloc=59,    # pause position within a repeat, bp
)
opts.expected_pauses_bp   # array([409, 473, 537, 601, 665, 729, 793, 857])
opts.ruler_end_bp         # 862.0 — the nucleosome starts here
opts.cross_bp             # 1019.0 — reaching this counts as crossed
```

The same four numbers are `run_analysis.py` command-line flags (`--start`, `--nrep`, `--per`,
`--pauloc`), so a different construct doesn't need a code change.

## 6. Contour-length conversion

Converting bead-to-bead extension (nm) into template length (bp) removes the force-dependent
stretching of the tether and puts every trace in units of transcribed base pairs. `contour_bp`
inverts the same extensible-WLC that
[`analysis.wlc.xwlc_extension`](../physics/force-extension.md) applies:

\[
x = L_c\left(1 - \tfrac{1}{2}\sqrt{\tfrac{k_BT}{PF}} + \tfrac{F}{S}\right)
\quad\Longrightarrow\quad
\text{bp} = \frac{1}{h}\cdot\frac{x}{1 - \tfrac{1}{2}\sqrt{k_BT/PF} + F/S}
\]

with \(P=50\) nm, \(S=900\) pN, \(k_BT=4.14\) pN·nm and \(h=0.34\) nm/bp. Samples below 0.1 pN
come back as `NaN`: the WLC diverges at zero force and the conversion is meaningless there.

## 7. Alignment

This is the heart of the method. `align_to_ruler` works in three stages:

1. **Scale.** Step-find the trace, keep the plateaus that are long enough to be pauses, then
   find the scale factor that makes those pause positions most periodic at 64 bp. Formally it
   maximises the dwell-weighted circular resultant

    \[
    R(a) = \left|\frac{\sum_j w_j e^{2\pi i\,a x_j/\text{per}}}{\sum_j w_j}\right|
    \]

    over trial scales \(a\), which is 1 when every pause sits at the same lattice phase and near
    0 when they're scattered. This is a weighted periodogram: it uses all the pauses at once, so
    a few spurious plateaus picked up from the translocation ramps can't drag the fit the way a
    median of pause spacings can. The fitted scale absorbs error in the WLC parameters and in
    the trap calibration, both of which stretch the bp axis multiplicatively.

2. **Phase.** The phase of the resultant gives the lattice position modulo 64 bp, pinning the
   pauses to their known positions at sub-repeat precision.

3. **Repeat number.** Phase alone leaves the offset ambiguous by whole repeats. That is resolved
   by requiring the trace's first plateau — the stall site, where the polymerase sits before
   transcription starts — to land at bp 0.

Because the ruler pauses are periodic but the nucleosome pauses are not, and on a trace that
crosses the nucleosome pauses can outnumber the ruler ones, the fit iterates: fit on all pauses,
then refit using only the pauses that the first pass placed inside the ruler.

```python
from ruler import align_to_ruler, contour_bp, crossed

bp = contour_bp(force, extension)
result = align_to_ruler(time, bp, opts)

if result.ok:
    print(result.scale, result.n_matched, result.resultant, result.rms_residual_bp)
    print(result.bp)              # aligned trace, bp from the stall site
    print(crossed(result, opts))  # whether the trace crossed the nucleosome
```

### Two tuning adjustments for long transcription traces

Both are worth knowing about, because they affect any long translocation trace, not just this
assay.

**The step-finder's penalty needs rescaling.** `find_steps` builds its acceptance threshold
as `pen_factor * var(data) * ln(N)`. On a transcription trace `var(data)` is dominated by the
several-hundred-bp rise across the ruler, not by the noise, so the default `pen_factor=2` demands
enormous steps and finds only a handful. The example estimates the sample-to-sample noise from
the first difference (`var(diff)/2`, insensitive to any slow trend) and rescales, making the
effective threshold `pen_factor * σ_noise² * ln(N)` — which is what the Kalafut-Visscher
criterion is meant to be. See [Step-finding theory](../physics/step-finding.md).

**Pause detection has to be relative.** Step-finding carves the ramps *between* pauses into short
plateaus too, and those outnumber the real pauses. An absolute dwell threshold can't separate
them, because how long a ramp plateau lasts depends on that trace's transcription rate. So a
plateau counts as a pause only if it also lasts `pause_dwell_factor` (default 2.5) times the
median plateau dwell **of its own trace**.

### Alignment can and should fail

A trace with no ruler in it still produces a best-fit scale, so the fit has to be able to say no.
Two things give a spurious fit away, and both are checked:

- the resultant is below `min_resultant` (default 0.5) — the pauses weren't periodic at any scale;
- the fitted scale ran into the end of the search range instead of settling inside it.

Always check `result.ok` and look at `result.reason` on the failures. A condition where half the
traces don't align is telling you something about the data, not about the code.

## 8. Per-condition analysis

`run_analysis.py` does the whole chain over a folder of condition subfolders:

```bash
uv run python examples/rnap_nuc_crossing/run_analysis.py \
    --conditions "Boltz V1" --plot rth.png
```

It prints per-trace alignment diagnostics, then a per-condition summary — how many traces
aligned, what fraction crossed the nucleosome, pause-free velocities, and residence time in the
ruler and nucleosome regions — and writes the residence-time figure.

The **residence-time histogram** works by having each trace contribute a histogram of its own
dwell time against position; the condition's curve is the mean over traces with the spread shown
as a standard error. `only_crossed=True` restricts to traces that made it past the nucleosome so
the average isn't dominated by traces that stalled. `RTH.ccdf` gives the survival curve, plotted
on a linear y-scale.

```python
from ruler import residence_time_histogram

rth = residence_time_histogram(results, bin_bp=10.0, range_bp=(0, 1200),
                               only_crossed=True, opts=opts)
rth.centers_bp, rth.mean_s, rth.sem_s, rth.ccdf
```

## 9. Cherry-picking

Picking traces by eye is a real part of quality control, but the alignment quality fields
(`ok`, `resultant`, `n_matched`, `rms_residual_bp`) reject most of what manual picking would
catch, and they do it reproducibly. Filter on those first:

```python
good = [r for r in results if r.ok and r.resultant > 0.8 and r.n_matched >= 6]
```

For the judgement calls that remain, use [`sfz gui`](gui-walkthrough.md) to view traces and drop
the ones you don't want from the condition folder. Whichever way you pick, record it — a
hand-selected subset and a filtered one are different results, and that distinction matters for
reproducing the analysis later.

## 10. Pause-free velocity

Pause-free velocity is the distance covered divided by the time spent actually moving:

\[
v_\text{pf} = \frac{\Delta \text{bp}}{t_\text{total} - t_\text{paused}}
\]

`pfv_by_region` reports it for two regions — the ruler (naked DNA) and the nucleosome:

```python
from ruler import pfv_by_region

for pfv in pfv_by_region(result, opts):
    print(pfv.region, pfv.velocity_bp_s, pfv.pause_fraction)
```

!!! warning "Not `analysis.velocity.step_velocities`"
    The library's `step_velocities` divides each step's rise by the dwell at the level it
    *arrives on*, which folds the pause following a step into that step's velocity — the
    opposite of what "pause-free" means. On a ruler trace it under-reports the rate by roughly
    3×. Use it for per-segment velocity distributions, not for this number. See
    [Velocity & pausing](../physics/velocity-pausing.md).

---

## Doing the QC pass in the GUI

None of the ruler-specific analysis — alignment, residence-time histograms, pause-free velocity —
has a GUI screen; it exists only as `align_to_ruler`, `residence_time_histogram` and
`pfv_by_region`, called from a script. But `sfz gui` (full walkthrough:
[GUI walkthrough](gui-walkthrough.md)) does cover the parts of this workflow that are about
*looking at one trace*, and it's worth using instead of writing throwaway plotting code for each
one:

1. **Open the processed trace.** `sfz process` (step 3) writes one `.h5` per file with exactly
   the `time`/`force`/`extension` shape the GUI expects — drag the condition folder onto the
   data rail and click a trace to load it straight into the Trace Viewer, no conversion needed.
   This is the fastest way to catch a trace that lost its tether before it gets averaged into a
   condition.

2. **Look for the ruler by eye.** Run **step-find** (Kalafut–Visscher or HMM) on the extension
   channel and look at the overlay. `align_to_ruler`'s scale fit (step 7) is doing the same job
   with more rigor — maximising how periodic the plateau positions are at 64 bp — but a quick look
   tells you in seconds whether a trace has a visible pause lattice at all, before spending the
   CPU on the full fit.

3. **Check the WLC parameters.** Switch to the Force-Extension viewer and fit the extensible WLC
   to force vs. extension (see [Force & extension](../physics/force-extension.md)). `contour_bp`
   (step 6) uses the same model with `P=50 nm`, `S=900 pN`; if the GUI's fit lands far from those
   numbers on a given trace, that trace's calibration is off before the ruler analysis ever sees
   it.

4. **Look at the pause durations.** Feed a step-find result into the **Dwell times** tab
   (`kinetics/fit`) to fit an exponential or gamma mixture to the plateau durations. This is not
   `pfv_by_region` (step 10) — it fits the whole dwell-time distribution rather than splitting
   paused/moving time by region — but it's a fast way to see a condition's pauses getting longer
   without leaving the GUI.

5. **Cherry-pick.** As in the cherry-picking step above: open each trace, judge it by eye, and
   drop the ones you don't trust from the condition folder.

Everything else — building the batch file, running `sfz process` itself, the ruler alignment and
phase fit, the residence-time histogram, and true pause-free velocity — has no GUI equivalent;
that's what `make_batch.py`, `sfz process`, and `run_analysis.py` are for.

---

## The example package

```text
examples/rnap_nuc_crossing/
  make_batch.py     build a sfz batch .txt from a raw acquisition folder
  ruler.py          contour conversion, RulerAlignOptions, alignment, RTH, PFV
  synth.py          synthetic ruler traces with known geometry
  run_analysis.py   the driver — conditions in, summary + figure out
```

The modules import each other by plain name, so run them from inside the directory or add it to
`sys.path` (which is what `tests/test_ruler_example.py` does).

### Validating the analysis

The dataset in `data/Datos Curso Biophysal` is a biophysics-course dataset — tether pulls and
two-state hopping — not ruler transcription data. It exercises steps 1–4 of this guide for real,
and it is a good check that the ruler fit **rejects** data with no ruler in it (it does: every
trace fails with either a low resultant or a scale pinned at the search boundary). But it cannot
validate the alignment itself, because no trace in it has a known lattice.

`synth.py` fills that gap by generating traces whose geometry is known by construction — an RNAP
that pauses at each lattice site and then either crosses the nucleosome or arrests in it,
converted to nm through the same WLC the pipeline inverts, with noise added. Run the whole
workflow against them:

```bash
uv run python examples/rnap_nuc_crossing/run_analysis.py --synthetic --plot rth.png
```

```text
a Just Ruler
  aligned          : 8/8
  crossed nucleosome: 8/8 (100%)
  pause-free velocity, ruler (naked DNA) :  19.32 bp/s  (paused 70% of the time, n=8 traces)
  pause-free velocity, nucleosome        :  15.65 bp/s  (paused 60% of the time, n=8 traces)
  residence time, ruler region     :   75.1 s
  residence time, nucleosome region:   15.0 s

b Nuc
  aligned          : 10/10
  crossed nucleosome: 5/10 (50%)
  pause-free velocity, ruler (naked DNA) :  20.06 bp/s  (paused 72% of the time, n=10 traces)
  pause-free velocity, nucleosome        :  16.75 bp/s  (paused 92% of the time, n=10 traces)
  residence time, ruler region     :   83.7 s
  residence time, nucleosome region:   41.4 s
```

The traces were simulated at 20 bp/s, and the ruler pause-free velocity comes back at 19.3 and
20.1 bp/s. The nucleosome condition shows what the assay is designed to detect: half the traces
arrest, the time spent in the nucleosome region nearly triples, and the polymerase is paused 92%
of the time there versus 72% on naked DNA.

`tests/test_ruler_example.py` locks this in — alignment recovers the lattice to within the
tolerance on every synthetic trace, crossing classification matches ground truth, the RTH peaks
at each expected pause position, pause-free velocity recovers the simulated rate, and both a
random walk and a pure ramp are correctly refused.

```bash
uv run --extra dev pytest tests/test_ruler_example.py -q
```

### Known limitations

- **The fitted scale carries a systematic bias of a few percent** (≈0.975 on synthetic traces
  built at exactly 1.0), because step-finding places plateau boundaries slightly into the
  adjacent ramps, which inflates the apparent pause spacing. Positions land within ~2–6 bp RMS
  of the lattice across the ruler, which is fine for residence histograms binned at 10 bp, but
  don't read single-bp positions off an aligned trace.
- **The nucleosome position is assumed to be immediately after the ruler**
  (`start + nrep*per`), and "crossed" means reaching one nucleosome length plus a margin past
  it. Both are `RulerAlignOptions` fields (`nuc_length_bp`, `cross_margin_bp`) — set them to
  match your construct.
- **Alignment needs resolvable pauses.** Traces that transcribe through the ruler without
  pausing, or where the ruler is buried in noise, will fail with `min_pauses`. That is the
  correct outcome, but it means the analysed set is biased toward pausing traces — report the
  alignment rate alongside the results.
