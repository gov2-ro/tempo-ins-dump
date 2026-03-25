#!/usr/bin/env python3
"""Generate SDMX Dashboard Generator YAML configs for INS TEMPO datasets.

Usage:
    python generate_sdmx_yaml.py                        # all datasets
    python generate_sdmx_yaml.py ACC102B POP101A        # specific codes
    python generate_sdmx_yaml.py --limit 20             # first 20 datasets
    python generate_sdmx_yaml.py --base-url http://my-server:8080

Output: sdmx-dashboards/{code}.yaml
"""
import argparse
import sys
from pathlib import Path

import duckdb
import yaml  # PyYAML

PROJECT_ROOT = Path(__file__).parent
DB_PATH = PROJECT_ROOT / "data" / "tempo_metadata.duckdb"
PARQUET_DIR = PROJECT_ROOT / "data" / "parquet-v3" / "ro"
OUT_DIR = PROJECT_ROOT / "data" / "sdmx-dashboards"

DEFAULT_BASE_URL = "http://localhost:8080"

# SDMX concept → chart role hint
CHART_TYPE_BY_ARCHETYPE = {
    "geo_time": "MAP",
    "time_series": "LINES",
    "demographic": "BARS",
    "time_residence": "LINES",
}

# Which concept to use as legend
LEGEND_PRIORITY = ["REF_AREA", "CATEGORY", "ECON_ACTIVITY"]


def preferred_legend(dim_cols: list[str]) -> str:
    for pref in LEGEND_PRIORITY:
        if pref in dim_cols:
            return pref
    # Fall back to first non-time, non-unit dim
    for col in dim_cols:
        if col not in ("TIME_PERIOD", "UNIT_MEASURE"):
            return col
    return dim_cols[0]


def guess_chart_type(archetype: str | None, dim_cols: list[str]) -> str:
    if archetype and archetype in CHART_TYPE_BY_ARCHETYPE:
        return CHART_TYPE_BY_ARCHETYPE[archetype]
    if "REF_AREA" in dim_cols:
        return "MAP"
    if "TIME_PERIOD" in dim_cols:
        return "LINES"
    return "BARS"


def generate_yaml(
    matrix_code: str,
    matrix_name: str,
    archetype: str | None,
    dim_cols: list[str],
    base_url: str,
    last_n: int = 10,
) -> dict:
    chart_type = guess_chart_type(archetype, dim_cols)
    legend = preferred_legend(dim_cols)

    data_url = f"{base_url}/sdmx/2.1/data/INS,{matrix_code}/.?lastNObservations={last_n}"
    dsd_url = f"{base_url}/sdmx/2.1/datastructure/INS/{matrix_code}/1.0"
    flow_url = f"{base_url}/sdmx/2.1/dataflow/INS/{matrix_code}/1.0"

    return {
        "DashID": f"INS_{matrix_code}",
        "Title": matrix_name,
        "Rows": [
            {
                "Row": 0,
                "chartType": chart_type,
                "Title": matrix_name,
                "DATA": data_url,
                "dsdLink": dsd_url,
                "metadataLink": flow_url,
                "xAxisConcept": "TIME_PERIOD" if "TIME_PERIOD" in dim_cols else dim_cols[0],
                "yAxisConcept": "OBS_VALUE",
                "legendConcept": legend,
            }
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Generate SDMX Dashboard YAML files")
    parser.add_argument("codes", nargs="*", help="Dataset codes (default: all)")
    parser.add_argument("--limit", type=int, default=0, help="Max number of datasets to process")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--last-n", type=int, default=10, help="lastNObservations param")
    parser.add_argument("--skip-splits", action="store_true", help="Skip split sub-datasets")
    args = parser.parse_args()

    conn = duckdb.connect(str(DB_PATH), read_only=True)

    if args.codes:
        placeholders = ",".join("?" * len(args.codes))
        rows = conn.execute(f"""
            SELECT m.matrix_code, m.matrix_name, mp.archetype, m.is_split
            FROM matrices m
            LEFT JOIN matrix_profiles mp ON mp.matrix_code = m.matrix_code
            WHERE m.matrix_code IN ({placeholders})
            ORDER BY m.matrix_code
        """, args.codes).fetchall()
    else:
        limit_sql = f"LIMIT {args.limit}" if args.limit > 0 else ""
        rows = conn.execute(f"""
            SELECT m.matrix_code, m.matrix_name, mp.archetype, m.is_split
            FROM matrices m
            LEFT JOIN matrix_profiles mp ON mp.matrix_code = m.matrix_code
            ORDER BY m.matrix_code
            {limit_sql}
        """).fetchall()

    OUT_DIR.mkdir(exist_ok=True)

    generated = 0
    skipped = 0

    for matrix_code, matrix_name, archetype, is_split in rows:
        if args.skip_splits and is_split:
            skipped += 1
            continue

        # Check parquet exists
        parquet = PARQUET_DIR / f"{matrix_code}.parquet"
        if not parquet.exists():
            print(f"  SKIP {matrix_code}: no parquet file", file=sys.stderr)
            skipped += 1
            continue

        # Get dimensions
        dims = conn.execute("""
            SELECT dim_column_name FROM dimensions
            WHERE matrix_code = ? ORDER BY dim_code
        """, [matrix_code]).fetchall()
        dim_cols = [d[0] for d in dims]

        if not dim_cols:
            print(f"  SKIP {matrix_code}: no dimensions", file=sys.stderr)
            skipped += 1
            continue

        config = generate_yaml(
            matrix_code=matrix_code,
            matrix_name=matrix_name or matrix_code,
            archetype=archetype,
            dim_cols=dim_cols,
            base_url=args.base_url,
            last_n=args.last_n,
        )

        out_path = OUT_DIR / f"{matrix_code}.yaml"
        with open(out_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        generated += 1
        if generated % 100 == 0:
            print(f"  Generated {generated}...")

    print(f"\nDone: {generated} YAML files → {OUT_DIR}/")
    if skipped:
        print(f"Skipped: {skipped}")


if __name__ == "__main__":
    main()
