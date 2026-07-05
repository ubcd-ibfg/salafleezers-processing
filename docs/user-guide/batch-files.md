# Batch files

`sfz process` takes a plain-text batch file — the same format as the original MATLAB
`AProcessDataV2.m` used, so existing lab batch files work unchanged:

```text
# batch.txt
230415
1   2   3   first tether
4   2   3   second tether
7   2   3   third tether
```

- **Line 1:** date string `YYMMDD`.
- **Every subsequent line:** `dat_num  off_num  cal_num  [comment]`
  - `dat_num` — the data file's number (e.g. `1` → `230415_001.dat`)
  - `off_num` — the offset file's number (a bead-interaction baseline measurement, subtracted
    during processing — see `processing/offset.py`)
  - `cal_num` — the calibration file's number (a free bead in the trap, used for the power
    spectrum fit — see [Calibration & trap stiffness](../physics/calibration.md))
  - anything after the third number is a free-text comment, ignored by the parser but useful
    for keeping track of which tether/experiment each line corresponds to

Run it:

```bash
uv run sfz process batch.txt --data-dir path/to/data/ --output-dir path/to/output/
```

This produces one output file per line (named `ForceExtension<YYMMDD>_<dat_num>.<ext>`), each
holding that data file's force/extension trace processed against its own offset and
calibration file. Use `--json` to get one NDJSON progress event per line instead of the Rich
progress bar — useful when calling `sfz process` from another script or CI pipeline.
