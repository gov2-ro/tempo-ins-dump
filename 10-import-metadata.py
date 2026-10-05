"""
Import / refresh metadata in the DuckDB database

This script imports:
1. contexts: From context.csv
2. matrices: From matrices.csv + JSON metadata + parquet/CSV file stats
3. dimensions: From JSON metadata
4. dimension_options: From JSON metadata

Every processed matrix is *reconciled* against data/2-metas/<CODE>.json: only changed
columns/options are written, so a refreshed dataset gets its new options/periods and
an unchanged one is a no-op.

Usage:
    python 10-import-metadata.py                       # reconcile every matrix that has a JSON
    python 10-import-metadata.py --matrix A,B          # targeted refresh; other matrices untouched
    python 10-import-metadata.py --matrix A --stats-only   # row_count/size/path after conversion
    python 10-import-metadata.py --only-missing        # legacy: only matrices lacking context/dims
    python 10-import-metadata.py --dry-run             # report changes, read-only DB
"""
import argparse
import duckdb
import json
import csv
import sys
from pathlib import Path
from datetime import date, datetime
from typing import List, Dict, Any

# Import configuration and utilities
from duckdb_config import (
    DB_FILE,
    LANG,
    CONTEXT_CSV,
    MATRICES_CSV,
    METAS_DIR,
    CSV_SOURCE_DIR,
    PARQUET_DIR,
    LOGS_DIR,
    TEST_LIMIT,
    validate_inputs,
    sanitize_column_name
)


def import_contexts(conn: duckdb.DuckDBPyConnection) -> int:
    """
    Import contexts from context.csv

    Returns:
        Number of rows imported
    """
    print(f"\n📁 Importing contexts from {CONTEXT_CSV}...")

    # Read and import CSV (note: CSV uses camelCase column names)
    conn.execute(f"""
        INSERT INTO contexts (context_code, parent_code, level, context_name)
        SELECT
            context_code,
            "parentCode" as parent_code,
            level,
            context_name
        FROM read_csv('{CONTEXT_CSV}',
                      header=true,
                      delim=',',
                      auto_detect=true)
        ON CONFLICT (context_code) DO NOTHING
    """)

    count = conn.execute("SELECT COUNT(*) FROM contexts").fetchone()[0]
    print(f"✓ Imported {count} contexts")

    return count


def import_matrices_basic(conn: duckdb.DuckDBPyConnection) -> int:
    """
    Import basic matrix info from matrices.csv

    Returns:
        Number of rows imported
    """
    print(f"\n📁 Importing basic matrix info from {MATRICES_CSV}...")

    # Read and import CSV (just code and name for now)
    conn.execute(f"""
        INSERT INTO matrices (matrix_code, matrix_name)
        SELECT
            code as matrix_code,
            name as matrix_name
        FROM read_csv('{MATRICES_CSV}',
                      header=true,
                      delim=',',
                      auto_detect=true)
        ON CONFLICT (matrix_code) DO NOTHING
    """)

    # Also pick up new datasets from matrices-list.csv (built from JSON metas,
    # may contain codes not yet in matrices.csv from the last full API scrape)
    matrices_list_csv = MATRICES_CSV.parent / "matrices-list.csv"
    if matrices_list_csv.exists():
        conn.execute(f"""
            INSERT INTO matrices (matrix_code, matrix_name)
            SELECT
                filename as matrix_code,
                matrixName as matrix_name
            FROM read_csv('{matrices_list_csv}',
                          header=true,
                          delim=',',
                          auto_detect=true)
            ON CONFLICT (matrix_code) DO NOTHING
        """)

    count = conn.execute("SELECT COUNT(*) FROM matrices").fetchone()[0]
    print(f"✓ Imported {count} matrices (basic info)")

    return count




# ---------------------------------------------------------------------------
# Refresh model (FIX-03 phase 2a)
#
# The metadata JSON in data/2-metas is the source of truth. For every matrix we
# process, the DB rows are *reconciled* against it: only the columns / options that
# differ are written, so an unchanged matrix is a no-op and a refreshed one picks up
# new options and periods (the old "already has dimensions -> skip" guard did not).
#
# DuckDB limitation that shapes the write order: an UPDATE touching an indexed column
# (matrices.context_code / mat_active / mat_max_dim, dimensions.dim_label /
# dim_column_name) is executed as delete+insert and fails the FK check while child
# rows exist. Non-indexed columns, dimension_options and option_count update fine.
# So an indexed change detaches the matrix's dimensions (autocommit, options first),
# applies the update and re-inserts the very same rows (same ids and column names).
# Interrupted between those steps the matrix has no dimensions; the next run (or the
# orchestrator retry) rebuilds them from the metadata JSON.
# ---------------------------------------------------------------------------

INDEXED_MATRIX_COLS = {"context_code", "mat_active", "mat_max_dim"}
STATS_COLS = ("row_count", "file_size_bytes", "parquet_path")


class IdAllocator:
    """MAX+1 ids for dimensions / dimension_options.

    The DB sequences (seq_dimension_id / seq_option_id) lag the real maximum because
    split registration (12-split-datasets.py) allocates MAX+1 itself, so nextval()
    would hand out ids that already exist.
    """

    def __init__(self, conn):
        self.conn = conn
        self._dim = None
        self._opt = None

    def dim_id(self) -> int:
        if self._dim is None:
            self._dim = self.conn.execute(
                "SELECT COALESCE(MAX(dimension_id), 0) FROM dimensions").fetchone()[0]
        self._dim += 1
        return self._dim

    def option_ids(self, n: int) -> int:
        if self._opt is None:
            self._opt = self.conn.execute(
                "SELECT COALESCE(MAX(option_id), 0) FROM dimension_options").fetchone()[0]
        start = self._opt + 1
        self._opt += n
        return start


def load_meta(matrix_code: str) -> Dict[str, Any]:
    json_file = METAS_DIR / f"{matrix_code}.json"
    if not json_file.exists():
        raise FileNotFoundError(f"metadata JSON not found: {json_file}")
    with open(json_file, "r", encoding="utf-8") as f:
        return json.load(f)


def _iso_date(raw):
    """DD-MM-YYYY -> YYYY-MM-DD, None when absent/unparseable."""
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw).strip(), "%d-%m-%Y").date().isoformat()
    except ValueError:
        return None


def _norm(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10]
    if isinstance(v, tuple):
        return list(v)
    return v


def file_stats(conn, matrix_code: str) -> Dict[str, Any]:
    """row_count / file_size_bytes / parquet_path from the corpus parquet (CSV row
    count as a fallback), all None when neither file exists."""
    parquet_file = PARQUET_DIR / f"{matrix_code}.parquet"
    csv_file = CSV_SOURCE_DIR / f"{matrix_code}.csv"
    stats = {"row_count": None, "file_size_bytes": None, "parquet_path": None}
    if parquet_file.exists():
        try:
            stats["row_count"] = conn.execute(
                f"SELECT COUNT(*) FROM read_parquet('{parquet_file}')").fetchone()[0]
            stats["file_size_bytes"] = parquet_file.stat().st_size
            stats["parquet_path"] = str(parquet_file)
        except Exception:
            pass
    elif csv_file.exists():
        try:
            with open(csv_file, "r", encoding="utf-8", errors="replace") as f:
                stats["row_count"] = max(sum(1 for _ in f) - 1, 0)
        except Exception:
            pass
    return stats


def matrix_values(conn, matrix_code: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """The matrices columns this script owns, computed from the metadata JSON."""
    ancestors = data.get("ancestors", [])
    context_code = None
    for ancestor in reversed(ancestors):
        code = ancestor.get("code", "")
        if code and str(code).isdigit():
            context_code = str(code)
            break
    details = data.get("details", {}) or {}
    vals = {
        "context_code": context_code,
        "ancestor_codes": [str(a.get("code", "")) for a in ancestors if a.get("code")],
        "ancestor_path": " > ".join(a.get("name", "") for a in ancestors if a.get("name")),
        "periodicitati": data.get("periodicitati", []),
        "definitie": data.get("definitie"),
        "metodologie": data.get("metodologie"),
        "ultima_actualizare": _iso_date(data.get("ultimaActualizare")),
        "observatii": data.get("observatii"),
        "persoane_responsabile": data.get("persoaneResponsabile"),
        "nom_jud": bool(details.get("nomJud", 0)),
        "nom_loc": bool(details.get("nomLoc", 0)),
        "mat_max_dim": details.get("matMaxDim"),
        "mat_um_spec": bool(details.get("matUMSpec", 0)),
        "mat_siruta": bool(details.get("matSiruta", 0)),
        "mat_caen1": bool(details.get("matCaen1", 0)),
        "mat_caen2": bool(details.get("matCaen2", 0)),
        "mat_reg_j": bool(details.get("matRegJ", 0)),
        "mat_charge": details.get("matCharge"),
        "mat_views": details.get("matViews"),
        "mat_downloads": details.get("matDownloads"),
        "mat_active": bool(details.get("matActive", 1)),
        "mat_time": details.get("matTime"),
    }
    vals.update(file_stats(conn, matrix_code))
    return vals


def _detach_dimensions(conn, matrix_code: str):
    """Snapshot, then delete, a matrix's dimensions + options (autocommit, options first)."""
    dims = conn.execute(
        "SELECT dimension_id, matrix_code, dim_code, dim_label, dim_column_name, option_count "
        "FROM dimensions WHERE matrix_code = ?", [matrix_code]).fetchall()
    opts = conn.execute(
        "SELECT option_id, dimension_id, nom_item_id, option_label, option_offset, parent_id "
        "FROM dimension_options WHERE dimension_id IN "
        "(SELECT dimension_id FROM dimensions WHERE matrix_code = ?)", [matrix_code]).fetchall()
    conn.execute(
        "DELETE FROM dimension_options WHERE dimension_id IN "
        "(SELECT dimension_id FROM dimensions WHERE matrix_code = ?)", [matrix_code])
    conn.execute("DELETE FROM dimensions WHERE matrix_code = ?", [matrix_code])
    return dims, opts


def _reattach_dimensions(conn, dims, opts) -> None:
    if dims:
        conn.executemany(
            "INSERT INTO dimensions (dimension_id, matrix_code, dim_code, dim_label, "
            "dim_column_name, option_count) VALUES (?, ?, ?, ?, ?, ?)", dims)
    if opts:
        conn.executemany(
            "INSERT INTO dimension_options (option_id, dimension_id, nom_item_id, option_label, "
            "option_offset, parent_id) VALUES (?, ?, ?, ?, ?, ?)", opts)


def enrich_matrix_metadata(conn, matrix_code: str, dry_run: bool = False) -> Dict[str, Any]:
    """Reconcile the matrices row with its metadata JSON.

    Creates the row if missing, then updates only the columns that changed. Returns
    {"created": bool, "changed": [cols], "detached": bool}. Raises on any failure.
    """
    data = load_meta(matrix_code)
    result = {"created": False, "changed": [], "detached": False}

    new = matrix_values(conn, matrix_code, data)
    cols = list(new)
    row = conn.execute(
        f"SELECT {', '.join(cols)} FROM matrices WHERE matrix_code = ?", [matrix_code]
    ).fetchone()

    if row is None:
        result["created"] = True
        if dry_run:
            return result
        name = data.get("matrixName") or data.get("name") or matrix_code
        conn.execute("INSERT INTO matrices (matrix_code, matrix_name) VALUES (?, ?)",
                     [matrix_code, name])
        current = {c: None for c in cols}
    else:
        current = dict(zip(cols, row))

    changed = [c for c in cols if _norm(current[c]) != _norm(new[c])]
    result["changed"] = changed
    if not changed or dry_run:
        return result

    has_dims = conn.execute(
        "SELECT COUNT(*) FROM dimensions WHERE matrix_code = ?", [matrix_code]).fetchone()[0] > 0
    saved = None
    if has_dims and INDEXED_MATRIX_COLS & set(changed):
        saved = _detach_dimensions(conn, matrix_code)
        result["detached"] = True

    sets = ", ".join(f"{c} = ?" for c in changed)
    try:
        conn.execute(f"UPDATE matrices SET {sets} WHERE matrix_code = ?",
                     [new[c] for c in changed] + [matrix_code])
    finally:
        if saved is not None:
            _reattach_dimensions(conn, *saved)
    return result


def refresh_stats(conn, matrix_code: str, dry_run: bool = False) -> List[str]:
    """Refresh only row_count / file_size_bytes / parquet_path from the parquet on disk
    (run after conversion: the first enrich saw the previous generation's file)."""
    exists = conn.execute(
        "SELECT 1 FROM matrices WHERE matrix_code = ?", [matrix_code]).fetchone()
    if not exists:
        raise LookupError(f"{matrix_code} is not in matrices")
    new = file_stats(conn, matrix_code)
    row = conn.execute(
        f"SELECT {', '.join(STATS_COLS)} FROM matrices WHERE matrix_code = ?", [matrix_code]
    ).fetchone()
    changed = [c for c, cur in zip(STATS_COLS, row) if _norm(cur) != _norm(new[c])]
    if changed and not dry_run:
        conn.execute(
            f"UPDATE matrices SET {', '.join(c + ' = ?' for c in changed)} WHERE matrix_code = ?",
            [new[c] for c in changed] + [matrix_code])
    return changed


def _dedupe_options(options: list, matrix_code: str, dim_label: str) -> list:
    seen, out = set(), []
    for opt in options:
        nid = opt["nomItemId"]
        if nid in seen:
            print(f"  ⚠ {matrix_code}/{dim_label}: duplicate nomItemId {nid} ignored")
            continue
        seen.add(nid)
        out.append(opt)
    return out


def sync_dimensions(conn, matrix_code: str, ids: IdAllocator,
                    dry_run: bool = False) -> Dict[str, int]:
    """Reconcile dimensions + dimension_options of one matrix with its metadata JSON.

    Position (dim_code) identifies a dimension (INS renames labels between fetches, the
    position is stable). dim_column_name is NOT compared: in the real corpus it was
    canonicalised to the SDMX name (REF_AREA, TIME_PERIOD, ...) after the first import
    and must survive; only a brand-new dimension gets the sanitised legacy name (which
    11-build-sdmx-codes then maps). A changed label replaces the dimension row in place
    (same dimension_id and column name; the label is indexed so UPDATE is not possible).
    Options are diffed by nom_item_id (insert new, delete gone, update changed
    labels/offsets). Other matrices are never touched.
    """
    data = load_meta(matrix_code)
    dims_json = data.get("dimensionsMap", [])
    stats = {"dims_added": 0, "dims_removed": 0, "dims_rebuilt": 0,
             "options_added": 0, "options_removed": 0, "options_updated": 0}
    if not dims_json:
        raise ValueError("no dimensionsMap in metadata")

    existing = {
        r[1]: r for r in conn.execute(
            "SELECT dimension_id, dim_code, dim_label, dim_column_name, option_count "
            "FROM dimensions WHERE matrix_code = ?", [matrix_code]).fetchall()
    }

    def insert_dimension(dim_idx, dim):
        label = dim["label"]
        options = _dedupe_options(dim.get("options", []), matrix_code, label)
        stats["options_added"] += len(options)
        if dry_run:
            return
        dim_id = ids.dim_id()
        conn.execute(
            "INSERT INTO dimensions (dimension_id, matrix_code, dim_code, dim_label, "
            "dim_column_name, option_count) VALUES (?, ?, ?, ?, ?, ?)",
            [dim_id, matrix_code, dim_idx, label, sanitize_column_name(label), len(options)])
        if options:
            start = ids.option_ids(len(options))
            conn.executemany(
                "INSERT INTO dimension_options (option_id, dimension_id, nom_item_id, "
                "option_label, option_offset, parent_id) VALUES (?, ?, ?, ?, ?, ?)",
                [(start + i, dim_id, o["nomItemId"], o["label"], o.get("offset"),
                  o.get("parentId")) for i, o in enumerate(options)])

    # dimensions that no longer exist in the metadata
    for dim_code in sorted(set(existing) - set(range(1, len(dims_json) + 1))):
        stats["dims_removed"] += 1
        if not dry_run:
            conn.execute("DELETE FROM dimension_options WHERE dimension_id = ?",
                         [existing[dim_code][0]])
            conn.execute("DELETE FROM dimensions WHERE dimension_id = ?",
                         [existing[dim_code][0]])

    for dim_idx, dim in enumerate(dims_json, 1):
        label = dim["label"]
        cur = existing.get(dim_idx)
        if cur is None:
            stats["dims_added"] += 1
            insert_dimension(dim_idx, dim)
            continue
        dim_id, _, cur_label, cur_col, cur_count = cur
        if cur_label != label:
            stats["dims_rebuilt"] += 1
            if not dry_run:
                saved = conn.execute(
                    "SELECT option_id, dimension_id, nom_item_id, option_label, option_offset, "
                    "parent_id FROM dimension_options WHERE dimension_id = ?", [dim_id]).fetchall()
                conn.execute("DELETE FROM dimension_options WHERE dimension_id = ?", [dim_id])
                conn.execute("DELETE FROM dimensions WHERE dimension_id = ?", [dim_id])
                conn.execute(
                    "INSERT INTO dimensions (dimension_id, matrix_code, dim_code, dim_label, "
                    "dim_column_name, option_count) VALUES (?, ?, ?, ?, ?, ?)",
                    [dim_id, matrix_code, dim_idx, label, cur_col, cur_count])
                if saved:
                    conn.executemany(
                        "INSERT INTO dimension_options (option_id, dimension_id, nom_item_id, "
                        "option_label, option_offset, parent_id) VALUES (?, ?, ?, ?, ?, ?)", saved)

        options = _dedupe_options(dim.get("options", []), matrix_code, label)
        db_opts = {
            r[0]: r for r in conn.execute(
                "SELECT nom_item_id, option_id, option_label, option_offset, parent_id "
                "FROM dimension_options WHERE dimension_id = ?", [dim_id]).fetchall()
        }
        new_ids = {o["nomItemId"] for o in options}
        gone = [db_opts[n][1] for n in db_opts if n not in new_ids]
        added = [o for o in options if o["nomItemId"] not in db_opts]
        updated = [
            (o, db_opts[o["nomItemId"]][1]) for o in options
            if o["nomItemId"] in db_opts and (
                db_opts[o["nomItemId"]][2] != o["label"]
                or db_opts[o["nomItemId"]][3] != o.get("offset")
                or db_opts[o["nomItemId"]][4] != o.get("parentId"))
        ]
        stats["options_removed"] += len(gone)
        stats["options_added"] += len(added)
        stats["options_updated"] += len(updated)
        if dry_run:
            continue
        if gone:
            conn.executemany("DELETE FROM dimension_options WHERE option_id = ?",
                             [(g,) for g in gone])
        if added:
            start = ids.option_ids(len(added))
            conn.executemany(
                "INSERT INTO dimension_options (option_id, dimension_id, nom_item_id, "
                "option_label, option_offset, parent_id) VALUES (?, ?, ?, ?, ?, ?)",
                [(start + i, dim_id, o["nomItemId"], o["label"], o.get("offset"),
                  o.get("parentId")) for i, o in enumerate(added)])
        for o, option_id in updated:
            conn.execute(
                "UPDATE dimension_options SET option_label = ?, option_offset = ?, "
                "parent_id = ? WHERE option_id = ?",
                [o["label"], o.get("offset"), o.get("parentId"), option_id])
        if cur_count != len(options):
            conn.execute("UPDATE dimensions SET option_count = ? WHERE dimension_id = ?",
                         [len(options), dim_id])
    return stats


def import_dimensions(conn, matrix_code: str, ids: IdAllocator = None) -> int:
    """Back-compat wrapper: reconcile dimensions, return the dimension count."""
    sync_dimensions(conn, matrix_code, ids or IdAllocator(conn))
    return conn.execute(
        "SELECT COUNT(*) FROM dimensions WHERE matrix_code = ?", [matrix_code]).fetchone()[0]


def _reconcile_one(conn, code: str, ids: IdAllocator, dry_run: bool) -> Dict[str, Any]:
    res = enrich_matrix_metadata(conn, code, dry_run=dry_run)
    dim_stats = sync_dimensions(conn, code, ids, dry_run=dry_run)
    res.update(dim_stats)
    return res


def _changed(res: Dict[str, Any]) -> bool:
    return bool(res["created"] or res["changed"] or any(
        res[k] for k in ("dims_added", "dims_removed", "dims_rebuilt",
                         "options_added", "options_removed", "options_updated")))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Import / refresh matrix metadata in DuckDB")
    ap.add_argument("--matrix", metavar="CODE[,CODE,...]",
                    help="Refresh only these matrices (creates missing rows from the "
                         "metadata JSON; no other matrix is touched)")
    ap.add_argument("--only-missing", action="store_true",
                    help="Legacy global behaviour: enrich only matrices without a context "
                         "or dimensions instead of reconciling every matrix with a JSON")
    ap.add_argument("--stats-only", action="store_true",
                    help="Only refresh row_count/file_size_bytes/parquet_path from the "
                         "parquet on disk (requires --matrix; run after conversion)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would change; opens the DB read-only")
    return ap


def main(argv=None):
    """Main execution. Returns 0 on success, 1 on any failure."""
    args = build_parser().parse_args(argv)
    targeted = [c.strip() for c in args.matrix.split(",") if c.strip()] if args.matrix else []
    if args.stats_only and not targeted:
        print("❌ --stats-only requires --matrix")
        return 2

    print("=" * 70)
    print("Import Metadata to DuckDB" + (" [DRY-RUN]" if args.dry_run else ""))
    print("=" * 70)

    if targeted or args.stats_only:
        if not METAS_DIR.exists():
            print(f"\n❌ Metadata directory not found: {METAS_DIR}")
            return 1
    elif not validate_inputs():
        print("\n❌ Input validation failed!")
        return 1

    if not DB_FILE.exists():
        print(f"\n❌ Database not found: {DB_FILE}")
        print(f"   Run: python3 8-setup-duckdb-schema.py")
        return 1

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"metadata-import-{timestamp}.log"
    print(f"\n📊 Connecting to database: {DB_FILE}")
    conn = duckdb.connect(str(DB_FILE), read_only=args.dry_run)
    failed: List[str] = []
    totals = {"created": 0, "changed": 0, "unchanged": 0}

    try:
        if args.stats_only:
            for code in targeted:
                try:
                    cols = refresh_stats(conn, code, dry_run=args.dry_run)
                    print(f"  ✓ {code}: stats {'updated ' + ','.join(cols) if cols else 'unchanged'}")
                except Exception as e:
                    print(f"  ✗ {code}: {e}")
                    failed.append(code)
            return 1 if failed else 0

        if not args.dry_run:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)

        if targeted:
            if not args.dry_run and CONTEXT_CSV.exists():
                try:
                    import_contexts(conn)  # FK target for new matrices; ON CONFLICT DO NOTHING
                except Exception as e:
                    print(f"  ⚠ contexts import skipped: {e}")
            to_process = targeted
        else:
            if not args.dry_run:
                import_contexts(conn)
                import_matrices_basic(conn)
            if args.only_missing:
                to_process = [r[0] for r in conn.execute("""
                    SELECT m.matrix_code FROM matrices m
                    LEFT JOIN dimensions d ON d.matrix_code = m.matrix_code
                    WHERE m.context_code IS NULL OR d.dimension_id IS NULL
                    GROUP BY m.matrix_code, m.context_code
                    ORDER BY m.matrix_code
                """).fetchall()]
            else:
                cols = {r[0] for r in conn.execute("DESCRIBE matrices").fetchall()}
                split_filter = "WHERE COALESCE(is_split, FALSE) = FALSE " if "is_split" in cols else ""
                to_process = [r[0] for r in conn.execute(
                    f"SELECT matrix_code FROM matrices {split_filter}ORDER BY matrix_code"
                ).fetchall() if (METAS_DIR / f"{r[0]}.json").exists()]
            if TEST_LIMIT:
                to_process = to_process[:TEST_LIMIT]

        print(f"\n🔄 Reconciling {len(to_process)} matrices with their metadata JSON...")
        ids = IdAllocator(conn)
        for idx, code in enumerate(to_process, 1):
            try:
                res = _reconcile_one(conn, code, ids, args.dry_run)
            except Exception as e:
                print(f"  ✗ {code}: {e}")
                failed.append(code)
                continue
            if res["created"]:
                totals["created"] += 1
            elif _changed(res):
                totals["changed"] += 1
            else:
                totals["unchanged"] += 1
            if _changed(res) and (targeted or idx <= 10 or idx % 100 == 0):
                detail = {k: v for k, v in res.items() if v and k != "changed"}
                print(f"  ✓ {code}: {'would change' if args.dry_run else 'changed'} "
                      f"{res['changed']} {detail}")
            if idx % 500 == 0:
                print(f"Progress: {idx}/{len(to_process)}")

        summary = (f"\n{'=' * 70}\nImport Summary\n{'=' * 70}\n"
                   f"Matrices processed: {len(to_process)}\n"
                   f"  - Created: {totals['created']}\n  - Changed: {totals['changed']}\n"
                   f"  - Unchanged: {totals['unchanged']}\n  - Failed: {len(failed)}"
                   + (f" ({', '.join(failed[:20])})" if failed else "") + "\n")
        print(summary)
        if not args.dry_run:
            with open(log_file, "w", encoding="utf-8") as log:
                log.write(f"Metadata Import Log - {timestamp}\n{summary}")
    except Exception as e:
        print(f"\n❌ Error during import: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        conn.close()

    if failed:
        print(f"\n⚠️  Import completed with {len(failed)} failures.")
        return 1
    print("\n✅ Import completed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
