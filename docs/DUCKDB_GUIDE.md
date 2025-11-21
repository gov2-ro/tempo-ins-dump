# DuckDB + Parquet Guide

## Overview

This guide explains how DuckDB and Parquet work together in this project.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Your Application                      │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────────────┐    ┌────────────────────────┐│
│  │  DuckDB Metadata     │    │   Parquet Files        ││
│  │  ==================  │    │   ===============      ││
│  │                      │    │                        ││
│  │  • contexts          │    │   ACC101B.parquet      ││
│  │  • matrices          │    │   AGR101A.parquet      ││
│  │  • dimensions        │    │   IND106C.parquet      ││
│  │  • dimension_options │    │   ... (1,886 files)    ││
│  │                      │    │                        ││
│  └──────────────────────┘    └────────────────────────┘│
│           ↓                            ↓                │
│    Fast metadata lookups      Fast data queries        │
└─────────────────────────────────────────────────────────┘
```

## Two Separate Data Stores

### 1. DuckDB Database (`data/tempo_metadata.duckdb`)

**What:** SQLite-like database with metadata about datasets

**Contains:**
- `contexts` - Category hierarchy (339 rows)
- `matrices` - Dataset metadata (1,889 rows)
- `dimensions` - Dimension definitions (7,159 rows)
- `dimension_options` - Dimension value lookups (325,762 rows)

**Use for:**
- Searching datasets by name, category, or dimension
- Building navigation menus and filters
- Getting dataset info (row count, dimensions, etc.)

**Example queries:**
```python
import duckdb
conn = duckdb.connect('data/tempo_metadata.duckdb', read_only=True)

# Find datasets about population
result = conn.execute("""
    SELECT matrix_code, matrix_name
    FROM matrices
    WHERE matrix_name LIKE '%populatie%'
""").fetchdf()

# Get dimensions for a dataset
result = conn.execute("""
    SELECT dim_label, option_count
    FROM dimensions
    WHERE matrix_code = 'ACC101B'
""").fetchdf()
```

### 2. Parquet Files (`data/parquet/ro/*.parquet`)

**What:** Columnar data files containing the actual statistical data

**Structure:** Each file = one dataset with:
- Natural column names from dimensions (e.g., `perioade_nom_id`, `value`)
- Text labels in dimension columns (VARCHAR)
- Numeric values in `value` column (DOUBLE)
- NULL for confidential/suppressed values

**Use for:**
- Querying actual data
- Aggregations, filtering, sorting
- Data visualization

**Example queries:**
```python
import duckdb
conn = duckdb.connect()  # In-memory connection

# Query data directly
result = conn.execute("""
    SELECT perioade_nom_id, COUNT(*), AVG(value)
    FROM 'data/parquet/ro/ACC101B.parquet'
    GROUP BY perioade_nom_id
""").fetchdf()

# Filter by dimension value
result = conn.execute("""
    SELECT *
    FROM 'data/parquet/ro/ACC101B.parquet'
    WHERE perioade_nom_id LIKE '%2020%'
    LIMIT 100
""").fetchdf()
```

## Key Concepts

### 1. No Need to JOIN Metadata + Data

**They're separate concerns!**

- Use **DuckDB metadata** to find datasets (search, browse, discover)
- Use **Parquet files** to query the data you found

You **don't** need to join them because:
- Metadata is for discovery/navigation
- Data files are for analytics/display

### 2. Parquet Files Are Self-Describing

Each Parquet file contains its own schema:

```python
# Get column info from Parquet file
result = conn.execute("""
    DESCRIBE SELECT * FROM 'data/parquet/ro/ACC101B.parquet'
""").fetchdf()
```

Output:
```
column_name                                     column_type
macroregiuni_regiuni_de_dezvoltare_si_judet_nom_id  VARCHAR
perioade_nom_id                                     VARCHAR
um_numar_nom_id                                     VARCHAR
value                                               DOUBLE
```

### 3. Text Labels vs. Numeric IDs

**Current approach:** Using text labels (original CSVs)
- ✅ 100% reliable - all data matches
- ✅ Human-readable in queries
- ❌ Larger files (~40% bigger than IDs)

**Future optimization:** Using numeric IDs (compacted CSVs)
- ✅ Smaller files (40-50% reduction)
- ✅ Faster queries on joins
- ❌ Requires fuzzy matching to fix data quality issues

See [TODO_COMPACTION.md](TODO_COMPACTION.md) for details.

### 4. NULL Handling

Non-numeric values (like "c" for confidential) are stored as NULL:

```python
result = conn.execute("""
    SELECT
        COUNT(*) as total,
        COUNT(value) as with_value,
        COUNT(*) - COUNT(value) as nulls
    FROM 'data/parquet/ro/IND106C.parquet'
""").fetchdf()
```

## Common Query Patterns

### Pattern 1: Search and List Datasets

```python
import duckdb

# Connect to metadata DB
conn = duckdb.connect('data/tempo_metadata.duckdb', read_only=True)

# Search by keyword
datasets = conn.execute("""
    SELECT matrix_code, matrix_name, row_count
    FROM matrices
    WHERE LOWER(matrix_name) LIKE LOWER(?)
    ORDER BY matrix_name
""", [f'%{search_term}%']).fetchall()

# Get categories
categories = conn.execute("""
    SELECT context_code, context_name, level
    FROM contexts
    WHERE level = 1
    ORDER BY context_name
""").fetchall()

conn.close()
```

### Pattern 2: Get Dataset Details

```python
# Get metadata
conn = duckdb.connect('data/tempo_metadata.duckdb', read_only=True)

metadata = conn.execute("""
    SELECT matrix_code, matrix_name, row_count, mat_max_dim
    FROM matrices
    WHERE matrix_code = ?
""", [matrix_code]).fetchone()

dimensions = conn.execute("""
    SELECT dim_label, dim_column_name, option_count
    FROM dimensions
    WHERE matrix_code = ?
    ORDER BY dim_code
""", [matrix_code]).fetchall()

conn.close()
```

### Pattern 3: Query Data

```python
# Query Parquet file
conn = duckdb.connect()  # In-memory

data = conn.execute(f"""
    SELECT *
    FROM 'data/parquet/ro/{matrix_code}.parquet'
    LIMIT 100
""").fetchdf()

# Get statistics
stats = conn.execute(f"""
    SELECT
        COUNT(*) as total_rows,
        AVG(value) as avg_value,
        MIN(value) as min_value,
        MAX(value) as max_value
    FROM 'data/parquet/ro/{matrix_code}.parquet'
""").fetchone()

conn.close()
```

### Pattern 4: Filter by Dimension

```python
conn = duckdb.connect()

# First, get the column names from metadata
conn_meta = duckdb.connect('data/tempo_metadata.duckdb', read_only=True)
columns = conn_meta.execute("""
    SELECT dim_column_name
    FROM dimensions
    WHERE matrix_code = ?
    ORDER BY dim_code
""", [matrix_code]).fetchall()
conn_meta.close()

# Then query with filter
filter_col = columns[0][0]  # First dimension
filtered_data = conn.execute(f"""
    SELECT *
    FROM 'data/parquet/ro/{matrix_code}.parquet'
    WHERE {filter_col} LIKE ?
""", [f'%{filter_value}%']).fetchdf()

conn.close()
```

### Pattern 5: Aggregate by Dimension

```python
conn = duckdb.connect()

result = conn.execute(f"""
    SELECT
        perioade_nom_id,
        COUNT(*) as count,
        ROUND(SUM(value), 2) as total,
        ROUND(AVG(value), 2) as average
    FROM 'data/parquet/ro/{matrix_code}.parquet'
    GROUP BY perioade_nom_id
    ORDER BY perioade_nom_id
""").fetchdf()

conn.close()
```

## Building a UI

### Basic Pattern

```python
from flask import Flask, jsonify
import duckdb

app = Flask(__name__)

@app.route('/api/datasets')
def list_datasets():
    """List all datasets"""
    conn = duckdb.connect('data/tempo_metadata.duckdb', read_only=True)
    result = conn.execute("""
        SELECT matrix_code, matrix_name, row_count
        FROM matrices
        ORDER BY matrix_name
    """).fetchall()
    conn.close()

    return jsonify([
        {'code': r[0], 'name': r[1], 'rows': r[2]}
        for r in result
    ])

@app.route('/api/data/<matrix_code>')
def get_data(matrix_code):
    """Get data for dataset"""
    conn = duckdb.connect()
    result = conn.execute(f"""
        SELECT * FROM 'data/parquet/ro/{matrix_code}.parquet'
        LIMIT 100
    """).fetchdf()
    conn.close()

    return result.to_json(orient='records')
```

### UI Components

1. **Left Sidebar:** Browse datasets
   - Query `contexts` for categories
   - Query `matrices` for dataset list
   - Use search to filter

2. **Main Panel:** Display data
   - Query Parquet file for actual data
   - Show statistics, charts, tables

3. **Filters:** Filter by dimensions
   - Query `dimensions` to get dimension list
   - Query `dimension_options` to get filter values
   - Query Parquet with WHERE clause

## Tools Provided

### 1. `explore-data.py`
Interactive examples showing all query patterns.

```bash
python3 explore-data.py
```

### 2. `query-duckdb.py`
Query helper for metadata database.

```bash
# Interactive mode
python3 query-duckdb.py

# Command line query
python3 query-duckdb.py "SELECT * FROM matrices LIMIT 5"
```

### 3. `duckdb-browser.py`
Simple web-based browser (running now at http://localhost:5050).

```bash
python3 duckdb-browser.py
```

Features:
- Dataset list with search
- Dataset details (metadata, dimensions)
- Data preview (first 50 rows)
- Demonstrates full metadata + data pattern

## Performance Tips

1. **Metadata queries are fast** - DuckDB is optimized for small analytical queries
2. **Parquet queries are also fast** - Columnar format, compressed, skip unused columns
3. **For large datasets:** Use LIMIT or WHERE to reduce data transfer
4. **For aggregations:** Let DuckDB do the work - it's fast at SUM, AVG, GROUP BY
5. **No need to import:** DuckDB queries Parquet files directly - no loading step!

## Storage Efficiency

- **Original CSVs:** 5.1 GB
- **Parquet files:** 134 MB (97.4% reduction!)
- **DuckDB metadata:** 68.5 MB
- **Total:** 202.5 MB (96% space savings)

## Next Steps

1. **Explore the data:** Run `python3 explore-data.py`
2. **Try the browser:** Open http://localhost:5050
3. **Build your UI:** Use patterns from `duckdb-browser.py`
4. **Optimize queries:** Add indexes, use WHERE clauses
5. **(Future) Fix compaction:** See [TODO_COMPACTION.md](TODO_COMPACTION.md)

## Resources

- [DuckDB Documentation](https://duckdb.org/docs/)
- [Parquet Format](https://parquet.apache.org/docs/)
- [DuckDB Python API](https://duckdb.org/docs/api/python/overview.html)
