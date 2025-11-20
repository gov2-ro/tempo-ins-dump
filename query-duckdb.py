"""
Query helper tool for DuckDB + Parquet database

Provides example queries and interactive query capabilities
"""
import duckdb
import sys
from pathlib import Path

# Import configuration
from duckdb_config import DB_FILE, PARQUET_DIR

def query_examples():
    """Show example queries"""
    print("\n" + "=" * 70)
    print("Example Queries")
    print("=" * 70)

    examples = [
        ("Count all tables", "SELECT table_name, (SELECT COUNT(*) FROM main.|| table_name) as count FROM information_schema.tables WHERE table_schema = 'main'"),
        ("List all contexts", "SELECT * FROM contexts ORDER BY level, context_code LIMIT 10"),
        ("Matrices by context", "SELECT c.context_name, COUNT(m.matrix_code) as dataset_count FROM contexts c LEFT JOIN matrices m ON c.context_code = m.context_code GROUP BY c.context_code, c.context_name ORDER BY dataset_count DESC"),
        ("Top 10 largest datasets", "SELECT matrix_code, matrix_name, row_count, file_size_bytes / 1024 / 1024 as size_mb FROM matrices ORDER BY row_count DESC LIMIT 10"),
        ("Matrices with most dimensions", "SELECT matrix_code, matrix_name, mat_max_dim FROM matrices ORDER BY mat_max_dim DESC LIMIT 10"),
        ("Query single Parquet file", "SELECT * FROM 'data/parquet/ro/ACC101B.parquet' LIMIT 5"),
    ]

    for i, (desc, sql) in enumerate(examples, 1):
        print(f"\n{i}. {desc}:")
        print(f"   {sql}\n")


def run_query(conn, sql: str):
    """Execute a query and display results"""
    try:
        result = conn.execute(sql).fetchdf()
        if len(result) == 0:
            print("No results")
        else:
            print(result.to_string())
            print(f"\n({len(result)} rows)")
    except Exception as e:
        print(f"❌ Error: {e}")


def main():
    """Main execution"""
    print("=" * 70)
    print("DuckDB Query Tool")
    print("=" * 70)

    # Check if database exists
    if not DB_FILE.exists():
        print(f"\n❌ Database not found: {DB_FILE}")
        print(f"   Run: python3 8-setup-duckdb-schema.py")
        print(f"   Then: python3 10-import-metadata.py")
        return 1

    # Connect to database
    print(f"\n📊 Connected to: {DB_FILE}")
    print(f"   Database size: {DB_FILE.stat().st_size / (1024**2):.1f} MB")
    conn = duckdb.connect(str(DB_FILE), read_only=True)

    # Show table counts
    print(f"\n📋 Table Counts:")
    tables = ['contexts', 'matrices', 'dimensions', 'dimension_options']
    for table in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"   {table}: {count:,}")

    # Check for command line SQL
    if len(sys.argv) > 1:
        sql = ' '.join(sys.argv[1:])
        print(f"\n🔍 Executing query:")
        print(f"   {sql}\n")
        run_query(conn, sql)
        conn.close()
        return 0

    # Show examples
    query_examples()

    # Interactive mode
    print("\n" + "=" * 70)
    print("Interactive Mode")
    print("=" * 70)
    print("Enter SQL queries (or 'quit' to exit)")
    print()

    while True:
        try:
            query = input("SQL> ").strip()

            if not query:
                continue

            if query.lower() in ['quit', 'exit', 'q']:
                break

            if query.lower() == 'help':
                query_examples()
                continue

            run_query(conn, query)
            print()

        except KeyboardInterrupt:
            print("\n\nExiting...")
            break
        except EOFError:
            break

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
