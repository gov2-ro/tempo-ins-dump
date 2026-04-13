# MCP v1 Documentation + MCP v2 Improvements

## Context

The `tempo-dev` MCP server (v1) was built in our last session with 4 introspection tools backed by a shared service layer. It works and is registered in `.mcp.json`, but has zero documentation beyond docstrings in `server.py` and a brief table in `CLAUDE.md`. Before improving the MCP, we need to document what v1 does.

The v2 improvements address the friction points identified during v1 usage: LIKE-based search can't handle bilingual/fuzzy queries, there's no way to query aggregated data (only raw samples), and no corpus-level awareness.

---

## Part A: MCP v1 Documentation

**File:** `tools/tempo-dev-mcp/README.md`

Contents:
- What the MCP is and why it exists (dev introspection for Claude Code sessions)
- Prerequisites (Python venv, DuckDB, parquet corpus)
- Registration (`.mcp.json` at repo root — already done)
- All 4 tools documented with: description, parameters, return shape, example usage
  - `tempo_dataset_info(matrix_code)` — full metadata + dims + chart scores + sample
  - `tempo_search_datasets(query, has_geo, archetype, limit)` — catalog search
  - `tempo_chart_signature(matrix_code)` — chart selection scoring breakdown
  - `tempo_sample(matrix_code, n, filters)` — labelled rows from parquet
- Architecture note: shared service layer (`app/services/dataset_search.py`, `dataset_meta.py`)
- Limitations / known gaps (search is LIKE-based, no aggregation, no cross-dataset)

**Also update:** `CLAUDE.md` — expand the brief MCP table with parameter signatures.

---

## Part B: MCP v2 — New Tools

### B1. `tempo_query` — Aggregated data queries

The missing "answer a data question" capability. Wraps `query_builder.build_data_query()`.

```python
tempo_query(
    matrix_code: str,
    filters: str | None = None,   # JSON: {"REF_AREA": ["Bucuresti"]}
    group_by: str | None = None,  # JSON: ["TIME_PERIOD", "SEX"]
    limit: int = 1000
) -> str  # JSON with columns + rows
```

**Implementation:** call `get_dataset_meta()` for dimensions, build query via `build_data_query()`, execute on DuckDB, return `{matrix_code, columns, rows, row_count, query_sql}`.

**Key files:**
- `tools/tempo-dev-mcp/server.py` — add tool
- `app/services/query_builder.py` — already exists, reuse as-is
- `app/services/dataset_meta.py` — for dimension list

### B2. `tempo_catalog_stats` — Corpus-level awareness

Answers "how many datasets cover education?", "what archetypes exist?", "how many datasets have geo?"

```python
tempo_catalog_stats(
    group_by: str = "archetype"  # "archetype" | "category" | "unit_type" | "geo"
) -> str  # JSON breakdown with counts
```

**Implementation:** simple DuckDB aggregation over `matrices` + `matrix_profiles` + `contexts`.

### B3. FTS search upgrade for `tempo_search_datasets`

Replace LIKE-based search with DuckDB FTS. Build a sidecar `data/corpus/search.duckdb` to avoid write-lock on `metadata.duckdb`.

**Approach:**
1. New script `scripts/build-search-index.py` — creates `search.duckdb` with FTS over:
   - `matrices.matrix_name` + `matrices.matrix_name_en`
   - `dataset_tags.tag` (92k bilingual tags)
   - `matrices.definitie` (definitions)
2. Update `app/services/dataset_search.py` — try FTS sidecar first, fallback to LIKE if sidecar missing
3. MCP `tempo_search_datasets` benefits automatically (calls same service)

**Key decision:** sidecar DB avoids the metadata.duckdb write-lock. The sidecar is read-only at runtime; rebuilt by script when needed.

---

## Implementation Order

1. **Write `tools/tempo-dev-mcp/README.md`** — document v1
2. **Update CLAUDE.md** — expand MCP tool table
3. **Add `tempo_query` tool** to server.py
4. **Add `tempo_catalog_stats` tool** to server.py
5. **Build FTS search index** — `scripts/build-search-index.py`
6. **Upgrade search service** — FTS in `dataset_search.py`
7. **Update README** — document new v2 tools

## Files to modify/create

| File | Action |
|---|---|
| `tools/tempo-dev-mcp/README.md` | CREATE — full MCP documentation |
| `tools/tempo-dev-mcp/server.py` | MODIFY — add `tempo_query` + `tempo_catalog_stats` |
| `scripts/build-search-index.py` | CREATE — FTS sidecar builder |
| `app/services/dataset_search.py` | MODIFY — FTS-first search |
| `CLAUDE.md` | MODIFY — expand MCP section |
| `docs/activity-history.md` | MODIFY — log changes |
| `docs/BACKLOG.md` | MODIFY — check off completed items |

## Verification

1. **README accuracy:** read the README, call each documented tool via MCP, confirm return shapes match docs
2. **`tempo_query`:** call with `tempo_query("POP101A", group_by='["TIME_PERIOD"]')` — should return aggregated population by year
3. **`tempo_catalog_stats`:** call with each group_by option, verify counts are sensible (~3,600 total datasets)
4. **FTS search:**
   - `python scripts/build-search-index.py` — creates sidecar
   - `tempo_search_datasets("population by county")` — should find POP datasets (currently returns nothing with LIKE)
   - `tempo_search_datasets("somaj")` — should still work (regression check)
5. **Existing functionality:** `uvicorn app.main:app --port 8080` — verify `/api/datasets?q=somaj` still works
