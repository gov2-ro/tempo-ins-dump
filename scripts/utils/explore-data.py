"""
Exploration script to understand DuckDB + Parquet integration

This demonstrates:
1. Querying metadata from DuckDB
2. Querying Parquet files directly
3. Combining metadata + data queries
4. Understanding the data structure
"""
import duckdb
from pathlib import Path
from duckdb_config import DB_FILE, PARQUET_DIR


def example_1_metadata_queries():
    """Example 1: Query metadata from DuckDB"""
    print("\n" + "="*70)
    print("EXAMPLE 1: Metadata Queries (from DuckDB)")
    print("="*70)

    conn = duckdb.connect(str(DB_FILE), read_only=True)

    # Find datasets about population
    print("\n1a. Find datasets containing 'populatie' (population):")
    result = conn.execute("""
        SELECT matrix_code, matrix_name, row_count
        FROM matrices
        WHERE LOWER(matrix_name) LIKE '%populatie%'
        ORDER BY row_count DESC
        LIMIT 5
    """).fetchdf()
    print(result.to_string(index=False))

    # Get dimensions for a specific dataset
    print("\n1b. What dimensions does ACC101B have?")
    result = conn.execute("""
        SELECT dim_label, option_count
        FROM dimensions
        WHERE matrix_code = 'ACC101B'
        ORDER BY dim_code
    """).fetchdf()
    print(result.to_string(index=False))

    # Find all dimension options for a dimension
    print("\n1c. What are the options for 'Macroregiuni...' dimension in ACC101B?")
    result = conn.execute("""
        SELECT opts.option_label, opts.nom_item_id
        FROM dimension_options AS opts
        JOIN dimensions d ON opts.dimension_id = d.dimension_id
        WHERE d.matrix_code = 'ACC101B'
        AND d.dim_label LIKE 'Macroregiuni%'
        LIMIT 10
    """).fetchdf()
    print(result.to_string(index=False))

    conn.close()


def example_2_parquet_queries():
    """Example 2: Query Parquet files directly"""
    print("\n" + "="*70)
    print("EXAMPLE 2: Direct Parquet Queries (no DuckDB needed)")
    print("="*70)

    conn = duckdb.connect()  # In-memory connection

    # Basic query - get all data
    print("\n2a. Sample rows from ACC101B.parquet:")
    result = conn.execute("""
        SELECT *
        FROM 'data/parquet/ro/ACC101B.parquet'
        LIMIT 5
    """).fetchdf()
    print(result.to_string(index=False))

    # Get statistics
    print("\n2b. Statistics for ACC101B:")
    result = conn.execute("""
        SELECT
            COUNT(*) as total_rows,
            COUNT(DISTINCT macroregiuni_regiuni_de_dezvoltare_si_judet_nom_id) as unique_regions,
            COUNT(DISTINCT perioade_nom_id) as unique_periods,
            ROUND(AVG(value), 2) as avg_value,
            ROUND(MIN(value), 2) as min_value,
            ROUND(MAX(value), 2) as max_value
        FROM 'data/parquet/ro/ACC101B.parquet'
    """).fetchdf()
    print(result.to_string(index=False))

    # Filter and aggregate
    print("\n2c. Filter by specific dimension value:")
    result = conn.execute("""
        SELECT perioade_nom_id, COUNT(*) as count, ROUND(SUM(value), 2) as total
        FROM 'data/parquet/ro/ACC101B.parquet'
        WHERE macroregiuni_regiuni_de_dezvoltare_si_judet_nom_id LIKE '%BUCURESTI%'
        GROUP BY perioade_nom_id
        ORDER BY perioade_nom_id
        LIMIT 5
    """).fetchdf()
    print(result.to_string(index=False))

    conn.close()


def example_3_schema_inspection():
    """Example 3: Inspect Parquet schema"""
    print("\n" + "="*70)
    print("EXAMPLE 3: Understanding Parquet Schema")
    print("="*70)

    conn = duckdb.connect()

    # Get schema info
    print("\n3a. Column information for ACC101B.parquet:")
    result = conn.execute("""
        DESCRIBE SELECT * FROM 'data/parquet/ro/ACC101B.parquet'
    """).fetchdf()
    print(result.to_string(index=False))

    # Get file size info
    parquet_file = PARQUET_DIR / "ACC101B.parquet"
    print(f"\n3b. File info:")
    print(f"   File size: {parquet_file.stat().st_size:,} bytes")
    print(f"   Path: {parquet_file}")

    conn.close()


def example_4_combined_queries():
    """Example 4: Combine metadata + data (the powerful pattern!)"""
    print("\n" + "="*70)
    print("EXAMPLE 4: Combined Metadata + Data Queries")
    print("="*70)

    # This requires using metadata to find Parquet files, then querying them
    conn_meta = duckdb.connect(str(DB_FILE), read_only=True)
    conn_data = duckdb.connect()  # For Parquet queries

    # Strategy: Get list of datasets from metadata, then query each Parquet file
    print("\n4a. Find datasets with 'Perioade' dimension and show sample data:")

    # Step 1: Get dataset list from metadata
    datasets = conn_meta.execute("""
        SELECT DISTINCT m.matrix_code, m.matrix_name
        FROM matrices m
        JOIN dimensions d ON m.matrix_code = d.matrix_code
        WHERE d.dim_label = 'Perioade'
        LIMIT 3
    """).fetchall()

    # Step 2: Query each dataset's Parquet file
    for matrix_code, matrix_name in datasets:
        parquet_file = PARQUET_DIR / f"{matrix_code}.parquet"
        if parquet_file.exists():
            print(f"\n{matrix_code}: {matrix_name[:60]}...")
            result = conn_data.execute(f"""
                SELECT COUNT(*) as rows, COUNT(DISTINCT perioade_nom_id) as periods
                FROM '{parquet_file}'
            """).fetchdf()
            print(result.to_string(index=False))

    conn_meta.close()
    conn_data.close()


def example_5_practical_patterns():
    """Example 5: Practical query patterns for UI"""
    print("\n" + "="*70)
    print("EXAMPLE 5: Practical Patterns for Building a UI")
    print("="*70)

    conn = duckdb.connect(str(DB_FILE), read_only=True)

    # Pattern 1: Get dataset list with metadata
    print("\n5a. Dataset list (for sidebar/menu):")
    result = conn.execute("""
        SELECT
            matrix_code,
            matrix_name,
            row_count,
            mat_max_dim as num_dimensions
        FROM matrices
        WHERE row_count > 0
        ORDER BY matrix_name
        LIMIT 10
    """).fetchdf()
    print(result.to_string(index=False))

    # Pattern 2: Get category tree
    print("\n5b. Category tree (for navigation):")
    result = conn.execute("""
        SELECT
            context_code,
            context_name,
            level,
            (SELECT COUNT(*) FROM matrices m WHERE m.context_code = c.context_code) as dataset_count
        FROM contexts c
        WHERE level = 1
        ORDER BY context_name
        LIMIT 5
    """).fetchdf()
    print(result.to_string(index=False))

    # Pattern 3: Get dimensions for dataset (for filters)
    print("\n5c. Dimensions for dataset (for filter dropdowns):")
    result = conn.execute("""
        SELECT
            dim_label,
            dim_column_name,
            option_count
        FROM dimensions
        WHERE matrix_code = 'AGR101A'
        ORDER BY dim_code
    """).fetchdf()
    print(result.to_string(index=False))

    conn.close()


def example_6_data_preview():
    """Example 6: Generate data preview with actual values"""
    print("\n" + "="*70)
    print("EXAMPLE 6: Data Preview Pattern")
    print("="*70)

    matrix_code = "AGR101A"
    conn = duckdb.connect()

    # Preview data
    print(f"\n6a. Preview first 10 rows of {matrix_code}:")
    result = conn.execute(f"""
        SELECT *
        FROM 'data/parquet/ro/{matrix_code}.parquet'
        LIMIT 10
    """).fetchdf()
    print(result.to_string(index=False))

    # Show unique values for each dimension
    print(f"\n6b. Unique values per dimension (for faceted search):")

    # Get column names (excluding 'value')
    columns = [col for col in result.columns if col != 'value']

    for col in columns:
        unique_count = conn.execute(f"""
            SELECT COUNT(DISTINCT {col}) as count
            FROM 'data/parquet/ro/{matrix_code}.parquet'
        """).fetchone()[0]
        print(f"   {col}: {unique_count} unique values")

    conn.close()


def main():
    """Run all examples"""
    print("\n" + "="*70)
    print("DuckDB + Parquet Exploration Guide")
    print("="*70)
    print("\nThis script demonstrates different query patterns.")
    print("Each example can be adapted for your browser UI.")

    try:
        example_1_metadata_queries()
        example_2_parquet_queries()
        example_3_schema_inspection()
        example_4_combined_queries()
        example_5_practical_patterns()
        example_6_data_preview()

        print("\n" + "="*70)
        print("Key Takeaways:")
        print("="*70)
        print("""
1. METADATA queries use: duckdb.connect(str(DB_FILE), read_only=True)
   - Query tables: contexts, matrices, dimensions, dimension_options
   - Fast lookups for dataset info, categories, dimension definitions

2. DATA queries use: duckdb.connect() + 'path/to/file.parquet'
   - Query Parquet files directly without importing
   - Each file has natural column names from dimensions
   - Use standard SQL: WHERE, GROUP BY, JOINS, aggregations

3. COMBINED pattern:
   - Use metadata DB to find datasets (search, filter, browse)
   - Use Parquet files to query actual data
   - No need to join them - they're separate concerns!

4. For a UI:
   - Left panel: Query contexts/matrices for navigation
   - Main panel: Query Parquet files for data display
   - Filters: Use dimension_options for dropdown values
        """)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
