# INS TEMPO LLM tooling — minimal dev MCP, then NL→Data agent

## Context

The user asked "how would an NL2SQL set-up look like?" and then asked a sharper follow-up: could an LLM toolset *also* help us develop the platform itself?

**Two architectural decisions came out of that conversation:**

1. **Literal NL2SQL is the wrong frame.** With 3,632 different parquet schemas, the hard problem is "which parquet + which columns," not "what SQL." The repo already has [app/services/query_builder.py](app/services/query_builder.py) `build_data_query()` doing safe parametrised SQL — throwing it away to let an LLM emit raw SQL would re-introduce every bug it solves. The right shape is a **tool-calling agent** that uses the existing safe layer; SQL is never LLM-generated. The loop is ~80 lines; no LangChain.

2. **A separate dev-tooling MCP compounds across every future session.** The biggest cost in our current collaboration isn't writing code — it's re-discovering schema, sampling parquets, running `chart_selector` mentally, grepping for routes. A small MCP server exposing the same services gives both Claude Code (me) and the user fast introspection. Built once, reused forever.

The plan combines them in an order that maximises compounding without overbuilding.

---

## Roadmap (4 steps)

| Step | What | Time | Why this order |
|---|---|---|---|
| **1** | Minimal `tempo-dev` MCP (4 introspection tools) + extracted service layer | ~2h | Refactor forces `dataset_search.py` + `dataset_meta.py` extraction. Both Step 2 and Step 3 reuse them. Compounding starts immediately. |
| **2** | v1 user-facing NL→Data agent (`POST /api/ask`) | ~2.5h | Built with the MCP loaded — every iteration is faster. Validates the LLM tool-calling pattern, FTS sidecar, provider abstraction against a real user flow. Ships public-facing value. |
| **3** | Expand the MCP with heavy tools (eval, lineage, screenshots, route introspection) | ~3–4h | Now informed by what Step 2 surfaced as real friction. No overbuilding. |
| **4** | v2 user features (cross-dataset, embeddings, narrative, methodology RAG, …) | varies | Built much faster thanks to Steps 1 + 3. See the v2+ vision section at the bottom. |

**Critical shared substrate:** Step 1 extracts `app/services/dataset_search.py` and `app/services/dataset_meta.py`. Both surfaces (MCP server in Step 1, FastAPI agent in Step 2) call into them. One refactor, four reuses.

---

## Step-1 / Step-2 architecture

```
                          ┌──────────────────────────────────────────┐
                          │   shared service layer (Step 1 extracts) │
                          │                                          │
                          │   app/services/dataset_search.py         │
                          │   app/services/dataset_meta.py           │
                          │   app/services/query_builder.py (exists) │
                          │   app/services/chart_selector.py (exists)│
                          └──────────────┬───────────────────────────┘
                                         │
                ┌────────────────────────┼─────────────────────────┐
                ▼                        ▼                         ▼
   ┌────────────────────────┐  ┌────────────────────┐   ┌────────────────────┐
   │  tempo-dev MCP server  │  │  /api/datasets     │   │  POST /api/ask     │
   │  (Step 1 + Step 3)     │  │  (existing route,  │   │  (Step 2)          │
   │                        │  │   refactored)      │   │                    │
   │  for Claude Code +     │  │  for the existing  │   │  agent.run() loop  │
   │  developer use         │  │  static UI         │   │  user-facing NL    │
   └────────────────────────┘  └────────────────────┘   └────────────────────┘
```

The same Python services back three surfaces. The dev MCP is the simplest consumer (it just returns rich JSON for me to read). The existing UI route stays unchanged in behaviour but switches to the service layer. The agent in Step 2 wires the same services as tool-call handlers.

---

## Step 1: Minimal dev MCP (~2h)

**Goal:** unblock everything else. After Step 1, every Claude Code session on this repo has fast schema introspection, instant chart-selector probing, and one-shot dataset sampling. Step 2 itself becomes faster to write because I can validate tool inputs/outputs interactively while writing the agent loop.

### Step 1 — Tools (4)

These are designed for **developer use**, not for an LLM tool loop. They return rich combined responses (a single call gives you everything you need), unlike the agent's atomic, predictable tools in Step 2.

1. **`tempo_dataset_info(matrix_code)`** — the workhorse. Returns in one shot:
   - Basic metadata (name, code, definitie, ultima_actualizare, context path)
   - Dimensions + parsed options (capped to 50/dim)
   - View profile JSON if present
   - `chart_selector.build_signature()` output + top 3 chart eligibilities
   - `dataset_value_profiles` row + `dataset_coverage` row + `dataset_trends` row
   - 10 sample rows from the parquet
   - Splits + `parent_matrix_code`
   - Replaces what currently takes 5 file reads + 2 grep cycles per session.

2. **`tempo_search_datasets(query, has_geo=None, archetype=None, limit=10)`** — same shape as the v1 agent's `search_datasets` tool. Wraps `services/dataset_search.py:search_datasets()`. Falls back to `LIKE` if no FTS sidecar exists yet.

3. **`tempo_chart_signature(matrix_code)`** — runs `build_signature()` + `select_charts()` and returns the full eligibility table with scores per chart type. **This one alone changes how I tune chart selection.** Today I have to read code and guess; with this tool I just call it and read the scores.

4. **`tempo_sample(matrix_code, n=10, filters=None)`** — labelled rows (joined with dimension labels for human readability). Useful for "what does this dataset actually look like."

### Step 1 — Files

```
tools/tempo-dev-mcp/
  pyproject.toml          # uv-compatible, single-file install
  README.md               # how to register with Claude Code
  server.py               # MCP server, ~150 lines, uses official `mcp` Python SDK

app/services/
  dataset_search.py       # NEW — extracted from app/routers/datasets.py:list_datasets
  dataset_meta.py         # NEW — extracted from app/routers/datasets.py:get_dataset

app/routers/
  datasets.py             # MODIFIED — list_datasets and get_dataset become thin wrappers
```

### Step 1 — How the MCP gets registered

Add to user-level Claude Code MCP config (or `.mcp.json` at repo root):

```jsonc
{
  "mcpServers": {
    "tempo-dev": {
      "command": "python",
      "args": ["/Users/pax/devbox/gov2/tempo-ins-dump/tools/tempo-dev-mcp/server.py"],
      "env": {
        "TEMPO_REPO_ROOT": "/Users/pax/devbox/gov2/tempo-ins-dump"
      }
    }
  }
}
```

Use the `.mcp.json` (repo-local) approach so it's checked into git and picked up by every session in this directory automatically.

### Step 1 — Verification

```bash
source ~/devbox/envs/240826/bin/activate

# 1. Sanity-check the extracted services don't break the existing route
python -c "from app.services.dataset_search import search_datasets; print(len(search_datasets('somaj', limit=5)))"
python -c "from app.services.dataset_meta import get_dataset_meta; print(get_dataset_meta('SOM103D')['matrix_code'])"

# 2. Run the existing UI route and confirm parity (no behaviour change)
uvicorn app.main:app --port 8080 &
curl -s 'localhost:8080/api/datasets?q=somaj&limit=5' | jq '.[] | .matrix_code'
curl -s 'localhost:8080/api/datasets/SOM103D' | jq '.matrix_code, .dimensions | length'

# 3. Smoke-test the MCP server (manual JSON-RPC handshake)
python tools/tempo-dev-mcp/server.py &
# In Claude Code: restart, confirm tempo-dev tools appear in the tool list
```

After this step, in any future Claude Code session I can call `tempo_dataset_info("ACC101B")` and get everything I need in one shot, instead of grepping.

---

## Step 2: v1 user-facing NL→Data agent (~2.5h)

The existing v1 design from this plan, now built **on top of** Step 1's service layer. Time drops from ~3h to ~2.5h because the MCP tools accelerate verification.

### Step 2 — What you'll be able to ask

The agent has 4 tools (search → schema → query → categories) over ~3,632 datasets covering demographics, economy, labor, health, education, and geography back to ~1990. Question categories it handles well:

### 1. Single-fact lookup
- *"Care era populația României în 2023?"*
- *"How many hospitals are there in Cluj county?"*
- *"What was the inflation rate in December 2024?"*

### 2. Filter + aggregate within one dataset (the sweet spot)
- *"Show me unemployment by county in 2023"* → group_by REF_AREA
- *"Populația pe grupe de vârstă și sex în 2024"* → group_by AGE, SEX
- *"Average wage by economic activity over the last 5 years"*
- *"Births per county in 2023, sorted descending"*

### 3. Time series for one indicator
- *"Evoluția PIB-ului între 2010 și 2024"*
- *"Unemployment rate trend in Iași over the last decade"*
- *"Show me the CPI monthly series for 2024"*

### 4. Compare across one dimension
- *"Compare urban vs rural population in 2023"* → RESIDENCE filter
- *"Male vs female employment by age group"*
- *"Bucharest vs Cluj population growth since 2010"* (two queries on the same dataset)

### 5. Dataset discovery (no data, just navigation)
- *"What datasets do you have about education?"*
- *"Ce date aveți despre migrație?"*
- *"Find datasets with monthly data on prices"*

### 6. Multi-step / disambiguation
- *"I want population data by county"* → agent finds the dataset, sees it's split, picks the `_judete` sub-dataset, fetches schema, returns shape
- *"Show me the labor force, but for women only and only people 25–54"*

### What v1 will NOT do well

| Limitation | Why | When it lands |
|---|---|---|
| **Cross-dataset JOIN** ("GDP per capita by county" combining GDP + population) | Different parquets, no JOIN tool | v2 — `compute_ratio` tool or two-query orchestration |
| **Derived metrics** ("year-over-year growth rate") unless the dataset has them | Agent only filters/groups, doesn't compute | v2 — already sit in [dataset_trends](data/corpus/metadata.duckdb) table; expose via tool |
| **Forecasts / predictions** | Not a statistical inference engine | Out of scope |
| **"Why" questions** | Causation isn't in the data | Out of scope |
| **Geospatial math** (density per km², distance) | No geo computation tools | v2 maybe |
| **Up-to-the-minute data** | INS publishes monthly at most | Inherent |
| **Free chart customisation** ("stacked bar with log scale") | `chart_selector` is rule-based, not LLM-driven | v2 — let agent override defaults |

### Smoke-test questions (exercise the full pipeline)

1. *"Care este populația Clujului în 2023?"* — single fact, geo filter
2. *"Show me unemployment trends by county in the last 5 years"* — bilingual query, group_by, time filter, split dataset
3. *"Câte spitale sunt în România pe județe?"* — split dataset disambiguation
4. *"Compară numărul de nașteri în mediu urban și rural în 2024"* — RESIDENCE compare
5. *"Ce date aveți despre comerțul exterior?"* — pure discovery, no data query

### Step 2 — Files to create

(All files below are new in Step 2. The service-layer extractions `dataset_search.py` + `dataset_meta.py` already exist from Step 1.)

#### `app/services/llm_client.py` — provider abstraction (~120 lines)

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

#### `app/services/agent.py` — agent loop + tool registry + system prompt (~250 lines)

```python
def run_agent(question: str, history: list[Message] = []) -> AgentResult:
    # AgentResult = {answer, citations: [matrix_code], tool_trace, chart_spec, data, warnings}
```

- System prompt as a constant string (see "System prompt" section below).
- Tool registry: dict of `name → callable` mapping tool name to a Python function that takes `input: dict` and returns a JSON-serialisable result.
- Loop: call `complete_with_tools`, dispatch any `tool_calls`, append results, repeat until `stop_reason == "end_turn"` OR iteration cap (default 8) hit.
- After the loop, if any tool call returned data, attach `chart_spec` from `chart_selector.select_charts()` based on the last queried matrix.
- Returns the full `tool_trace` so curl debugging is easy.

#### `app/services/dataset_search.py` and `app/services/dataset_meta.py`

These already exist after Step 1. The Step 2 agent imports them directly:

```python
from app.services.dataset_search import search_datasets   # used by `search_datasets` tool
from app.services.dataset_meta   import get_dataset_meta  # used by `get_dataset_schema` tool
```

No new files. The agent's tool handlers are 5-line wrappers around these calls, formatting the result for LLM consumption (compact JSON, capped to 25 cards / 100 dim values).

#### `app/routers/ask.py` — single endpoint

```python
@router.post("/api/ask")
def ask(req: AskRequest) -> AskResponse:
    if not config.ASK_ENABLED: raise HTTPException(404)
    return run_agent(req.question, req.history or [])
```

Mounted in [app/main.py](app/main.py) only when `ASK_ENABLED=true`.

#### `scripts/build-search-index.py` — sidecar FTS index builder

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
- Add a graceful fallback in `dataset_search.py`: if `search.duckdb` is missing, fall back to `LIKE` queries against `metadata.duckdb` so the agent still works without the index. Step 1 already wires this fallback (the MCP shipped before the FTS index existed); Step 2 just builds the index for real performance.

#### `app/config.py` — add four flags

```python
ASK_ENABLED        = os.environ.get("TEMPO_ASK_ENABLED", "false").lower() in ("1","true","yes")
LLM_PROVIDER       = os.environ.get("TEMPO_LLM_PROVIDER", "anthropic")  # anthropic | openai
LLM_MODEL          = os.environ.get("TEMPO_LLM_MODEL", "claude-sonnet-4-5")
ASK_MAX_TOOL_CALLS = int(os.environ.get("TEMPO_ASK_MAX_TOOL_CALLS", "8"))
SEARCH_DB_PATH     = DATA_ROOT / "corpus" / "search.duckdb"
```

API keys come from `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` env vars (standard SDK behaviour, no app changes needed).

---

### Step 2 — Agent tool definitions (JSON Schema)

These are different from the Step 1 MCP tools — these are atomic, predictable tools for an LLM tool loop, not rich combined responses for a developer. Four tools cover everything:

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

### Step 2 — System prompt outline

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

### Step 2 — Functions to reuse (no changes)

- [app/db.py](app/db.py) `get_conn()` — cursor-per-request, mandatory pattern.
- [app/services/query_builder.py](app/services/query_builder.py) `build_data_query()` — call as-is from the `query_dataset_data` tool. Already handles escaping, group_by, legacy column resolution.
- [app/services/chart_selector.py](app/services/chart_selector.py) `build_signature()` + `select_charts()` — call after the agent picks data, attach `chart_spec` to the response. **Do not let the LLM choose chart types.**
- [app/routers/dataset_data.py](app/routers/dataset_data.py) — copy the filter-parsing + large-dataset guard pattern into the `query_dataset_data` tool.
- `app/services/dataset_search.py` and `app/services/dataset_meta.py` — both created in Step 1, imported directly by the agent tool handlers.

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

## What is explicitly NOT in Step 2

- UI / chat panel — deferred. API only.
- Precomputed embeddings / vector search — FTS is enough. Embedding upgrade lands in Step 4.
- Streaming responses (SSE) — Step 4.
- Conversational memory beyond `history` parameter — Step 4.
- LLM response caching — Step 4 (after eval harness exists).
- Eval harness with hand-written test set — Step 3 deliverable.
- Multi-dataset comparison charts — Step 4.
- LangChain / LlamaIndex — never. The loop is 80 lines.

---

## Step 3: Expand the dev MCP (~3–4h)

After Step 2 ships you'll know which dev tools you actually want, because v1's failures will surface the real friction. The candidate set below is what I'd build *unless* Step 2 surfaces something more urgent.

### Step 3 — Additional MCP tools

**Pipeline state introspection**
- `tempo_pipeline_status()` — for each numbered pipeline stage, count of datasets present/missing/stale. Replaces ad-hoc DuckDB queries.
- `tempo_dataset_lineage(matrix_code)` — raw CSV → compacted → parquet → view profile, with timestamps. Spot stale outputs.
- `tempo_outdated()` — datasets where source CSV is newer than parquet (one query, many uses).

**Code introspection**
- `tempo_routes()` — all FastAPI routes via `app.openapi()` introspection. Returns path, method, params, response model.
- `tempo_call_endpoint(path, params)` — invoke a route in-process via FastAPI's `TestClient` without spinning up uvicorn. Faster than curl, no port collisions.
- `tempo_grep_python(pattern, path_glob)` — wraps ripgrep but scoped to Python files in `app/` and pipeline scripts. Cheaper than launching the Grep tool when I just need a quick lookup.

**Eval / regression**
- `tempo_eval_chart_selector(subset='all'|'archetype:geo_time'|matrix_code_list)` — runs `select_charts` across N datasets, diffs against a baseline file at `data/eval/chart_selector_baseline.json`, returns the rows that changed. **Critical for tuning chart_selector confidently.**
- `tempo_eval_agent(question_file)` — runs the v1 agent against a YAML of reference questions (`data/eval/agent_questions.yaml`), reports per-question pass/fail with the expected vs actual `matrix_code` and tool_trace summary. Hand-write 30–50 questions covering the categories in Step 2's "what you'll be able to ask" section.
- `tempo_check_view_profiles()` — validate every view profile JSON against the actual parquet schema. Returns mismatches. (Would have caught real bugs already.)

**Frontend probing (Playwright is already installed per CLAUDE.md)**
- `tempo_render_dataset(matrix_code, viewport='1280x800')` — Playwright opens the dataset page, takes a screenshot, returns the path. I can read the screenshot directly.
- `tempo_console_errors(path)` — Playwright opens, captures `console.error` + uncaught exceptions, returns them.
- `tempo_validate_echarts_spec(spec)` — schema-check an ECharts JSON spec before it ships. Catches typos in `series.type` etc.

**Safe mutations** (gated behind a `TEMPO_DEV_MUTATIONS=true` env var)
- `tempo_run_pipeline_script(name, args, dry_run=True)` — wraps the numbered scripts with stdout/stderr capture, default dry-run.
- `tempo_regen_view_profile(matrix_code)` — single dataset, fast iteration when tuning.
- `tempo_clear_search_index()` — drop and rebuild `data/corpus/search.duckdb`.

### Step 3 — Files

```
tools/tempo-dev-mcp/
  server.py               # MODIFIED — add ~10 new tools
  pipeline_state.py       # NEW — pipeline introspection logic
  eval.py                 # NEW — chart_selector and agent eval runners
  playwright_tools.py     # NEW — screenshot, console-error capture
  mutations.py            # NEW — gated wrappers for write operations

data/eval/
  chart_selector_baseline.json   # NEW — captured snapshot for diffing
  agent_questions.yaml           # NEW — hand-written reference set (~30–50 questions)
```

### Step 3 — Verification

```bash
# Eval baselines exist and pass on a clean checkout
python -c "from tools.tempo_dev_mcp.eval import run_chart_selector_eval; print(run_chart_selector_eval('all'))"
# Should report: 0 regressions vs baseline

# Pipeline state matches reality
python -c "from tools.tempo_dev_mcp.pipeline_state import status; print(status())"
# Should match what `ls data/corpus/parquet/ | wc -l` shows

# Playwright snapshots work
python -c "from tools.tempo_dev_mcp.playwright_tools import render_dataset; print(render_dataset('SOM103D'))"
# Should return a screenshot path I can read
```

After Step 3, every Claude Code session on this repo loads the full toolset. v2 features (Step 4) are built with `tempo_eval_chart_selector` running after each tweak, `tempo_render_dataset` after each frontend change, `tempo_eval_agent` after each prompt change.

---

## "Tomorrow" checklist (in order)

### Day 1 — Step 1: Minimal MCP (~2h)

1. **(15 min)** Re-read [app/routers/datasets.py:28-142](app/routers/datasets.py#L28-L142), [app/services/query_builder.py](app/services/query_builder.py), [app/services/chart_selector.py](app/services/chart_selector.py) `build_signature` + `select_charts`.
2. **(30 min)** Refactor: extract `search_datasets()` and `get_dataset_meta()` from [app/routers/datasets.py](app/routers/datasets.py) into [app/services/dataset_search.py](app/services/dataset_search.py) and [app/services/dataset_meta.py](app/services/dataset_meta.py). Keep route behaviour identical. Verify with curl on `/api/datasets?q=somaj` and `/api/datasets/SOM103D`. Commit.
3. **(45 min)** Write `tools/tempo-dev-mcp/server.py` with the 4 introspection tools (`tempo_dataset_info`, `tempo_search_datasets`, `tempo_chart_signature`, `tempo_sample`). Use the official `mcp` Python SDK.
4. **(15 min)** Add `.mcp.json` at repo root pointing at the server. Restart Claude Code, verify the `tempo_dev` tools appear in the tool list. Test each one against `ACC101B` and `SOM103D`.
5. **(15 min)** Update [CLAUDE.md](CLAUDE.md) with the new MCP server (one paragraph + how to register). Add an entry to [docs/activity-history.md](docs/activity-history.md). Commit.

### Day 1 cont. or Day 2 — Step 2: v1 user-facing agent (~2.5h)

6. **(20 min)** `pip install anthropic openai`. Write [app/services/llm_client.py](app/services/llm_client.py) with both backends. Test each from a Python REPL with a no-op tool. (Use `tempo_dataset_info` to spot-check the data shapes you're about to feed the agent.)
7. **(45 min)** Write [app/services/agent.py](app/services/agent.py): tool registry, system prompt constant, `run_agent()` loop, `AgentResult` dataclass.
8. **(20 min)** Write [app/routers/ask.py](app/routers/ask.py): one POST endpoint, feature-flag gate. Mount in [app/main.py](app/main.py).
9. **(20 min)** Write [scripts/build-search-index.py](scripts/build-search-index.py). Run it. Verify with a direct DuckDB query that the FTS index produces sensible results.
10. **(30 min)** Run the smoke-test questions. Inspect `tool_trace`, fix obvious prompt issues, repeat. Use `tempo_chart_signature` to verify chart selection on the datasets the agent picked.
11. **(15 min)** Update [CLAUDE.md](CLAUDE.md) with the new endpoint + script. Add Step 3/4 items to [docs/BACKLOG.md](docs/BACKLOG.md). Add an entry to [docs/activity-history.md](docs/activity-history.md). Commit.

Total: ~4.5 hours of focused work for a working Step 1 + Step 2. Step 3 is a separate session once you've used Step 2 enough to know what you actually want.

---

## Critical files (cheat-sheet)

| Path | Role in this plan | Step |
|---|---|---|
| [app/routers/datasets.py](app/routers/datasets.py) | Refactored: `list_datasets` → service, `get_dataset` → service | 1 |
| `app/services/dataset_search.py` | NEW — extracted, reused by MCP, agent, existing route | 1 |
| `app/services/dataset_meta.py` | NEW — extracted, reused by MCP, agent, existing route | 1 |
| `tools/tempo-dev-mcp/server.py` | NEW — MCP server for Claude Code | 1, expanded in 3 |
| `.mcp.json` | NEW — repo-local MCP registration | 1 |
| [app/services/query_builder.py](app/services/query_builder.py) | Reused as-is by `query_dataset_data` | 2 |
| [app/services/chart_selector.py](app/services/chart_selector.py) | `select_charts()` attached to agent response | 2 |
| [app/routers/dataset_data.py](app/routers/dataset_data.py) | Filter-handling pattern copied into the data tool | 2 |
| [app/db.py](app/db.py) | Cursor-per-request — mandatory, do not break | 1, 2 |
| [app/config.py](app/config.py) | New flags: `ASK_ENABLED`, `LLM_PROVIDER`, `LLM_MODEL`, `SEARCH_DB_PATH` | 2 |
| `app/services/llm_client.py` | NEW — provider abstraction (Anthropic + OpenAI) | 2 |
| `app/services/agent.py` | NEW — tool-calling loop + system prompt | 2 |
| `app/routers/ask.py` | NEW — `POST /api/ask` behind feature flag | 2 |
| [app/main.py](app/main.py) | Mount `ask` router behind feature flag | 2 |
| `scripts/build-search-index.py` | NEW — sidecar FTS index builder | 2 |
| [data/corpus/metadata.duckdb](data/corpus/metadata.duckdb) | Read-only source for FTS sidecar build | 2 |
| `data/corpus/search.duckdb` | NEW sidecar — FTS index over matrices + tags | 2 |
| `data/eval/chart_selector_baseline.json` | NEW — regression baseline | 3 |
| `data/eval/agent_questions.yaml` | NEW — hand-written reference set | 3 |
| [CLAUDE.md](CLAUDE.md) | Document MCP server + agent endpoint | 1, 2 |
| [docs/BACKLOG.md](docs/BACKLOG.md) | Step 3/4 items as `- [ ]` entries | 2 |

---

## Step 4: v2+ vision — what a more advanced LLM integration could achieve

Once Steps 1–3 ship, the architecture (tool-calling agent + dev MCP + safe data layer) opens up much more ambitious capabilities. Every item below benefits from the dev MCP loaded in every session — `tempo_eval_chart_selector`, `tempo_render_dataset`, `tempo_eval_agent` make iterating on these features dramatically faster than building Steps 1–2 was. Grouped by horizon and grounded in what the existing data + DuckDB tables actually support.

### Tier 1 — Natural extensions (next steps after v1)

**Cross-dataset reasoning.** Add a `query_two_datasets` or `compute_ratio` tool that fetches two parquets, joins them in pandas on shared SDMX dims (TIME_PERIOD, REF_AREA, SEX, …) and returns derived rows. Unlocks:
- *"GDP per capita by county"* (GDP ÷ population)
- *"Doctors per 1,000 inhabitants by county"*
- *"Healthcare spending vs life expectancy"* — correlation across two datasets
- *"Education spending as a share of GDP over time"*

**Derived metrics tool.** Expose [dataset_trends](data/corpus/metadata.duckdb) (3,632 rows of trend_direction, slope, yoy_growth, breakpoint_years, seasonality) as a `get_trend_summary(matrix_code)` tool. The agent then answers:
- *"Is unemployment growing or shrinking in Romania?"*
- *"When did inflation break trend in the last decade?"*
- *"Which counties are outliers in birth rates?"* (already in `geo_outlier_counties`)

**Multi-turn drill-down with session memory.** A simple in-process session store keyed by session_id, holding (question, answer, citations, last_matrix_code). Lets the user say:
- *"Show me population by county"* → *"Now break Cluj down by age group"* → *"Compare to Iași"* → *"Plot it as a line chart"*
- The agent maintains pinned context (current dataset, current filters) and drills deeper.

**Embedding-based retrieval upgrade.** Replace FTS with hybrid lexical + vector. Embed a "dataset card" (name + tags + dim names + context path + definition) using `BAAI/bge-m3` or `multilingual-e5-large`. Stored as a sidecar parquet. Reciprocal-rank-fusion against FTS. Unlocks:
- *"Quality of life indicators"* → finds wellness, health, income, education datasets
- *"Datasets relevant to climate policy"* → semantic match across categories
- *"Locuri de muncă"* → matches `ocupare a forței de muncă` even though the literal phrase isn't in the tags

**Eval harness.** Hand-write 50 reference questions with expected `matrix_code` + dimension filters + a sketch of the right answer. Run nightly. Track precision/recall as a CI signal. Without this, every prompt change is a leap of faith.

**Streaming + UI panel.** SSE from the agent loop to a chat panel in [app/static/index.html](app/static/index.html). Inline charts via the existing [chart-factory.js](app/static/js/chart-factory.js). Pin charts to conversation history.

### Tier 2 — New capabilities (medium-term)

**Statistical narrative generation.** *"Tell me the story of Romanian unemployment from 2010 to 2024."* The agent calls `query_dataset_data` for the series, calls `get_trend_summary` for breakpoints, optionally calls a new `get_news_around(date)` tool against the existing [get-news.py](get-news.py) press-release scraper, then writes a narrative paragraph with citations. Effectively automated explanatory journalism over INS data.

**Methodology Q&A (RAG).** [matrices.definitie](data/corpus/metadata.duckdb) and [matrices.metodologie](data/corpus/metadata.duckdb) already hold INS's own definitions. Embed them. Add a `lookup_methodology(matrix_code | concept)` tool. Answers:
- *"How does INS measure inflation?"*
- *"What's the difference between LFS unemployment and registered unemployment?"*
- *"Which population concept does this dataset use — resident or de facto?"*

**Anomaly detection across the corpus.** *"What's unusual about the latest data release?"* Cross-reference [dataset_trends.breakpoint_years](data/corpus/metadata.duckdb) (already detected!) and `geo_outlier_counties` for the most recent year. Surface as a daily/weekly briefing. Could run as a background cron.

**Custom user-defined indicators.** User defines a derived dataset: `my_unemployment_index = unemployment_25-54 - vacancies`. Stored as a yaml file or a small `user_indicators` table. The agent can query custom indicators just like canonical ones via a wrapping tool. Lets power users curate their own dashboards.

**LLM-driven chart customisation.** Beyond [chart_selector.py](app/services/chart_selector.py)'s rule-based picks: let the user say *"make it a stacked area with log scale, group by region"*. Agent emits an ECharts JSON delta that overrides the default spec. Validated against an ECharts schema before rendering.

**Auto-generated periodic reports.** *"Quarterly economic summary for Q1 2025."* Multi-dataset, multi-chart, narrative output as Markdown / PDF / HTML. Templates per topic (labor, inflation, demographics) + generated commentary. Could power a public newsletter.

### Tier 3 — Ambitious / research-grade

**Cross-source augmentation.** Extend tools beyond INS: Eurostat, World Bank, OECD, BNR (national bank). *"How does Romanian unemployment compare to the EU average?"* Each source becomes a new tool. The agent picks the right one or calls multiple. Requires building (small) connectors but the tool-calling architecture handles it cleanly.

**Correlation discovery across all datasets.** *"What datasets correlate with unemployment trends in Cluj?"* Pre-compute pairwise Pearson correlations on common time-and-geo indices, store as `dataset_correlations` table similar to existing `dataset_relationships`. Agent surfaces top hypotheses with the caveat that correlation ≠ causation. Becomes a legitimate research tool.

**Semantic data model layer.** A "concept" maps to multiple matrix_codes depending on year/granularity/methodology. *"Show me population"* might resolve differently for 1990 vs 2024. A `resolve_concept(name) → [matrix_code]` tool with curated mappings. This is the analytics-engineering "metric layer" applied to public statistics.

**Code generation for power users.** *"Give me a Python snippet to download this dataset and reproduce this chart."* The agent emits a runnable script (`pandas`/`duckdb`/`matplotlib`) that the user can paste into a notebook. Lowers the barrier between exploration and reproducible analysis.

**Multilingual report rendering.** Same data, generate the report in Romanian OR English on demand. The bilingual data layer already supports this.

**Voice / audio briefings.** TTS over the daily anomaly briefing. *"Listen to today's INS data update."* Niche, but the underlying pipeline is the same.

**Agentic data quality patrol.** Background agent that runs after each pipeline incremental update, compares new vs old `dataset_value_profiles`, flags anomalies (sudden mean shifts, fill-rate drops, outlier years), opens entries in [docs/BACKLOG.md](docs/BACKLOG.md) for the user to review. Self-monitoring data infrastructure.

**Embedded explorer / shareable answers.** Every agent answer becomes a URL with a deterministic ID (hash of question + tool_trace). Shareable, embeddable, citable. Turns the assistant from a chat tool into a knowledge graph node.

### Tier 4 — Speculative

**"Why" questions, partial answers.** True causation is out of reach, but the agent could surface *plausible explanations* by combining: trend breakpoints (`dataset_trends.breakpoint_years`) + correlated datasets + relevant news around the breakpoint date (from [get-news.py](get-news.py)). Honest framing: *"Unemployment rose 1.8 points in Q2 2020. Around the same period: COVID lockdowns began (news), labor force participation dropped (correlated dataset), and the breakpoint detector flagged this as a structural break."* It's pattern-matching, not causal inference, but it's useful.

**Federated multi-agency agent.** Same architecture pointed at multiple statistical agencies' open data. The tool-calling abstraction is provider-agnostic for both LLMs and data sources. Could become a generic "ask the official statistics" interface.

**Counterfactual exploration.** *"What would the unemployment rate look like if labor force participation had stayed at 2019 levels?"* Requires a small simulation layer on top of the data. Possible but well outside v1 scope.

### What this means for the v1 architecture

The good news: **none of these require throwing v1 away.** Every tier above adds new tools to the same agent loop, or new tables to the same DuckDB metadata layer, or new sidecars next to `search.duckdb`. The tool-calling architecture is the right substrate for all of them. That is the strongest argument against pure NL2SQL — it's a dead-end architecture, while tool-calling compounds.

The only architectural change later tiers might force is a **task graph** instead of a single agent loop (multi-step plans with explicit dependencies), but even that drops in cleanly where `run_agent()` lives today.
