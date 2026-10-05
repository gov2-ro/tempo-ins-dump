#!/usr/bin/env python3
"""Backfill dimension_structure on a COPY of metadata.duckdb (FIX-03 measurement).

Drives 13-dimension-structure.py's own profile_matrix()/to_row()/DDL but tolerates
matrices whose dimensions map to the same column twice: the stock script's
INSERT hits the (matrix_code, dim_column) primary key and aborts half-way
(e.g. INT109A_lei.ECON_ACTIVITY). Duplicates are skipped and listed; the first
profile per key wins.

Refuses to touch any DB under a real <repo>/data/corpus. Parquets are only read.

  python scripts/utils/backfill-structure-copy.py --db COPY.duckdb \
         --parquet-dir DIR [--codes-file F | --unprofiled-served] [--report FILE]
"""
import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--parquet-dir", required=True)
    ap.add_argument("--codes-file")
    ap.add_argument("--unprofiled-served", action="store_true",
                    help="all is_canonical matrices lacking dimension_structure rows and having a parquet")
    ap.add_argument("--report")
    a = ap.parse_args()
    db = Path(a.db).resolve()
    for anc in [REPO, *REPO.parents]:  # this checkout, or the main checkout above a worktree
        if (anc / "data" / "corpus") in db.parents:
            sys.exit("refusing: --db is inside a repo data/corpus; pass a copy in a temp dir")
    os.environ["TEMPO_STRUCTURE_DB"] = str(db)
    os.environ["TEMPO_STRUCTURE_PARQUET_DIR"] = str(Path(a.parquet_dir).resolve())
    spec = importlib.util.spec_from_file_location("dimstruct", REPO / "13-dimension-structure.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    rconn = duckdb.connect(str(db), read_only=True)
    if a.codes_file:
        codes = [c.strip() for c in Path(a.codes_file).read_text().replace("\n", ",").split(",") if c.strip()]
    elif a.unprofiled_served:
        codes = [r[0] for r in rconn.execute(
            "SELECT matrix_code FROM matrices m WHERE is_canonical AND NOT EXISTS "
            "(SELECT 1 FROM dimension_structure d WHERE d.matrix_code = m.matrix_code) ORDER BY 1").fetchall()]
        codes = [c for c in codes if (m.CORPUS_PARQUET_DIR / f"{c}.parquet").exists()]
    else:
        sys.exit("need --codes-file or --unprofiled-served")
    pconn = duckdb.connect(config={"memory_limit": "2GB"})
    records, failed, dup = [], [], []
    seen = set()
    for code in codes:
        try:
            recs = m.profile_matrix(rconn, pconn, code)
        except Exception as e:
            failed.append({"code": code, "error": str(e)[:150]})
            continue
        for r in recs:
            k = (r["matrix_code"], r["dim_column"])
            if k in seen:
                dup.append(f"{k[0]}.{k[1]}")
                continue
            seen.add(k)
            records.append(r)
    rconn.close()
    w = duckdb.connect(str(db))
    w.execute(m.DDL.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS"))
    done = sorted({r["matrix_code"] for r in records})
    w.execute("DELETE FROM dimension_structure WHERE matrix_code IN (SELECT unnest(?))", [done])
    ins = f"INSERT INTO dimension_structure ({', '.join(m.COLS)}) VALUES ({', '.join('?' for _ in m.COLS)})"
    for r in records:
        w.execute(ins, m.to_row(r))
    n = w.execute("SELECT count(DISTINCT matrix_code) FROM dimension_structure").fetchone()[0]
    w.close()
    rep = {"requested": len(codes), "profiled_matrices": len(done), "dimension_rows": len(records),
           "no_dimensions_or_no_rows": len(codes) - len(done) - len(failed), "failed": failed,
           "duplicate_dim_columns_skipped": sorted(set(dup)), "matrices_with_structure_now": n}
    print(json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in rep.items()}))
    if a.report:
        Path(a.report).write_text(json.dumps(rep, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
