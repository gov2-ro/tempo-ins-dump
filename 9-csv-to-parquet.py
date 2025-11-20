"""
Convert CSV files to Parquet format with proper schemas

This script:
1. Reads JSON metadata to get dimension labels
2. Sanitizes labels to create valid SQL column names
3. Reads CSV data (skip header, use nom_item_id values)
4. Writes Parquet files with appropriate schema and types
"""
import duckdb
import json
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Dict

# Import configuration
from duckdb_config import (
    METAS_DIR,
    COMPACT_CSV_DIR,
    PARQUET_DIR,
    LOGS_DIR,
    PARQUET_COMPRESSION,
    PROGRESS_INTERVAL,
    MAX_COLUMN_NAME_LENGTH,
    COLUMN_SUFFIX,
    VALUE_COLUMN,
    TEST_LIMIT,
    ensure_directories,
    sanitize_column_name
)


def load_metadata(matrix_code: str) -> Tuple[List[str], List[str]]:
    """
    Load metadata JSON and extract dimension information

    Args:
        matrix_code: Matrix identifier (e.g., "ACC101B")

    Returns:
        Tuple of (column_names, dimension_labels)
    """
    json_file = METAS_DIR / f"{matrix_code}.json"

    if not json_file.exists():
        raise FileNotFoundError(f"Metadata not found: {json_file}")

    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    dimensions_map = data.get('dimensionsMap', [])

    if not dimensions_map:
        raise ValueError(f"No dimensions found in metadata for {matrix_code}")

    # Extract labels and create column names
    dimension_labels = []
    column_names = []

    for dim in dimensions_map:
        label = dim['label']
        dimension_labels.append(label)
        col_name = sanitize_column_name(label)
        column_names.append(col_name)

    # Add value column
    column_names.append(VALUE_COLUMN)

    return column_names, dimension_labels


def convert_csv_to_parquet(matrix_code: str, conn: duckdb.DuckDBPyConnection) -> Dict:
    """
    Convert a single CSV file to Parquet format

    Args:
        matrix_code: Matrix identifier
        conn: DuckDB connection

    Returns:
        Dict with conversion statistics
    """
    csv_file = COMPACT_CSV_DIR / f"{matrix_code}.csv"
    parquet_file = PARQUET_DIR / f"{matrix_code}.parquet"

    stats = {
        'matrix_code': matrix_code,
        'success': False,
        'rows': 0,
        'csv_size': 0,
        'parquet_size': 0,
        'error': None
    }

    try:
        # Check if CSV exists
        if not csv_file.exists():
            stats['error'] = "CSV file not found"
            return stats

        # Get CSV size
        stats['csv_size'] = csv_file.stat().st_size

        # Load metadata
        try:
            column_names, dimension_labels = load_metadata(matrix_code)
        except Exception as e:
            stats['error'] = f"Metadata error: {e}"
            return stats

        # Build column list for SELECT (all as INTEGER except last as DOUBLE)
        num_dims = len(column_names) - 1  # Exclude value column
        column_casts = []

        for i in range(num_dims):
            column_casts.append(f"CAST(column{i} AS INTEGER) AS {column_names[i]}")

        # Last column is the value
        column_casts.append(f"CAST(column{num_dims} AS DOUBLE) AS {VALUE_COLUMN}")

        # Build SQL query
        select_columns = ",\n    ".join(column_casts)

        sql = f"""
        COPY (
            SELECT
                {select_columns}
            FROM read_csv('{csv_file}',
                          header=false,
                          skip=1,
                          delim=',',
                          auto_detect=true)
        ) TO '{parquet_file}'
        (FORMAT PARQUET, COMPRESSION '{PARQUET_COMPRESSION}');
        """

        # Execute conversion
        conn.execute(sql)

        # Get row count from Parquet file
        count_result = conn.execute(f"SELECT COUNT(*) FROM '{parquet_file}'").fetchone()
        stats['rows'] = count_result[0] if count_result else 0

        # Get Parquet size
        if parquet_file.exists():
            stats['parquet_size'] = parquet_file.stat().st_size
            stats['success'] = True

        return stats

    except Exception as e:
        stats['error'] = str(e)
        return stats


def main():
    """Main execution"""
    print("=" * 70)
    print("CSV to Parquet Conversion")
    print("=" * 70)

    # Ensure directories exist
    ensure_directories()

    # Check for matrix-specific conversion
    if '--matrix' in sys.argv:
        idx = sys.argv.index('--matrix')
        if idx + 1 < len(sys.argv):
            matrix_code = sys.argv[idx + 1]
            matrices = [matrix_code]
            print(f"\n🎯 Converting single matrix: {matrix_code}")
        else:
            print("❌ Error: --matrix flag requires a matrix code")
            return 1
    else:
        # Get all JSON files to process
        json_files = sorted(METAS_DIR.glob("*.json"))
        matrices = [f.stem for f in json_files]

        if TEST_LIMIT:
            matrices = matrices[:TEST_LIMIT]
            print(f"\n⚠️  TEST MODE: Processing only {TEST_LIMIT} files")

        print(f"\n📊 Found {len(matrices)} matrices to convert")

    # Setup logging
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"parquet-conversion-{timestamp}.log"
    print(f"📋 Log file: {log_file}")

    # Connect to DuckDB (in-memory for conversion)
    conn = duckdb.connect()

    # Process matrices
    print(f"\n🔄 Converting CSV files to Parquet...")
    print()

    processed = 0
    skipped = 0
    errors = 0
    total_csv_size = 0
    total_parquet_size = 0

    with open(log_file, 'w', encoding='utf-8') as log:
        log.write(f"CSV to Parquet Conversion Log - {timestamp}\n")
        log.write("=" * 70 + "\n\n")

        for idx, matrix_code in enumerate(matrices, 1):
            # Check if already converted
            parquet_file = PARQUET_DIR / f"{matrix_code}.parquet"
            if parquet_file.exists() and '--force' not in sys.argv:
                skipped += 1
                if idx % PROGRESS_INTERVAL == 0:
                    print(f"Progress: {idx}/{len(matrices)} (processed: {processed}, skipped: {skipped}, errors: {errors})")
                continue

            # Convert file
            stats = convert_csv_to_parquet(matrix_code, conn)

            if stats['success']:
                processed += 1
                total_csv_size += stats['csv_size']
                total_parquet_size += stats['parquet_size']

                compression_ratio = stats['csv_size'] / stats['parquet_size'] if stats['parquet_size'] > 0 else 0

                msg = f"✓ {matrix_code}.parquet ({stats['rows']:,} rows, {stats['parquet_size']:,} bytes, {compression_ratio:.1f}x compression)"
                print(msg)
                log.write(msg + "\n")
            else:
                errors += 1
                msg = f"✗ {matrix_code}: {stats['error']}"
                print(msg)
                log.write(msg + "\n")

            # Progress update
            if idx % PROGRESS_INTERVAL == 0:
                print(f"\nProgress: {idx}/{len(matrices)} (processed: {processed}, skipped: {skipped}, errors: {errors})\n")

        # Summary
        overall_ratio = total_csv_size / total_parquet_size if total_parquet_size > 0 else 0

        summary = f"""
{'=' * 70}
Conversion Summary
{'=' * 70}
Total matrices: {len(matrices)}
Processed: {processed}
Skipped: {skipped}
Errors: {errors}

CSV total size: {total_csv_size:,} bytes ({total_csv_size / (1024**2):.1f} MB)
Parquet total size: {total_parquet_size:,} bytes ({total_parquet_size / (1024**2):.1f} MB)
Overall compression ratio: {overall_ratio:.1f}x

Parquet directory: {PARQUET_DIR}
Log file: {log_file}
"""
        print(summary)
        log.write(summary + "\n")

    conn.close()

    if errors > 0:
        print(f"\n⚠️  Conversion completed with {errors} errors. Check log file for details.")
        return 1
    else:
        print(f"\n✅ Conversion completed successfully!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
