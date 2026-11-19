# Review: insseption (csaladenes) — what we can learn and reuse

Date: 2026-11-19. Reviewed: <https://github.com/csaladenes/insseption> at `54d0adf`
(36 commits, 2026-10-23 → now, one author, MIT) and the live site <https://insse.csaladen.es>.
insseption lists this project as "gov2-ro/tempo-ins-dump — Full warehouse + UI at ins.gov2.ro"
(`api/insseption/main.py:58`, and in its docs).

## 1. What insseption is

| Part | What it does | Size |
|---|---|---|
| API (`api/insseption/`) | A live JSON proxy over TEMPO: `context`, `matrix`, `matrix/dataSet`, `news`. No local corpus. TTL caches, single-flight, circuit breaker, 4 concurrent upstream calls. | ~1.3k lines |
| Python client | `pip install insseption`, plus a CLI. Thin wrapper over the API. | 230 lines |
| Agent (`agent/`) | A separate container. One fixed pass per question: rewrite the follow-up → plan JSON → "preflight" revise → regex overrides → one query → HTML answer. It is not a tool-calling loop. OpenRouter, two cheap models. In-memory sessions (30 min). | ~1.7k lines |
| UI (`web/`) | Chat-first landing in RO/EN/HU, example pills, Chart.js, Mapbox GL county choropleth (5 quintiles), CSV and PNG export of each answer. | ~1.2k lines |
| Docs | Trilingual guide at `/docs/{lang}`: recipes in curl/Python/R/JS/Excel, "errors and caching", "cite the data". Swagger at `/docs/{lang}/reference`. | ~1.5k lines |
| Eval | 35 graded multi-turn cases (RO/EN/HU) with number bands, matrix prefixes, chart kind, row counts, refusals; an LLM judge for faithfulness; "UPST" grade for upstream outages. | 530 + 290 lines |

**There is no MCP server.** The "agent" is a chat endpoint, not an MCP.

### Live checks (2026-11-19)
- `/api/v1/health` → `upstream_ok: true`. A default query answered in 0.4 s.
- `GET /api/v1/matrices/POP105A/query?lang=en` returns the three TEMPO header rows as data rows,
  and the value as the string `"<u>19041322</u>"`. `row_count` is 4 for 1 observation.
- Agent, "Care este rata somajului pe judete in 2024?": 11.8 s, chose SOM103A (registered rate),
  42 counties, map. The same choice as our `discovery_defaults.json` (county → registered).

### The basic trade-off
insseption is always current and stores nothing. It has no profiling, no hierarchy detection, no
grain checks, no published-total checks and no history. It fails when TEMPO fails. Our snapshot
model has the opposite profile. The two projects complement each other; they do not compete on
the same axis.

## 2. Data fetching and transformation

### 2.1 Found in our corpus: lossy decoding of metadata (fix now)
insseption decodes TEMPO bodies as UTF-8 with a Windows-1250 fallback for stray bytes
(`upstream.py:_cp1250_fallback`). TEMPO mixes cp1250 bytes (for example 0xA0) into UTF-8 bodies.

Our `3-fetch-metas.py` writes `response.text` (requests' decode). I scanned our raw files:
- `data/4-datasets/*/*.csv` (6,631 files): 0 invalid UTF-8, 0 replacement characters.
- `data/2-metas/*/*.json` (3,821 files): **13 files contain U+FFFD** (ro: ASS113F, JUS109B,
  SAN102B; en: FOM102A, FOM114A, FOM115A, FOM116A, IND121A, SAN102B, SAN102C, THO0721, TRN112A,
  TRN113A).
- The damage reached the served DB. `dimension_options` and `sdmx_codes` hold
  `Din total: viol sav�rsit asupra unui minor` (JUS109B, nom 102715) and
  `… protectie �n Romania` (ASS113F, nom 100775) as `sdmx_value` and `display_label_ro`.
  The CSV has the correct `savârsit`. The other 11 files have the damage in definitions/notes
  text, not in option labels.

Fix: decode `response.content` with a UTF-8 + cp1250 fallback in `3-fetch-metas.py` (and in any
fetcher that stores text), reject a body that still has U+FFFD, re-fetch the 13 metas and
re-run stages 10/11/9 for ASS113F and JUS109B. Add a corpus-audit rule: no U+FFFD in labels.

### 2.2 Error envelope with HTTP 200 (verify, then fix)
TEMPO reports a failed query as HTTP 200 with one text cell: "results to your query could not be
returned" / "rezultatul solicitat nu poate fi returnat" (`upstream.py:is_error_envelope`).
insseption returns 502 and never caches such a body.

Our `6-fetch-csv.py` checks only the cell-limit text. If `/pivot` returns this envelope, the
body is saved as a CSV, `count_csv_rows` finds 0 rows, the chunk/judet retries run, and the
script can exit 3. `update-pipeline.py:219` records exit 3 as "empty, not retried". A transient
INS outage could then mark a matrix as permanently empty.

I did not prove that `/pivot` emits this envelope (insseption saw it on `/matrix/dataSet`).
No stored CSV contains the marker text, so it has not damaged the corpus. Fix: detect both
markers in every fetcher, raise a retryable error, and never write the body.

### 2.3 Data-path health probe (adopt)
insseption's `/health` runs a one-cell `dataSet` query (memoised 60 s), because TEMPO's metadata
endpoints can be up while data queries fail. `update-pipeline.py` should run the same probe
before a run. If the probe fails, the run stops before it touches state, so the watermark and
the retry set stay clean.

### 2.4 Live single-cell queries for drift checks (consider)
`POST /matrix/dataSet/{code}` with an explicit `arr` selection returns exact cells as JSON.
We already use `/pivot` for published totals (`fetch-ins-reference-cells.py`). A small weekly
"drift sentinel" could compare a few dozen served values (KPI tiles, recipe answers) with live
TEMPO. It would flag silent INS revisions between news-feed updates.

### 2.5 Do not adopt
- Default selection by label ("Total"-like first option, last option of a year dimension). It
  is the heuristic our `dimension_structure` work replaced.
- Header rows and `<u>…</u>` HTML passed through as data, values as strings.
- LLM translation of statistical labels (`/translate`). We use INS's own EN labels
  (`labels_i18n`). An unverified translation is a data-quality risk.

## 3. Agent and MCP

### 3.1 Their design versus ours
Their agent makes one query per question and corrects the model with regex rules: a RO/HU→EN
synonym table, a topic→matrix "knowledge bank", county-name expansion, and an employee-table
override. Our Ask and public MCP use eight validated tools, a grain guard, scope checks,
verified claims and a discovery policy. Do not copy their override chain; it does not scale
past a few dozen topics.

### 3.2 Ideas worth taking
1. **Use their eval set as an external benchmark.** Their 35 cases (MIT) are questions a
   different team chose, with number bands, expected matrix families, chart kinds and county
   row counts (42). Convert them to our `data/eval/ask_tasks.json` format and run them against
   our MCP tools. Disagreements show discovery gaps that our own tasks do not cover. Keep the
   attribution.
2. **Year-coverage gate.** Their knowledge bank skips a topic→matrix route when the matrix does
   not cover the asked years (POP105A starts 2003; POP107A starts 1992). Check that
   `discover_indicators` ranks by period coverage when the question names years.
3. **"Upstream" as a separate eval outcome.** Their grader marks an upstream outage as UPST,
   not FAIL. Our live probes (`mcp_probe.py`, release check) could separate "server busy /
   query budget" from "wrong answer" in the same way.
4. **Hungarian questions.** They accept and answer in HU. Our tools take `lang` ro|en. A HU
   question to Ask works only by model translation. If HU users matter, add HU synonyms to
   the search index and allow a HU answer language in Ask; the tool codes stay the same.
5. **Clickable follow-up suggestions** and **session-expiry notice** in the chat UI. Our Ask
   returns `context`; suggestions as buttons are a small UI change.
6. **Cheap model for follow-up rewriting.** They use a mid-tier model to rewrite short
   follow-ups ("and 1990–2000?") into a full question before planning. This may cut one of our
   counted model calls on follow-up turns. Measure it before adopting.

### 3.3 Not to adopt
In-memory sessions (lost on restart, one worker only), HTML built by the model, and a bare
`/agent/*` reverse proxy that forwards all request headers.

## 4. UI and developer surface

1. **Developer guide.** Their `/docs` is better than our FastAPI `/docs` + `llms.txt` for a
   human: task recipes in curl/Python/R/JS/Excel, an "errors and caching" page, and a
   "cite the data" block. We have more to show (SDMX 2.1, CSV/XLSX, evidence links, MCP). A
   static recipe page, built from the same examples that `release-check.py` already runs, would
   stay correct.
2. **A thin Python client.** `pip install insseption` lowers the entry cost. For us, the MCP
   already serves agents; a small REST client (search, describe, data → pandas) would serve
   notebooks. It belongs to the consumption repo (see section 5).
3. **Chat-first entry.** Their landing page is one question box with three random examples. Our
   home is catalogue-first, and hosted Ask is off by default. An "ask" box on the home that
   routes to search when Ask is off is one option. Decide on cost first.
4. **Export of each answer** as CSV and PNG. Check that our Ask answers offer the same.
5. **Maps.** They use Mapbox GL with a token. Keep our ECharts + local GeoJSON: no vendor token,
   works in the static build. Their 5-quintile legend placed above the map is a good reading
   pattern.
6. **Attribution wording.** They write "Data from the National Institute of Statistics" and
   "Unofficial service; not endorsed by INS" on every page, and send `X-Source` on every
   response. Check that our pages and API responses state the same.

## 5. Impact on the repo split (ingestion / consumption)

insseption is, in effect, a consumption surface with a live TEMPO client inside it. That shows
where our boundary should be.

1. **Extract a `tempo-client` library into the ingestion repo.** It holds the TEMPO HTTP layer
   that today lives in scripts 1, 2, 3, 6, `get-news.py` and `fetch-ins-reference-cells.py`:
   endpoints, headers, decoding (2.1), envelope detection (2.2), the 30,000-cell limit, judet
   split and chunking, retries, the health probe (2.3). Today each script repeats its own copy
   of headers and URLs. This library is also a natural thing to share with insseption; the
   owner decides whether to contact its author.
2. **The contract between the repos is the generation**, not Python modules: the
   `generation-manifest.json` schema, the parquet layout, the `metadata.duckdb` tables the app
   reads, `search.duckdb` and `view-profiles/`. Write that contract down and version it before
   the split.
3. **Known coupling:** `app/` imports one root module, `sdmx_labels` (shared label matching for
   stages 9/11). Before the split, either move it into the shared contract package or vendor it
   into the app with a parity test.
4. **Version visibility.** Their README warns that an rsynced API fix without a rebuild "runs
   the old code with no error". Our `/api/health` reports the generation; also report the code
   commit, so that two independently released repos stay traceable.

## 6. Recommended order

| # | Item | Effort | Section |
|---|---|---|---|
| 1 | Fix metadata decoding; re-fetch 13 metas; repair ASS113F and JUS109B; add a U+FFFD audit rule | S | 2.1 |
| 2 | Detect the TEMPO error envelope in all fetchers (after one probe confirms the `/pivot` form) | S | 2.2 |
| 3 | Data-path probe before `update-pipeline.py` runs | S | 2.3 |
| 4 | Port their 35 eval cases into an external benchmark for our tools | M | 3.2.1 |
| 5 | Developer recipe page + citation block | M | 4.1 |
| 6 | `tempo-client` library as the first step of the ingestion split | M | 5.1 |
| 7 | Generation contract document | M | 5.2 |
| 8 | HU support, follow-up buttons, drift sentinel, Python client | later | 2.4, 3.2, 4.2 |
