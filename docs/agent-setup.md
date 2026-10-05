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
| `TEMPO_ASK_MAX_ITERATIONS` | `8` | Max model calls per request |
| `TEMPO_ASK_MAX_TOOL_CALLS` | `12` | Max tools dispatched per request, counting every tool in a multi-tool response. (Before FIX-08 this env var meant loop iterations.) |
| `TEMPO_ASK_MAX_SECONDS` | `90` | Wall-clock budget per request; checked before every model call and tool |
| `TEMPO_ASK_MAX_CONCURRENT` | `2` | In-process cap on simultaneous agent requests; extra requests get `503` + `Retry-After` |
| `TEMPO_ASK_RETRY_AFTER_SECONDS` | `10` | `Retry-After` value for the concurrency rejection |
| `TEMPO_ASK_PROVIDER_TIMEOUT` | `30` | Per provider call timeout (also clamped to the remaining request budget) |
| `TEMPO_ASK_PROVIDER_MAX_RETRIES` | `1` | SDK-level retries per provider call |
| `TEMPO_ASK_MAX_HISTORY_TURNS` / `_MAX_TURN_CHARS` / `_MAX_REQUEST_CHARS` | `20` / `8000` / `40000` | History bounds; violations return `400` (shape) or `413` (size) before any provider call |
| `TEMPO_ASK_ALLOWED_PROVIDERS` | all in `ask-models.json` | Comma list restricting BYOK providers |
| `TEMPO_ASK_ALLOWED_MODELS` | from `app/static/ask-models.json` | Comma list `provider:model` replacing the JSON allowlist for BYOK calls |
| `TEMPO_ASK_SERVER_MODELS` | `TEMPO_LLM_PROVIDER:TEMPO_LLM_MODEL` | `provider:model` pairs a server-funded (no user key) call may use |
| `TEMPO_ASK_LOG_CHATS` | `false` | Content logging, see below. Keep off unless you accept the retention terms |
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
- **Budgets per request**: 8 model calls, 12 tools, 90 s (all configurable, see section 2). When one is hit the response is a partial result (`stop_reason` = `iterations`/`tools`/`deadline`/`provider`, plus a warning), not an error.
- **Dimension labels are Romanian-only** — the agent is aware and searches bilingually, but raw values in `data.rows` will be Romanian strings.
- **No streaming** — the response is returned only when the full agent loop completes.
- **Not idempotent** — repeated identical questions may produce slightly different tool call paths (LLM non-determinism).
- **Write operations are impossible by design** — the agent has read-only service access.

---

## 9. Request limits, keys and logging (FIX-08)

**Validation.** `history` accepts only `{role: user|assistant, content}` turns where content is a
string or a list of `{type: text, text}` blocks. System/developer/tool roles, tool blocks and extra
fields are rejected with 400; size violations with 413. Nothing reaches a provider before validation,
allowlist and concurrency checks pass. Unknown providers/models are 400 (BYOK) or 403 (server-funded);
they never fall back to another provider.

**Errors.** Provider failures become stable messages: 401 (key rejected), 429/503 with `Retry-After`
(rate limit, timeout, outage), 502 otherwise. Provider text, headers and keys are never returned or logged.

**Keys.** The chat page keeps a BYOK key in memory and `sessionStorage` (this tab only). "Remember this
key on this device" is an explicit opt-in that writes it unencrypted to `localStorage`. Clear removes it
from both. A key stored in `localStorage` by an older version is not deleted silently: it is loaded,
shown as "saved on this device" with the box ticked, and removed by Clear. The key is never copied back
into the DOM. The key is sent to this server with every request (the server calls the provider for
you); it is not stored or logged by the app, but it does transit the server.

**Logging contract.**
- Always: one `ASK_METRICS {json}` line per request (status, provider/model, byok flag, iterations, tools,
  elapsed, question length). No question, answer, history, tool payload or credential.
- Only with `TEMPO_ASK_LOG_CHATS=true` (default off, also in `fly.toml`): a separate `CHAT_LOG {json}` line
  on stdout (`fly logs`) and `logs/ask-chats.jsonl` containing question, answer, tool trace and citations.
  The page shows a banner (from `GET /api/ask/config`) before any question is submitted. Retention is that of
  the log sink; the app does not rotate or purge it, and anyone with log access can read it.
- Credentials are redacted recursively (key names such as `api_key`/`authorization`, `sk-...`, `AIza...`,
  `Bearer ...`, and the request's own key) in chat logs, tool errors and agent/ask loggers.

**Not yet done (item 7).** Consuming FIX-02 aggregation outcomes in answers/citations is deferred until
FIX-02 merges; the hook point is marked in `app/services/agent.py` where `query_dataset_data` results are handled.
