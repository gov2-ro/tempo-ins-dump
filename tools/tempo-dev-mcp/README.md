# tempo-dev MCP Server

Developer introspection tools for the INS TEMPO dataset explorer. Designed for Claude Code sessions — gives instant access to dataset metadata, chart scoring, data sampling, and catalog search without manual DuckDB queries or file reads.

Registered repo-locally in `.mcp.json` — auto-loaded in every Claude Code session in this directory.

## Prerequisites

- Python venv: `source ~/devbox/envs/240826/bin/activate`
- DuckDB metadata: `data/corpus/metadata.duckdb` (16 tables)
- Parquet corpus: `data/corpus/parquet/` (~3,600 files)

## Registration

Already configured in `.mcp.json` at repo root:

```json
{
  "mcpServers": {
    "tempo-dev": {
      "command": "/Users/pax/devbox/envs/240826/bin/python",
      "args": ["/Users/pax/devbox/gov2/tempo-ins-dump/tools/tempo-dev-mcp/server.py"],
      "env": {
        "TEMPO_REPO_ROOT": "/Users/pax/devbox/gov2/tempo-ins-dump"
      }
    }
  }
}
```

## Architecture

All tools call into the shared service layer — no duplicated logic:

```
tools/tempo-dev-mcp/server.py
    │
    ├── app/services/dataset_search.py   ← search_datasets()
    ├── app/services/dataset_meta.py     ← get_dataset_meta()
    ├── app/services/chart_selector.py   ← build_signature(), select_charts()
    └── app/services/query_builder.py    ← build_data_query()
```

The same services back the FastAPI routes (`app/routers/`) and will back the future NL→Data agent.

## Tools

### 1. `tempo_dataset_info(matrix_code)`

Full introspection for a single dataset in one call. Replaces what would otherwise take 5+ file reads and DuckDB queries.

**Parameters:**

| Param | Type | Description |
|---|---|---|
| `matrix_code` | `str` (required) | Dataset identifier, e.g. `ACC101B`, `POP301A_judete` |

**Returns** JSON with:

```json
{
  "matrix_code": "AMG157G",
  "matrix_name": "AMIGO - Rata somajului BIM ...",
  "definitie": "Rata somajului ...",
  "ultima_actualizare": "2026-03-31",
  "context_path": [{"code": "15", "name": "..."}, ...],
  "row_count": 1560,
  "dim_count": 4,
  "is_split": false,
  "parent_matrix_code": null,
  "splits": [],
  "dimensions": [
    {
      "dim_code": 1,
      "dim_label": "Grupe de varsta",
      "dim_column_name": "AGE",
      "dim_type": "age",
      "option_count": 3,
      "options": [
        {"nom_item_id": 123, "label": "15 - 24 ani", "sdmx_value": "15 - 24 ani", ...}
      ]
    }
  ],
  "chart_config": {
    "primary_chart": "line",
    "archetype": "demographic",
    "ranked_charts": [...],
    "dataset_signature": {...}
  },
  "view_profile": { ... },
  "value_profile": { "mean": ..., "median": ..., "distribution_shape": ... },
  "coverage": { "fill_rate": ..., "time_coverage": ..., "geo_coverage": ... },
  "trend": { "trend_direction": "volatile", "slope": ..., "yoy_growth": ... },
  "sample_rows": [
    {"AGE": "15 - 24 ani", "SEX": "Masculin", "TIME_PERIOD": "2004-01", "OBS_VALUE": 21.7}
  ]
}
```

Options are capped at 50 per dimension (with `_options_truncated` count if exceeded). Sample rows default to 10.

**Example use case:** "Tell me everything about this dataset" — structure, dimensions, what the data looks like, how it charts, coverage gaps, trend direction.

---

### 2. `tempo_search_datasets(query, has_geo?, archetype?, limit?)`

Search the catalog of ~3,600 canonical datasets.

**Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `query` | `str` (required) | — | Free-text search (Romanian or English) |
| `has_geo` | `bool \| null` | `null` | Filter to datasets with geographic dimension |
| `archetype` | `str \| null` | `null` | Filter: `geo_time`, `demographic`, `time_residence`, `time_series` |
| `limit` | `int` | `10` | Max results (max 25) |

**Returns** JSON:

```json
{
  "total": 9,
  "datasets": [
    {
      "matrix_code": "AMG157G",
      "matrix_name": "AMIGO - Rata somajului BIM ...",
      "context_code": "1511",
      "ultima_actualizare": "2026-03-31",
      "row_count": 1560,
      "dim_count": 4,
      "archetype": "demographic",
      "has_time": true,
      "has_geo": false,
      "time_range": "2004-2025",
      "primary_unit_type": "percentage",
      "time_granularity": "monthly",
      "is_split": false,
      "parent_matrix_code": null,
      "split_count": 0
    }
  ]
}
```

**Known limitation:** Search is currently LIKE-based (`WHERE matrix_name LIKE '%query%'`). English queries against Romanian names won't match. FTS upgrade planned.

---

### 3. `tempo_chart_signature(matrix_code)`

Chart selection scoring breakdown. Shows exactly why each chart type was chosen or rejected.

**Parameters:**

| Param | Type | Description |
|---|---|---|
| `matrix_code` | `str` (required) | Dataset identifier |

**Returns** JSON:

```json
{
  "matrix_code": "AMG157G",
  "archetype": "demographic",
  "signature": {
    "has_time": true,
    "time_points": 2025,
    "time_granularity": "monthly",
    "has_geo": false,
    "geo_count": 0,
    "has_gender": true,
    "has_age": true,
    "has_residence": false,
    "total_dims": 4,
    "primary_unit_type": "percentage",
    "trend_direction": "volatile",
    "has_seasonality": false
  },
  "ranked_charts": [
    {
      "chart_type": "line",
      "score": 0.75,
      "confidence": "low",
      "complementary_to": "population_pyramid",
      "roles": {
        "x_axis": "TIME_PERIOD",
        "series": "SEX",
        "filter": ["AGE"],
        "filter_hints": {"AGE": "pill_group"},
        "defaults": {"exclude_total": true}
      }
    }
  ]
}
```

**Example use case:** "Why is this dataset showing a bar chart instead of a line chart?" — check the scores and signature to understand the scoring logic.

---

### 4. `tempo_sample(matrix_code, n?, filters?)`

Sample rows from a dataset's parquet file. Values are human-readable SDMX strings (not numeric IDs).

**Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `matrix_code` | `str` (required) | — | Dataset identifier |
| `n` | `int` | `10` | Number of rows (max 100) |
| `filters` | `str \| null` | `null` | JSON string: `{"COLUMN": ["val1", "val2"]}` |

**Returns** JSON:

```json
{
  "matrix_code": "AMG157G",
  "row_count": 3,
  "rows": [
    {
      "AGE": "15 - 24 ani",
      "SEX": "Masculin",
      "TIME_PERIOD": "2004-01",
      "UNIT_MEASURE": "Procente",
      "OBS_VALUE": 21.7
    }
  ]
}
```

**Example use case:** "What does this dataset actually look like?" — inspect actual values, column names, data types before writing queries or building features.

---

### 5. `tempo_query(matrix_code, filters?, group_by?, limit?)`

Aggregated data queries. Wraps `query_builder.build_data_query()` — SQL is never LLM-generated. Automatically picks the right aggregation function (SUM for counts/currency, AVG for percentages).

**Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `matrix_code` | `str` (required) | — | Dataset identifier |
| `filters` | `str \| null` | `null` | JSON string: `{"COLUMN": ["val1", "val2"]}` |
| `group_by` | `str \| null` | `null` | JSON string: `["TIME_PERIOD", "SEX"]` |
| `limit` | `int` | `1000` | Max rows (max 5000) |

**Returns** JSON:

```json
{
  "matrix_code": "AMG157G",
  "columns": ["TIME_PERIOD", "OBS_VALUE"],
  "rows": [
    {"TIME_PERIOD": "2004-01", "OBS_VALUE": 21.7},
    {"TIME_PERIOD": "2004-02", "OBS_VALUE": 21.7}
  ],
  "row_count": 252,
  "agg_func": "AVG",
  "query_sql": "SELECT ... FROM read_parquet(...) ..."
}
```

Without `group_by`, returns raw rows (like `tempo_sample` but with filters and higher limit). With `group_by`, aggregates — e.g. `group_by=["TIME_PERIOD"]` gives one value per period.

**Example use case:** "What's the average unemployment rate per year?" — `tempo_query("AMG157G", group_by='["TIME_PERIOD"]', filters='{"SEX":["Total"],"AGE":["Total"]}')`.

---

### 6. `tempo_catalog_stats(group_by?)`

Corpus-level statistics. Answers "what does the catalog contain?"

**Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `group_by` | `str` | `"archetype"` | One of: `archetype`, `category`, `unit_type`, `geo`, `time_granularity` |

**Returns** JSON:

```json
{
  "group_by": "archetype",
  "total_datasets": 1225,
  "breakdown": [
    {"label": "time_series", "count": 860},
    {"label": "demographic", "count": 180},
    {"label": "geo_time", "count": 126},
    {"label": "time_residence", "count": 58}
  ]
}
```

**Example use case:** "How many datasets have geographic data?" — `tempo_catalog_stats(group_by="geo")`.

---

## Search

Search uses a two-tier strategy:

1. **FTS (primary)** — DuckDB full-text search over a sidecar database (`data/corpus/search.duckdb`). Searches across matrix names (RO + EN), 92k bilingual tags, definitions, and category paths. Bilingual queries work (e.g. "unemployment rate" finds Romanian somaj datasets).

2. **LIKE (fallback)** — If the FTS sidecar doesn't exist, falls back to `LIKE '%query%'` on matrix names. Build the sidecar with:

```bash
python scripts/build-search-index.py
```

The sidecar is ~14 MB, built in ~2 seconds, read-only at runtime. Rebuild after metadata changes.

## Known Limitations

- **No cross-dataset queries** — can't compare or join two datasets.
- **Options capped** — `tempo_dataset_info` caps dimension options at 50 per dimension for response size.
- **DuckDB write lock** — if the dev server (`uvicorn`) is running, MCP reads work fine. But don't run pipeline scripts that write to DuckDB while MCP is active.
- **FTS ranking** — BM25 without stemmer; Romanian morphology not handled. "populatia" won't match "populatie". Embedding-based search planned for v3.

## Files

```
tools/tempo-dev-mcp/
  server.py          — MCP server (6 tools), uses official `mcp` Python SDK (FastMCP)
  README.md          — this file

app/services/        — shared service layer (used by MCP, FastAPI routes, future agent)
  dataset_search.py  — search_datasets() with FTS-first strategy
  dataset_meta.py    — get_dataset_meta()
  chart_selector.py  — build_signature(), select_charts(), assign_roles()
  query_builder.py   — build_data_query()

scripts/
  build-search-index.py  — builds FTS sidecar (data/corpus/search.duckdb)
```
