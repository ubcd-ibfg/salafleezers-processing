"""Generate `sfz process` batch files from a raw acquisition folder.

The MATLAB workflow (`procFran` / `AProcessDataV2`) expected a hand-written
`YYMMDD.txt` listing `data offset cal` triplets. Acquisition folders don't ship
one, but every `.dat` header already records what kind of run it was, so the
triplets can be recovered:

    datatype 0  regular data      -> the trace to process
    datatype 1  calibration       -> the `cal` column
    datatype 2  AOM raster scan   -> the `offset` column
    datatype 3  MCL raster scan   -> stage scan, not used here

Each data file is paired with the most recent preceding offset and calibration
run, which is the order the instrument acquires them in.

Usage
-----
    uv run python examples/rnap_nuc_crossing/make_batch.py DAY_DIR [-o OUT.txt]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from salafleezers.io.reader import read_header

DATA, CAL, OFFSET = 0, 1, 2


def classify(day_dir: Path) -> dict[int, list[int]]:
    """Return {datatype: [file numbers]} for one acquisition folder."""
    day = day_dir.name
    by_type: dict[int, list[int]] = {}
    for path in sorted(day_dir.glob(f"{day}_[0-9][0-9][0-9].dat")):
        try:
            meta, _, _ = read_header(path)
        except ValueError as exc:  # truncated / pre-v9 file
            print(f"  skipping {path.name}: {exc}", file=sys.stderr)
            continue
        num = int(path.stem.split("_")[1])
        by_type.setdefault(int(meta["datatype"]), []).append(num)
    return by_type


def build_triplets(by_type: dict[int, list[int]]) -> list[tuple[int, int, int]]:
    """Pair each data file with the nearest preceding offset and cal run."""
    offsets = by_type.get(OFFSET, [])
    cals = by_type.get(CAL, [])
    triplets = []
    for num in by_type.get(DATA, []):
        off = max((n for n in offsets if n < num), default=None)
        cal = max((n for n in cals if n < num), default=None)
        if off is None or cal is None:
            print(f"  skipping {num:03d}: no preceding "
                  f"{'offset' if off is None else 'cal'} run", file=sys.stderr)
            continue
        triplets.append((num, off, cal))
    return triplets


def write_batch(day: str, triplets: list[tuple[int, int, int]], out: Path) -> None:
    lines = [day]
    lines += [f"{d}\t{o}\t{c}\tauto-paired" for d, o, c in triplets]
    out.write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("day_dir", type=Path,
                    help="folder named YYMMDD holding the .dat files")
    ap.add_argument("-o", "--output", type=Path, help="batch file to write "
                    "(default: <day_dir>/<YYMMDD>.txt)")
    args = ap.parse_args()

    day_dir: Path = args.day_dir
    if not day_dir.is_dir():
        print(f"not a directory: {day_dir}", file=sys.stderr)
        return 1

    by_type = classify(day_dir)
    for dtype, nums in sorted(by_type.items()):
        name = {0: "data", 1: "cal", 2: "offset", 3: "stage scan"}.get(dtype, "unknown")
        print(f"  datatype {dtype} ({name}): {len(nums)} files")

    triplets = build_triplets(by_type)
    if not triplets:
        print("no processable data files found", file=sys.stderr)
        return 1

    out = args.output or day_dir / f"{day_dir.name}.txt"
    write_batch(day_dir.name, triplets, out)
    print(f"wrote {len(triplets)} triplets -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
