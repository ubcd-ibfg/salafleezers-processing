# RNAP nucleosome crossing with a molecular ruler

Worked example reproducing the lab how-to *"Processing RNAP nucleosome crossing data with a
molecular ruler"* with `sfz` instead of MATLAB. The full write-up is
[docs/user-guide/rnap-nucleosome-crossing.md](../../docs/user-guide/rnap-nucleosome-crossing.md);
this file is just the map.

| File | Replaces | What it does |
| --- | --- | --- |
| `make_batch.py` | hand-written `YYMMDD.txt` | Builds an `sfz process` batch file from a raw acquisition folder by reading each `.dat` header's `datatype` |
| `ruler.py` | `procFranp2`, `procFranp3`, `ezFactPlot`, `procFran_PFVv2` | Contour-length conversion, `RulerAlignOptions` (the `rAopts` struct), lattice alignment, residence-time histograms, pause-free velocity |
| `synth.py` | — | Synthetic ruler traces with known geometry, for validating the analysis |
| `run_analysis.py` | the MATLAB driver session | Runs the chain over a folder of per-condition subfolders and writes the summary + figure |

The modules import each other by plain name, so run them from inside this directory.

## Quick start

```bash
# 1. Build a batch file from a raw acquisition folder
uv run python make_batch.py "../../data/Datos Curso Biophysal/260625"

# 2. Raw .dat -> force/extension  (from the repo root)
uv run sfz process "data/Datos Curso Biophysal/260625/260625.txt" \
    --data-dir "data/Datos Curso Biophysal/260625" --output-dir processed/

# 3. Sort processed traces into per-condition subfolders, then analyse
uv run python run_analysis.py --conditions "Boltz V1" --plot rth.png
```

## Checking the analysis itself

`data/Datos Curso Biophysal` is a course dataset — tether pulls and two-state hopping, no ruler
traces — so it can't validate the alignment. Use the synthetic traces, whose geometry is known
by construction:

```bash
uv run python run_analysis.py --synthetic --plot rth.png
uv run --extra dev pytest ../../tests/test_ruler_example.py -q
```
