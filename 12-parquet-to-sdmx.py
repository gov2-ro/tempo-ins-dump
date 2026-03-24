#!/usr/bin/env python3
"""
12-parquet-to-sdmx.py — Transform parquet-v2 files to SDMX-native parquet-v3.

Changes:
  1. Column names:  macroregiuni_..._nom_id → REF_AREA  (from sdmx_column_map)
  2. Cell values:   21295 (nomItemId)       → "Bihor"   (from sdmx_codes)
  3. Value column:  value → OBS_VALUE

Input:  data/parquet-v2/{lang}/*.parquet   (integer nomItemIds)
        data/tempo_metadata.duckdb         (sdmx_codes + sdmx_column_map tables)
Output: data/parquet-v3/{lang}/*.parquet   (SDMX column names, human-readable values)

Usage:
    python 12-parquet-to-sdmx.py                    # process all
    python 12-parquet-to-sdmx.py --matrix ACC101B   # single dataset
    python 12-parquet-to-sdmx.py --force             # re-process existing
    python 12-parquet-to-sdmx.py --debug             # verbose logging
    python 12-parquet-to-sdmx.py --lang en           # English parquets
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import duckdb

from duckdb_config import DB_FILE, PARQUET_COMPRESSION

# ── Config ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"


# ── Lookup builders ──────────────────────────────────────────────────────────

def build_id_to_value_map(conn) -> dict:
    """Build global map: nom_item_id → sdmx_value (string)."""
    rows = conn.execute("""
        SELECT nom_item_id, sdmx_value
        FROM sdmx_codes
    """).fetchall()
    lookup = {nom_id: val for nom_id, val in rows}
    log.info(f"  ID→value lookup: {len(lookup):,} entries")
    return lookup


def build_column_map(conn) -> dict:
    """Build per-matrix column rename map: {matrix_code: {old_col: new_col}}."""
    rows = conn.execute("""
        SELECT matrix_code, old_column_name, sdmx_column_name
        FROM sdmx_column_map
    """).fetchall()
    cmap = {}
    for mc, old, new in rows:
        cmap.setdefault(mc, {})[old] = new
    log.info(f"  Column map: {len(cmap):,} matrices")
    return cmap


# ── Per-matrix conversion ───────────────────────────────────────────────────

def convert_matrix(
    matrix_code: str,
    conn,
    id_to_value: dict,
    col_map: dict,
    src_dir: Path,
    dst_dir: Path,
    debug: bool = False,
) -> dict:
    """Convert one parquet file from v2 (nomItemIds) to v3 (SDMX values).

    Returns dict with stats or error.
    """
    src = src_dir / f"{matrix_code}.parquet"
    dst = dst_dir / f"{matrix_code}.parquet"

    if not src.exists():
        return {"error": f"Source not found: {src.name}"}

    # Get column rename map for this matrix
    rename = col_map.get(matrix_code)
    if not rename:
        return {"error": "No column map in sdmx_column_map"}

    # Read source parquet into pandas DataFrame
    try:
        df = conn.execute(f"""
            SELECT * FROM read_parquet('{src}')
        """).fetchdf()
    except Exception as e:
        return {"error": f"Read error: {e}"}

    src_rows = len(df)
    if src_rows == 0:
        return {"error": "Empty parquet"}

    # Convert dimension columns: nomItemId integers → sdmx_value strings
    unmapped_cols = {}
    value_col = None

    for col in list(df.columns):
        if col == "value":
            value_col = col
            continue

        # This is a dimension column — convert integer IDs to string values
        unmapped_count = 0
        unmapped_samples = []

        def map_id(v):
            nonlocal unmapped_count, unmapped_samples
            if v is None or (hasattr(v, '__class__') and v.__class__.__name__ == 'NAType'):
                return None
            try:
                int_v = int(v)
            except (ValueError, TypeError):
                # Already a string? Keep as-is
                return str(v).strip()
            result = id_to_value.get(int_v)
            if result is None:
                unmapped_count += 1
                if len(unmapped_samples) < 5:
                    unmapped_samples.append(int_v)
                return str(int_v)  # fallback
            return result

        df[col] = df[col].map(map_id)

        if unmapped_count > 0:
            unmapped_cols[col] = {
                "count": unmapped_count,
                "samples": unmapped_samples,
            }
            if debug:
                log.debug(
                    f"  [{matrix_code}] {col}: {unmapped_count} unmapped IDs, "
                    f"samples: {unmapped_samples[:3]}"
                )

    # Rename columns: old_name → SDMX name
    new_columns = {}
    for col in df.columns:
        new_name = rename.get(col, col)
        new_columns[col] = new_name
    df = df.rename(columns=new_columns)

    # Write output parquet via DuckDB
    try:
        conn.execute(f"""
            COPY (SELECT * FROM df)
            TO '{dst}'
            (FORMAT PARQUET, COMPRESSION '{PARQUET_COMPRESSION}')
        """)
    except Exception as e:
        return {"error": f"Write error: {e}"}

    dst_size = dst.stat().st_size if dst.exists() else 0
    src_size = src.stat().st_size

    return {
        "rows": src_rows,
        "src_size": src_size,
        "dst_size": dst_size,
        "unmapped": unmapped_cols if unmapped_cols else None,
        "columns": list(df.columns),
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Convert parquet-v2 to SDMX-native parquet-v3")
    parser.add_argument("--matrix", help="Process a single matrix (e.g. ACC101B)")
    parser.add_argument("--lang", default="ro", choices=["ro", "en"], help="Language (default: ro)")
    parser.add_argument("--force", action="store_true", help="Re-process existing files")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    parser.add_argument("--limit", type=int, help="Process only first N matrices (for testing)")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    src_dir = DATA_DIR / "parquet-v2" / args.lang
    dst_dir = DATA_DIR / "parquet-v3" / args.lang
    dst_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"Source: {src_dir}")
    log.info(f"Output: {dst_dir}")
    log.info(f"DB:     {DB_FILE}")

    conn = duckdb.connect(str(DB_FILE), read_only=True)

    try:
        # Build lookup tables
        log.info("Building lookups...")
        id_to_value = build_id_to_value_map(conn)
        col_map = build_column_map(conn)

        # Get list of parquet files to process
        if args.matrix:
            matrices = [args.matrix]
        else:
            # All parquet-v2 files that have column mappings
            all_files = sorted(f.stem for f in src_dir.glob("*.parquet"))
            matrices = [m for m in all_files if m in col_map]
            unmapped = [m for m in all_files if m not in col_map]
            if unmapped:
                log.warning(f"  {len(unmapped)} parquet files have no column map (skipped)")
            if args.limit:
                matrices = matrices[:args.limit]

        total = len(matrices)
        log.info(f"Processing {total} parquet files...\n")

        t0 = time.time()
        success = 0
        errors = 0
        skipped = 0
        total_src = 0
        total_dst = 0
        total_unmapped = 0

        for i, matrix_code in enumerate(matrices, 1):
            # Skip if already converted
            dst = dst_dir / f"{matrix_code}.parquet"
            if dst.exists() and not args.force:
                skipped += 1
                continue

            result = convert_matrix(
                matrix_code, conn, id_to_value, col_map,
                src_dir, dst_dir, debug=args.debug,
            )

            if "error" in result:
                errors += 1
                log.warning(f"  [{matrix_code}] ERROR: {result['error']}")
            else:
                success += 1
                total_src += result["src_size"]
                total_dst += result["dst_size"]
                if result.get("unmapped"):
                    total_unmapped += sum(v["count"] for v in result["unmapped"].values())

            # Progress
            if not args.matrix and i % 200 == 0:
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                log.info(f"  Progress: {i}/{total} ({rate:.0f}/s, {errors} errors)")

        elapsed = time.time() - t0

        # Summary
        print(f"\n{'─' * 60}")
        print(f"Done in {elapsed:.1f}s")
        print(f"  Success:  {success}")
        print(f"  Skipped:  {skipped}")
        print(f"  Errors:   {errors}")
        if total_src > 0:
            print(f"  Size:     {total_src / 1024 / 1024:.1f} MB → {total_dst / 1024 / 1024:.1f} MB "
                  f"({total_dst / total_src:.1%})")
        if total_unmapped > 0:
            print(f"  Unmapped: {total_unmapped} cell values fell back to str(nomItemId)")

        # Show a sample conversion
        if success > 0 and not args.matrix:
            sample = matrices[0] if matrices else None
            if sample:
                print(f"\n  Sample: {sample}")
                try:
                    sample_df = conn.execute(f"""
                        SELECT * FROM read_parquet('{dst_dir / sample}.parquet') LIMIT 3
                    """).fetchdf()
                    print(f"  Columns: {list(sample_df.columns)}")
                    print(sample_df.to_string(index=False))
                except Exception:
                    pass

        # Single matrix detail
        if args.matrix and success > 0:
            print(f"\n  Output: {dst_dir / args.matrix}.parquet")
            try:
                df = conn.execute(f"""
                    SELECT * FROM read_parquet('{dst_dir / args.matrix}.parquet') LIMIT 5
                """).fetchdf()
                print(f"  Columns: {list(df.columns)}")
                print(df.to_string(index=False))
            except Exception:
                pass

    finally:
        conn.close()


if __name__ == "__main__":
    main()
