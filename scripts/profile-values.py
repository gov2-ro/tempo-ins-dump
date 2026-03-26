#!/usr/bin/env python3
"""
Rebuild dataset_value_profiles for all datasets with parquet files.
Adapted from the phase1-value-profiler agent spec for v3 (OBS_VALUE column).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb
from duckdb_config import DB_FILE

conn = duckdb.connect(str(DB_FILE))

conn.execute("DROP TABLE IF EXISTS dataset_value_profiles")
conn.execute("""
    CREATE TABLE dataset_value_profiles (
        matrix_code      VARCHAR PRIMARY KEY,
        row_count        BIGINT,
        val_min          DOUBLE,
        val_max          DOUBLE,
        val_mean         DOUBLE,
        val_median       DOUBLE,
        val_stddev       DOUBLE,
        val_p25          DOUBLE,
        val_p75          DOUBLE,
        null_pct         DOUBLE,
        zero_pct         DOUBLE,
        negative_pct     DOUBLE,
        coeff_variation  DOUBLE,
        magnitude        VARCHAR,
        distribution_shape VARCHAR
    )
""")

matrices = conn.execute("""
    SELECT matrix_code, parquet_path FROM matrices
    WHERE parquet_path IS NOT NULL AND is_canonical = TRUE
    ORDER BY matrix_code
""").fetchall()

print(f"Profiling {len(matrices)} datasets...")
t0 = time.time()
success = 0
errors = 0

for i, (mc, ppath) in enumerate(matrices, 1):
    if not Path(ppath).exists():
        errors += 1
        continue

    try:
        # Detect value column name
        cols = {r[0] for r in conn.execute(
            f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet('{ppath}'))"
        ).fetchall()}
        val_col = "OBS_VALUE" if "OBS_VALUE" in cols else "value"

        row = conn.execute(f"""
            SELECT
                COUNT(*) as row_count,
                MIN(CAST("{val_col}" AS DOUBLE)) as val_min,
                MAX(CAST("{val_col}" AS DOUBLE)) as val_max,
                AVG(CAST("{val_col}" AS DOUBLE)) as val_mean,
                APPROX_QUANTILE(CAST("{val_col}" AS DOUBLE), 0.5) as val_median,
                STDDEV(CAST("{val_col}" AS DOUBLE)) as val_stddev,
                APPROX_QUANTILE(CAST("{val_col}" AS DOUBLE), 0.25) as val_p25,
                APPROX_QUANTILE(CAST("{val_col}" AS DOUBLE), 0.75) as val_p75,
                COUNT(*) FILTER (WHERE "{val_col}" IS NULL) * 100.0 / COUNT(*) as null_pct,
                COUNT(*) FILTER (WHERE CAST("{val_col}" AS DOUBLE) = 0) * 100.0 / COUNT(*) as zero_pct,
                COUNT(*) FILTER (WHERE CAST("{val_col}" AS DOUBLE) < 0) * 100.0 / COUNT(*) as negative_pct
            FROM read_parquet('{ppath}')
        """).fetchone()

        row_count, val_min, val_max, val_mean, val_median, val_stddev, val_p25, val_p75, null_pct, zero_pct, negative_pct = row

        # Derived metrics
        cv = (val_stddev / val_mean) if val_mean and val_stddev and val_mean != 0 else None

        abs_max = max(abs(val_min or 0), abs(val_max or 0))
        if abs_max < 1000:
            magnitude = "units"
        elif abs_max < 1_000_000:
            magnitude = "thousands"
        elif abs_max < 1_000_000_000:
            magnitude = "millions"
        else:
            magnitude = "billions"

        if (null_pct or 0) > 50:
            dist = "sparse"
        elif val_stddev and val_stddev > 0 and val_mean is not None and val_median is not None:
            skew = (val_mean - val_median) / val_stddev
            if abs(skew) < 0.5:
                dist = "normal"
            elif skew > 0.5:
                dist = "right_skewed"
            elif skew < -0.5:
                dist = "left_skewed"
            else:
                dist = "normal"
        elif cv is not None and cv < 0.1:
            dist = "uniform"
        else:
            dist = None

        conn.execute("""
            INSERT INTO dataset_value_profiles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, [mc, row_count, val_min, val_max, val_mean, val_median, val_stddev,
              val_p25, val_p75, null_pct, zero_pct, negative_pct, cv, magnitude, dist])
        success += 1

    except Exception as e:
        errors += 1
        if errors <= 5:
            print(f"  Error {mc}: {e}")

    if i % 500 == 0:
        print(f"  Progress: {i}/{len(matrices)} ({success} ok, {errors} err)")

elapsed = time.time() - t0
print(f"\nDone in {elapsed:.1f}s: {success} profiled, {errors} errors")

# Summary
for shape, cnt in conn.execute(
    "SELECT distribution_shape, COUNT(*) FROM dataset_value_profiles GROUP BY 1 ORDER BY 2 DESC"
).fetchall():
    print(f"  {shape}: {cnt}")

conn.close()
