# NL→Data agent for INS TEMPO

## Context

The user wants to add a natural-language interface to the INS TEMPO explorer (~3,632 Romanian statistical datasets, FastAPI + DuckDB + parquet). They asked "how would an NL2SQL set-up look like?"

**Key finding from exploration:** literal NL2SQL is the wrong frame here. Reasons:

- 3,632 different parquet schemas — the LLM can't write correct SQL without first knowing *which* parquet and *which columns*. That is a retrieval problem, not a SQL problem.
- The repo already has a battle-tested safe query layer ([app/services/query_builder.py](app/services/query_builder.py) `build_data_query()`) that handles parquet path resolution, escaping, group_by aggregation and the legacy `_nom_id` column issue. Generating SQL from an LLM throws all of that away.
- Romanian + statistical vocabulary (`rata șomajului`, `pe județe`, `pe medii`) is the hard part. SQL is the easy step that comes after entity resolution.
- Split datasets ([dataset_splits](data/corpus/metadata.duckdb)) require the agent to pick the right sub-variant (e.g. `_judete` vs the parent), which a SQL-only LLM cannot reliably do.

**Recommended architecture: tool-calling agent.** A single LLM is given 4 tools that wrap the existing safe APIs. SQL is never LLM-generated. The agent loop is ~80 lines of Python; no LangChain, no LlamaIndex.

---

## v1 scope (per user)

- Full agent: search → schema → data query → answer + chart spec
- Multi-provider LLM abstraction (Anthropic + OpenAI to start, swappable via env var)
- Retrieval via DuckDB FTS in a **sidecar** `data/corpus/search.duckdb` (kept out of `metadata.duckdb` to avoid the documented write-lock issue)
- API only — no UI in v1. Test via curl.
- Behind a feature flag (`TEMPO_ASK_ENABLED`)

---

## Architecture

```
POST /api/ask  ──▶  agent.run(question, history)
                       │
                       ├─ tool: search_datasets       ──▶ services/dataset_search.py
                       │                                    └─ FTS query against search.duckdb
                       │                                       (fallback: LIKE on metadata.duckdb)
                       │
                       ├─ tool: get_dataset_schema    ──▶ services/dataset_meta.py
                       │                                    └─ matrices + dimensions + parsed options
                       │                                       + splits + parent_matrix_code
                       │
                       └─ tool: query_dataset_data   ──▶ services/query_builder.build_data_query()
                                                            └─ executes against corpus/parquet/{code}.parquet
                                                            └─ chart_selector.select_charts() attaches chart_spec
```

---

## Files to create

### 1. `app/services/llm_client.py` — provider abstraction (~120 lines)

A thin shim with one entry point:

```python
def complete_with_tools(
    messages: list[dict],
    tools: list[dict],
    *,
    provider: str | None = None,   # "anthropic" | "openai", defaults to env
    model: str | None = None,
    max_tokens: int = 2048,
) -> LLMResponse  # normalised: {stop_reason, text, tool_calls: [{id,name,input}]}
```

- Pick provider via `TEMPO_LLM_PROVIDER` env (default `"anthropic"`).
- Two backends (`_anthropic.py`, `_openai.py`) returning the same `LLMResponse` shape.
- Tools defined once in JSON-Schema; backends translate to provider-native format (Anthropic `tools=[...]`, OpenAI `tools=[{"type":"function", "function":{...}}]`).
- Normalised tool-result message helper so the agent loop is provider-agnostic.
- Add `anthropic` and `openai` to `requirements.txt` (or whatever the project uses; check first).

### 2. `app/services/agent.py` — agent loop + tool registry + system prompt (~250 lines)

```python
def run_agent(question: str, history: list[Message] = []) -> AgentResult:
    # AgentResult = {answer, citations: [matrix_code], tool_trace, chart_spec, data, warnings}
```

- System prompt as a constant string (see "System prompt" section below).
- Tool registry: dict of `name → callable` mapping tool name to a Python function that takes `input: dict` and returns a JSON-serialisable result.
- Loop: call `complete_with_tools`, dispatch any `tool_calls`, append results, repeat until `stop_reason == "end_turn"` OR iteration cap (default 8) hit.
- After the loop, if any tool call returned data, attach `chart_spec` from `chart_selector.select_charts()` based on the last queried matrix.
- Returns the full `tool_trace` so curl debugging is easy.

### 3. `app/services/dataset_search.py` — extracted search logic

Extract the search/filter portion of [app/routers/datasets.py:list_datasets](app/routers/datasets.py) into a service function:

```python
def search_datasets(
    query: str,
    *,
    has_geo: bool | None = None,
    archetype: str | None = None,
    limit: int = 10,
    lang: str = "ro",
) -> list[DatasetCard]
```

- Tries the FTS sidecar first (if `search.duckdb` exists), falls back to LIKE on `matrices.matrix_name` joined with `dataset_tags`.
- Returns compact cards: `{matrix_code, name, dim_count, time_year_min, time_year_max, archetype, has_geo, is_split, parent_matrix_code, ultima_actualizare, score}`.
- The existing `/api/datasets` route is refactored to call this function (no behaviour change). 30 minutes of refactor; the win is that the agent and the existing route share one code path.

### 4. `app/services/dataset_meta.py` — extracted schema fetcher

Extract from [app/routers/datasets.py](app/routers/datasets.py) `get_dataset()`:

```python
def get_dataset_meta(matrix_code: str, lang: str = "ro") -> DatasetMeta
```

- Returns dimensions + dimension_options_parsed (capped to 100 values per dim) + splits + parent_matrix_code + definitie + ultima_actualizare + time/geo coverage from `dataset_coverage`.
- Existing `/api/datasets/{id}` route refactored to call this.

### 5. `app/routers/ask.py` — single endpoint

```python
@router.post("/api/ask")
def ask(req: AskRequest) -> AskResponse:
    if not config.ASK_ENABLED: raise HTTPException(404)
    return run_agent(req.question, req.history or [])
```

Mounted in [app/main.py](app/main.py) only when `ASK_ENABLED=true`.

### 6. `scripts/build-search-index.py` — sidecar FTS index builder

A one-off, re-runnable script:

```python
# Creates data/corpus/search.duckdb (separate file — does NOT touch metadata.duckdb)
# 1. ATTACH metadata.duckdb AS meta (READ_ONLY)
# 2. CREATE TABLE dataset_search AS
#    SELECT m.matrix_code,
#           m.matrix_name,
#           m.matrix_name_en,
#           string_agg(DISTINCT t.tag_ro, ' ') AS tags_ro,
#           string_agg(DISTINCT t.tag_en, ' ') AS tags_en,
#           m.context_code,
#           p.archetype, p.has_geo, p.has_time, p.dim_count,
#           p.time_year_min, p.time_year_max,
#           m.ultima_actualizare
#    FROM meta.matrices m
#    LEFT JOIN meta.matrix_profiles p USING (matrix_code)
#    LEFT JOIN meta.dataset_tags t USING (matrix_code)
#    GROUP BY ...
# 3. INSTALL fts; LOAD fts;
# 4. PRAGMA create_fts_index('dataset_search', 'matrix_code',
#                            'matrix_name','matrix_name_en','tags_ro','tags_en',
#                            stemmer='none')   # 'romanian' is not built-in; tags already cover variants
```

- **Why a sidecar?** [app/db.py](app/db.py) opens `metadata.duckdb` and the documented write-lock issue says "only one process can write at a time". Writing the FTS index into the same file would conflict with the running app and pipeline scripts. A sidecar file is opened separately, read-only, and rebuilt out-of-band.
- Document the script in [CLAUDE.md](CLAUDE.md) as part of the pipeline.
- Add a graceful fallback in `dataset_search.py`: if `search.duckdb` is missing, fall back to `LIKE` queries against `metadata.duckdb` so the agent still works without the index.

### 7. `app/config.py` — add four flags

```python
ASK_ENABLED        = os.environ.get("TEMPO_ASK_ENABLED", "false").lower() in ("1","true","yes")
LLM_PROVIDER       = os.environ.get("TEMPO_LLM_PROVIDER", "anthropic")  # anthropic | openai
LLM_MODEL          = os.environ.get("TEMPO_LLM_MODEL", "claude-sonnet-4-5")
ASK_MAX_TOOL_CALLS = int(os.environ.get("TEMPO_ASK_MAX_TOOL_CALLS", "8"))
SEARCH_DB_PATH     = DATA_ROOT / "corpus" / "search.duckdb"
```

API keys come from `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` env vars (standard SDK behaviour, no app changes needed).

---

## Tool definitions (JSON Schema)

Keep the inventory small. Four tools cover everything:

```jsonc
[
  {
    "name": "search_datasets",
    "description": "Search the catalog of ~3,600 Romanian INS statistical datasets. Returns top matches by name, tags, and category. Supports Romanian and English keywords. Use this first when you don't know the matrix code. Returns matrix_code, name, dim_count, time_range, archetype, has_geo, is_split, parent_matrix_code for each hit.",
    "input_schema": {
      "type": "object",
      "properties": {
        "query":     {"type": "string", "description": "Free-text query in Romanian or English"},
        "has_geo":   {"type": "boolean"},
        "archetype": {"type": "string", "enum": ["geo_time","demographic","time_residence","time_series"]},
        "limit":     {"type": "integer", "default": 10, "maximum": 25}
      },
      "required": ["query"]
    }
  },
  {
    "name": "get_dataset_schema",
    "description": "Fetch the full schema for a specific dataset: dimensions, dimension types (time/geo/age/gender/...), available values per dimension (capped to 100), time coverage, splits, and a brief definition. Call this BEFORE query_dataset_data so you know which columns and values are valid. If the dataset is_split=true, the response also lists sub-datasets — usually pick a sub-dataset matching the user's geographic or demographic granularity.",
    "input_schema": {
      "type": "object",
      "properties": {"matrix_code": {"type": "string"}},
      "required": ["matrix_code"]
    }
  },
  {
    "name": "query_dataset_data",
    "description": "Query a dataset's parquet file with structured filters and an optional GROUP BY. Returns up to 5,000 rows. Use group_by to aggregate (e.g. ['TIME_PERIOD','SEX']). Filters MUST use exact dimension values from get_dataset_schema. Always pass enough filters or a group_by to keep the result manageable.",
    "input_schema": {
      "type": "object",
      "properties": {
        "matrix_code": {"type": "string"},
        "filters":     {"type": "object", "description": "{column_name: [value, ...]}"},
        "group_by":    {"type": "array",  "items": {"type": "string"}}
      },
      "required": ["matrix_code"]
    }
  },
  {
    "name": "list_categories",
    "description": "Return the 3-level INS category tree from the contexts table. Useful when the user asks about a topic area rather than a specific indicator.",
    "input_schema": {"type": "object", "properties": {}}
  }
]
```

---

## System prompt outline

Keep under 800 tokens. Sections:

1. **Identity.** Assistant for the Romanian National Institute of Statistics (INS) TEMPO explorer.
2. **Bilingual policy.** User may write in Romanian or English. Datasets are primarily Romanian. Search in BOTH languages by translating internally before calling `search_datasets`. Reply in the user's language.
3. **Workflow.** (a) `search_datasets` first. (b) Disambiguate among candidates by recency and coverage. (c) ALWAYS call `get_dataset_schema` before querying — never guess columns or values. (d) For split datasets, prefer the sub-dataset matching the user's granularity ("pe județe" → `_judete`). (e) Use `group_by` for aggregate questions; never pull raw rows for a chart.
4. **Statistical vocabulary cheatsheet** (10–15 mappings): `șomaj/șomajului → unemployment`, `populație activă → labor force`, `IPC → consumer price index`, `pe județe → REF_AREA at county level`, `pe medii → RESIDENCE (urban/rural)`, `pe sexe → SEX`, `pe grupe de vârstă → AGE`, `nivel de educație → EDU_LEVEL`, etc.
5. **"Total" gotcha.** If a query returns 0 rows and a "Total" filter was applied, retry without it. The metadata sometimes lists "Total" rows that don't exist in the parquet — already documented in MEMORY.md.
6. **Output format.** End with a one-paragraph plain-language answer, the cited matrix_code(s), and (if applicable) note that a chart will render.
7. **Honesty.** If `search_datasets` returns nothing relevant, say so. Never invent matrix codes.
8. **Refusal.** Decline questions unrelated to Romanian statistics.

---

## Functions to reuse (no changes)

- [app/db.py](app/db.py) `get_conn()` — cursor-per-request, mandatory pattern.
- [app/services/query_builder.py](app/services/query_builder.py) `build_data_query()` — call as-is from the `query_dataset_data` tool. Already handles escaping, group_by, legacy column resolution.
- [app/services/chart_selector.py](app/services/chart_selector.py) `build_signature()` + `select_charts()` — call after the agent picks data, attach `chart_spec` to the response. **Do not let the LLM choose chart types.**
- [app/routers/dataset_data.py](app/routers/dataset_data.py) — copy the filter-parsing + large-dataset guard pattern into the `query_dataset_data` tool.

---

## Files to refactor (existing-file changes)

Two refactors, each ~30 minutes, behaviour-preserving:

1. **[app/routers/datasets.py](app/routers/datasets.py)** — extract `list_datasets` body into `services/dataset_search.py:search_datasets()`. The route becomes a thin wrapper. The agent tool calls the same service function. Run dev server, hit `/api/datasets?q=somaj` to confirm parity.
2. **[app/routers/datasets.py](app/routers/datasets.py)** — extract `get_dataset` body into `services/dataset_meta.py:get_dataset_meta()`. Same wrapper pattern. Hit `/api/datasets/SOM103D` to verify.

Both refactors land in a single commit before any agent code is added.

---

## Risks / gotchas (project-specific)

| Risk | Mitigation |
|---|---|
| Romanian/English mix in queries | Prompt instructs bilingual search; `search_datasets` queries both `tag_ro` and `tag_en` |
| Statistical vocabulary | Inline cheatsheet in system prompt; expand to glossary tool only if it grows past 20 entries |
| "Total" rows missing in some parquets | Prompt says retry without "Total" filter; `query_dataset_data` also auto-retries and returns a `warning` |
| Split datasets — wrong variant chosen | `get_dataset_schema` always returns `splits` + `parent_matrix_code`; prompt instructs sub-dataset preference |
| Hallucinated matrix codes | Tools return clear error on missing matrix; agent recovers via another `search_datasets` call |
| DuckDB write lock on `metadata.duckdb` | FTS index lives in **sidecar** `search.duckdb`; app opens `metadata.duckdb` read-only |
| LLM provider lock-in | `llm_client.py` abstraction; both backends produce identical `LLMResponse` |
| Cost & latency | ~$0.01–0.03 per question on Sonnet 4.5; ~3–8s end-to-end. Acceptable for v1; streaming deferred to v2 |
| Prompt injection from user input | Tools validate inputs server-side (matrix_code regex, filter dict shape); `build_data_query` already escapes |

---

## Verification

End-to-end smoke test once everything is wired:

```bash
source ~/devbox/envs/240826/bin/activate

# 1. Build the FTS sidecar
python scripts/build-search-index.py
# Should print row count and create data/corpus/search.duckdb

# 2. Sanity-check the FTS index directly
python -c "
import duckdb
con = duckdb.connect('data/corpus/search.duckdb', read_only=True)
print(con.execute(\"SELECT matrix_code, matrix_name FROM (SELECT *, fts_main_dataset_search.match_bm25(matrix_code, 'somaj judete') AS s FROM dataset_search) WHERE s IS NOT NULL ORDER BY s DESC LIMIT 5\").fetchall())
"

# 3. Start the dev server with the flag on
TEMPO_ASK_ENABLED=true ANTHROPIC_API_KEY=sk-... uvicorn app.main:app --reload --port 8080

# 4. Three test questions covering search/schema/query, geo, demographic, splits
curl -X POST localhost:8080/api/ask -H 'Content-Type: application/json' -d '{
  "question": "Care este populația Clujului în 2023?"
}'

curl -X POST localhost:8080/api/ask -H 'Content-Type: application/json' -d '{
  "question": "Show me unemployment trends by county in the last 5 years"
}'

curl -X POST localhost:8080/api/ask -H 'Content-Type: application/json' -d '{
  "question": "Câte spitale sunt în România pe județe?"
}'

# 5. Inspect the tool_trace in each response — verify:
#    - search_datasets returned plausible matches (RO + EN both work)
#    - get_dataset_schema was called before query_dataset_data
#    - For "pe județe" questions, a _judete sub-dataset was picked when available
#    - The chart_spec is attached and matches the existing chart_selector output

# 6. Provider swap test
TEMPO_LLM_PROVIDER=openai TEMPO_LLM_MODEL=gpt-4.1 OPENAI_API_KEY=sk-... \
  uvicorn app.main:app --reload --port 8080
# Run the same three curls — verify identical tool_trace shape, comparable answers.
```

Pass criterion: at least 2 of 3 questions return a sensible answer with the right matrix_code on first try, both providers work, no SQL ever appears in the LLM output.

---

## What is explicitly NOT in v1

- UI / chat panel — deferred. API only.
- Precomputed embeddings / vector search — FTS is enough for v1. Add `bge-m3` sidecar in v2.
- Streaming responses (SSE) — v2.
- Conversational memory beyond `history` parameter — v2.
- LLM response caching — v2 (after eval harness exists).
- Eval harness with hand-written test set — v2 but high priority.
- Multi-dataset comparison charts — v2.
- LangChain / LlamaIndex — never. The loop is 80 lines.

After v1 ships, add backlog entries to [docs/BACKLOG.md](docs/BACKLOG.md) for each of the above.

---

## "Tomorrow" checklist (in order)

1. **(15 min)** Re-read [app/routers/datasets.py:28-142](app/routers/datasets.py#L28-L142), [app/services/query_builder.py](app/services/query_builder.py), [app/services/chart_selector.py](app/services/chart_selector.py) `build_signature` + `select_charts`.
2. **(20 min)** `pip install anthropic openai`. Write [app/services/llm_client.py](app/services/llm_client.py) with both backends. Test each from a Python REPL with a no-op tool.
3. **(30 min)** Refactor: extract `search_datasets()` and `get_dataset_meta()` from [app/routers/datasets.py](app/routers/datasets.py) into `app/services/`. Keep route behaviour identical. Commit.
4. **(45 min)** Write [app/services/agent.py](app/services/agent.py): tool registry, system prompt constant, `run_agent()` loop, `AgentResult` dataclass.
5. **(20 min)** Write [app/routers/ask.py](app/routers/ask.py): one POST endpoint, feature-flag gate. Mount in [app/main.py](app/main.py).
6. **(20 min)** Write [scripts/build-search-index.py](scripts/build-search-index.py). Run it. Verify the FTS index works with a direct DuckDB query.
7. **(30 min)** Run the three curl tests above. Inspect `tool_trace`, fix obvious prompt issues, repeat.
8. **(10 min)** Update [CLAUDE.md](CLAUDE.md) with the new endpoint + script. Add v2 items to [docs/BACKLOG.md](docs/BACKLOG.md). Add a note to [docs/activity-history.md](docs/activity-history.md).

Total: ~3 hours of focused work for a working v1.

---

## Critical files (cheat-sheet)

| Path | Role in this plan |
|---|---|
| [app/services/query_builder.py](app/services/query_builder.py) | Reused as-is by the `query_dataset_data` tool |
| [app/services/chart_selector.py](app/services/chart_selector.py) | `select_charts()` attached to agent response |
| [app/routers/datasets.py](app/routers/datasets.py) | Refactored: `list_datasets` → service, `get_dataset` → service |
| [app/routers/dataset_data.py](app/routers/dataset_data.py) | Filter-handling pattern copied into the data tool |
| [app/db.py](app/db.py) | Cursor-per-request — mandatory, do not break |
| [app/config.py](app/config.py) | New flags: `ASK_ENABLED`, `LLM_PROVIDER`, `LLM_MODEL`, `SEARCH_DB_PATH` |
| [app/main.py](app/main.py) | Mount `ask` router behind feature flag |
| [data/corpus/metadata.duckdb](data/corpus/metadata.duckdb) | Read-only source for FTS sidecar build |
| [data/corpus/search.duckdb](data/corpus/search.duckdb) | NEW sidecar — FTS index over matrices + tags |
| [CLAUDE.md](CLAUDE.md) | Document new endpoint + script |
| [docs/BACKLOG.md](docs/BACKLOG.md) | v2 items: embeddings, streaming, eval harness, UI |
