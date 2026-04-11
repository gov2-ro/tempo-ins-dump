# NL→Data Agent — Setup & Usage

The `POST /api/ask` endpoint exposes a tool-calling LLM agent over the ~3,600 INS TEMPO
statistical datasets. The LLM never generates SQL — all data access goes through the safe
`query_builder.build_data_query()` service. The agent searches, picks, and queries datasets
on behalf of the user, then returns a plain-language answer plus structured data and a chart spec.

---

## 1. Prerequisites

### Python packages

```bash
# Anthropic (default provider)
pip install anthropic

# OpenAI (optional alternative)
pip install openai
```

### API key

Set the key for whichever provider you use:

```bash
# Anthropic (default)
export ANTHROPIC_API_KEY=sk-ant-...

# OpenAI (optional)
export OPENAI_API_KEY=sk-...
```

The SDK picks up the key from the environment — no code change needed.

---

## Recommended providers & models

The agent makes 4-8 sequential tool-call requests per question. Each request resends the accumulated message history, so the **cumulative tokens-per-minute** (TPM) is roughly `request_count × avg_request_size ≈ 18-25k TPM` per question in the current configuration.

| Provider / Model | Recommended? | Notes |
|---|---|---|
| **Anthropic Claude Sonnet 4.6** | ✅ Recommended | Best tool-use discipline. Follows "MUST" directives reliably. High TPM on all tiers. Default. |
| **Anthropic Claude Opus 4.6** | ✅ Overkill but works | Same discipline as Sonnet; slower, pricier. |
| **OpenAI gpt-4o** | ✅ Acceptable | Adequate tool-use. Tier-1 TPM (30k) is tight but workable with the trimmed prompts. |
| **OpenAI gpt-4-turbo** | ❌ Avoid on tier-1 | 30k TPM limit is hit on ~6-iteration runs. Weaker tool-use discipline than Claude (tends to skip mandatory steps and ask permission instead of fetching). Upgrade the OpenAI account tier or switch provider. |
| **OpenAI gpt-4o-mini** | ❌ Avoid | Higher TPM, but tool-use discipline is poor. Expect "would you like me to..." responses instead of fetching data. |

**Rule of thumb**: if you can't use Anthropic, use `gpt-4o`, not `gpt-4-turbo` or `gpt-4o-mini`.

## 2. Configuration

All settings are env vars. None are required except enabling the endpoint and providing an API key.

| Env var | Default | Description |
|---|---|---|
| `TEMPO_ASK_ENABLED` | `false` | **Must be `true`** to activate `POST /api/ask`. Returns 404 otherwise. |
| `TEMPO_LLM_PROVIDER` | `anthropic` | `anthropic` or `openai` |
| `TEMPO_LLM_MODEL` | `claude-sonnet-4-6` | Any model ID accepted by the provider |
| `TEMPO_ASK_MAX_TOOL_CALLS` | `8` | Max LLM→tool iterations per request |
| `TEMPO_DEBUG` | `false` | Set `true` for verbose agent iteration logs |

### Launch examples

**Anthropic (default)**
```bash
source ~/devbox/envs/240826/bin/activate
TEMPO_ASK_ENABLED=1 ANTHROPIC_API_KEY=sk-ant-... uvicorn app.main:app --reload --port 8080
```

**OpenAI**
```bash
source ~/devbox/envs/240826/bin/activate
TEMPO_ASK_ENABLED=1 TEMPO_LLM_PROVIDER=openai TEMPO_LLM_MODEL=gpt-4o OPENAI_API_KEY=sk-proj-... uvicorn app.main:app --reload --port 8080
```

> **Common mistakes:**
> - Setting `OPENAI_API_KEY` without `TEMPO_LLM_PROVIDER=openai` → the app still uses Anthropic and fails with "authentication" error.
> - Setting `TEMPO_LLM_PROVIDER=openai` without `TEMPO_LLM_MODEL` → sends `claude-sonnet-4-6` (the default) to OpenAI, which returns 404 "model not found".
> - All three vars (`TEMPO_LLM_PROVIDER`, `TEMPO_LLM_MODEL`, `OPENAI_API_KEY`) are required together when using OpenAI.

---

## 3. API Reference

### `POST /api/ask`

**Request body**

```json
{
  "question": "string (1–2000 chars, required)",
  "history":  [ { "role": "user"|"assistant", "content": "string" } ]
}
```

`history` is optional (defaults to `[]`). Pass prior turns for multi-turn conversations.

**Response**

```json
{
  "answer":     "string — plain-language response (Romanian or English)",
  "citations":  ["POP101A", "SOM101D_judete"],
  "tool_trace": [
    {
      "tool":   "search_datasets | get_dataset_schema | query_dataset_data | list_categories",
      "input":  { ... },
      "output": { ... }
    }
  ],
  "data": {
    "matrix_code": "SOM101D_judete",
    "columns":     ["REF_AREA", "TIME_PERIOD", "OBS_VALUE"],
    "rows":        [["Alba", "2023", 3.4], ["Arad", "2023", 2.1]],
    "row_count":   42,
    "truncated":   false,
    "warnings":    []
  },
  "chart_spec": { ... },
  "warnings":   []
}
```

- `data` — the last successful `query_dataset_data` result; `null` if no query was run.
- `chart_spec` — chart configuration for the last queried dataset from `chart_selector`; `null` if no query was run.
- `warnings` — agent-level warnings (double-counting alerts, tool call limit, etc.)
- `citations` — matrix codes extracted from the answer text and tool trace.

**Error responses**

| Status | Cause |
|---|---|
| `404` | `TEMPO_ASK_ENABLED` is `false` |
| `500` | Unhandled agent error (message in `detail`) |

---

## 4. Agent Tools

The LLM has access to four tools (internal — not user-callable directly):

| Tool | Purpose |
|---|---|
| `search_datasets` | Full-text search over ~3,600 datasets; returns ranked cards |
| `get_dataset_schema` | Fetches dimensions, value lists, time coverage for a `matrix_code` |
| `query_dataset_data` | Queries a dataset with optional filters + GROUP BY; returns up to 5,000 rows |
| `list_categories` | Returns the top-2 levels of the INS category tree |

The agent always calls `search_datasets` first (unless it already knows the code), then
`get_dataset_schema`, then `query_dataset_data`. It never guesses column names or values.

---

## 5. Usage Examples

### curl

```bash
BASE=http://localhost:8080

# English question
curl -s -X POST "$BASE/api/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the unemployment rate in Romania by county for 2023?"}' \
  | python -m json.tool

# Romanian question
curl -s -X POST "$BASE/api/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "Care este rata șomajului pe județe în 2023?"}' \
  | python -m json.tool

# Multi-turn: follow-up question
curl -s -X POST "$BASE/api/ask" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Which county had the highest rate?",
    "history": [
      {"role": "user",      "content": "What is the unemployment rate in Romania by county for 2023?"},
      {"role": "assistant", "content": "The unemployment rate for 2023 by county... (SOM101D_judete)"}
    ]
  }' | python -m json.tool
```

### Python

```python
import requests

BASE = "http://localhost:8080"

# Single question
resp = requests.post(f"{BASE}/api/ask", json={
    "question": "Show me GDP evolution in Romania since 2010"
})
r = resp.json()
print(r["answer"])
print("Citations:", r["citations"])
if r["data"]:
    print("Columns:", r["data"]["columns"])
    print("Rows:", r["data"]["rows"][:3])

# Check warnings (double-counting alerts etc.)
if r["warnings"]:
    print("Warnings:", r["warnings"])
```

### HTTPie

```bash
http POST localhost:8080/api/ask question="Population of Romania by age group in 2022"
```

---

## 6. Good Test Questions

### English
```
What was the population of Romania in 2023?
Show unemployment rate by county for the last 5 years.
What is Romania's GDP trend since 2000?
Birth rate vs death rate in Romania — annual comparison.
Which counties have the highest average wage?
Show industrial production index for 2020–2024.
What percentage of the population lives in urban areas?
Agricultural production by crop type in 2022.
```

### Romanian
```
Care este rata șomajului pe județe în 2023?
Evoluția populației României după 1990.
Câți copii s-au născut în România în 2022?
Care sunt județele cu cel mai mare salariu mediu net?
Producția agricolă pe culturi în 2022.
Evoluția PIB-ului României din 2000 până în prezent.
Numărul de elevi înscriși în învățământul preuniversitar.
```

### Edge cases worth testing
```
# Should trigger split-dataset handling
Unemployment by county (uses SOM101D which splits into _judete / _national)

# Should trigger double-counting auto-lock warning
Population by age group (POP datasets have Total rows alongside breakdowns)

# Should return 0 results gracefully
Something completely unrelated to Romanian statistics

# Broad category question (should call list_categories)
What topics does the INS data cover?
```

---

## 7. Inspecting the Tool Trace

The `tool_trace` array shows every step the agent took. Useful for debugging:

```python
resp = requests.post(f"{BASE}/api/ask", json={"question": "..."})
for step in resp.json()["tool_trace"]:
    print(f"[{step['tool']}]")
    print("  input:", step["input"])
    # step["output"] can be large — print selectively
    if "error" in step["output"]:
        print("  ERROR:", step["output"]["error"])
    elif step["tool"] == "search_datasets":
        print("  found:", step["output"].get("total"), "datasets")
    elif step["tool"] == "query_dataset_data":
        print("  rows:", step["output"].get("row_count"))
        print("  warnings:", step["output"].get("warnings"))
```

---

## 8. Limitations

- **Max 5,000 rows** per `query_dataset_data` call (returns `truncated: true` if hit).
- **Max 8 tool calls** per request (configurable via `TEMPO_ASK_MAX_TOOL_CALLS`).
- **Dimension labels are Romanian-only** — the agent is aware and searches bilingually, but raw values in `data.rows` will be Romanian strings.
- **No streaming** — the response is returned only when the full agent loop completes.
- **Not idempotent** — repeated identical questions may produce slightly different tool call paths (LLM non-determinism).
- **Write operations are impossible by design** — the agent has read-only service access.
