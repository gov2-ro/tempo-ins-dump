# Plan: SDMX-Native Internal Data Format

## Context

The INS TEMPO explorer currently stores data as parquet files with opaque Romanian column names (`macroregiuni_regiuni_de_dezvoltare_si_judet_nom_id`) and integer `nomItemId` values (`21295`). This is unusable for:
- **Generic charting UI** — other SDMX sources (Eurostat, OECD) use standard concept IDs
- **NL2SQL** — an LLM can't write `WHERE macroregiuni_nom_id = 21295`; it needs `WHERE REF_AREA = 'Bihor'`
- **Jupyter notebooks** — researchers need self-documenting data they can load and understand
- **Cross-source joins** — can't join INS `nomItemId=3068` with Eurostat `geo=RO111`

The goal is to make SDMX the **canonical internal format** so all consumers (charting UI, NL2SQL, notebooks, exports) share one data shape.

## Target Format: Parquet v3

### Column Names → SDMX Concept IDs

| Current (parquet-v2) | Target (parquet-v3) | Source |
|---|---|---|
| `macroregiuni_regiuni_..._nom_id` | `REF_AREA` | `classify_dimensions()` |
| `perioade_nom_id` | `TIME_PERIOD` | `classify_dimensions()` |
| `um_numar_nom_id` | `UNIT_MEASURE` | `classify_dimensions()` |
| `sexe_nom_id` | `SEX` | `classify_dimensions()` |
| `varste_si_grupe_de_varsta_nom_id` | `AGE` | `classify_dimensions()` |
| `categorii_de_someri_nom_id` | `DIM_1` (or descriptive) | fallback |
| `value` | `OBS_VALUE` | always |

For duplicate concepts (2 geo dims): `REF_AREA`, `REF_AREA_2` (already handled by `unique_name()` in `10-sdmx-export.py`).

### Cell Values → Human-Readable Strings

| Dimension | Current | Target | Mapping Source |
|---|---|---|---|
| TIME_PERIOD | `4285` (nomItemId) | `"1992"` (ISO 8601) | `parse_time_period()` in `10-sdmx-export.py` |
| REF_AREA | `3068` | `"Bihor"` | `dimension_options.option_label` (cleaned) |
| SEX | `106` | `"Masculin"` / `"Male"` | `dimension_options.option_label` |
| AGE | `8832` | `"25-29 ani"` | `dimension_options.option_label` |
| UNIT_MEASURE | `9669` | `"Numar"` | `dimension_options.option_label` |
| INDICATOR | `101155` | `"Total"` | `dimension_options.option_label` |
| OBS_VALUE | `6.0` | `6.0` | unchanged (numeric) |

**Why labels, not standard codes?**
- NL2SQL needs what humans type: `"Bihor"`, not `"RO111"`
- Self-documenting for notebooks
- The charting UI can display directly (no label resolution needed for basic use)
- Standard codes (NUTS, ISO) live in a **sidecar mapping table** for cross-source joins

### Concrete Example

**Current parquet-v2 (ACC101B.parquet):**
```
macroregiuni_regiuni_de_dezvoltare_si_judet_nom_id | perioade_nom_id | um_numar_nom_id | value
21295                                               | 4285            | 9669            | 6
3068                                                | 4285            | 9669            | 1
```

**Target parquet-v3 (ACC101B.parquet):**
```
REF_AREA        | TIME_PERIOD | UNIT_MEASURE | OBS_VALUE
Macroregiunea 1 | 1992        | Numar        | 6
Bihor           | 1992        | Numar        | 1
```

---

## Implementation Phases

### Phase 0: Code Mapping Table in DuckDB
**Goal:** Single source of truth mapping `nom_item_id` → SDMX-friendly values.

New table: `sdmx_codes`
```sql
CREATE TABLE sdmx_codes (
    nom_item_id INTEGER PRIMARY KEY,
    dim_type VARCHAR,           -- time/geo/gender/age/unit/residence/indicator
    sdmx_value VARCHAR,         -- the value to use in parquet-v3
    display_label_ro VARCHAR,   -- Romanian display label
    display_label_en VARCHAR,   -- English display label
    standard_code VARCHAR,      -- NUTS/ISO/SDMX cross-domain code (nullable)
    source VARCHAR              -- 'parsed'/'manual'/'inferred'
);
```

Population logic per dim_type:
- **time**: `sdmx_value = parse_time_period(option_label)` — already 74% coverage, rest from label cleanup
- **geo**: `sdmx_value = option_label` (cleaned) — 86.3% coverage. Foreign countries get ISO alpha-2 codes.
- **gender**: `sdmx_value = option_label` — trivial (Masculin/Feminin/Total)
- **age**: `sdmx_value = option_label` — as-is ("25-29 ani", "0-4 ani")
- **unit**: `sdmx_value = option_label` — as-is ("Numar", "Procente", "Lei")
- **residence**: `sdmx_value = option_label` — as-is ("Urban", "Rural")
- **indicator**: `sdmx_value = option_label` — as-is (thematic labels)

For `standard_code` (sidecar, for cross-source joins):
- geo counties → NUTS3 codes (RO111, RO112, ...) — 42 mappings, manual but one-time
- geo regions → NUTS2 codes (RO11, RO12, ...) — 8 mappings
- countries → ISO 3166-1 alpha-2 — ~200 mappings (use a standard list)
- sex → SDMX CL_SEX (M, F, T)
- freq → SDMX CL_FREQ (A, Q, M, S)

**Script:** `11-build-sdmx-codes.py`
**Input:** `dimension_options_parsed` + `dimension_options` tables
**Output:** `sdmx_codes` table in DuckDB

**Files to reuse:**
- `10-sdmx-export.py:parse_time_period()` — time conversion
- `10-classify-dimensions.py` — geo_name_clean, unit_type, gender parsing
- `dimension_options_parsed` table — pre-computed semantic fields

### Phase 1: SDMX Column Mapping Table
**Goal:** Map each dataset's parquet columns to SDMX concept IDs.

New table: `sdmx_column_map`
```sql
CREATE TABLE sdmx_column_map (
    matrix_code VARCHAR,
    old_column_name VARCHAR,    -- current parquet-v2 column name
    sdmx_column_name VARCHAR,   -- SDMX concept ID (REF_AREA, TIME_PERIOD, etc.)
    dim_type VARCHAR,           -- semantic type
    PRIMARY KEY (matrix_code, old_column_name)
);
```

Population: For each dataset, use `classify_dimensions()` logic from `10-sdmx-export.py` to map dimensions to SDMX names.

**Script:** Same `11-build-sdmx-codes.py` (second pass)
**Input:** `dimensions` table + `dimension_options_parsed` (majority dim_type per dimension)
**Output:** `sdmx_column_map` table

### Phase 2: Parquet v3 Generation
**Goal:** Transform 1,886 parquet files to SDMX-native format.

**Script:** `12-parquet-to-sdmx.py`

```
For each matrix:
  1. Read parquet-v2 file (integer nomItemIds)
  2. Look up sdmx_column_map for column renaming
  3. Look up sdmx_codes for value replacement (nomItemId → sdmx_value)
  4. Special handling for TIME_PERIOD: parse to ISO 8601 string
  5. Rename 'value' → 'OBS_VALUE'
  6. Write to data/parquet-v3/{lang}/{matrix_code}.parquet
  7. Store parquet metadata (key-value) with dataset info
```

**Pattern to follow:** `utils/14-parquet-to-ids.py` (same read-transform-write loop)

**Output:** `data/parquet-v3/ro/` (1,886 files) + `data/parquet-v3/en/` (1,886 files)

**Edge cases:**
- Unmapped nomItemIds (5.7%): fall back to `str(nomItemId)` with a log warning
- Multiple geo dimensions: REF_AREA, REF_AREA_2 (already handled by unique_name())
- Singleton dimensions (1 value): keep in parquet (filter panel already hides these)
- Mixed encoding in compacted CSV: use parquet-v2 (already fully numeric) as input, not CSV

### Phase 3: Update DuckDB Metadata
**Goal:** Point metadata to new parquet-v3 schema.

Updates to `dimensions` table:
```sql
UPDATE dimensions d
SET dim_column_name = m.sdmx_column_name
FROM sdmx_column_map m
WHERE d.matrix_code = m.matrix_code
  AND d.dim_column_name = m.old_column_name;
```

Updates to `matrices` table:
```sql
UPDATE matrices
SET parquet_path = REPLACE(parquet_path, 'parquet-v2', 'parquet-v3');
```

Add `sdmx_concept` column to `dimensions` table for explicit concept tagging.

**Also regenerate:** View profiles (`generate_view_profiles.py`) since they reference column names.

### Phase 4: Backend Updates
**Goal:** Minimal changes to serve parquet-v3 data.

Changes needed:
1. **`app/config.py`**: Point `PARQUET_DIR` to `data/parquet-v3/ro/`
2. **`app/services/query_builder.py`**: Change filter handling from integer-only to string values
   - Current: `safe_ids = [str(int(i)) for i in ids if _is_int(i)]`
   - New: Also accept string values, quote properly for DuckDB
3. **`app/routers/dataset_data.py`**: Label resolution simplifies — parquet values ARE labels now
   - Still keep `column_labels` in API response (for backward compat and EN translation)
   - But the primary display value comes from the data itself
4. **Filter panel**: Frontend sends string values instead of nomItemIds
   - `{"REF_AREA": ["Bihor", "Cluj"]}` instead of `{"macroregiuni_nom_id": [3068, 3072]}`

**Key insight:** The frontend is already column-name-agnostic. It reads `dim_column_name` from metadata. So column renames propagate automatically through the metadata update in Phase 3.

### Phase 5: NL2SQL Preparation
**Goal:** Make data queryable by LLMs.

1. **Schema registry** — generate per-dataset JSON schema files:
```json
{
  "table": "ACC101B",
  "description": "Accidente de circulatie rutiera, pe categorii de accidente...",
  "columns": {
    "REF_AREA": {"type": "VARCHAR", "description": "County/region", "examples": ["Bihor", "Cluj", "Bucuresti"]},
    "TIME_PERIOD": {"type": "VARCHAR", "description": "Year", "examples": ["1992", "2020"]},
    "UNIT_MEASURE": {"type": "VARCHAR", "description": "Unit", "examples": ["Numar"]},
    "OBS_VALUE": {"type": "DOUBLE", "description": "Observed value"}
  },
  "row_count": 1155,
  "time_range": "1992-2023"
}
```

2. **DuckDB views** for easy querying:
```sql
-- Register all parquet files as named views
CREATE VIEW ACC101B AS SELECT * FROM read_parquet('data/parquet-v3/ro/ACC101B.parquet');
```

3. **Corpus description** for LLM context: a summary of all datasets, their dimensions, and value ranges — generated from `matrices` + `sdmx_column_map` + `dataset_coverage`.

### Phase 6: Multi-Source Adapter Framework
**Goal:** Define how Eurostat/OECD data fits alongside INS data.

**Universal dataset registry** — extend `matrices` table or create new:
```sql
CREATE TABLE dataset_registry (
    source VARCHAR,          -- 'INS', 'EUROSTAT', 'OECD'
    dataset_code VARCHAR,    -- matrix_code or Eurostat flow ID
    title_en VARCHAR,
    parquet_path VARCHAR,
    column_schema JSON,      -- [{name: "REF_AREA", concept: "geo", codelist: "CL_INS_GEO"}]
    PRIMARY KEY (source, dataset_code)
);
```

**Eurostat adapter** (future script):
1. Download SDMX-CSV from Eurostat API
2. Data already has SDMX column names and codes
3. Write to `data/parquet-v3/eurostat/{flow_id}.parquet`
4. Register in dataset_registry
5. Code → label mappings from Eurostat's codelist API → store in DuckDB

**The charting UI** consumes `dataset_registry` + parquet files uniformly regardless of source.

---

## Dependency Graph

```
Phase 0 (sdmx_codes table)
  ↓
Phase 1 (sdmx_column_map table)
  ↓
Phase 2 (parquet-v3 generation)    ← biggest batch job
  ↓
Phase 3 (DuckDB metadata updates)
  ↓
Phase 4 (backend updates)          ← enables the new UI
  ↓
Phase 5 (NL2SQL preparation)       ← parallel with Phase 4
  ↓
Phase 6 (multi-source framework)   ← future, after UI is working
```

## Key Files to Create/Modify

| File | Action | Purpose |
|---|---|---|
| `11-build-sdmx-codes.py` | **Create** | Build sdmx_codes + sdmx_column_map tables |
| `12-parquet-to-sdmx.py` | **Create** | Generate parquet-v3 from parquet-v2 |
| `app/config.py` | Modify | Point PARQUET_DIR to parquet-v3 |
| `app/services/query_builder.py` | Modify | Support string-value filters |
| `app/routers/dataset_data.py` | Modify | Simplified label resolution |
| `generate_view_profiles.py` | Re-run | Regenerate with new column names |
| `8-setup-duckdb-schema.py` | Modify | Add sdmx_codes, sdmx_column_map tables |

## Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| 5.7% unmapped nomItemIds | Some values show as raw IDs | Log warnings, fix incrementally; fall back to str(nomItemId) |
| Compaction failures (40-50% of datasets) | Some parquet-v2 files may have text labels mixed with IDs | parquet-v2 is post-`14-parquet-to-ids.py`, should be clean; verify first |
| String filters slower than integer | Query performance regression | DuckDB handles string equality well; parquet predicate pushdown works on strings |
| View profiles reference old column names | Stale profiles break UI | Regenerate profiles after Phase 3 |
| English parquet needs same treatment | Double the work | Same script, different lang parameter |

## Verification Plan

1. **After Phase 2**: Spot-check 10 parquet-v3 files across archetypes (time_series, geo_time, demographic, time_residence)
2. **After Phase 4**: Start dev server, navigate to 5 datasets, verify charts render
3. **After Phase 5**: Test 10 NL2SQL queries against DuckDB views
4. **Regression**: Compare parquet-v3 row counts to parquet-v2 (must match exactly)

## Effort Estimate

- Phase 0-1: ~1 session (automated from existing parsed data)
- Phase 2: ~1-2 sessions (batch script + edge case handling)
- Phase 3-4: ~1 session (config changes + query builder update)
- Phase 5: ~1 session (schema generation + views)
- Phase 6: ~2-3 sessions (Eurostat adapter, design work)
- **Total: ~6-8 sessions for Phases 0-5, plus ~3 for Phase 6**
