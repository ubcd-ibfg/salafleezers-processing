# Data formats

## Raw instrument files (`.dat`)

SalaFleezer `.dat` files are big-endian binary with this layout:

```text
float64        hdrlen        — number of header doubles
float64 × N    hdr           — header fields (see below)
float64        cmtlen        — comment byte count
char × M       cmt           — ASCII comment string
int16 × K      data          — interleaved QPD channels (nch × nsamples, column-major)
```

Key header fields (0-based index):

| Index | Field | Description |
| --- | --- | --- |
| 0 | `filever` | File format version (must be ≥ 9) |
| 1 | `Fsampraw` | Raw ADC sampling rate (Hz) |
| 2 | `Fsamp` | Output sample interval (s); `Fs = 1/Fsamp` |
| 3 | `nChannels` | Number of interleaved channels |
| 4 | `channelID` | Channel layout selector (2 = SalaFleezer default) |
| 5 | `datatype` | 0 = regular, 1 = calibration, 2 = AOM scan, 3 = MCL scan |
| 6–11 | `initMHz` | Initial trap positions (MHz) |
| 12 | `extraData` | Bitmask: bit 0 = `_fl` saved, bit 1 = `_pos` saved |

Associated sidecar files (same stem, same directory):

| File | Format | Content |
| --- | --- | --- |
| `_fl.dat` | big-endian uint32 | Interleaved APD1/APD2 photon counts |
| `_pos.dat` | big-endian uint64 | DDS trap frequencies → MHz via `× 49.152×6 / 2⁴⁸` |
| `_grn.dat` | big-endian float64 | Green laser status (4 channels) |

Parsed by `salafleezers.io.reader.read_dat`, which returns a dataclass with `.meta` (header
dict), `.channels` (dict of named float32 arrays), and `.time`.

## Processed output files

`sfz process` / `process_one` write one file per data file, containing a time/force/extension
trace plus per-trap calibration constants. Three formats are supported via `--save-format`:

| Format | Extension | Notes |
| --- | --- | --- |
| HDF5 (default) | `.h5` | Chunked, gzip-compressed, readable from any language via `h5py`/`pytables`/etc. — no MATLAB dependency. |
| MATLAB v5 | `.mat` | Via `scipy.io.savemat`, for compatibility with existing MATLAB analysis scripts. |
| NumPy | `.npz` | `np.savez_compressed` — simplest to read back in Python, used by the golden-file test fixtures. |

All three formats hold the same fields (see `ProcessedData.to_dict()` in
`processing/pipeline.py`): `time`, `force`, `extension`, per-axis force channels, and the
calibration constants (`fc`, `alpha`, `kappa`, `D`) for each trap/axis.

Both the CLI's `stepfind`/`wlc-fit`/`velocity`/`pwd` commands and the web GUI's "Open file"
accept any of these three formats — see `web/io.py::load_file` for the format dispatch used by
the GUI, and note it also accepts a bare `.npz` with just `time` + named channel arrays (which
is exactly what the golden-file test fixtures and this project's own smoke tests use, so you
don't need real instrument hardware to try the GUI).

## Web GUI channel model

Internally the GUI treats every file as `{time: float32[N], channels: {name: float32[N], …}}` —
this is the same shape whether it came from a `.dat`, `.h5`, `.mat`, or `.npz` file, which is
what lets one `TraceSegment`/`TracePreview` API model serve all of them (see
[API reference](../developer/api-reference.md)).
