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
data/parquet-v3/ro/*.parquet          # 1,886 files - SDMX-native format (current)
data/parquet-v2/ro/*.parquet          # 1,886 files - Integer nomItemId format (legacy)
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
- `dim_column_name` uses SDMX concept IDs (since parquet-v3 migration)
- Mapped via `sdmx_column_map` table from original Romanian names
- Example: "Macroregiuni, regiuni de dezvoltare si judete" → `REF_AREA`

**Sample Data**:
```
dimension_id | matrix_code | dim_code | dim_label                           | dim_column_name | option_count
-------------|-------------|----------|-------------------------------------|-----------------|-------------
1            | ACC101B     | 1        | Macroregiuni, regiuni de dezvoltare | REF_AREA        | 56
2            | ACC101B     | 2        | Perioade                            | TIME_PERIOD     | 32
3            | ACC101B     | 3        | UM: Numar                           | UNIT_MEASURE    | 1
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

### Two Generations

The project maintains two parquet formats:

| | Parquet v2 (legacy) | Parquet v3 (current) |
|---|---|---|
| **Path** | `data/parquet-v2/ro/` | `data/parquet-v3/ro/` |
| **Column names** | Romanian (`macroregiuni_..._nom_id`) | SDMX concepts (`REF_AREA`) |
| **Cell values** | Integer nomItemIds (`21295`) | Human-readable strings (`"MACROREGIUNEA UNU"`) |
| **Value column** | `value` | `OBS_VALUE` |
| **Column types** | INT32 + DOUBLE | VARCHAR + DOUBLE |
| **Generated by** | `9-csv-to-parquet.py` | `12-parquet-to-sdmx.py` |

The app reads from **parquet-v3** (configured in `app/config.py`).

### File Organization
```
data/parquet-v3/ro/
├── ACC101B.parquet
├── ACC101C.parquet
├── POP107D.parquet
└── ... (1,886 files total, 128 MB)
```

### Parquet v3 Schema (SDMX-native)

Each Parquet file has a **custom schema** based on its dimensions, using SDMX concept IDs:

**Example: ACC101B.parquet** (3 dimensions)
```
Schema:
  - REF_AREA: VARCHAR        (geographic area)
  - TIME_PERIOD: VARCHAR     (time period, ISO 8601)
  - UNIT_MEASURE: VARCHAR    (unit of measurement)
  - OBS_VALUE: DOUBLE        (observed value)

Sample data:
REF_AREA            | TIME_PERIOD | UNIT_MEASURE | OBS_VALUE
--------------------|-------------|--------------|----------
MACROREGIUNEA UNU   | 1992        | Numar        | 6.0
MACROREGIUNEA UNU   | 1993        | Numar        | 8.0
Bihor               | 1992        | Numar        | 1.0
```

**Example: POP107D.parquet** (6 dimensions)
```
Schema:
  - AGE: VARCHAR              (age group)
  - SEX: VARCHAR              (gender)
  - REF_AREA: VARCHAR         (county/region)
  - REF_AREA_2: VARCHAR       (locality)
  - TIME_PERIOD: VARCHAR      (time period)
  - UNIT_MEASURE: VARCHAR     (unit)
  - OBS_VALUE: DOUBLE         (observed value)

Sample data:
AGE         | SEX      | REF_AREA | REF_AREA_2 | TIME_PERIOD | UNIT_MEASURE | OBS_VALUE
------------|----------|----------|------------|-------------|--------------|----------
0-4 ani     | Masculin | Alba     | Alba Iulia | 1992        | Numar        | 3111.0
0-4 ani     | Masculin | Alba     | Alba Iulia | 1993        | Numar        | 2795.0
```

### SDMX Concept ID Mapping

Column names follow SDMX standard concepts:

| Dimension Type | SDMX Concept ID | Examples |
|---|---|---|
| Time | `TIME_PERIOD` | "1992", "2023-Q3", "2024-01" |
| Geography | `REF_AREA` | "Bihor", "MACROREGIUNEA UNU" |
| Gender | `SEX` | "Masculin", "Feminin", "Total" |
| Age | `AGE` | "0-4 ani", "25-29 ani" |
| Unit | `UNIT_MEASURE` | "Numar", "Procente", "Lei" |
| Residence | `URBANISATION` | "Urban", "Rural", "Total" |
| Activity | `ACTIVITY` | CAEN sector labels |
| Education | `EDUCATION_LEV` | Education level labels |
| Indicator | `INDICATOR` | Thematic indicator labels |
| Other | `DIM_1`, `DIM_2` | Fallback for unclassified dims |

For duplicate concepts (e.g., two geo dims): `REF_AREA`, `REF_AREA_2`.

### Benefits of Parquet v3 Format

1. **Self-documenting**: Data is human-readable without joining metadata tables
2. **NL2SQL ready**: LLMs can write `WHERE REF_AREA = 'Bihor'` without ID lookup
3. **Notebook-friendly**: Researchers load parquet and immediately understand the data
4. **Cross-source joinable**: SDMX column names match Eurostat/OECD conventions
5. **Natural Schema**: Each dataset keeps its natural column structure
6. **Compression**: ~128 MB for 1,886 datasets
7. **Column Pruning**: Read only needed columns via DuckDB

---

### Table 5: `sdmx_codes`
Global mapping from INS nomItemId integers to SDMX-friendly string values.

```sql
CREATE TABLE sdmx_codes (
    nom_item_id INTEGER PRIMARY KEY,
    dim_type VARCHAR,           -- time/geo/gender/age/unit/residence/indicator
    sdmx_value VARCHAR,         -- value used in parquet-v3
    display_label_ro VARCHAR,   -- Romanian display label
    display_label_en VARCHAR,   -- English display label (nullable)
    standard_code VARCHAR,      -- NUTS/ISO code for cross-source joins (nullable)
    source VARCHAR              -- 'parsed'/'manual'/'inferred'
);
```

**18,203 rows.** Built by `11-build-sdmx-codes.py` from `dimension_options_parsed`.

**Sample Data**:
```
nom_item_id | dim_type | sdmx_value          | display_label_ro      | standard_code
------------|----------|---------------------|-----------------------|--------------
3068        | geo      | Bihor               | Bihor                 | RO111
4285        | time     | 1992                | Anul 1992             | NULL
106         | gender   | Masculin            | Masculin              | M
9669        | unit     | Numar               | Numar                 | NULL
```

---

### Table 6: `sdmx_column_map`
Per-dataset mapping from original parquet-v2 column names to SDMX concept IDs.

```sql
CREATE TABLE sdmx_column_map (
    matrix_code VARCHAR,
    old_column_name VARCHAR,    -- parquet-v2 column name
    sdmx_column_name VARCHAR,   -- SDMX concept ID
    dim_type VARCHAR,           -- semantic type
    PRIMARY KEY (matrix_code, old_column_name)
);
```

**10,683 rows.** Built by `11-build-sdmx-codes.py`.

**Sample Data**:
```
matrix_code | old_column_name                                | sdmx_column_name | dim_type
------------|------------------------------------------------|------------------|----------
ACC101B     | macroregiuni_regiuni_de_dezvoltare_si_judet... | REF_AREA         | geo
ACC101B     | perioade_nom_id                                | TIME_PERIOD      | time
ACC101B     | um_numar_nom_id                                | UNIT_MEASURE     | unit
```

---

## Data Transformation Pipeline

### Stage 1: CSV → Parquet v2 (integer IDs)

Script: `9-csv-to-parquet.py`

For each CSV file in `data/5-compact-datasets/ro/`:
1. Load metadata from JSON
2. Generate column names by sanitizing Romanian dim labels + `_nom_id` suffix
3. Cast columns to INT32, value to DOUBLE
4. Write to `data/parquet-v2/ro/`

### Stage 2: Parquet v2 → Parquet v3 (SDMX-native)

Scripts: `11-build-sdmx-codes.py` + `12-parquet-to-sdmx.py`

1. **Build lookup tables** (`11-build-sdmx-codes.py`):
   - `sdmx_codes`: nomItemId → human-readable string (from `dimension_options_parsed`)
   - `sdmx_column_map`: old column name → SDMX concept ID (from `classify_dimensions()` logic)

2. **Transform parquet files** (`12-parquet-to-sdmx.py`):
   - Read parquet-v2 (integer nomItemIds)
   - Replace cell values: `3068` → `"Bihor"` (via `sdmx_codes`)
   - Rename columns: `macroregiuni_..._nom_id` → `REF_AREA` (via `sdmx_column_map`)
   - Rename `value` → `OBS_VALUE`
   - Write to `data/parquet-v3/ro/`

3. **Update metadata** (manual):
   - `dimensions.dim_column_name` updated to SDMX concept IDs
   - View profiles regenerated via `generate_view_profiles.py`

---

## Query Examples (Parquet v3)

### 1. Query Single Dataset — Self-Documenting

```sql
-- No JOINs needed — values are human-readable
SELECT *
FROM 'data/parquet-v3/ro/ACC101B.parquet'
WHERE TIME_PERIOD = '2020'
LIMIT 10;

-- Result:
-- REF_AREA          | TIME_PERIOD | UNIT_MEASURE | OBS_VALUE
-- Bihor             | 2020        | Numar        | 0.0
-- Cluj              | 2020        | Numar        | 1.0
```

### 2. NL2SQL-Friendly Queries

```sql
-- An LLM can generate this directly from natural language
SELECT REF_AREA, OBS_VALUE
FROM 'data/parquet-v3/ro/ACC101B.parquet'
WHERE TIME_PERIOD = '2023'
  AND REF_AREA IN ('Bihor', 'Cluj', 'Timis')
ORDER BY OBS_VALUE DESC;
```

### 3. Find Datasets with Specific Dimensions

```sql
-- Find all datasets with county-level geography
SELECT m.matrix_code, m.matrix_name, d.dim_label
FROM matrices m
JOIN dimensions d ON m.matrix_code = d.matrix_code
WHERE d.dim_column_name = 'REF_AREA'
  AND d.dim_label LIKE '%judete%'
ORDER BY m.matrix_code;
```

### 4. Dynamic Query Helper

```sql
CREATE MACRO query_dataset(dataset_code) AS TABLE
SELECT * FROM read_parquet('data/parquet-v3/ro/' || dataset_code || '.parquet');

-- Usage:
SELECT * FROM query_dataset('ACC101B')
WHERE REF_AREA = 'Bihor'
LIMIT 10;
```

### 5. Dataset Statistics

```sql
SELECT
    m.matrix_code,
    m.matrix_name,
    m.row_count,
    p.min_val, p.max_val, p.avg_val
FROM matrices m
CROSS JOIN (
    SELECT MIN(OBS_VALUE) min_val, MAX(OBS_VALUE) max_val, AVG(OBS_VALUE) avg_val
    FROM read_parquet('data/parquet-v3/ro/' || m.matrix_code || '.parquet')
) p
WHERE m.matrix_code = 'ACC101B';
```

### 6. Legacy v2 Queries (with JOIN for labels)

```sql
-- Still works for parquet-v2 files (integer nomItemIds)
SELECT o1.option_label as region, o2.option_label as period, p.value
FROM 'data/parquet-v2/ro/ACC101B.parquet' p
JOIN dimensions d1 ON d1.matrix_code = 'ACC101B' AND d1.dim_code = 1
JOIN dimension_options o1 ON o1.dimension_id = d1.dimension_id
                          AND o1.nom_item_id = p.macroregiuni_regiuni_nom_id
JOIN dimensions d2 ON d2.matrix_code = 'ACC101B' AND d2.dim_code = 2
JOIN dimension_options o2 ON o2.dimension_id = d2.dimension_id
                          AND o2.nom_item_id = p.perioade_nom_id
WHERE o2.option_label LIKE 'Anul 2020%'
LIMIT 10;
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
# Paths (app/config.py)
PARQUET_DIR = DATA_DIR / "parquet-v3" / "ro"      # Current SDMX-native format
PARQUET_V2_DIR = DATA_DIR / "parquet-v2" / "ro"   # Legacy fallback
DB_PATH = DATA_DIR / "tempo_metadata.duckdb"

# Paths (duckdb_config.py — pipeline scripts)
DB_FILE = "data/tempo_metadata.duckdb"
PARQUET_COMPRESSION = 'zstd'
```

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

### Pipeline Scripts
```
8-setup-duckdb-schema.py       # Create database and metadata tables
9-csv-to-parquet.py            # Convert CSV → Parquet v2 (integer IDs)
10-sdmx-export.py              # SDMX-CSV export (standalone)
11-build-sdmx-codes.py         # Build sdmx_codes + sdmx_column_map tables
12-parquet-to-sdmx.py          # Convert Parquet v2 → v3 (SDMX-native)
generate_view_profiles.py      # Generate per-dataset view profiles
duckdb_config.py               # Shared configuration constants
```

### Directory Structure
```
data/
├── 1-indexes/ro/              # Context and matrices CSVs
├── 2-metas/ro/                # JSON metadata per dataset
├── 5-compact-datasets/ro/     # Compacted CSV data files
├── parquet-v2/ro/             # Parquet v2: integer nomItemIds (legacy)
├── parquet-v3/ro/             # Parquet v3: SDMX-native strings (current)
├── view-profiles/             # Per-dataset JSON view profiles
└── tempo_metadata.duckdb      # DuckDB metadata database
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

## Pipeline Status

1. ✅ DuckDB schema + metadata import (`8-setup-duckdb-schema.py`)
2. ✅ CSV → Parquet v2 conversion (`9-csv-to-parquet.py`)
3. ✅ Dimension classification + enrichment (`10-classify-dimensions.py`)
4. ✅ SDMX code mapping tables (`11-build-sdmx-codes.py`)
5. ✅ Parquet v2 → v3 SDMX transformation (`12-parquet-to-sdmx.py`)
6. ✅ DuckDB metadata updated with SDMX column names
7. ✅ View profiles regenerated
8. ✅ FastAPI backend serving parquet-v3

### Pending
- [ ] NL2SQL schema registry + DuckDB views (Phase 5)
- [ ] Multi-source adapter — Eurostat/OECD ingestion (Phase 6)
- [ ] English parquet-v3 generation (`--lang en`)
- [ ] Clean up stale split profile files
