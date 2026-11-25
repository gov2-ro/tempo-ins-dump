#!/usr/bin/env python3
"""Remove what a retired split child leaves behind (HZ-5, backlog P3).

Stage 12 replaces a parent's child set. A child code that is not in the new set loses its
`matrices`, `dimensions` and `dataset_splits` rows and its parquet, but not its rows in the
profile tables, nor its view profile and `_index.json` entry. This script removes those.

Rule: a code is live when `matrices` lists it. A row of any other table is deleted when one of
its code columns (matrix_code, sub_matrix_code, parent_matrix_code in dataset_splits,
matrix_a, matrix_b) names a code that is not live. The tables come from information_schema, so
a new table keyed by matrix_code is covered without a change here. The view profile files and
`_index.json` entries of non-live codes are removed too. Parquet files of non-live codes are
only reported (stage 12 owns them).

Writes the DB in DIR/corpus and the view profiles. Run it on a pipeline run's copy, never on the
served generation: it refuses the repository's own data/.

  python scripts/cleanup-retired-children.py --data-dir RUN/data [--dry-run] [--json-out F]
"""
import argparse
import json
import os
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parent.parent

# Code columns, and the tables each applies to (None: every table that has the column).
CODE_COLUMNS = {
    "matrix_code": None,
    "sub_matrix_code": None,
    "parent_matrix_code": {"dataset_splits"},
    "matrix_a": None,
    "matrix_b": None,
}
# `matrices` defines liveness. The others describe contexts or labels, not datasets.
SKIP_TABLES = {"matrices"}


def orphan_tables(conn) -> list[tuple[str, list[str]]]:
    """[(table, [code columns])] for every base table that names datasets."""
    out = []
    for (table,) in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_type = 'BASE TABLE' ORDER BY 1").fetchall():
        if table in SKIP_TABLES:
            continue
        cols = {r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'main' AND table_name = ?", [table]).fetchall()}
        used = [c for c, only in CODE_COLUMNS.items() if c in cols and (only is None or table in only)]
        if used:
            out.append((table, used))
    return out


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def cleanup(data_dir: Path, dry_run: bool = False) -> dict:
    """Remove the leftovers of non-live codes. Returns what was (or would be) removed."""
    corpus = Path(data_dir) / "corpus"
    db_path = corpus / "metadata.duckdb"
    report = {"tables": {}, "codes": [], "view_profiles": [], "index_entries": 0, "orphan_parquet": []}
    conn = duckdb.connect(str(db_path), read_only=dry_run)
    try:
        live = {r[0] for r in conn.execute("SELECT matrix_code FROM matrices").fetchall()}
        retired: set[str] = set()
        for table, cols in orphan_tables(conn):
            cond = " OR ".join(f'("{c}" IS NOT NULL AND "{c}" NOT IN (SELECT matrix_code FROM matrices))'
                               for c in cols)
            hit = conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE {cond}').fetchone()[0]
            if not hit:
                continue
            for c in cols:
                retired |= {r[0] for r in conn.execute(
                    f'SELECT DISTINCT "{c}" FROM "{table}" WHERE "{c}" IS NOT NULL '
                    f'AND "{c}" NOT IN (SELECT matrix_code FROM matrices)').fetchall()}
            report["tables"][table] = hit
            if not dry_run:
                conn.execute(f'DELETE FROM "{table}" WHERE {cond}')   # one autocommit statement each
        report["codes"] = sorted(retired)
    finally:
        conn.close()

    vp_dir = corpus / "view-profiles"
    if vp_dir.is_dir():
        for p in sorted(vp_dir.glob("*.json")):
            if p.name != "_index.json" and p.stem not in live:
                report["view_profiles"].append(p.stem)
                if not dry_run:
                    p.unlink()
        index = vp_dir / "_index.json"
        if index.exists():
            entries = json.loads(index.read_text(encoding="utf-8"))
            kept = [e for e in entries if e.get("code") in live]
            report["index_entries"] = len(entries) - len(kept)
            if report["index_entries"] and not dry_run:
                _atomic_write(index, json.dumps(kept, ensure_ascii=False))
    pq_dir = corpus / "parquet"
    if pq_dir.is_dir():
        report["orphan_parquet"] = sorted(p.stem for p in pq_dir.glob("*.parquet") if p.stem not in live)
    report["codes"] = sorted(set(report["codes"]) | set(report["view_profiles"]))
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", required=True, help="a run copy's data/ (never the served one)")
    ap.add_argument("--dry-run", action="store_true", help="report only")
    ap.add_argument("--json-out", help="write the report here")
    a = ap.parse_args(argv)
    data_dir = Path(a.data_dir).resolve()
    if data_dir == (REPO / "data").resolve():
        ap.error("refusing the repository's own data/: run it on a copy")
    rep = cleanup(data_dir, dry_run=a.dry_run)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(rep, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    verb = "would remove" if a.dry_run else "removed"
    print(f"{verb} rows for {len(rep['codes'])} retired codes: "
          f"{sum(rep['tables'].values())} rows in {len(rep['tables'])} tables, "
          f"{len(rep['view_profiles'])} view profiles, {rep['index_entries']} index entries; "
          f"orphan parquet (reported only): {len(rep['orphan_parquet'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
