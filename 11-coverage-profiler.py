"""
Coverage & Sparsity Profiler for INS TEMPO datasets.
Measures data completeness across dimensions and writes results to DuckDB.
"""

import duckdb
import json
import os
import time
from collections import Counter

from duckdb_config import DB_FILE
DB_PATH = str(DB_FILE)
FALLBACK_DB = "data/dataset_coverage.duckdb"
CURRENT_YEAR = 2026
PROGRESS_INTERVAL = 200

DDL = """
CREATE TABLE dataset_coverage (
    matrix_code VARCHAR PRIMARY KEY,
    time_dim_column VARCHAR,
    time_min_year INTEGER,
    time_max_year INTEGER,
    time_year_count INTEGER,
    time_gap_years VARCHAR,
    time_granularity VARCHAR,
    geo_dim_column VARCHAR,
    geo_county_count INTEGER,
    geo_has_national BOOLEAN,
    geo_has_locality BOOLEAN,
    geo_level_counts VARCHAR,
    theoretical_max BIGINT,
    actual_rows BIGINT,
    fill_rate DOUBLE,
    freshness_years INTEGER,
    sparse_dims VARCHAR,
    dim_count INTEGER,
    created_at TIMESTAMP DEFAULT current_timestamp
)
"""

COLS = [
    "matrix_code", "time_dim_column", "time_min_year", "time_max_year",
    "time_year_count", "time_gap_years", "time_granularity",
    "geo_dim_column", "geo_county_count", "geo_has_national",
    "geo_has_locality", "geo_level_counts",
    "theoretical_max", "actual_rows", "fill_rate",
    "freshness_years", "sparse_dims", "dim_count",
]

EMPTY_REC = {c: None for c in COLS}


def open_write_conn():
    try:
        conn = duckdb.connect(DB_PATH, read_only=False)
        print(f"Writing to main DB: {DB_PATH}")
        return conn, DB_PATH, True
    except duckdb.IOException:
        print(f"Main DB locked, writing to fallback: {FALLBACK_DB}")
        conn = duckdb.connect(FALLBACK_DB)
        return conn, FALLBACK_DB, False


def load_metadata(rconn):
    print("Loading dimension metadata...")
    dim_type_map = {}
    for dim_id, dtype, cnt in rconn.execute(
        "SELECT do2.dimension_id, dop.dim_type, COUNT(*) as cnt "
        "FROM dimension_options do2 "
        "JOIN dimension_options_parsed dop ON dop.nom_item_id = do2.nom_item_id "
        "GROUP BY do2.dimension_id, dop.dim_type "
        "ORDER BY do2.dimension_id, cnt DESC"
    ).fetchall():
        if dim_id not in dim_type_map:
            dim_type_map[dim_id] = dtype

    dims_by_matrix = {}
    for dim_id, mc, col, opt_count in rconn.execute(
        "SELECT dimension_id, matrix_code, dim_column_name, option_count FROM dimensions"
    ).fetchall():
        dims_by_matrix.setdefault(mc, []).append({
            "dimension_id": dim_id, "column": col,
            "option_count": opt_count, "dim_type": dim_type_map.get(dim_id),
        })

    time_years = {}
    for nid, year, tg in rconn.execute(
        "SELECT nom_item_id, year, time_granularity "
        "FROM dimension_options_parsed WHERE dim_type='time' AND year IS NOT NULL"
    ).fetchall():
        time_years[nid] = (year, tg)

    geo_levels = {}
    for nid, gl in rconn.execute(
        "SELECT nom_item_id, geo_level "
        "FROM dimension_options_parsed WHERE dim_type='geo' AND geo_level IS NOT NULL"
    ).fetchall():
        geo_levels[nid] = gl

    # nom_item_ids per dimension (for fallback when no parquet)
    dim_nids = {}
    for dim_id, nid in rconn.execute(
        "SELECT dimension_id, nom_item_id FROM dimension_options"
    ).fetchall():
        dim_nids.setdefault(dim_id, []).append(nid)

    matrices = rconn.execute(
        "SELECT matrix_code, row_count, parquet_path FROM matrices ORDER BY matrix_code"
    ).fetchall()

    return dims_by_matrix, time_years, geo_levels, dim_nids, matrices


def _pq_query(pconn, sql, ppath):
    """Run a parquet query with proper quoting."""
    full_sql = sql.replace("__PPATH__", ppath.replace("'", "''"))
    return pconn.execute(full_sql)


def profile_dataset(mc, row_count, ppath, dims, time_years, geo_levels, dim_nids, pconn):
    time_dim = next((d for d in dims if d["dim_type"] == "time"), None)
    geo_dim = next((d for d in dims if d["dim_type"] == "geo"), None)
    has_parquet = ppath and os.path.exists(ppath)

    rec = dict(EMPTY_REC)
    rec["matrix_code"] = mc
    rec["actual_rows"] = row_count
    rec["dim_count"] = len(dims)

    # -- Time coverage --
    if time_dim:
        rec["time_dim_column"] = time_dim["column"]
        if has_parquet:
            col = time_dim["column"]
            ids = [r[0] for r in _pq_query(pconn,
                f'SELECT DISTINCT "{col}" FROM read_parquet(\'__PPATH__\')', ppath).fetchall()]
            years = set()
            grans = Counter()
            for tid in ids:
                if tid in time_years:
                    y, tg = time_years[tid]
                    years.add(y)
                    if tg:
                        grans[tg] += 1
            if years:
                rec["time_min_year"] = min(years)
                rec["time_max_year"] = max(years)
                rec["time_year_count"] = len(years)
                gaps = sorted(set(range(min(years), max(years) + 1)) - years)
                rec["time_gap_years"] = json.dumps(gaps) if gaps else None
                rec["freshness_years"] = CURRENT_YEAR - max(years)
            if grans:
                rec["time_granularity"] = grans.most_common(1)[0][0]

    # -- Geo coverage --
    if geo_dim:
        rec["geo_dim_column"] = geo_dim["column"]
        if has_parquet:
            col = geo_dim["column"]
            ids = [r[0] for r in _pq_query(pconn,
                f'SELECT DISTINCT "{col}" FROM read_parquet(\'__PPATH__\')', ppath).fetchall()]
            lc = Counter()
            for gid in ids:
                gl = geo_levels.get(gid)
                if gl:
                    lc[gl] += 1
            rec["geo_county_count"] = lc.get("county", 0)
            rec["geo_has_national"] = lc.get("national", 0) > 0
            rec["geo_has_locality"] = lc.get("locality", 0) > 0
            rec["geo_level_counts"] = json.dumps(dict(lc)) if lc else None
        else:
            # Fallback: estimate geo stats from dimension metadata
            dim_id = geo_dim["dimension_id"]
            nids = dim_nids.get(dim_id, [])
            lc = Counter()
            for nid in nids:
                gl = geo_levels.get(nid)
                if gl:
                    lc[gl] += 1
            if lc:
                rec["geo_county_count"] = lc.get("county", 0)
                rec["geo_has_national"] = lc.get("national", 0) > 0
                rec["geo_has_locality"] = lc.get("locality", 0) > 0
                rec["geo_level_counts"] = json.dumps(dict(lc))

    # -- Fill rate --
    if dims:
        theoretical = 1
        for d in dims:
            oc = d["option_count"]
            if oc and oc > 0:
                theoretical *= oc
        rec["theoretical_max"] = theoretical
        if row_count and theoretical > 0:
            rec["fill_rate"] = round(row_count / theoretical, 6)

    # -- Sparse dims --
    if has_parquet and dims:
        sparse = []
        for d in dims:
            col = d["column"]
            expected = d["option_count"] or 0
            if expected == 0:
                continue
            actual = _pq_query(pconn,
                f'SELECT COUNT(DISTINCT "{col}") FROM read_parquet(\'__PPATH__\')',
                ppath).fetchone()[0]
            ratio = actual / expected if expected > 0 else 1.0
            if ratio < 0.5:
                sparse.append({"dim": col, "actual": actual, "expected": expected,
                               "ratio": round(ratio, 3)})
        rec["sparse_dims"] = json.dumps(sparse) if sparse else None

    return rec


def print_summary(conn):
    print("\n" + "=" * 60)
    print("COVERAGE PROFILER RESULTS")
    print("=" * 60)

    r = conn.execute(
        "SELECT COUNT(*), COUNT(time_min_year), COUNT(geo_dim_column), "
        "ROUND(AVG(fill_rate), 4), ROUND(AVG(freshness_years), 1), "
        "COUNT(sparse_dims) FROM dataset_coverage"
    ).fetchone()
    print(f"\n  Total datasets:   {r[0]}")
    print(f"  With time dim:    {r[1]}")
    print(f"  With geo dim:     {r[2]}")
    print(f"  Avg fill rate:    {r[3]}")
    print(f"  Avg freshness:    {r[4]} years")
    print(f"  Has sparse dims:  {r[5]}")

    print("\n--- Fill Rate Distribution ---")
    for b, c in conn.execute(
        "SELECT CASE "
        "WHEN fill_rate IS NULL THEN 'NULL' "
        "WHEN fill_rate >= 1.0 THEN '100%+' "
        "WHEN fill_rate >= 0.75 THEN '75-99%' "
        "WHEN fill_rate >= 0.5 THEN '50-74%' "
        "WHEN fill_rate >= 0.25 THEN '25-49%' "
        "ELSE '<25%' END, COUNT(*) FROM dataset_coverage GROUP BY 1 ORDER BY 1"
    ).fetchall():
        print(f"  {b:>10}: {c}")

    print("\n--- Freshness Distribution ---")
    for b, c in conn.execute(
        "SELECT CASE "
        "WHEN freshness_years IS NULL THEN 'no time dim' "
        "WHEN freshness_years <= 1 THEN 'current (0-1y)' "
        "WHEN freshness_years <= 3 THEN 'recent (2-3y)' "
        "WHEN freshness_years <= 5 THEN 'aging (4-5y)' "
        "ELSE 'stale (>5y)' END, COUNT(*) FROM dataset_coverage GROUP BY 1 ORDER BY 1"
    ).fetchall():
        print(f"  {b:>16}: {c}")

    print("\n--- Top 5 Largest with Time+Geo ---")
    for r in conn.execute(
        "SELECT matrix_code, time_min_year, time_max_year, time_granularity, "
        "geo_county_count, ROUND(fill_rate, 4), freshness_years "
        "FROM dataset_coverage "
        "WHERE time_min_year IS NOT NULL AND geo_county_count > 0 "
        "ORDER BY actual_rows DESC LIMIT 5"
    ).fetchall():
        print(f"  {r[0]}: {r[1]}-{r[2]} ({r[3]}), {r[4]} counties, fill={r[5]}, fresh={r[6]}y")

    print("\n--- Datasets with Most Time Gaps ---")
    for r in conn.execute(
        "SELECT matrix_code, time_min_year, time_max_year, time_gap_years "
        "FROM dataset_coverage WHERE time_gap_years IS NOT NULL "
        "ORDER BY LENGTH(time_gap_years) DESC LIMIT 5"
    ).fetchall():
        g = r[3][:80] + "..." if len(r[3]) > 80 else r[3]
        print(f"  {r[0]}: {r[1]}-{r[2]}, gaps={g}")

    print("\n--- Stalest Datasets ---")
    for r in conn.execute(
        "SELECT matrix_code, time_max_year, freshness_years "
        "FROM dataset_coverage WHERE freshness_years IS NOT NULL "
        "ORDER BY freshness_years DESC LIMIT 5"
    ).fetchall():
        print(f"  {r[0]}: last_year={r[1]}, stale={r[2]}y")


def main():
    start = time.time()
    # Try write to main DB first; if locked, use fallback
    wconn, write_path, is_main = open_write_conn()
    wconn.execute("DROP TABLE IF EXISTS dataset_coverage")
    wconn.execute(DDL)
    # Read from same conn if main, else open read-only
    if is_main:
        rconn = wconn
    else:
        rconn = duckdb.connect(DB_PATH, read_only=True)
    pconn = duckdb.connect()

    dims_by_matrix, time_years, geo_levels, dim_nids, matrices = load_metadata(rconn)
    total = len(matrices)
    print(f"Processing {total} datasets...")

    results = []
    errors = 0
    placeholders = ", ".join(f"${j+1}" for j in range(len(COLS)))
    insert_sql = f"INSERT INTO dataset_coverage ({', '.join(COLS)}) VALUES ({placeholders})"

    for i, (mc, row_count, ppath) in enumerate(matrices):
        if (i + 1) % PROGRESS_INTERVAL == 0:
            print(f"  [{i+1}/{total}] {time.time() - start:.1f}s elapsed")
        dims = dims_by_matrix.get(mc, [])
        try:
            rec = profile_dataset(mc, row_count, ppath, dims, time_years, geo_levels, dim_nids, pconn)
        except Exception as e:
            errors += 1
            rec = dict(EMPTY_REC)
            rec["matrix_code"] = mc
            rec["actual_rows"] = row_count
            rec["dim_count"] = len(dims)
            if errors <= 5:
                print(f"  ERROR on {mc}: {e}")
        results.append(rec)

    print(f"\nInserting {len(results)} records...")
    for rec in results:
        wconn.execute(insert_sql, [rec[c] for c in COLS])

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.1f}s ({errors} errors)")
    print_summary(wconn)

    if not is_main:
        print(f"\n*** Results in {FALLBACK_DB} (main DB was locked). ***")
        print("To merge later: ATTACH + CREATE TABLE AS SELECT")

    if rconn is not wconn:
        rconn.close()
    pconn.close()
    wconn.close()


if __name__ == "__main__":
    main()
