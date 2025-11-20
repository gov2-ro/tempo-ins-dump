"""
Initialize DuckDB database and create metadata schema

This script creates the DuckDB database with all metadata tables:
- contexts: Category hierarchy
- matrices: Dataset metadata
- dimensions: Dimension definitions
- dimension_options: Dimension value lookups
"""
import duckdb
from pathlib import Path
from datetime import datetime
import sys

# Import configuration
from duckdb_config import DB_FILE, LOGS_DIR, ensure_directories

# SQL schemas from specs
SCHEMA_SQL = """
-- Table 1: contexts
CREATE TABLE IF NOT EXISTS contexts (
    context_code TEXT PRIMARY KEY,
    parent_code TEXT,
    level INTEGER,
    context_name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_contexts_parent ON contexts(parent_code);
CREATE INDEX IF NOT EXISTS idx_contexts_level ON contexts(level);

-- Table 2: matrices
CREATE TABLE IF NOT EXISTS matrices (
    matrix_code TEXT PRIMARY KEY,
    matrix_name TEXT NOT NULL,
    context_code TEXT,
    ancestor_codes TEXT[],
    ancestor_path TEXT,
    periodicitati TEXT[],
    definitie TEXT,
    metodologie TEXT,
    ultima_actualizare DATE,
    observatii TEXT,
    persoane_responsabile TEXT,
    intrerupere_last_period TEXT,
    continuare_serie TEXT,
    nom_jud BOOLEAN,
    nom_loc BOOLEAN,
    mat_max_dim INTEGER,
    mat_um_spec BOOLEAN,
    mat_siruta BOOLEAN,
    mat_caen1 BOOLEAN,
    mat_caen2 BOOLEAN,
    mat_reg_j BOOLEAN,
    mat_charge INTEGER,
    mat_views INTEGER,
    mat_downloads INTEGER,
    mat_active BOOLEAN,
    mat_time INTEGER,
    row_count BIGINT,
    file_size_bytes BIGINT,
    parquet_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (context_code) REFERENCES contexts(context_code)
);

CREATE INDEX IF NOT EXISTS idx_matrices_context ON matrices(context_code);
CREATE INDEX IF NOT EXISTS idx_matrices_active ON matrices(mat_active);
CREATE INDEX IF NOT EXISTS idx_matrices_dims ON matrices(mat_max_dim);

-- Table 3: dimensions
CREATE TABLE IF NOT EXISTS dimensions (
    dimension_id INTEGER PRIMARY KEY,
    matrix_code TEXT NOT NULL,
    dim_code INTEGER NOT NULL,
    dim_label TEXT NOT NULL,
    dim_column_name TEXT NOT NULL,
    option_count INTEGER,

    FOREIGN KEY (matrix_code) REFERENCES matrices(matrix_code),
    UNIQUE(matrix_code, dim_code)
);

CREATE INDEX IF NOT EXISTS idx_dimensions_matrix ON dimensions(matrix_code);
CREATE INDEX IF NOT EXISTS idx_dimensions_label ON dimensions(dim_label);
CREATE INDEX IF NOT EXISTS idx_dimensions_column ON dimensions(dim_column_name);

-- Table 4: dimension_options
CREATE TABLE IF NOT EXISTS dimension_options (
    option_id INTEGER PRIMARY KEY,
    dimension_id INTEGER NOT NULL,
    nom_item_id INTEGER NOT NULL,
    option_label TEXT NOT NULL,
    option_offset INTEGER,
    parent_id INTEGER,

    FOREIGN KEY (dimension_id) REFERENCES dimensions(dimension_id),
    UNIQUE(dimension_id, nom_item_id)
);

CREATE INDEX IF NOT EXISTS idx_options_dimension ON dimension_options(dimension_id);
CREATE INDEX IF NOT EXISTS idx_options_nom_item ON dimension_options(nom_item_id);
CREATE INDEX IF NOT EXISTS idx_options_label ON dimension_options(option_label);

-- Sequences for auto-increment IDs
CREATE SEQUENCE IF NOT EXISTS seq_dimension_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_option_id START 1;
"""


def setup_database(db_path: Path, force: bool = False):
    """
    Create database and initialize schema

    Args:
        db_path: Path to database file
        force: If True, delete existing database and recreate
    """
    # Check if database exists
    if db_path.exists():
        if force:
            print(f"⚠️  Removing existing database: {db_path}")
            db_path.unlink()
        else:
            print(f"ℹ️  Database already exists: {db_path}")
            response = input("  Delete and recreate? (yes/no): ")
            if response.lower() in ['yes', 'y']:
                db_path.unlink()
                print(f"✓ Deleted existing database")
            else:
                print(f"  Keeping existing database, will verify schema...")

    print(f"\n📊 Creating database: {db_path}")

    # Connect to database
    conn = duckdb.connect(str(db_path))

    try:
        # Execute schema creation
        print(f"\n📝 Creating schema...")
        conn.execute(SCHEMA_SQL)

        # Verify tables were created
        tables = conn.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
            ORDER BY table_name
        """).fetchall()

        print(f"\n✓ Schema created successfully!")
        print(f"\n📋 Tables created:")
        for (table,) in tables:
            # Get row count
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  - {table}: {count} rows")

        # Get database size
        db_size = db_path.stat().st_size if db_path.exists() else 0
        print(f"\n💾 Database size: {db_size:,} bytes ({db_size / 1024:.1f} KB)")

        return True

    except Exception as e:
        print(f"\n❌ Error creating schema: {e}")
        return False

    finally:
        conn.close()


def main():
    """Main execution"""
    print("=" * 60)
    print("DuckDB Schema Setup")
    print("=" * 60)

    # Ensure directories exist
    ensure_directories()

    # Check for force flag
    force = '--force' in sys.argv or '-f' in sys.argv

    # Setup database
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"schema-setup-{timestamp}.log"

    print(f"\n📋 Log file: {log_file}")

    success = setup_database(DB_FILE, force=force)

    if success:
        print(f"\n✅ Database setup completed successfully!")
        print(f"\n📂 Database location: {DB_FILE}")
        print(f"\n💡 Next steps:")
        print(f"  1. Run: python3 9-csv-to-parquet.py")
        print(f"  2. Run: python3 10-import-metadata.py")
        return 0
    else:
        print(f"\n❌ Database setup failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
