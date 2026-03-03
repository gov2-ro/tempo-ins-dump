"""
Convert Parquet files from text labels to numeric nom_item_ids

Current parquet files store raw text labels ("Anul 1992", " Cluj") in columns
named *_nom_id. This script converts them to actual integer IDs by:
1. Reading dimension_options table for label → nom_item_id mapping
2. For each matrix, mapping text values to integer IDs
3. Writing new parquet files to parquet-v2/

This enables fast integer JOINs with dimension_options_parsed for the web app.
"""
import duckdb
import sys
import time
from pathlib import Path

# Paths — relative to project root (parent of utils/)
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_FILE = DATA_DIR / "tempo_metadata.duckdb"
PARQUET_DIR = DATA_DIR / "parquet" / "ro"
PARQUET_V2_DIR = DATA_DIR / "parquet-v2" / "ro"
PARQUET_COMPRESSION = 'snappy'
VALUE_COLUMN = 'value'

DEBUG = '--debug' in sys.argv


def build_label_to_id_map(conn):
    """Build a global map: (dimension_id, TRIM(option_label)) → nom_item_id"""
    rows = conn.execute("""
        SELECT dimension_id, TRIM(option_label) as label, nom_item_id
        FROM dimension_options
    """).fetchall()

    lookup = {}
    for dim_id, label, nom_id in rows:
        lookup[(dim_id, label)] = nom_id

    print(f"  Built label→ID lookup: {len(lookup):,} entries")
    return lookup


def convert_matrix(matrix_code, conn, label_map):
    """Convert a single parquet file from text labels to integer IDs.

    Returns dict with stats or error.
    """
    src = PARQUET_DIR / f"{matrix_code}.parquet"
    dst = PARQUET_V2_DIR / f"{matrix_code}.parquet"

    if not src.exists():
        return {'error': f"Source parquet not found: {src}"}

    # Get dimensions for this matrix
    dims = conn.execute("""
        SELECT dimension_id, dim_code, dim_column_name
        FROM dimensions
        WHERE matrix_code = ?
        ORDER BY dim_code
    """, [matrix_code]).fetchall()

    if not dims:
        return {'error': "No dimensions found in metadata"}

    # Read source parquet
    try:
        src_df = conn.execute(f"""
            SELECT * FROM read_parquet('{src}')
        """).fetchdf()
    except Exception as e:
        return {'error': f"Read error: {e}"}

    src_rows = len(src_df)
    if src_rows == 0:
        return {'error': "Empty parquet file"}

    # Convert each dimension column from text to integer ID
    unmapped = {}
    for dim_id, dim_code, col_name in dims:
        if col_name not in src_df.columns:
            return {'error': f"Column '{col_name}' not in parquet (cols: {list(src_df.columns)})"}

        # Build per-dimension lookup
        dim_lookup = {label: nom_id for (d_id, label), nom_id in label_map.items() if d_id == dim_id}

        # Map text values to IDs
        original = src_df[col_name]
        mapped = original.map(lambda v: dim_lookup.get(str(v).strip()) if v is not None else None)

        # Check for unmapped values
        null_mask = mapped.isna() & original.notna()
        null_count = null_mask.sum()
        if null_count > 0:
            bad_vals = original[null_mask].unique()[:5]
            unmapped[col_name] = {'count': int(null_count), 'samples': [str(v) for v in bad_vals]}

        src_df[col_name] = mapped.astype('Int64')

    # Write converted parquet using DuckDB for consistent format
    conn.execute(f"""
        COPY (SELECT * FROM src_df)
        TO '{dst}'
        (FORMAT PARQUET, COMPRESSION '{PARQUET_COMPRESSION}')
    """)

    dst_size = dst.stat().st_size if dst.exists() else 0
    src_size = src.stat().st_size

    return {
        'rows': src_rows,
        'src_size': src_size,
        'dst_size': dst_size,
        'unmapped': unmapped if unmapped else None,
    }


def main():
    print("=" * 70)
    print("Parquet Text → ID Conversion")
    print("=" * 70)

    PARQUET_V2_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  Source: {PARQUET_DIR}")
    print(f"  Output: {PARQUET_V2_DIR}")
    print(f"  DB:     {DB_FILE}")

    # Single matrix mode
    single_matrix = None
    if '--matrix' in sys.argv:
        idx = sys.argv.index('--matrix')
        if idx + 1 < len(sys.argv):
            single_matrix = sys.argv[idx + 1]
            print(f"\n  Single matrix mode: {single_matrix}")

    conn = duckdb.connect(str(DB_FILE), read_only=False)

    # Build global label lookup
    print("\nBuilding label → ID lookup...")
    label_map = build_label_to_id_map(conn)

    # Get list of matrices with parquet files
    if single_matrix:
        matrices = [(single_matrix,)]
    else:
        matrices = conn.execute("""
            SELECT matrix_code
            FROM matrices
            WHERE parquet_path IS NOT NULL
            ORDER BY matrix_code
        """).fetchall()

    total = len(matrices)
    print(f"\nConverting {total} parquet files...\n")

    t0 = time.time()
    success = 0
    errors = 0
    skipped = 0
    total_src = 0
    total_dst = 0
    all_unmapped = {}

    for i, (matrix_code,) in enumerate(matrices, 1):
        # Skip if already converted (unless --force)
        dst = PARQUET_V2_DIR / f"{matrix_code}.parquet"
        if dst.exists() and '--force' not in sys.argv:
            skipped += 1
            continue

        result = convert_matrix(matrix_code, conn, label_map)

        if 'error' in result:
            errors += 1
            print(f"  FAIL {matrix_code}: {result['error']}")
        else:
            success += 1
            total_src += result['src_size']
            total_dst += result['dst_size']

            if result['unmapped']:
                all_unmapped[matrix_code] = result['unmapped']
                if DEBUG:
                    print(f"  WARN {matrix_code}: unmapped values in {list(result['unmapped'].keys())}")

            if DEBUG or i % 100 == 0 or i == total:
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                print(f"  [{i}/{total}] {matrix_code}: {result['rows']:,} rows, "
                      f"{result['src_size']:,}→{result['dst_size']:,} bytes "
                      f"({rate:.0f} files/sec)")

    elapsed = time.time() - t0

    # Update matrices.parquet_path to point to v2
    if success > 0 and not single_matrix:
        conn.execute(f"""
            UPDATE matrices
            SET parquet_path = REPLACE(parquet_path, 'parquet/ro/', 'parquet-v2/ro/')
            WHERE parquet_path LIKE '%parquet/ro/%'
        """)
        print(f"\n  Updated matrices.parquet_path to parquet-v2/")

    # Summary
    print(f"\n{'=' * 70}")
    print(f"Conversion Summary ({elapsed:.1f}s)")
    print(f"{'=' * 70}")
    print(f"  Total:    {total}")
    print(f"  Success:  {success}")
    print(f"  Skipped:  {skipped}")
    print(f"  Errors:   {errors}")
    if total_src > 0:
        print(f"  Size:     {total_src / 1e6:.1f} MB → {total_dst / 1e6:.1f} MB "
              f"({total_dst / total_src * 100:.0f}%)")

    if all_unmapped:
        print(f"\n  Unmapped values in {len(all_unmapped)} files:")
        for mc, cols in list(all_unmapped.items())[:10]:
            for col, info in cols.items():
                print(f"    {mc}.{col}: {info['count']} unmapped, samples: {info['samples']}")
        if len(all_unmapped) > 10:
            print(f"    ... and {len(all_unmapped) - 10} more")

    conn.close()
    return 1 if errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
