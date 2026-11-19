#!/usr/bin/env python3
"""Load fetched INS Total cells into a generation's DB as `published_totals`.

  python scripts/fetch-ins-reference-cells.py --spec app/data/published_totals.json \
      --meta-dir DATA/2-metas/ro --out DIR
  python scripts/load-published-totals.py --cells DIR --db DATA/corpus/metadata.duckdb [--dry-run]

Each fetched CSV holds one value per (area, period, breakdown). Every dimension
except the area, the period and the unit is pinned to INS's "Total" option, which
is checked here. A dimension that the spec names in `breakdown` (for example SEX)
may also hold other options. Its non-Total option becomes the row's `breakdown`:
canonical JSON such as {"SEX":"Feminin"}. The value '' means every dimension is
Total. A matrix without an area dimension (spec `"area": false`) files its rows
under area TOTAL. Rows for the fetched matrices are replaced; other matrices are
untouched. Provenance (query id, fetch time, file and metadata sha256, INS update
date) travels with every row. Write to a copied generation, never the live DB.
"""
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sdmx_labels import parse_time_period  # noqa: E402  (shared with stages 9 and 11)

SCHEMA = """CREATE TABLE IF NOT EXISTS published_totals (
    matrix_code VARCHAR NOT NULL, ref_area VARCHAR NOT NULL, time_period VARCHAR NOT NULL,
    breakdown VARCHAR NOT NULL DEFAULT '',
    value DOUBLE, unit VARCHAR, query_id VARCHAR, fetched_at VARCHAR,
    file_sha256 VARCHAR, meta_sha256 VARCHAR, ins_updated VARCHAR,
    PRIMARY KEY (matrix_code, ref_area, time_period, breakdown))"""
COLUMNS = ("matrix_code, ref_area, time_period, breakdown, value, unit, query_id, fetched_at, "
           "file_sha256, meta_sha256, ins_updated")
NATIONAL_AREA = "TOTAL"       # INS's label for the country; used when a matrix has no area dimension


def ensure_schema(con) -> None:
    """Create the table, or rebuild an older one that has no `breakdown` column (its rows mean '')."""
    cols = [r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'published_totals'"
    ).fetchall()]
    if cols and "breakdown" not in cols:
        con.execute("ALTER TABLE published_totals RENAME TO published_totals_old")
        con.execute(SCHEMA)
        con.execute(f"INSERT INTO published_totals ({COLUMNS}) SELECT matrix_code, ref_area, time_period, '', "
                    "value, unit, query_id, fetched_at, file_sha256, meta_sha256, ins_updated "
                    "FROM published_totals_old")
        con.execute("DROP TABLE published_totals_old")
    else:
        con.execute(SCHEMA)


def read_cells(path: Path, breakdown: dict | None = None, area=None) -> list[tuple]:
    """[(ref_area, period, breakdown_json, value, unit)] from one fetched CSV.
    Raises on any row that is not a Total cell.

    A row holds the matrix dimensions in order, then the period, the unit and the value
    (the period is the last dimension INS lists, the unit is the "UM" dimension).
    `breakdown` maps a name to a dimension position ({"SEX": 1}). `area` is the area
    position, False when the matrix has no area dimension, None for the usual place
    (the dimension just before the period)."""
    breakdown = breakdown or {}
    with open(path, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    out, seen = [], set()
    for r in rows[1:]:
        r = [c.strip() for c in r]
        if not any(r):
            continue
        *dims, period, unit, val = r
        ai = None if area is False else (len(dims) - 1 if area is None else int(area))
        ref_area = dims[ai] if ai is not None else NATIONAL_AREA
        bd = {}
        for i, label in enumerate(dims):
            if i == ai or label.lower() == "total":
                continue
            name = next((n for n, pos in breakdown.items() if pos == i), None)
            if name is None:
                raise ValueError(f"{path.name}: not a Total cell: {r}")
            bd[name] = label
        t = parse_time_period(period)
        if t is None:
            raise ValueError(f"{path.name}: unsupported period {period!r}")
        bkey = json.dumps(bd, sort_keys=True, ensure_ascii=False, separators=(",", ":")) if bd else ""
        key = (ref_area, t, bkey)
        if key in seen:
            raise ValueError(f"{path.name}: duplicate cell {key}")
        seen.add(key)
        try:
            v = float(val)
        except ValueError:
            v = None                      # INS marks a missing value with a symbol
        out.append((ref_area, t, bkey, v, unit))
    if not out:
        raise ValueError(f"{path.name}: no cells")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cells", required=True, help="output dir of fetch-ins-reference-cells.py")
    ap.add_argument("--db", required=True, help="the copied generation's metadata.duckdb")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    cells = Path(a.cells)
    manifest = json.loads((cells / "manifest.json").read_text(encoding="utf-8"))
    load = []
    for qid, f in manifest["fetches"].items():
        path = cells / f["file"]
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != f["sha256"]:
            sys.exit(f"{path.name}: sha256 differs from manifest.json")
        meta = json.loads(Path(f["meta_file"]).read_text(encoding="utf-8")) \
            if Path(f["meta_file"]).exists() else {}
        for area, period, bd, v, unit in read_cells(path, f.get("breakdown"), f.get("area")):
            load.append((f["matrix"], area, period, bd, v, unit, qid, f["fetched_at"], f["sha256"],
                         f.get("meta_sha256"), meta.get("ultimaActualizare")))
    matrices = sorted({r[0] for r in load})
    print(f"{len(load)} cells for {', '.join(matrices)}")
    if a.dry_run:
        return 0
    con = duckdb.connect(a.db)
    con.execute("BEGIN")
    ensure_schema(con)
    con.execute(f"DELETE FROM published_totals WHERE matrix_code IN ({','.join('?' * len(matrices))})",
                matrices)
    con.executemany("INSERT INTO published_totals VALUES (?,?,?,?,?,?,?,?,?,?,?)", load)
    con.execute("COMMIT")
    print(f"published_totals: {con.execute('SELECT count(*) FROM published_totals').fetchone()[0]} rows")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
