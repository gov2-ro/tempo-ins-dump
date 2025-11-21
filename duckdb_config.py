"""
Configuration constants for DuckDB + Parquet import process
"""
import os
import re
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

# Input paths
CONTEXT_CSV = DATA_DIR / "1-indexes" / "ro" / "context.csv"
MATRICES_CSV = DATA_DIR / "1-indexes" / "ro" / "matrices.csv"
METAS_DIR = DATA_DIR / "2-metas" / "ro"
ORIGINAL_CSV_DIR = DATA_DIR / "4-datasets" / "ro"  # Original CSVs with text labels
COMPACT_CSV_DIR = DATA_DIR / "5-compact-datasets" / "ro"  # Compacted CSVs with IDs (TODO: fix compaction issues)

# Which CSV source to use for Parquet conversion
# Options: ORIGINAL_CSV_DIR (text labels, larger) or COMPACT_CSV_DIR (IDs, smaller but has issues)
CSV_SOURCE_DIR = ORIGINAL_CSV_DIR  # Using original for reliability

# Output paths
PARQUET_DIR = DATA_DIR / "parquet" / "ro"
DB_FILE = DATA_DIR / "tempo_metadata.duckdb"
LOGS_DIR = DATA_DIR / "logs"

# Processing settings
BATCH_SIZE = 100  # Files to process before progress update
PARQUET_COMPRESSION = 'snappy'  # Options: 'snappy', 'gzip', 'zstd'
PROGRESS_INTERVAL = 50  # Log progress every N files
MAX_COLUMN_NAME_LENGTH = 50  # Maximum length for column names

# Debug settings
DEBUG_MODE = False  # Set to True for verbose logging
TEST_LIMIT = None  # Set to N to only process N files for testing

# Column name sanitization settings
COLUMN_SUFFIX = "_nom_id"  # Suffix for all dimension columns
VALUE_COLUMN = "value"  # Name of the value column


# Utility functions
def sanitize_column_name(label: str, max_length: int = MAX_COLUMN_NAME_LENGTH) -> str:
    """
    Convert dimension label to valid SQL column name

    Rules:
    1. Convert to lowercase
    2. Replace spaces and special chars with underscores
    3. Remove consecutive underscores
    4. Trim leading/trailing underscores
    5. Limit to max_length characters
    6. Append _nom_id suffix

    Args:
        label: Original dimension label
        max_length: Maximum length for column name

    Returns:
        Sanitized column name
    """
    # Convert to lowercase
    name = label.lower()

    # Replace special characters with underscores
    name = re.sub(r'[^a-z0-9_]', '_', name)

    # Remove consecutive underscores
    name = re.sub(r'_+', '_', name)

    # Trim leading/trailing underscores
    name = name.strip('_')

    # Limit length (leave room for suffix)
    suffix_len = len(COLUMN_SUFFIX)
    if len(name) > (max_length - suffix_len):
        name = name[:(max_length - suffix_len)]

    # Add suffix
    name = f"{name}{COLUMN_SUFFIX}"

    return name


# Ensure output directories exist
def ensure_directories():
    """Create output directories if they don't exist"""
    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"✓ Output directories ready:")
    print(f"  - Parquet: {PARQUET_DIR}")
    print(f"  - Database: {DB_FILE.parent}")
    print(f"  - Logs: {LOGS_DIR}")

# Validate input directories exist
def validate_inputs():
    """Validate that all required input files and directories exist"""
    errors = []

    if not CONTEXT_CSV.exists():
        errors.append(f"Context CSV not found: {CONTEXT_CSV}")

    if not MATRICES_CSV.exists():
        errors.append(f"Matrices CSV not found: {MATRICES_CSV}")

    if not METAS_DIR.exists():
        errors.append(f"Metadata directory not found: {METAS_DIR}")

    if not CSV_SOURCE_DIR.exists():
        errors.append(f"CSV source directory not found: {CSV_SOURCE_DIR}")

    if errors:
        print("❌ Validation errors:")
        for error in errors:
            print(f"  - {error}")
        return False

    # Count files
    json_count = len(list(METAS_DIR.glob("*.json")))
    csv_count = len(list(CSV_SOURCE_DIR.glob("*.csv")))

    print(f"✓ Input validation passed:")
    print(f"  - Context CSV: {CONTEXT_CSV}")
    print(f"  - Matrices CSV: {MATRICES_CSV}")
    print(f"  - JSON metadata files: {json_count}")
    print(f"  - CSV source: {CSV_SOURCE_DIR}")
    print(f"  - CSV files: {csv_count}")

    return True

if __name__ == "__main__":
    print("DuckDB Import Configuration")
    print("=" * 50)
    print(f"\nBase directory: {BASE_DIR}")
    print(f"\nValidating inputs...")
    if validate_inputs():
        print(f"\nEnsuring output directories...")
        ensure_directories()
        print(f"\n✓ Configuration ready!")
    else:
        print(f"\n❌ Configuration validation failed!")
