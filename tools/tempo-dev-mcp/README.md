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

### 7. `tempo_routes()`

List every FastAPI route registered on `app.main:app`. Useful as a sanity check after mounting new routers, or to discover endpoints for `tempo_call_endpoint`.

**Returns** JSON: `{total, routes: [{methods, path, name, endpoint, tags}]}`. API routes (`/api/*`) are listed first, then static mounts.

---

### 8. `tempo_call_endpoint(method, path, params_json?, body_json?)`

Hit any FastAPI endpoint in-process via `starlette.testclient.TestClient`. No live server required.

**Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `method` | `str` (required) | — | HTTP method (`GET`/`POST`/`PUT`/`PATCH`/`DELETE`) |
| `path` | `str` (required) | — | Route path, e.g. `/api/datasets/POP107D` |
| `params_json` | `str` | `""` | JSON-encoded query params, e.g. `'{"lang":"en"}'` |
| `body_json` | `str` | `""` | JSON-encoded request body for POST/PUT/PATCH |

**Returns** JSON: `{status_code, content_type, body, truncated, json?}`. Body is capped to 8000 chars; JSON responses are also parsed into `json`.

**Example use case:** Smoke-test the new `/api/ask` endpoint after a refactor — `tempo_call_endpoint("POST", "/api/ask", body_json='{"question":"populatia Cluj 2023"}')`. Note: requires `TEMPO_ASK_ENABLED=true` in the MCP server's environment to actually invoke the agent.

---

### 9. `tempo_outdated(days=180, limit=50)`

List datasets with stale or missing `ultima_actualizare`. **Caveat:** the underlying column is sourced from INS metadata JSONs and is often stale — treat the output as a hint, not ground truth.

**Returns** JSON: `{threshold_days, caveat, counts: {total, fresh, stale, unknown_null}, oldest: [...], null_sample: [...]}`.

**Example use case:** "Which datasets haven't been refreshed in 5+ years?" — `tempo_outdated(days=1825, limit=20)`.

---

### 10. `tempo_pipeline_status(recent_log_count=10)`

Report pipeline state: `last-pipeline-run.txt` marker, `corpus-audit.json` summary, and the most recently-modified log files in `data/logs/` with ERROR/WARNING line counts.

**Returns** JSON: `{logs_dir, last_pipeline_run, corpus_audit: {timestamp, summary}, recent_logs: [{file, mtime, size_bytes, errors, warnings}]}`. Logs above 2 MB are listed without scanning their contents (counts default to 0).

**Example use case:** "Did the latest update run cleanly?" — `tempo_pipeline_status()` and look for non-zero `errors` in the most recent entries.

---

### 11. `tempo_dataset_lineage(matrix_code)`

Trace a dataset across every pipeline stage. For each artifact (`metadata_json`, `raw_csv`, `parquet_v2`, `corpus_parquet`, `view_profile`) reports presence/size/mtime, plus DuckDB row presence in `matrices`/`matrix_profiles`/`dataset_coverage`/`dataset_trends`/`dataset_value_profiles`, plus split/parent relationships.

**Returns** JSON: `{matrix_code, stages: {…}, db_state: {matrices: {…}, matrix_profiles: {exists}, …, dimensions_count}, splits: {children, parent?}}`.

**Example use case:** "Why is dataset X missing from the UI?" — `tempo_dataset_lineage("ACC102B")` shows which stage the artifact stops at.

---

### 12. `tempo_eval_chart_selector(score_threshold=0.05)`

Regression test for the chart-selection engine. Re-scores every dataset and diffs against the committed baseline at `data/eval/chart_selector_baseline.json`. Use after any change to `app/services/chart_selector.py` to surface ranking drift.

**Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `score_threshold` | `float` | `0.05` | Min primary-score delta to flag as drift |

**Returns** JSON: `{summary, primary_changes, top_set_changes, confidence_changes, score_drifts, missing, added, baseline_path, baseline_version}`. Caps: `primary_changes` always full, others 30-50 entries.

```json
{
  "summary": {
    "total_baseline": 1959,
    "total_current": 1959,
    "ok": 1959,
    "primary_changed": 0,
    "top_set_changed": 0,
    "confidence_changed": 0,
    "score_drift": 0,
    "missing": 0,
    "added": 0,
    "score_threshold": 0.05
  },
  "primary_changes": [],
  "top_set_changes": [],
  "confidence_changes": [],
  "score_drifts": [],
  "missing": [],
  "added": [],
  "baseline_path": "data/eval/chart_selector_baseline.json",
  "baseline_version": 1
}
```

**Refresh the baseline** after an intentional `chart_selector.py` change:

```bash
python scripts/build_chart_selector_baseline.py
# then review:  git diff data/eval/chart_selector_baseline.json
```

The baseline uses a custom compact format (one dataset per line) so single-row drifts produce tight git diffs. Both the build script and the MCP tool share `app/services/chart_selector_eval.py::evaluate_all()`, so the baseline and the live eval are guaranteed in lock-step.

**Example use case:** "I tweaked the line-chart threshold — which datasets flipped their primary chart?" — run `tempo_eval_chart_selector()`, inspect `primary_changes` to see before/after.

---

### 13. `tempo_check_view_profiles()`

Diagnostic audit of `data/corpus/view-profiles/`. No parameters, no baseline — just a live cross-check against the parquet corpus and the DB `matrix_profiles` table.

**Surfaces:**

| Key | Meaning |
|---|---|
| `missing_vps` | Parquet files with no corresponding VP JSON — run `generate_view_profiles.py` |
| `orphan_vps` | VP JSONs whose parquet no longer exists — candidates for cleanup |
| `version_drift` | VPs whose `meta.profile_version` < the generator's current `PROFILE_VERSION` |
| `archetype_mismatches` | VPs whose `archetype` disagrees with `matrix_profiles.archetype` |
| `profiles_with_warnings` | Count of VPs carrying a non-empty `warnings[]` (e.g. `multi_unit`, `sparse_data`) |
| `top_warnings` | Top 10 warning categories by count, with 5 sample matrix_codes each |
| `parse_errors` | VPs that failed JSON parse |
| `stale_files` | Files with `_stale` in their name |

**Returns:**

```json
{
  "summary": {
    "parquet_files": 3706,
    "view_profiles": 4184,
    "stale_files": 1,
    "missing_vps": 197,
    "orphan_vps": 675,
    "version_drift": 0,
    "archetype_mismatches": 49,
    "profiles_with_warnings": 933,
    "parse_errors": 0,
    "current_profile_version": 1
  },
  "missing_vps": [...cap 30...],
  "orphan_vps": [...cap 30...],
  "archetype_mismatches": [{"matrix_code", "vp_archetype", "db_archetype"}, ...],
  "top_warnings": [{"warning", "count", "sample_matrix_codes"}, ...]
}
```

**Example use case:** "Why is dataset X not rendering?" — run the audit, check `missing_vps`. "Why does dataset Y show the wrong chart?" — check `archetype_mismatches`.

---

### 14. `tempo_eval_agent()`

Search-quality regression detection for the NL→Data agent's retrieval layer. Runs `search_datasets()` for every question in `data/eval/agent_questions.yaml` and diffs the top-K hits against `data/eval/agent_search_baseline.json`.

Uses the same baseline-diff pattern as `tempo_eval_chart_selector`, but pins the *search* layer rather than the chart scorer. Because full agent runs need an API key and are non-deterministic, this harness exercises retrieval only — which is the biggest lever on agent correctness anyway.

**Returns:** `{summary, top_set_changes, order_changes, total_hit_drifts, missing, added, baseline_path, questions_path, baseline_version}`. Drift categories:

| Category | Trigger |
|---|---|
| `top_set_changes` | Top-K set of `matrix_code`s differs (order-insensitive). Always full list |
| `order_changes` | Same set but ordering shifted. Cap 30 |
| `total_hit_drifts` | `total_hits` moved by >20% AND delta > 5. Cap 20 (signals FTS scope shifts) |
| `missing` / `added` | Questions gained/lost between runs |

**Refresh the baseline** after an intentional change to FTS, ranking, or the corpus:

```bash
python scripts/build_agent_search_baseline.py
# then review:  git diff data/eval/agent_search_baseline.json
```

The seed question set (`agent_questions.yaml`) covers 15 common query intents (population, unemployment, inflation, GDP, exports, tourism, agriculture, etc.). Add new questions sparingly — the baseline is most useful when small and stable.

**Important:** This is *regression detection*, not a golden-answer test. The baseline captures whatever the search returns today — a human still has to review the diff to decide if a drift is an improvement or a regression.

**Example use case:** "I rebuilt the FTS index — did anything get worse?" — run `tempo_eval_agent()`, inspect `top_set_changes`, then `git diff data/eval/agent_search_baseline.json` after regenerating the baseline.

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
  server.py          — MCP server (14 tools), uses official `mcp` Python SDK (FastMCP)
  README.md          — this file

app/services/        — shared service layer (used by MCP, FastAPI routes, agent)
  dataset_search.py       — search_datasets() with FTS-first strategy
  dataset_meta.py         — get_dataset_meta()
  chart_selector.py       — build_signature(), select_charts(), assign_roles()
  chart_selector_eval.py  — evaluate_all() + diff_against_baseline() for charts
  agent_eval.py           — run_search_eval() + diff_against_baseline() for search
  query_builder.py        — build_data_query()

scripts/
  build-search-index.py              — builds FTS sidecar (data/corpus/search.duckdb)
  build_chart_selector_baseline.py   — regenerates chart_selector baseline
  build_agent_search_baseline.py     — regenerates agent search baseline

data/eval/
  chart_selector_baseline.json       — committed baseline (1959 datasets, ~290 KB)
  agent_questions.yaml               — 15 seed questions for agent search eval
  agent_search_baseline.json         — committed baseline (top-10 per question)
```
