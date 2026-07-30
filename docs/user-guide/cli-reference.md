# CLI reference

This is the real `--help` output of every `sfz` command (Typer + Rich), captured from the
installed CLI so it can't drift from what's actually implemented in `src/salafleezers/cli/main.py`.

## `sfz`

```text
Usage: sfz [OPTIONS] COMMAND [ARGS]...

SalaFleezer optical tweezers data processing tool.

Commands:
  inspect    Print the header metadata of a .dat file.
  calibrate  Calibrate a single .dat file (power spectrum + Lorentzian fit).
  process    Batch-process files listed in a .txt batch file.
  stepfind   Detect steps in a processed data file.
  wlc-fit    Fit a WLC model to a force-extension curve.
  velocity   Compute velocity distribution from a processed data file.
  pwd        Compute pairwise-distance histogram to identify step sizes.
  gui        Launch the interactive web GUI (requires sfz[gui] extra).
```

Every command supports `--help`, and most support `--json` for scriptable/NDJSON output
instead of Rich tables.

## `sfz inspect`

```text
Usage: sfz inspect [OPTIONS] DAT_FILE

Print the header metadata of a .dat file.

Arguments:
  DAT_FILE   .dat file to inspect  [required]

Options:
  --json     Output as JSON
```

## `sfz calibrate`

```text
Usage: sfz calibrate [OPTIONS] DAT_FILE

Calibrate a single .dat file (power spectrum + Lorentzian fit).

Arguments:
  DAT_FILE   .dat file to calibrate  [required]

Options:
  --plot                    Show power spectrum plot
  --json                    Output as JSON
  --ra-a         FLOAT      Bead radius for trap A (nm)              [default: 500.0]
  --ra-b         FLOAT      Bead radius for trap B (nm)              [default: 500.0]
  --fmin         FLOAT      Calibration fit lower frequency (Hz)     [default: 100.0]
  --fmax         FLOAT      Calibration fit upper frequency (Hz); default = Nyquist
  --n-bin        INTEGER    Points per spectral bin                 [default: 1563]
  --n-alias      INTEGER    Lorentzian aliasing order                [default: 20]
  --no-normalize            Skip QPD sum normalization
  -v, --verbose
```

## `sfz process`

```text
Usage: sfz process [OPTIONS] TXT_FILE

Batch-process files listed in a .txt batch file.

Batch file format (matches AProcessDataV2.m):
  Line 1:   YYMMDD  (date string, e.g. 230415)
  Line 2+:  dat_num  off_num  cal_num  [comment]

Arguments:
  TXT_FILE   Batch .txt file  [required]

Options:
  --data-dir      PATH               Directory containing .dat files
  --output-dir    PATH               Output directory
  --json                             Output NDJSON progress events
  --ra-a          FLOAT              Bead radius for trap A (nm)          [default: 500.0]
  --ra-b          FLOAT              Bead radius for trap B (nm)          [default: 500.0]
  --fmin          FLOAT              Calibration fit lower frequency (Hz) [default: 100.0]
  --fmax          FLOAT              Calibration fit upper frequency (Hz); default = Nyquist
  --n-bin         INTEGER            Points per spectral bin             [default: 1563]
  --n-alias       INTEGER            Lorentzian aliasing order            [default: 20]
  --no-normalize
  --save-format   [hdf5|npz|mat]     Output file format                  [default: hdf5]
  -v, --verbose
```

See [Batch files](batch-files.md) for the `.txt` file format in detail.

## `sfz stepfind`

```text
Usage: sfz stepfind [OPTIONS] DATA_FILE

Detect steps in a processed data file.

Arguments:
  DATA_FILE   Processed HDF5/npz file  [required]

Options:
  -c, --channel      TEXT       Channel to analyse       [default: extension]
  -a, --algorithm    [kv|hmm]   Detection algorithm       [default: kv]
  --pen-factor       FLOAT      Penalty factor (KV)       [default: 2.0]
  --n-states         INTEGER    Number of HMM states      [default: 2]
  --json
```

See [Step-finding theory](../physics/step-finding.md) for what `--pen-factor` and `--n-states`
actually control.

## `sfz wlc-fit`

```text
Usage: sfz wlc-fit [OPTIONS] DATA_FILE

Fit a WLC model to a force-extension curve.

Arguments:
  DATA_FILE   Processed HDF5/npz file  [required]

Options:
  --method   [basic|marko_siggia|bouchiat]   [default: basic]
  --p0       FLOAT   Initial persistence length (nm)   [default: 50.0]
  --s0       FLOAT   Initial stretch modulus (pN)      [default: 900.0]
  --json
```

See [Force & extension](../physics/force-extension.md) for what these three methods mean
physically, and why only `basic` is golden-tested.

## `sfz velocity`

```text
Usage: sfz velocity [OPTIONS] DATA_FILE

Compute velocity distribution from a processed data file.

Arguments:
  DATA_FILE   Processed HDF5/npz file  [required]

Options:
  --channel     TEXT      [default: extension]
  --window      INTEGER   SG window (samples)      [default: 21]
  --polyorder   INTEGER   SG polynomial order       [default: 2]
  --json
```

## `sfz pwd`

```text
Usage: sfz pwd [OPTIONS] DATA_FILE

Compute pairwise-distance histogram to identify step sizes.

Arguments:
  DATA_FILE   Processed HDF5/npz file  [required]

Options:
  --channel   TEXT      [default: extension]
  --bins      INTEGER   [default: 200]
  --json
```

## `sfz gui`

```text
Usage: sfz gui [OPTIONS]

Launch the interactive web GUI (requires sfz[gui] extra).

Options:
  --host          TEXT      [default: 127.0.0.1]
  --port          INTEGER   [default: 8765]
  --no-browser
```

`--no-browser` is what the Docker image's `CMD` uses — there's no display inside a container
to open a browser window in.

Auth (`SFZ_AUTH_TOKEN`/`SFZ_TRUSTED_USER_HEADER`) and the path prefix the GUI is served under
(`FRONTEND_BASE_PATH`) are environment variables rather than flags — see
[Installation](installation.md#docker).
