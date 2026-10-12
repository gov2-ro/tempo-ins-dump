#!/usr/bin/env python3
"""Load fetched INS Total cells into a generation's DB as `published_totals`.

  python scripts/fetch-ins-reference-cells.py --spec app/data/published_totals.json \
      --meta-dir DATA/2-metas/ro --out DIR
  python scripts/load-published-totals.py --cells DIR --db DATA/corpus/metadata.duckdb [--dry-run]

Each fetched CSV holds one value per (area, year): every dimension except the
area, the year and the unit is pinned to INS's "Total" option, which is checked
here. Rows for the fetched matrices are replaced; other matrices are untouched.
Provenance (query id, fetch time, file and metadata sha256, INS update date)
travels with every row. Write to a copied generation, never the live DB.
"""
import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

import duckdb

SCHEMA = """CREATE TABLE IF NOT EXISTS published_totals (
    matrix_code VARCHAR NOT NULL, ref_area VARCHAR NOT NULL, time_period VARCHAR NOT NULL,
    value DOUBLE, unit VARCHAR, query_id VARCHAR, fetched_at VARCHAR,
    file_sha256 VARCHAR, meta_sha256 VARCHAR, ins_updated VARCHAR,
    PRIMARY KEY (matrix_code, ref_area, time_period))"""


def read_cells(path: Path) -> list[tuple]:
    """[(ref_area, year, value, unit)] from one fetched CSV; raises on any
    row that is not a Total cell."""
    with open(path, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    head, body = rows[0], rows[1:]
    out, seen = [], set()
    for r in body:
        r = [c.strip() for c in r]
        *pinned, area, period, unit, val = r
        if any(p.lower() != "total" for p in pinned):
            raise ValueError(f"{path.name}: not a Total cell: {r}")
        m = re.fullmatch(r"Anul (\d{4})", period)
        if not m:
            raise ValueError(f"{path.name}: unsupported period {period!r}")
        key = (area, m.group(1))
        if key in seen:
            raise ValueError(f"{path.name}: duplicate cell {key}")
        seen.add(key)
        try:
            v = float(val)
        except ValueError:
            v = None                      # INS marks a missing value with a symbol
        out.append((area, m.group(1), v, unit))
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
        for area, year, v, unit in read_cells(path):
            load.append((f["matrix"], area, year, v, unit, qid, f["fetched_at"], f["sha256"],
                         f.get("meta_sha256"), meta.get("ultimaActualizare")))
    matrices = sorted({r[0] for r in load})
    print(f"{len(load)} cells for {', '.join(matrices)}")
    if a.dry_run:
        return 0
    con = duckdb.connect(a.db)
    con.execute("BEGIN")
    con.execute(SCHEMA)
    con.execute(f"DELETE FROM published_totals WHERE matrix_code IN ({','.join('?' * len(matrices))})",
                matrices)
    con.executemany("INSERT INTO published_totals VALUES (?,?,?,?,?,?,?,?,?,?)", load)
    con.execute("COMMIT")
    print(f"published_totals: {con.execute('SELECT count(*) FROM published_totals').fetchone()[0]} rows")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
