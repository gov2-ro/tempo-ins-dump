# Initial model evaluation of the tools over MCP (2026-10-16)

**Status: exploratory, not AT-04 acceptance.** It exists to find out whether the weak Ask
results came from the tools or from the model/provider loop, before any live-provider budget is
spent. Nothing deployed; no corpus table changed (copied generation `9b3e065d`, read-only).

## Method

- Public MCP (AT-03) on a local port, with the gate relaxed so it matches what Ask has in
  process: concurrency 4, 60 s deadline, 100 M scan rows. (With the production defaults, one
  slot and no queue, parallel callers would have got `busy`.)
- `scripts/mcp_eval_client.py` is the only way the models reached data: `list`, `call`,
  `final`. It traces every call and enforces Ask's 12-tool-call budget per question.
- Models: Claude Haiku and Sonnet, each at `low` and `high` effort, as Claude Code
  sub-agents. Each was given Ask's real `SYSTEM_PROMPT` (`from app.services.agent import
  SYSTEM_PROMPT`) and told to treat each question as a fresh conversation. Eight agents, four
  questions each; 67 tool calls were traced.
- **Limits of the method.** Native function calling is replaced by a CLI, so this measures the
  tool surface and the prompt, not the Ask loop, the provider SDKs or DeepSeek/OpenAI-style
  models. The four questions of one agent ran in sequence, so later ones benefited from what
  the agent had learned about the tools. The orchestrating model (which wrote the code) did not
  take part, because it is not a fair test subject. Sub-agent reports of their own behaviour are
  self-reports; the numbers below come from the traces.

## Questions and ground truth

| # | Question | Ground truth (direct read of the Parquet) |
|---|---|---|
| 1 | populația curentă a celor mai populate 30 de orașe | domicile population 2025, summed over the 18 five-year bands, localities `MUNICIPIUL …`/`ORAS …`: București 2,124,150; Iași 379,371; Cluj-Napoca 325,408; Timișoara 296,936; Constanța 295,767 … 30th Tulcea 78,862 |
| 2 | … cu populație și densitate de populație | needs the same plus an area per locality (`AGR101B_localitate` is a land-use table) |
| 3 | Ce județe au pierdut cel mai mult din populație între 2012 și 2021? | `POP105A`, 5-year bands: Prahova −58,119, București −58,085, Teleorman −53,623, Olt −47,904, Buzău −45,281 (percent: Teleorman −14.18%, Brăila −12.16%, Olt −11.04%) |
| 4 | Câte înnoptări … revin la un locuitor în Brașov, în 2025? | recipe `tourism_intensity` |
| 5 | Cum a evoluat rata șomajului în România în ultimii ani? | two official definitions (registered `SOM103A`, ILO `AMG157A`) |
| 6 | How many live births … each year since 2015? | no published national total in the corpus |
| 7 | Compară salariul mediu net din București cu cel din Cluj. | recipe `net_earnings_county` |
| 8 | Cine va câștiga alegerile prezidențiale? | out of scope: decline |

## Results

`✓` = figures from tool results, matching the ground truth where there is one; `ask` = stopped at
a clarification, no figures; `no` = declined as not answerable with the tools.

| Q | Haiku low | Haiku high | Sonnet low | Sonnet high |
|---|---|---|---|---|
| 1 top-30 cities | ask (1 call) | ask (2) | no (5) | ask (3) |
| 2 + density | ask (1) | ask (3) | no (2) | no (2) |
| 3 county change | ask (1) | ask (1) | **✓** (3) | ask (3, ran `compare_periods`, withheld the result) |
| 4 stays per resident | ✓ 4.91 (2) | ✓ 4.91 (3) | ✓ 4.91 (2) | ✓ 4.91 (3) |
| 5 unemployment | ask (1) | ask (1) | ask (1) | ask (1) |
| 6 births | figures, `POP201E` (3) | figures, `POP201E` (4) | figures, `POP201A_macroregiuni` (4) | figures, `POP201D` (5) |
| 7 two wages | ✓ 6,730 vs 5,921 (2) | ✓ (2) | ✓ (2) | ✓ (2) |
| 8 election | declined (0) | declined (0) | declined (1) | declined (1) |

- **The tool layer was healthy.** Slowest call 188 ms; 67 calls: 48 `ok`, 18 `needs_clarification`,
  one refusal (`conflicting_grain`, which the model recovered from by following `recovery`); no
  schema errors, no `busy`. One to five tool calls per question. The screenshots show 8 and 11
  calls, a plain sign of a weaker model flailing, ending in a provider failure.
- **No model invented a figure.** Q1 and Q2 were declined by all, Q8 by all. One agent computed
  a difference between two wages, then removed it on its own because the prompt forbids
  arithmetic.
- **Effort did not buy accuracy; it bought literalness.** Haiku low and high gave identical
  answers; high used about 1.5× the calls (16 vs 11 over eight questions; Sonnet 20 vs 20). Sonnet high obeyed "do not guess a definition"
  (rule 1) and stopped on Q3, where Sonnet low picked the resident definition, ran
  `compare_periods` and gave the right ranking.
- **Q6 is the one to worry about.** The two series disagree, both with `status: ok`,
  `valid_total`, `scope.domain_complete: null`: 2023 is 164,004 (`POP201E`/`POP201A_macroregiuni`)
  vs 168,079 (`POP201D`); 2024 is 148,916 vs 157,270. Every agent mentioned that completeness
  was unverified, but each still stated a number as the answer. This is the FIX-02 class (a sum
  with no agreement with a published total).

## Findings, in the order they cost answers

1. **The clarification gate decides most outcomes.** Every question containing "populația" or
   "rata șomajului" (Q1, Q2, Q3, Q5) returns `needs_clarification/ambiguous_definition`, even
   with "curentă" or a period. Nothing in the envelope says which definition is the default, and
   the system prompt contradicts itself (rule 1: ask, do not guess; rule 5: never ask, fetch and
   caveat). Result: Haiku always stops, Sonnet stops or breaks the rule. The three population
   concept cards all point at county datasets (`POP105A_judete_grupe`, `POP107A_judete_grupe`,
   `POP106A_judete_grupe`).
2. **A ranked level query does not exist.** `query_data` has no `order_by`, a hard cap of 200
   rows and a rule that the model must not rank raw rows; `compare_periods` ranks only change.
   "Top 30 cities" cannot be answered, whatever the model. The locality table
   (`POP107D_grupe_localitate`, 3,181 mixed communes, towns and municipalities, no type column)
   is reachable only via `describe_dataset` of the parent.
3. **`interpretation` misses the words:** `level` stays null for "orașe", `latest` stays false for
   "curentă".
4. **No density or area concept**; searches return green-space area and street length. `ok` with
   no density in it reads as a match.
5. **No two-entity comparison.** Q7 got both figures but could not state the gap without breaking
   the arithmetic rule.
6. **Choices are not actionable:** `choices[].next_call` re-runs `discover_indicators` with a
   reworded query, not a dataset or concept id; for registered unemployment `choice.recipe` is
   null while `concepts[0].recipe` is set. Some candidates have `next_call: null` with the reason
   only in notes.
7. **`run_recipe` areas need exact names** (`Municipiul Bucuresti`, `Brasov`) and nothing lists
   them; results do not say the level (a county, not the city). The 2021→2022 series break sits in
   `provenance.sources.notes`, not in `warnings`.
8. **Models over-promise:** one Haiku answer to Q2 offers to "calculate the top" if the user
   picks a definition, which no tool can do.

## What the user's screenshots add (not reproducible without the key)

- Both ended `outcome: partial, reason: provider`: the provider returned a retryable failure
  (timeout after 30 s, 429 or 5xx) after tools had run and again on the one retry. The page said
  "I could not finish within the request limits", which blamed the question. **Fixed in this
  branch:** the notice, the warning and the metrics now name the cause (`provider_timeout`,
  `provider_rate_limited`, `provider_unavailable`) and suggest trying again or choosing another
  model (`test_at02_loop.py::TestProviderOutcomes`). The server log line
  `Provider error after N tools: <code>` says which one it was; the uvicorn terminal has it.
- The table under the answer is the first 60 rows of an unordered, capped result for
  `POP107D_grupe_localitate` (communes included), under a question about the top 30 cities. The
  banner says it is not a ranking, but the table still reads as the answer. Candidate fix:
  caption a capped, unordered preview as "sample of the first N rows" and do not show it for
  ranking questions. Not done.

## Proposed changes (owner decisions; none made)

1. **Default instead of stop.** Give each ambiguous concept a reviewed default (resident
   population at 1 January; the headline unemployment definition to be chosen), return `ok` with
   `assumed` and `alternatives`, and keep `needs_clarification` for choices that change the
   answer (a period outside one definition's coverage, for example). Rewrite prompt rules 1/5
   to match. Touches AT-01 concept cards and the prompt.
2. **A ranking tool or mode** (`rank_entities`/`top_n`): one period, one level, ranked over all
   eligible entities by the tool, with an entity-class filter (cities = municipii + orașe) and a
   second measure joined by entity (population + area) so density is a tool figure. Plus a
   difference/ratio for two named entities. This is a contract change to `tempo-tools/1`
   (AT-00), so it needs its own spec.
3. **Area per locality** as a reviewed dataset or recipe (needs a decision on whether
   `AGR101B_localitate` totals equal administrative area).
4. **Totals without agreement** must not be `ok`: either `partial`/`unverified_total`, or the
   tool says which published total it was checked against (FIX-02).
5. Interpretation: map "curentă" → latest and "orașe" → level; make `choices[].next_call` a
   concrete call; lookup for recipe areas; series breaks into `warnings`.
6. Browser: caption/hide the capped unordered preview.

## Next evaluation steps

- Re-run this same set after (1) and (2); the client and the question list are reusable.
- AT-04 proper: real providers through the Ask loop (DeepSeek, OpenAI, Anthropic), native
  function calling, cost and the 512 MiB machine.

## How to repeat

```bash
TEMPO_DATA_DIR=<generation>/data TEMPO_MCP_ENABLED=true TEMPO_MCP_LOCAL_TEST=true \
 TEMPO_PUBLIC_BASE_URL=http://127.0.0.1:8097 TEMPO_MCP_MAX_CONCURRENT=4 TEMPO_MCP_MAX_SECONDS=60 \
 TEMPO_MCP_MAX_SCAN_ROWS=100000000 TEMPO_MCP_MAX_CALLS_PER_MINUTE=1200 \
 TEMPO_MCP_MAX_REQUESTS_PER_MINUTE=6000 uvicorn app.main:app --port 8097
python -c "from app.services.agent import SYSTEM_PROMPT; print(SYSTEM_PROMPT)" > system_prompt.md
python scripts/mcp_eval_client.py list
python scripts/mcp_eval_client.py --run haiku-low-q1 call discover_indicators '{"query": "…"}'
```
