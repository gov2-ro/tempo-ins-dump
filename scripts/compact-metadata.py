#!/usr/bin/env python3
"""Rewrite metadata.duckdb into a compact copy and verify it (HZ-5).

DuckDB does not reclaim space after deletes and rewrites: the served DB grew from 120 MB to 2.7 GB
through a refresh. This script writes a fresh file:

  1. schema only: COPY FROM DATABASE src TO dst (SCHEMA) (tables, constraints, indexes, views,
     sequences);
  2. rows, table by table, parents first. A plain COPY FROM DATABASE fails here: it copies the
     tables in alphabetical order, and `dimensions` (FK to `matrices`) comes before `matrices`;
  3. (sequences come with the schema copy; DuckDB has no setval, so the check below compares them);
  4. verification against the source: the same tables, views, columns, constraints, indexes and
     sequence values; the same row count and an order-independent content hash per table.
     On any difference the new file is deleted and the exit code is 1.

It never writes SRC and refuses an existing DST or a DST inside the repository's own data/.

  python scripts/compact-metadata.py SRC.duckdb DST.duckdb [--json-out FILE]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parent.parent


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def tables_in_fk_order(con, db: str) -> list[str]:
    """Base tables, every referenced table before its referrers (ties: alphabetical)."""
    names = [r[0] for r in con.execute(
        "SELECT table_name FROM duckdb_tables() WHERE database_name = ? AND schema_name = 'main' "
        "ORDER BY 1", [db]).fetchall()]
    refs = {n: set() for n in names}
    for t, ref in con.execute(
            "SELECT table_name, referenced_table FROM duckdb_constraints() "
            "WHERE database_name = ? AND schema_name = 'main' AND constraint_type = 'FOREIGN KEY'",
            [db]).fetchall():
        if ref and ref != t:
            refs[t].add(ref)
    ordered: list[str] = []
    pending = list(names)
    while pending:
        ready = [n for n in pending if refs[n] <= set(ordered)]
        if not ready:
            raise RuntimeError(f"foreign key cycle among {pending}")
        ordered.extend(ready)
        pending = [n for n in pending if n not in ready]
    return ordered


def fingerprint(con, db: str) -> dict:
    """Everything the compact copy must reproduce, read from one attached database."""
    fp = {"tables": {}, "views": {}, "constraints": [], "indexes": [], "sequences": {}}
    for t in tables_in_fk_order(con, db):
        cols = con.execute(
            "SELECT column_name, data_type FROM duckdb_columns() WHERE database_name = ? "
            "AND schema_name = 'main' AND table_name = ? ORDER BY column_index", [db, t]).fetchall()
        n = con.execute(f"SELECT COUNT(*) FROM {db}.main.{q(t)}").fetchone()[0]
        # sum of per-row hashes: independent of row order, a changed value changes the sum
        h = con.execute(f"SELECT COALESCE(SUM(hash(__row)::HUGEINT), 0)::VARCHAR FROM {db}.main.{q(t)} __row").fetchone()[0]
        fp["tables"][t] = {"columns": [list(c) for c in cols], "rows": n, "hash": h}
    for name, sql in con.execute(
            "SELECT view_name, sql FROM duckdb_views() WHERE database_name = ? AND NOT internal", [db]).fetchall():
        fp["views"][name] = sql
    fp["constraints"] = sorted(
        [t, ct, list(cols), ref or ""] for t, ct, cols, ref in con.execute(
            "SELECT table_name, constraint_type, constraint_column_names, referenced_table "
            "FROM duckdb_constraints() WHERE database_name = ? AND schema_name = 'main'", [db]).fetchall())
    fp["indexes"] = sorted([t, i, s] for t, i, s in con.execute(
        "SELECT table_name, index_name, sql FROM duckdb_indexes() WHERE database_name = ?", [db]).fetchall())
    for name, last, start, inc in con.execute(
            "SELECT sequence_name, last_value, start_value, increment_by FROM duckdb_sequences() "
            "WHERE database_name = ?", [db]).fetchall():
        fp["sequences"][name] = [last, start, inc]
    return fp


def diff(a: dict, b: dict) -> list[str]:
    out = []
    for key in ("views", "constraints", "indexes", "sequences"):
        if a[key] != b[key]:
            out.append(f"{key} differ")
    if set(a["tables"]) != set(b["tables"]):
        out.append(f"table sets differ: {sorted(set(a['tables']) ^ set(b['tables']))}")
    for t in sorted(set(a["tables"]) & set(b["tables"])):
        x, y = a["tables"][t], b["tables"][t]
        for k in ("columns", "rows", "hash"):
            if x[k] != y[k]:
                out.append(f"{t}: {k} differ ({x[k] if k != 'columns' else '...'} vs {y[k] if k != 'columns' else '...'})")
    return out


def compact(src: Path, dst: Path) -> dict:
    src, dst = Path(src).resolve(), Path(dst).resolve()
    live = (REPO / "data").resolve()
    if src == dst:
        raise SystemExit("SRC and DST are the same file")
    if dst.exists():
        raise SystemExit(f"refusing to overwrite {dst}")
    if dst == live or live in dst.parents:
        raise SystemExit(f"refusing to write {dst}: that is the repository's own data/")
    t0 = time.time()
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{dst}' AS dst")
        con.execute(f"ATTACH '{src}' AS src (READ_ONLY)")
        con.execute("COPY FROM DATABASE src TO dst (SCHEMA)")
        for t in tables_in_fk_order(con, "src"):
            con.execute(f"INSERT INTO dst.main.{q(t)} SELECT * FROM src.main.{q(t)}")
        con.execute("CHECKPOINT dst")
        problems = diff(fingerprint(con, "src"), fingerprint(con, "dst"))
    except Exception:
        con.close()
        dst.unlink(missing_ok=True)
        Path(str(dst) + ".wal").unlink(missing_ok=True)
        raise
    con.close()
    wal = Path(str(dst) + ".wal")
    if problems:
        dst.unlink(missing_ok=True)
        wal.unlink(missing_ok=True)
        return {"ok": False, "problems": problems}
    return {"ok": True, "problems": [], "src_bytes": src.stat().st_size, "dst_bytes": dst.stat().st_size,
            "seconds": round(time.time() - t0, 1)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--json-out")
    a = ap.parse_args(argv)
    rep = compact(Path(a.src), Path(a.dst))
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    if not rep["ok"]:
        print("COMPACTION FAILED, destination removed:", *rep["problems"], sep="\n  ", file=sys.stderr)
        return 1
    print(f"compact copy verified: {rep['src_bytes'] / 1e6:.1f} MB -> {rep['dst_bytes'] / 1e6:.1f} MB "
          f"in {rep['seconds']} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
