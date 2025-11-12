# DuckDB + Parquet Hybrid Architecture Specifications

## Overview
Import INS TEMPO data using a hybrid approach:
- **DuckDB database** for metadata (contexts, matrices, dimensions, options)
- **Parquet files** for statistical data (one file per dataset)

This approach leverages DuckDB's native Parquet support to query data files directly without importing them.

## Architecture

```
┌─────────────────────────────────────────────┐
│        DuckDB Metadata Database              │
│       data/tempo_metadata.duckdb             │
├─────────────────────────────────────────────┤
│  • contexts (339 rows)                       │
│  • matrices (1,888 rows)                     │
│  • dimensions (~5,000 rows)                  │
│  • dimension_options (~300,000 rows)         │
└─────────────────────────────────────────────┘
                    ↓
              queries with
                    ↓
┌─────────────────────────────────────────────┐
│        Parquet Data Files                    │
│         data/parquet/ro/                     │
├─────────────────────────────────────────────┤
│  • ACC101B.parquet (3 dims + value)         │
│  • POP107D.parquet (6 dims + value)         │
│  • ... 1,892 files total                    │
│  Each file has its natural schema            │
└─────────────────────────────────────────────┘
```

---

## Source Data Files

### Index Files
```
data/1-indexes/ro/context.csv          # 339 rows - Category hierarchy
data/1-indexes/ro/matrices.csv         # 1,970 rows - Dataset basic info
```

### Metadata Files
```
data/2-metas/ro/*.json                 # 1,888 files - Full dataset metadata
```

### Data Files (Input)
```
data/5-compact-datasets/ro/*.csv       # 1,892 files - Compacted statistical data
```

### Data Files (Output)
```
data/parquet/ro/*.parquet              # 1,892 files - Parquet format (to be created)
```

### Dimension Distribution
```
   793 datasets with 3 dimensions (42%)
   737 datasets with 4 dimensions (39%)
   311 datasets with 5 dimensions (16%)
    37 datasets with 6 dimensions (2%)
     3 datasets with 7 dimensions (<1%)
     1 dataset with 8 dimensions (<1%)
     2 datasets with 9 dimensions (<1%)
─────────────────────────────────────
 1,884 total datasets
```

---

## Database Schema (Metadata Only)

### Table 1: `contexts`
Category/context hierarchy from INS TEMPO.

```sql
CREATE TABLE contexts (
    context_code TEXT PRIMARY KEY,
    parent_code TEXT,
    level INTEGER,
    context_name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_contexts_parent ON contexts(parent_code);
CREATE INDEX idx_contexts_level ON contexts(level);
```

**Source**: `data/1-indexes/ro/context.csv`

**Columns**:
- `context_code`: Unique identifier (e.g., "1010", "1520")
- `parent_code`: Parent context code for hierarchy
- `level`: Hierarchy level (0, 1, 2)
- `context_name`: Display name (e.g., "A. STATISTICA SOCIALA")
- `created_at`: Import timestamp

**Sample Data**:
```
context_code | parent_code | level | context_name
-------------|-------------|-------|---------------------------
1            | 0           | 0     | A. STATISTICA SOCIALA
10           | 1           | 1     | A.1 POPULATIE SI STRUCTURA DEMOGRAFICA
1010         | 10          | 2     | 1. POPULATIA REZIDENTA
```

---

### Table 2: `matrices`
Dataset/matrix metadata and information.

```sql
CREATE TABLE matrices (
    matrix_code TEXT PRIMARY KEY,
    matrix_name TEXT NOT NULL,
    context_code TEXT,
    ancestor_codes TEXT[],           -- Array of ancestor codes
    ancestor_path TEXT,              -- Full path string
    periodicitati TEXT[],            -- Array: ["Anuala", "Lunara"]
    definitie TEXT,                  -- Definition
    metodologie TEXT,                -- Methodology
    ultima_actualizare DATE,         -- Last update date
    observatii TEXT,                 -- Observations/notes
    persoane_responsabile TEXT,      -- Responsible persons
    intrerupere_last_period TEXT,    -- Interruption info
    continuare_serie TEXT,           -- Series continuation
    nom_jud BOOLEAN,                 -- Has county dimension
    nom_loc BOOLEAN,                 -- Has locality dimension
    mat_max_dim INTEGER,             -- Number of dimensions
    mat_um_spec BOOLEAN,             -- Has special unit of measure
    mat_siruta BOOLEAN,              -- Has SIRUTA codes
    mat_caen1 BOOLEAN,               -- Has CAEN Rev.1
    mat_caen2 BOOLEAN,               -- Has CAEN Rev.2
    mat_reg_j BOOLEAN,               -- Has regional dimension
    mat_charge INTEGER,              -- Charge level
    mat_views INTEGER,               -- View count
    mat_downloads INTEGER,           -- Download count
    mat_active BOOLEAN,              -- Is active
    mat_time INTEGER,                -- Time dimension type
    row_count BIGINT,                -- Number of data rows
    file_size_bytes BIGINT,          -- Parquet file size
    parquet_path TEXT,               -- Path to parquet file
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (context_code) REFERENCES contexts(context_code)
);

CREATE INDEX idx_matrices_context ON matrices(context_code);
CREATE INDEX idx_matrices_active ON matrices(mat_active);
CREATE INDEX idx_matrices_dims ON matrices(mat_max_dim);
```

**Sources**:
- `data/1-indexes/ro/matrices.csv` (basic info)
- `data/2-metas/ro/{code}.json` (full metadata)
- `data/5-compact-datasets/ro/{code}.csv` (row counts)
- Generated parquet path: `data/parquet/ro/{code}.parquet`

**Sample Data**:
```
matrix_code | matrix_name                     | mat_max_dim | row_count  | parquet_path
------------|---------------------------------|-------------|------------|-------------------------
ACC101B     | Accidente colective de munca... | 3           | 1,792      | data/parquet/ro/ACC101B.parquet
POP107D     | Populatia rezidenta...          | 6           | 21,589,699 | data/parquet/ro/POP107D.parquet
```

---

### Table 3: `dimensions`
Dimension definitions for each matrix.

```sql
CREATE TABLE dimensions (
    dimension_id INTEGER PRIMARY KEY,
    matrix_code TEXT NOT NULL,
    dim_code INTEGER NOT NULL,      -- 1-based dimension number
    dim_label TEXT NOT NULL,         -- Human-readable label
    dim_column_name TEXT NOT NULL,   -- Column name in parquet file
    option_count INTEGER,            -- Number of options

    FOREIGN KEY (matrix_code) REFERENCES matrices(matrix_code),
    UNIQUE(matrix_code, dim_code)
);

CREATE INDEX idx_dimensions_matrix ON dimensions(matrix_code);
CREATE INDEX idx_dimensions_label ON dimensions(dim_label);
CREATE INDEX idx_dimensions_column ON dimensions(dim_column_name);
```

**Source**: `data/2-metas/ro/{code}.json` → `dimensionsMap` array

**Column Naming Convention**:
- Sanitize dimension labels to create valid SQL column names
- Example: "Macroregiuni, regiuni de dezvoltare si judete" → "macroregiuni_regiuni_nom_id"
- Always append "_nom_id" suffix

**Sample Data**:
```
dimension_id | matrix_code | dim_code | dim_label                           | dim_column_name              | option_count
-------------|-------------|----------|-------------------------------------|------------------------------|-------------
1            | ACC101B     | 1        | Macroregiuni, regiuni de dezvoltare | macroregiuni_regiuni_nom_id | 56
2            | ACC101B     | 2        | Perioade                            | perioade_nom_id              | 32
3            | ACC101B     | 3        | UM: Numar                           | um_numar_nom_id              | 1
```

---

### Table 4: `dimension_options`
All possible values for each dimension.

```sql
CREATE TABLE dimension_options (
    option_id INTEGER PRIMARY KEY,
    dimension_id INTEGER NOT NULL,
    nom_item_id INTEGER NOT NULL,    -- ID used in parquet data
    option_label TEXT NOT NULL,       -- Human-readable label
    offset INTEGER,                   -- Position in dimension
    parent_id INTEGER,                -- For hierarchical dimensions

    FOREIGN KEY (dimension_id) REFERENCES dimensions(dimension_id),
    UNIQUE(dimension_id, nom_item_id)
);

CREATE INDEX idx_options_dimension ON dimension_options(dimension_id);
CREATE INDEX idx_options_nom_item ON dimension_options(nom_item_id);
CREATE INDEX idx_options_label ON dimension_options(option_label);
```

**Source**: `data/2-metas/ro/{code}.json` → `dimensionsMap[].options` array

**Sample Data**:
```
option_id | dimension_id | nom_item_id | option_label          | offset | parent_id
----------|--------------|-------------|-----------------------|--------|----------
1         | 1            | 112         | TOTAL                 | 1      | NULL
2         | 1            | 21295       | MACROREGIUNEA UNU     | 2      | NULL
3         | 1            | 5726        | Regiunea NORD-VEST    | 3      | NULL
4         | 1            | 3068        | Bihor                 | 4      | NULL
```

---

## Parquet File Structure

### File Organization
```
data/parquet/ro/
├── ACC101B.parquet
├── ACC101C.parquet
├── POP107D.parquet
└── ... (1,892 files total)
```

### Individual File Schema

Each Parquet file has a **custom schema** based on its dimensions:

**Example: ACC101B.parquet** (3 dimensions)
```
Schema:
  - macroregiuni_regiuni_nom_id: INT32
  - perioade_nom_id: INT32
  - um_numar_nom_id: INT32
  - value: DOUBLE

Sample data:
macroregiuni_regiuni_nom_id | perioade_nom_id | um_numar_nom_id | value
---------------------------|-----------------|-----------------|-------
21295                      | 4285            | 9669            | 6.0
21295                      | 4304            | 9669            | 8.0
21295                      | 4323            | 9669            | 6.0
```

**Example: POP107D.parquet** (6 dimensions)
```
Schema:
  - varste_grupe_nom_id: INT32
  - sexe_nom_id: INT32
  - judete_nom_id: INT32
  - localitati_nom_id: INT32
  - perioade_nom_id: INT32
  - um_nom_id: INT32
  - value: DOUBLE

Sample data:
varste_grupe_nom_id | sexe_nom_id | judete_nom_id | localitati_nom_id | perioade_nom_id | um_nom_id | value
--------------------|-------------|---------------|-------------------|-----------------|-----------|-------
2                   | 106         | 3064          | 113               | 4285            | 9685      | 3111.0
2                   | 106         | 3064          | 113               | 4304            | 9685      | 2795.0
```

### Benefits of Parquet Format

1. **Natural Schema**: Each dataset keeps its natural column structure
2. **No NULL Padding**: No wasted space from unused dimension columns
3. **Compression**: Typically 10-20x smaller than CSV
4. **Type Safety**: Integers stored as INT32, not text
5. **Column Pruning**: Read only needed columns
6. **Fast Filtering**: Columnar format optimized for WHERE clauses
7. **Metadata Embedded**: Schema included in file

---

## Data Transformation Logic

### CSV to Parquet Transformation

For each CSV file in `data/5-compact-datasets/ro/`:

1. **Load metadata** from corresponding JSON file
2. **Extract dimension labels** from `dimensionsMap`
3. **Generate column names** by sanitizing labels
4. **Read CSV data** (skip header, use nom_item_id values)
5. **Create Parquet file** with proper schema and types

**Column Name Sanitization**:
```python
def sanitize_column_name(label):
    """Convert dimension label to valid SQL column name"""
    # Remove special characters, replace spaces with underscores
    # Lowercase, trim, add _nom_id suffix
    name = label.lower()
    name = re.sub(r'[^a-z0-9_]', '_', name)
    name = re.sub(r'_+', '_', name).strip('_')
    name = name[:50]  # Limit length
    return f"{name}_nom_id"

# Examples:
# "Macroregiuni, regiuni de dezvoltare si judete" → "macroregiuni_regiuni_de_dezvoltare_si_judete_nom_id"
# "UM: Numar" → "um_numar_nom_id"
# "Perioade" → "perioade_nom_id"
```

**DuckDB Conversion Example**:
```sql
-- Read CSV with metadata-derived column names
CREATE TEMP TABLE temp_data AS
SELECT
    CAST(column0 AS INTEGER) AS macroregiuni_regiuni_nom_id,
    CAST(column1 AS INTEGER) AS perioade_nom_id,
    CAST(column2 AS INTEGER) AS um_numar_nom_id,
    CAST(column3 AS DOUBLE) AS value
FROM read_csv('data/5-compact-datasets/ro/ACC101B.csv',
              skip=1,  -- Skip header
              header=false);

-- Write to Parquet
COPY temp_data TO 'data/parquet/ro/ACC101B.parquet'
(FORMAT PARQUET, COMPRESSION 'snappy');
```

---

## Query Examples

### 1. Query Single Dataset

```sql
-- Direct query of Parquet file
SELECT *
FROM 'data/parquet/ro/ACC101B.parquet'
WHERE perioade_nom_id = 4285
LIMIT 10;
```

### 2. Query with Dimension Labels

```sql
-- Join with dimension_options to get human-readable labels
SELECT
    o1.option_label as region,
    o2.option_label as period,
    p.value
FROM 'data/parquet/ro/ACC101B.parquet' p
JOIN dimensions d1 ON d1.matrix_code = 'ACC101B' AND d1.dim_code = 1
JOIN dimensions d2 ON d2.matrix_code = 'ACC101B' AND d2.dim_code = 2
JOIN dimension_options o1 ON o1.dimension_id = d1.dimension_id
                          AND o1.nom_item_id = p.macroregiuni_regiuni_nom_id
JOIN dimension_options o2 ON o2.dimension_id = d2.dimension_id
                          AND o2.nom_item_id = p.perioade_nom_id
WHERE o2.option_label LIKE 'Anul 2020%'
LIMIT 10;
```

### 3. Query All Datasets in a Category

```sql
-- Dynamic query using parquet_path from matrices table
SELECT
    m.matrix_code,
    m.matrix_name,
    COUNT(*) as row_count
FROM matrices m,
     read_parquet(m.parquet_path) p
WHERE m.context_code = '1010'
GROUP BY m.matrix_code, m.matrix_name;
```

### 4. Aggregate Across Multiple Datasets

```sql
-- Query all datasets using wildcard
SELECT
    COUNT(*) as total_rows,
    SUM(value) as total_value
FROM 'data/parquet/ro/*.parquet';
```

### 5. Find Datasets Containing Specific Dimension

```sql
-- Find all datasets with "Judete" dimension
SELECT
    m.matrix_code,
    m.matrix_name,
    d.dim_label
FROM matrices m
JOIN dimensions d ON m.matrix_code = d.matrix_code
WHERE d.dim_label LIKE '%judete%'
ORDER BY m.matrix_code;
```

### 6. Dynamic Query Helper Function

```sql
-- Create a macro for easier querying
CREATE MACRO query_dataset(dataset_code) AS TABLE
SELECT * FROM read_parquet('data/parquet/ro/' || dataset_code || '.parquet');

-- Usage:
SELECT * FROM query_dataset('ACC101B') LIMIT 10;
```

### 7. Get Dataset Statistics

```sql
-- Statistics for a single dataset
SELECT
    m.matrix_code,
    m.matrix_name,
    m.row_count,
    m.file_size_bytes / 1024 / 1024 as size_mb,
    p.min_value,
    p.max_value,
    p.avg_value
FROM matrices m
CROSS JOIN (
    SELECT
        MIN(value) as min_value,
        MAX(value) as max_value,
        AVG(value) as avg_value
    FROM read_parquet(m.parquet_path)
) p
WHERE m.matrix_code = 'ACC101B';
```

---

## Implementation Requirements

### Dependencies
```python
duckdb>=0.9.0       # DuckDB with Parquet support
pyarrow>=14.0.0     # Parquet library (used by DuckDB)
```

### Configuration
```python
# Paths
CONTEXT_CSV = "data/1-indexes/ro/context.csv"
MATRICES_CSV = "data/1-indexes/ro/matrices.csv"
METAS_DIR = "data/2-metas/ro/"
COMPACT_DIR = "data/5-compact-datasets/ro/"
PARQUET_DIR = "data/parquet/ro/"
DB_FILE = "data/tempo_metadata.duckdb"

# Processing
BATCH_SIZE = 100             # Files to process per batch
PARQUET_COMPRESSION = 'snappy'  # or 'gzip', 'zstd'
PROGRESS_INTERVAL = 50       # Log progress every N files
```

### Column Name Sanitization Rules

1. Convert to lowercase
2. Replace spaces and special chars with underscores
3. Remove consecutive underscores
4. Trim leading/trailing underscores
5. Limit to 50 characters
6. Append "_nom_id" suffix
7. Ensure uniqueness within dataset

---

## Performance Considerations

### Parquet File Optimization

1. **Compression**: Use 'snappy' for balance of speed/size (or 'zstd' for max compression)
2. **Row Groups**: Let DuckDB handle automatically
3. **Column Types**: INT32 for IDs, DOUBLE for values
4. **Statistics**: Parquet stores min/max per column for faster filtering

### Query Performance

1. **Partition Pruning**: Queries on specific datasets only read those files
2. **Column Pruning**: Only requested columns are read from Parquet
3. **Predicate Pushdown**: WHERE clauses filter at file level
4. **Indexes on Metadata**: Fast lookups in dimensions/options tables

### Expected Compression Ratios

```
CSV Format:        ~5-10 GB
Parquet (snappy):  ~500 MB - 1 GB  (10-20x compression)
Parquet (zstd):    ~300 MB - 600 MB (15-30x compression)
```

---

## Validation Queries

After import, run these queries to validate:

```sql
-- Check metadata counts
SELECT COUNT(*) FROM contexts;          -- Should be 339
SELECT COUNT(*) FROM matrices;          -- Should be ~1,888
SELECT COUNT(*) FROM dimensions;        -- Should be ~5,000-8,000
SELECT COUNT(*) FROM dimension_options; -- Should be ~300,000+

-- Check Parquet files exist
SELECT
    matrix_code,
    parquet_path,
    file_exists(parquet_path) as exists
FROM matrices
WHERE NOT file_exists(parquet_path);  -- Should be empty

-- Verify row counts match
SELECT
    m.matrix_code,
    m.row_count as metadata_count,
    (SELECT COUNT(*) FROM read_parquet(m.parquet_path)) as actual_count,
    m.row_count - (SELECT COUNT(*) FROM read_parquet(m.parquet_path)) as diff
FROM matrices m
WHERE m.row_count != (SELECT COUNT(*) FROM read_parquet(m.parquet_path))
LIMIT 10;  -- Should be empty

-- Check for orphaned records
SELECT COUNT(*) FROM matrices
WHERE context_code NOT IN (SELECT context_code FROM contexts);

-- Verify dimension integrity
SELECT
    m.matrix_code,
    m.mat_max_dim,
    COUNT(d.dim_code) as actual_dims
FROM matrices m
LEFT JOIN dimensions d ON m.matrix_code = d.matrix_code
GROUP BY m.matrix_code, m.mat_max_dim
HAVING m.mat_max_dim != COUNT(d.dim_code);

-- Sample data from largest datasets
SELECT
    m.matrix_code,
    m.row_count,
    (SELECT COUNT(*) FROM read_parquet(m.parquet_path)) as verified_count
FROM matrices m
ORDER BY m.row_count DESC
LIMIT 10;
```

---

## File Structure

### Scripts to Create
```
8-setup-duckdb-schema.py       # Create database and metadata tables
9-csv-to-parquet.py            # Convert CSV → Parquet with proper schemas
10-import-metadata.py          # Import contexts, matrices, dimensions, options
query-duckdb.py                # Helper query tool with examples
duckdb-config.py               # Configuration constants
```

### Directory Structure
```
data/
├── 1-indexes/ro/              # Input: Context and matrices CSVs
├── 2-metas/ro/                # Input: JSON metadata
├── 5-compact-datasets/ro/     # Input: CSV data files
├── parquet/ro/                # Output: Parquet data files (to be created)
├── tempo_metadata.duckdb      # Output: Metadata database (to be created)
└── logs/
    ├── parquet-conversion-{timestamp}.log
    └── metadata-import-{timestamp}.log
```

---

## Advantages of Parquet + DuckDB Hybrid

### vs. All-in-One Database Table
- ✅ No NULL padding for unused dimensions
- ✅ Natural schema per dataset
- ✅ Easier to add new datasets with any number of dimensions
- ✅ Can query files directly without import
- ✅ Portable Parquet files work with other tools

### vs. Keeping CSVs
- ✅ 10-20x smaller file sizes
- ✅ 5-50x faster queries
- ✅ Type safety (integers, not strings)
- ✅ Column-level compression
- ✅ Built-in statistics for faster filtering

### vs. SQLite
- ✅ Better analytics performance
- ✅ Native Parquet support
- ✅ Better compression
- ✅ Faster aggregations
- ✅ Modern SQL features (arrays, JSON, etc.)

---

## Next Steps

1. ✅ Create specification document (this file)
2. ⬜ Install DuckDB and PyArrow libraries
3. ⬜ Create `8-setup-duckdb-schema.py` to initialize database
4. ⬜ Create `9-csv-to-parquet.py` to convert all CSV files
5. ⬜ Create `10-import-metadata.py` to populate metadata tables
6. ⬜ Test with sample datasets first
7. ⬜ Run full conversion
8. ⬜ Validate data integrity
9. ⬜ Create query helper tools
10. ⬜ Update UI to query DuckDB + Parquet

---

## Success Criteria

- [ ] Database file created: `data/tempo_metadata.duckdb` (< 100 MB)
- [ ] All 339 contexts imported
- [ ] All ~1,888 matrices with metadata imported
- [ ] All dimensions and options imported
- [ ] 1,892 Parquet files created in `data/parquet/ro/`
- [ ] Total Parquet size < 2 GB (compressed from ~50 GB CSV)
- [ ] No orphaned foreign key references
- [ ] All validation queries pass
- [ ] Query performance: < 100ms for single dataset retrieval
- [ ] Query performance: < 2s for aggregations across category
