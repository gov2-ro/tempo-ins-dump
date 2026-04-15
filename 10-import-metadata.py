"""
Import metadata into DuckDB database

This script imports:
1. contexts: From context.csv
2. matrices: From matrices.csv + JSON metadata + CSV file stats
3. dimensions: From JSON metadata
4. dimension_options: From JSON metadata
"""
import duckdb
import json
import csv
import sys
from pathlib import Path
from datetime import datetime
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


def enrich_matrix_metadata(conn: duckdb.DuckDBPyConnection, matrix_code: str) -> bool:
    """
    Enrich matrix metadata from JSON file

    Args:
        conn: DuckDB connection
        matrix_code: Matrix identifier

    Returns:
        True if successful, False otherwise
    """
    json_file = METAS_DIR / f"{matrix_code}.json"

    if not json_file.exists():
        return False

    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Extract ancestors
        ancestors = data.get('ancestors', [])
        ancestor_codes = [str(a.get('code', '')) for a in ancestors if a.get('code')]
        ancestor_path = " > ".join([a.get('name', '') for a in ancestors if a.get('name')])

        # Determine context_code (last ancestor with non-empty code that's numeric)
        context_code = None
        for ancestor in reversed(ancestors):
            code = ancestor.get('code', '')
            if code and code.isdigit():
                context_code = code
                break

        # Extract other metadata
        periodicitati = data.get('periodicitati', [])
        definitie = data.get('definitie')
        metodologie = data.get('metodologie')
        observatii = data.get('observatii')
        persoane_responsabile = data.get('persoaneResponsabile')

        # Parse ultima_actualizare
        ultima_actualizare = data.get('ultimaActualizare')
        if ultima_actualizare:
            try:
                # Convert DD-MM-YYYY to YYYY-MM-DD
                parts = ultima_actualizare.split('-')
                if len(parts) == 3:
                    ultima_actualizare = f"{parts[2]}-{parts[1]}-{parts[0]}"
            except:
                ultima_actualizare = None

        # Extract details
        details = data.get('details', {})

        # Get file stats
        csv_file = CSV_SOURCE_DIR / f"{matrix_code}.csv"
        parquet_file = PARQUET_DIR / f"{matrix_code}.parquet"

        row_count = None
        file_size_bytes = None
        parquet_path = None

        if parquet_file.exists():
            # Get row count from Parquet
            try:
                row_count = conn.execute(f"SELECT COUNT(*) FROM '{parquet_file}'").fetchone()[0]
                file_size_bytes = parquet_file.stat().st_size
                parquet_path = str(parquet_file)
            except:
                pass
        elif csv_file.exists():
            # Fallback to CSV row count
            try:
                with open(csv_file, 'r') as f:
                    row_count = sum(1 for line in f) - 1  # Subtract header
            except:
                pass

        # Update matrix record
        conn.execute("""
            UPDATE matrices
            SET
                context_code = ?,
                ancestor_codes = ?,
                ancestor_path = ?,
                periodicitati = ?,
                definitie = ?,
                metodologie = ?,
                ultima_actualizare = ?,
                observatii = ?,
                persoane_responsabile = ?,
                nom_jud = ?,
                nom_loc = ?,
                mat_max_dim = ?,
                mat_um_spec = ?,
                mat_siruta = ?,
                mat_caen1 = ?,
                mat_caen2 = ?,
                mat_reg_j = ?,
                mat_charge = ?,
                mat_views = ?,
                mat_downloads = ?,
                mat_active = ?,
                mat_time = ?,
                row_count = ?,
                file_size_bytes = ?,
                parquet_path = ?
            WHERE matrix_code = ?
        """, [
            context_code,
            ancestor_codes,
            ancestor_path,
            periodicitati,
            definitie,
            metodologie,
            ultima_actualizare,
            observatii,
            persoane_responsabile,
            bool(details.get('nomJud', 0)),
            bool(details.get('nomLoc', 0)),
            details.get('matMaxDim'),
            bool(details.get('matUMSpec', 0)),
            bool(details.get('matSiruta', 0)),
            bool(details.get('matCaen1', 0)),
            bool(details.get('matCaen2', 0)),
            bool(details.get('matRegJ', 0)),
            details.get('matCharge'),
            details.get('matViews'),
            details.get('matDownloads'),
            bool(details.get('matActive', 1)),
            details.get('matTime'),
            row_count,
            file_size_bytes,
            parquet_path,
            matrix_code
        ])

        return True

    except Exception as e:
        print(f"  ✗ Error enriching {matrix_code}: {e}")
        return False


def import_dimensions(conn: duckdb.DuckDBPyConnection, matrix_code: str) -> int:
    """
    Import dimensions for a matrix from JSON metadata

    Args:
        conn: DuckDB connection
        matrix_code: Matrix identifier

    Returns:
        Number of dimensions imported
    """
    json_file = METAS_DIR / f"{matrix_code}.json"

    if not json_file.exists():
        return 0

    # Skip if dimensions already imported for this matrix
    existing = conn.execute("SELECT COUNT(*) FROM dimensions WHERE matrix_code = ?", [matrix_code]).fetchone()[0]
    if existing > 0:
        return existing

    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        dimensions_map = data.get('dimensionsMap', [])

        if not dimensions_map:
            return 0

        count = 0

        for dim_idx, dim in enumerate(dimensions_map, 1):
            dim_label = dim['label']
            dim_column_name = sanitize_column_name(dim_label)
            options = dim.get('options', [])
            option_count = len(options)

            # Get next dimension_id from sequence
            dim_id = conn.execute("SELECT nextval('seq_dimension_id')").fetchone()[0]

            # Insert dimension
            conn.execute("""
                INSERT INTO dimensions
                (dimension_id, matrix_code, dim_code, dim_label, dim_column_name, option_count)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [dim_id, matrix_code, dim_idx, dim_label, dim_column_name, option_count])

            # Insert dimension options
            for option in options:
                option_id = conn.execute("SELECT nextval('seq_option_id')").fetchone()[0]

                conn.execute("""
                    INSERT INTO dimension_options
                    (option_id, dimension_id, nom_item_id, option_label, option_offset, parent_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, [
                    option_id,
                    dim_id,
                    option['nomItemId'],
                    option['label'],
                    option.get('offset'),
                    option.get('parentId')
                ])

            count += 1

        return count

    except Exception as e:
        print(f"  ✗ Error importing dimensions for {matrix_code}: {e}")
        return 0


def main():
    """Main execution"""
    print("=" * 70)
    print("Import Metadata to DuckDB")
    print("=" * 70)

    # Validate inputs
    if not validate_inputs():
        print("\n❌ Input validation failed!")
        return 1

    # Check if database exists
    if not DB_FILE.exists():
        print(f"\n❌ Database not found: {DB_FILE}")
        print(f"   Run: python3 8-setup-duckdb-schema.py")
        return 1

    # Setup logging
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"metadata-import-{timestamp}.log"
    print(f"\n📋 Log file: {log_file}")

    # Connect to database
    print(f"\n📊 Connecting to database: {DB_FILE}")
    conn = duckdb.connect(str(DB_FILE))

    try:
        with open(log_file, 'w', encoding='utf-8') as log:
            log.write(f"Metadata Import Log - {timestamp}\n")
            log.write("=" * 70 + "\n\n")

            # Import contexts
            contexts_count = import_contexts(conn)
            log.write(f"Contexts imported: {contexts_count}\n\n")

            # Import basic matrices info
            matrices_count = import_matrices_basic(conn)
            log.write(f"Matrices imported (basic): {matrices_count}\n\n")

            # Only enrich matrices that are missing metadata (new/unregistered datasets):
            # - context_code IS NULL (never enriched), OR
            # - no dimensions yet (enrichment partial/incomplete)
            # Existing fully-enriched matrices are skipped to avoid DuckDB FK issues on UPDATE.
            matrices = conn.execute("""
                SELECT m.matrix_code FROM matrices m
                LEFT JOIN dimensions d ON d.matrix_code = m.matrix_code
                WHERE m.context_code IS NULL OR d.dimension_id IS NULL
                GROUP BY m.matrix_code, m.context_code
                HAVING m.context_code IS NULL OR COUNT(d.dimension_id) = 0
                ORDER BY m.matrix_code
            """).fetchall()
            matrices_to_process = [m[0] for m in matrices]
            print(f"\n📋 {len(matrices_to_process)} matrices need metadata/dimension enrichment")

            if TEST_LIMIT:
                matrices_to_process = matrices_to_process[:TEST_LIMIT]
                print(f"\n⚠️  TEST MODE: Processing only {TEST_LIMIT} matrices")

            print(f"\n🔄 Enriching {len(matrices_to_process)} matrices with metadata...")

            enriched = 0
            failed = 0
            total_dimensions = 0
            total_options = 0

            for idx, matrix_code in enumerate(matrices_to_process, 1):
                # Enrich matrix metadata
                if enrich_matrix_metadata(conn, matrix_code):
                    enriched += 1

                    # Import dimensions
                    dim_count = import_dimensions(conn, matrix_code)
                    total_dimensions += dim_count

                    if dim_count > 0:
                        # Get option count for this matrix
                        opt_count = conn.execute("""
                            SELECT COUNT(*)
                            FROM dimension_options AS opts
                            JOIN dimensions d ON opts.dimension_id = d.dimension_id
                            WHERE d.matrix_code = ?
                        """, [matrix_code]).fetchone()[0]

                        total_options += opt_count

                        if idx <= 10 or idx % 100 == 0:
                            print(f"  ✓ {matrix_code}: {dim_count} dimensions, {opt_count} options")
                    else:
                        print(f"  ⚠ {matrix_code}: No dimensions found")
                        failed += 1
                else:
                    print(f"  ✗ {matrix_code}: Failed to enrich")
                    failed += 1

                # Progress update
                if idx % 100 == 0:
                    print(f"\nProgress: {idx}/{len(matrices_to_process)} (enriched: {enriched}, failed: {failed})\n")

            # Commit transaction
            conn.commit()

            # Final counts
            final_contexts = conn.execute("SELECT COUNT(*) FROM contexts").fetchone()[0]
            final_matrices = conn.execute("SELECT COUNT(*) FROM matrices").fetchone()[0]
            final_dimensions = conn.execute("SELECT COUNT(*) FROM dimensions").fetchone()[0]
            final_options = conn.execute("SELECT COUNT(*) FROM dimension_options").fetchone()[0]

            summary = f"""
{'=' * 70}
Import Summary
{'=' * 70}
Contexts: {final_contexts}
Matrices: {final_matrices}
  - Enriched: {enriched}
  - Failed: {failed}
Dimensions: {final_dimensions}
Dimension Options: {final_options}

Database: {DB_FILE}
Database size: {DB_FILE.stat().st_size:,} bytes ({DB_FILE.stat().st_size / (1024**2):.1f} MB)
Log file: {log_file}
"""
            print(summary)
            log.write(summary + "\n")

    except Exception as e:
        print(f"\n❌ Error during import: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        conn.close()

    if failed > 0:
        print(f"\n⚠️  Import completed with {failed} failures. Check log file for details.")
        return 1
    else:
        print(f"\n✅ Import completed successfully!")
        print(f"\n💡 Next: Query the database with query-duckdb.py")
        return 0


if __name__ == "__main__":
    sys.exit(main())
