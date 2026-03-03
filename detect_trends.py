"""
Agent 1C: Trend & Pattern Detector
Analyzes temporal patterns and notable features in every dataset.
Writes results to dataset_trends table in DuckDB.
"""

import json
import math
import time
import duckdb

DB_PATH = "data/tempo_metadata.duckdb"


def classify_trend(slope_norm, yoy_changes):
    if not yoy_changes:
        return "flat"
    mean_yoy = sum(yoy_changes) / len(yoy_changes)
    if len(yoy_changes) > 1:
        var_yoy = sum((y - mean_yoy) ** 2 for y in yoy_changes) / len(yoy_changes)
        std_yoy = math.sqrt(var_yoy)
        cv_yoy = std_yoy / abs(mean_yoy) if abs(mean_yoy) > 1e-9 else 0
    else:
        cv_yoy = 0
    if cv_yoy > 0.5 and abs(slope_norm) < 0.05:
        return "volatile"
    if slope_norm > 0.02:
        return "increasing"
    if slope_norm < -0.02:
        return "decreasing"
    if cv_yoy > 0.5:
        return "volatile"
    return "flat"


def find_breakpoints(yoy_changes, years):
    if len(yoy_changes) < 3:
        return []
    mean_yoy = sum(yoy_changes) / len(yoy_changes)
    var_yoy = sum((y - mean_yoy) ** 2 for y in yoy_changes) / len(yoy_changes)
    std_yoy = math.sqrt(var_yoy)
    if std_yoy < 1e-9:
        return []
    breakpoints = []
    for i, yoy in enumerate(yoy_changes):
        z = abs((yoy - mean_yoy) / std_yoy)
        if z > 2:
            breakpoints.append(years[i + 1])
    return breakpoints


def process_dataset(conn, matrix_code, parquet_path, time_col, geo_col, time_granularity):
    result = {
        "matrix_code": matrix_code, "trend_direction": None, "trend_slope": None,
        "yoy_growth_latest": None, "max_value_year": None, "min_value_year": None,
        "has_seasonality": None, "breakpoint_years": None, "geo_variance": None,
        "geo_outlier_counties": None,
    }
    if not time_col:
        result["trend_direction"] = "no_time"
        return result

    try:
        query = f"""SELECT dop.year, SUM(p.value) as total
            FROM read_parquet(?) p
            JOIN dimension_options_parsed dop ON p.{time_col} = dop.nom_item_id AND dop.dim_type = 'time'
            WHERE dop.year IS NOT NULL AND p.value IS NOT NULL
            GROUP BY dop.year ORDER BY dop.year"""
        ts = conn.execute(query, [parquet_path]).fetchall()
    except Exception:
        result["trend_direction"] = "no_time"
        return result

    if not ts or len(ts) < 2:
        if ts and len(ts) == 1:
            result["trend_direction"] = "flat"
            result["max_value_year"] = ts[0][0]
            result["min_value_year"] = ts[0][0]
        else:
            result["trend_direction"] = "no_time"
        return result

    years = [r[0] for r in ts]
    totals = [float(r[1]) for r in ts]
    n = len(years)
    mean_x = sum(years) / n
    mean_y = sum(totals) / n

    if abs(mean_y) < 1e-9:
        result["trend_direction"] = "flat"
        result["trend_slope"] = 0.0
        result["max_value_year"] = years[totals.index(max(totals))]
        result["min_value_year"] = years[totals.index(min(totals))]
        return result

    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(years, totals))
    ss_xx = sum((x - mean_x) ** 2 for x in years)
    slope = ss_xy / ss_xx if ss_xx > 0 else 0
    slope_norm = slope / abs(mean_y)

    yoy_changes = []
    for i in range(1, n):
        if abs(totals[i - 1]) > 1e-9:
            yoy_changes.append((totals[i] - totals[i - 1]) / abs(totals[i - 1]) * 100)
        else:
            yoy_changes.append(0.0)

    result["trend_direction"] = classify_trend(slope_norm, yoy_changes)
    result["trend_slope"] = round(slope_norm, 6)
    result["yoy_growth_latest"] = round(yoy_changes[-1], 4) if yoy_changes else None
    result["max_value_year"] = years[totals.index(max(totals))]
    result["min_value_year"] = years[totals.index(min(totals))]

    # Seasonality
    result["has_seasonality"] = False
    if time_granularity in ("quarterly", "monthly"):
        try:
            period_col = "quarter" if time_granularity == "quarterly" else "month"
            sq = f"""SELECT dop.{period_col} as period, SUM(p.value) as total
                FROM read_parquet(?) p
                JOIN dimension_options_parsed dop ON p.{time_col} = dop.nom_item_id AND dop.dim_type = 'time'
                WHERE dop.{period_col} IS NOT NULL AND p.value IS NOT NULL
                GROUP BY dop.{period_col} ORDER BY dop.{period_col}"""
            seasonal_data = conn.execute(sq, [parquet_path]).fetchall()
            if seasonal_data and len(seasonal_data) > 1:
                period_totals = [float(r[1]) for r in seasonal_data]
                pm = sum(period_totals) / len(period_totals)
                if abs(pm) > 1e-9:
                    pv = sum((t - pm) ** 2 for t in period_totals) / len(period_totals)
                    cv = math.sqrt(pv) / abs(pm)
                    result["has_seasonality"] = cv > 0.3
        except Exception:
            pass

    # Breakpoints
    bp = find_breakpoints(yoy_changes, years)
    result["breakpoint_years"] = json.dumps(bp) if bp else "[]"

    # Geo analysis
    if geo_col:
        try:
            gq = f"""SELECT dop_g.geo_name_clean, SUM(p.value) as total
                FROM read_parquet(?) p
                JOIN dimension_options_parsed dop_t ON p.{time_col} = dop_t.nom_item_id AND dop_t.dim_type = 'time'
                JOIN dimension_options_parsed dop_g ON p.{geo_col} = dop_g.nom_item_id AND dop_g.dim_type = 'geo'
                WHERE dop_t.year = ? AND dop_g.geo_level = 'county' AND p.value IS NOT NULL
                GROUP BY dop_g.geo_name_clean"""
            geo_data = conn.execute(gq, [parquet_path, years[-1]]).fetchall()
            if geo_data and len(geo_data) > 1:
                geo_vals = [float(r[1]) for r in geo_data if r[1] is not None]
                if geo_vals:
                    gm = sum(geo_vals) / len(geo_vals)
                    gv = sum((v - gm) ** 2 for v in geo_vals) / len(geo_vals)
                    gs = math.sqrt(gv)
                    result["geo_variance"] = round(gv, 4)
                    threshold = gm + 2 * gs
                    outliers = [r[0] for r in geo_data if r[1] is not None and float(r[1]) > threshold]
                    result["geo_outlier_counties"] = json.dumps(outliers) if outliers else "[]"
        except Exception:
            pass

    return result


def _insert_batch(conn, batch):
    for r in batch:
        conn.execute(
            "INSERT INTO dataset_trends VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [r["matrix_code"], r["trend_direction"], r["trend_slope"], r["yoy_growth_latest"],
             r["max_value_year"], r["min_value_year"], r["has_seasonality"],
             r["breakpoint_years"], r["geo_variance"], r["geo_outlier_counties"]])


def main():
    t0 = time.time()
    conn = duckdb.connect(DB_PATH, read_only=False)

    conn.execute("DROP TABLE IF EXISTS dataset_trends")
    conn.execute("""CREATE TABLE dataset_trends (
        matrix_code VARCHAR PRIMARY KEY, trend_direction VARCHAR, trend_slope DOUBLE,
        yoy_growth_latest DOUBLE, max_value_year INTEGER, min_value_year INTEGER,
        has_seasonality BOOLEAN, breakpoint_years VARCHAR, geo_variance DOUBLE,
        geo_outlier_counties VARCHAR)""")

    matrices = conn.execute(
        "SELECT m.matrix_code, m.parquet_path FROM matrices m WHERE m.parquet_path IS NOT NULL ORDER BY m.matrix_code"
    ).fetchall()
    total = len(matrices)
    print(f"Processing {total} datasets...")

    dim_info = conn.execute("""
        SELECT d.matrix_code, d.dim_column_name, dop.dim_type
        FROM dimensions d
        JOIN dimension_options dopt ON dopt.dimension_id = d.dimension_id
        JOIN dimension_options_parsed dop ON dop.nom_item_id = dopt.nom_item_id
        GROUP BY d.matrix_code, d.dim_column_name, dop.dim_type""").fetchall()

    dim_map = {}
    for mc, col, dtype in dim_info:
        if mc not in dim_map:
            dim_map[mc] = {}
        dim_map[mc][dtype] = col

    gran_map = {}
    for row in conn.execute("SELECT matrix_code, time_granularity FROM matrix_profiles").fetchall():
        gran_map[row[0]] = row[1]

    processed = 0
    errors = 0
    batch = []

    for matrix_code, parquet_path in matrices:
        dims = dim_map.get(matrix_code, {})
        time_col = dims.get("time")
        geo_col = dims.get("geo")
        time_gran = gran_map.get(matrix_code)

        try:
            result = process_dataset(conn, matrix_code, parquet_path, time_col, geo_col, time_gran)
            batch.append(result)
        except Exception:
            errors += 1
            batch.append({
                "matrix_code": matrix_code, "trend_direction": "no_time", "trend_slope": None,
                "yoy_growth_latest": None, "max_value_year": None, "min_value_year": None,
                "has_seasonality": None, "breakpoint_years": None, "geo_variance": None,
                "geo_outlier_counties": None})

        processed += 1
        if len(batch) >= 100:
            _insert_batch(conn, batch)
            batch = []
        if processed % 200 == 0:
            elapsed = time.time() - t0
            rate = processed / elapsed if elapsed > 0 else 0
            print(f"  [{processed}/{total}] {elapsed:.1f}s elapsed, {rate:.0f}/s, {errors} errors")

    if batch:
        _insert_batch(conn, batch)

    elapsed = time.time() - t0
    print(f"\nDone: {processed} datasets in {elapsed:.1f}s ({errors} errors)")

    print("\n=== Trend Direction Summary ===")
    print(conn.execute("""SELECT trend_direction, COUNT(*) as cnt FROM dataset_trends
        GROUP BY trend_direction ORDER BY cnt DESC""").df().to_string(index=False))

    print("\n=== Seasonality ===")
    print(conn.execute("""SELECT has_seasonality, COUNT(*) as cnt FROM dataset_trends
        WHERE has_seasonality IS NOT NULL GROUP BY has_seasonality""").df().to_string(index=False))

    geo_outlier_cnt = conn.execute("""SELECT COUNT(*) FROM dataset_trends
        WHERE geo_outlier_counties IS NOT NULL AND geo_outlier_counties != '[]'""").fetchone()[0]
    print(f"\n=== Datasets with geo outliers: {geo_outlier_cnt} ===")

    print("\n=== Sample known datasets ===")
    for mc in ["ACC101B", "POP105A", "IND101B", "TUR101A", "AGR101A"]:
        row = conn.execute("SELECT * FROM dataset_trends WHERE matrix_code = ?", [mc]).fetchone()
        if row:
            print(f"  {mc}: direction={row[1]}, slope={row[2]}, yoy_latest={row[3]}, "
                  f"max_yr={row[4]}, min_yr={row[5]}, seasonal={row[6]}, "
                  f"breakpoints={row[7]}, geo_var={row[8]}")

    conn.close()


if __name__ == "__main__":
    main()
