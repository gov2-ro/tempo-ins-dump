# Audit: automatic chart selection and the public MCP

**8 November 2026 · Local audit of branch `fix/ask-answer-quality` (a50994f), corpus generation `062bd2b0` · Read-only**

## 1. Decision summary

The numbers the tools return are right. The charts the pages choose are not always right.
Four independent auditors and one evidence collector worked on the local checkout. The owner
asked for an independent audit of two surfaces: the automatic choice of charts, and the public
MCP. No auditor changed the repository or the corpus.

- **Charts: four P0 classes.** A page can show a wrong total that passes every existing check:
  a Total stacked on its own parts, a mixed sex and urban/rural dimension stacked as one
  partition, an INS-contradicted sum served as `valid_total` in tiles and ranking sentences, and
  annual and quarterly values drawn on one time axis. The composer and the aggregation policy are
  sound in design. The gaps are in the renderers, in v1, and in rules the policy does not yet apply.
- **Public MCP transport: no P0.** Two P1 items: one global rate bucket lets one host lock out
  every client, and the content log has no size cap on a 1 GB volume. The rest are P2.
- **Tool answers: no wrong numbers.** Every sum matched a direct parquet read. Every recipe
  matched the INS published cell. Refusals are correct and explicit. The P1 items are about source
  choice, ties and clarifications.
- **Evals do not test the right thing.** The chart eval diffs the selector against its own
  2026-07-20 output and covers under half of the served datasets. The Ask task eval is pinned to a
  retired generation, so it skips the real corpus.

Remediation started the same day on branch `audit/charts-mcp-2026-11`. Section 7 records what
was fixed, what was not, and what needs the owner.

## 2. Scope and method

| Auditor | Scope | Method |
|---|---|---|
| Chart source review | `chart_selector`, `dashboard_composer`, `aggregation_policy`, `insights`, renderers, v1, eval | Code reading, one in-process scan of every served matrix (9,973 composed tiles), renderers run in node on small inputs |
| Chart empirical | What the pages show for 44 datasets across shapes | In-process meta/insights/`/data`, HTTP on a local server, Playwright on 11 pages, `kpi_total_checks` |
| MCP security | `/mcp` protocol, limits, privacy, leakage | Local server with the operator profile, official SDK client, hand-made JSON-RPC, in-process apps with tiny limits |
| MCP answer quality | The eight tools' numbers, refusals, discovery | `registry.call_tool` in-process in RO and EN, REST via TestClient, ground truth read from parquet and INS published cells |
| Evidence | Tests, env vars, tool lists, chart inventory, git, CI | Full test run, grep, manifest |

Evidence labels: **Observed** (real local result), **Fixture** (real code on a hand-made input),
**Source** (code reading only). Raw reports and scripts stayed in the session scratchpad; the
findings below carry the evidence they need.

Baseline facts: 2,182 tests pass, 35 skip (34 of them pinned to another generation). The chart
eval is not run by CI or `release-check.py`. The tool contract document lists seven tools; the
code serves eight.

## 3. Chart selection findings

How a chart is chosen today: `chart_selector.select_charts` scores twelve chart types from
metadata only. `dashboard_composer.compose_dashboard` builds the tiles users see: it pins totals,
applies verified levels, gates stacking, and asks `aggregation_policy.decide` for every tile. The
v2 page re-checks each tile through `/data`. v1 reads the selector's ranking directly and ignores
the composition.

| ID | Pri | Finding | Evidence | Where |
|---|---|---|---|---|
| CH-01 | P0 | A Total series is stacked on its parts. The stacked-area renderer stacks every series; the composer keeps Total in the slice when the series has no verified level. FOM104G 2024 draws 10.9M for a 5.45M total. v1 SOM101A_macroregiuni stacks "Total someri" on "Someri neindemnizati". The v2 `bar_vertical` tile draws the Total beside its part. | Observed, Fixture | `chart-factory.js:133,176`, `dashboard_composer.py:590-598`, `explore-app.js` |
| CH-02 | P0 | A dimension with Masculin, Feminin, Urban, Rural is treated as one partition and stacked; everyone is counted twice. TAV0212 opens this way; TGA0526_regiuni sums to 25,980 for 12,990 people. | Observed, Source | `dashboard_composer.py:77,408-424`, `aggregation_policy.py:689` |
| CH-03 | P0 | "Prevalence" with no unit type is classed additive, so percentages get summed and stacked. | Observed, Source | `aggregation_policy.py:116-122` |
| CH-04 | P0 | A summed total that INS contradicts is still served as `valid_total` by tiles, `/data` and the ranking sentence. SCL104A_judete shows Bucharest teaching staff as 88,736; the level parts give about 24.9k. The latest KPI is correctly withheld (INS mismatch 2.65×), but only the KPI reads `kpi_total_checks`. Upper bound: 230 of the 301 mismatch datasets compose a summing tile; 46 show a ranking sentence. | Observed | `insights.py:323-361`, `dashboard_composer.py:522` |
| CH-05 | P0 | 113 parquets hold annual and quarterly values in one `TIME_PERIOD`. Tiles draw both on one axis: CON109C shows 1,287,070 for 2023 next to 320,212 for 2023-Q1. SOM101E's "−58.5% since 2010" compares an annual point with a monthly one. The latest-period pin can pick a quarter. | Observed | `dashboard_composer.py:556-645,227-241`, `chart-factory.js:118-125` |
| CH-06 | P1 | The headline sentence names a winner from an arbitrary pinned slice and does not say which. FOM106E: "Timis 5.292" is agriculture, men only. The latest KPI on the same page is withheld for `arbitrary_pin`. | Observed | `insights.py:186-196` vs `:323-361` |
| CH-07 | P1 | The tooltip "∑" sums every series, Total included, also on line and grouped views. About 38 tiles. | Fixture, Observed | `dashboard-v2.js:1293`, `chart-factory.js:198,213-228` |
| CH-08 | P1 | Mixed-grain axes stay mixed. Only 119 of 9,610 `dimension_structure` rows are verified; the policy adds a `mixed_grain_on_axis` warning that no page shows. 732 tiles in 356 datasets. ACC101B ranks regions next to counties; AMG130M draws a pyramid of 15-24, 15-74 and 25-74. | Observed, Fixture | `aggregation_policy.py:647-655` |
| CH-09 | P1 | Choropleth is chosen for countries and EU members (21 datasets: EXP101B, TUR107C…). The renderer asks for a map it never loaded. | Observed, Source | `chart_selector.py:80-91,240-244`, `chart-geo.js:83-100` |
| CH-10 | P1 | 350 split children with 16–439 periods have `has_time=False` in `matrix_profiles`. The selector trusts the flag and picks pyramids (66) and stacked bars (52) for time series, many of them rates. | Observed | `chart_selector.py:116`; pipeline profile |
| CH-11 | P1 | The composer proposes tiles that `/data` refuses for conflicting grain. POP107D_grupe_judet, TUR105H_judet, FOM104D_judet and SOM101E_anual_judet render with zero charts. | Observed | `dashboard_composer.py:522,731` |
| CH-12 | P1 | Pins chosen per dimension can combine into an empty slice. ASS118A pins a unit and a year with no rows together; TOY1333 the same. | Observed | `dashboard_composer.py:556` |
| CH-13 | P1 | v1 stacks rates. The selector gives percentages a stacking bonus; v1 takes its default from that ranking. 106 datasets with a non-additive measure open stacked in v1. | Observed, Source | `chart_selector.py:221-237,353-354,400`, `explore-app.js:1320-1324,1606` |
| CH-14 | P1 | The chart eval has no ground truth. It scores the selector only, against its own 2026-07-20 output: 1,986 of 4,110 datasets covered; 39 primary changes, 144 top-set changes and 301 score drifts never re-accepted. The hero tile users see differs from the selector's primary in 625 of 3,969 compositions. The taxonomy eval's expected sets were widened to fit the selector. Not in CI or `release-check.py`. | Observed | `chart_selector_eval.py` |
| CH-15 | P1 | FOM106E's hero map defaults to agriculture × men although the app holds the INS total series in `published_totals`. The composer does not read it. | Observed | `dashboard_composer.py:277-316` |
| CH-16 | P2 | The browser changes the server's default view from lines to grouped bars (`preferBarViews`); tests assert the server's default. | Source | `utils.js:521-537` |
| CH-17 | P2 | v1 sums raw rows in the browser when its aggregated request fails. | Source | `explore-app.js:2777-2783` |
| CH-18 | P2 | v1's yearly toggle sums monthly stock counts and partial years. | Source | `explore-app.js:2586-2625` |
| CH-19 | P2 | Time gaps are hidden: the axis lists only present periods and `connectNulls` is on. | Source | `chart-factory.js:118-125,174` |
| CH-20 | P2 | POP201A_* births 2024 sum to 148,916; INS has 157,270. Rows are missing in the parquet, but map, ranking and sentence are served as complete. | Observed | same gate as CH-04 |
| CH-21 | P2 | A 4-option geo dim with no national row is pinned to one macroregion instead of drawn as series (SAR102D_macroregiuni). | Observed | `dashboard_composer.py:344-406` |
| CH-22 | P2 | `generate_view_profiles.py` builds a second chart list that no page reads. Selector cardinality comes from metadata, not data. Static-site parity does not cover chart choice. | Source | — |

What works and must stay: the composer's slice builder (totals pinned off-axis, verified levels,
hierarchy roots), one policy verdict shared by tiles, insights, `/data`, Ask and MCP, the stacking
gate and its tests, the stacked-bar and ranking renderers dropping Total, insights withholding a
KPI that INS contradicts, overlapping age levels restricted or withheld (POP107A, POP107D,
POP105A), rates never summed, stale-response guards (A05 fixed) and Ask chart series identity (A03
fixed). Every latest-value KPI shown in the sample matched INS.

## 4. Public MCP: transport, limits, privacy

65 tests pass. The official SDK client (mcp 1.27.0) initializes, lists, calls and pings without
problems. Disabled, `/mcp` returns 404 for every method and subpath. The 64 KiB body cap is
checked before parsing. Host gives 421 and Origin 403; `Origin: null` is refused. Links come only
from `TEMPO_PUBLIC_BASE_URL`; a spoofed Host changes nothing. Argument schemas are strict and
dataset codes are pattern-checked, so no path traversal is possible. Filter values are bound as
parameters (A08 closed); A01 and A02 are closed on this surface.

| ID | Pri | Finding | Evidence | Where |
|---|---|---|---|---|
| MCP-01 | P1 | Every limit is one global bucket. Requests refused for Origin or Host still consume the request window, which is taken before the SDK checks. Five refused requests from one origin made a legitimate `ping` get 429 for 60 s (window set to 5). About 10 requests/s from one host blocks every client, `initialize` included. | Observed | `public_mcp.py:616-619,195-212,399-403` |
| MCP-02 | P1 | `mcp-calls.jsonl` has no size cap or rotation on the 1 GB volume. Refused calls are logged with full arguments (a 30 KB argument became a 31 KB line); precheck refusals skip the calls window. At the request window that is about 38 MiB/min, so the volume fills in about 27 min, and then Ask's chat log stops too. Writes are synchronous in the event loop. | Observed, Source | `public_mcp.py:370-393`, `fly.toml` |
| MCP-03 | P2 | The deadline interrupts once. If the timer fires between two queries, the work runs on; an `ok` after the deadline is returned and cached. `describe_dataset POP107D` returned `ok` after 2.14 s with a 0.3 s deadline. | Observed | `ask_guard.py:369-391`, `public_mcp.py:454-456` |
| MCP-04 | P2 | `describe_dataset` and `discover_indicators` skip the scan limit but read the whole parquet for period bounds (POP107D, 22.3M rows: 1.8–2.4 s cold). A test makes the exemption intended. | Observed | `discovery.py:1248-1262`, `data_query.py:576-593` |
| MCP-05 | P2 | The cache key is not normalised: reordered keys, or `lang` omitted versus `"ro"`, each run the tool again. | Observed | `public_mcp.py:357-359`, `contract.py:97-98` |
| MCP-06 | P2 | A client that hangs up does not stop its work; only the deadline bounds the slot. | Observed | `public_mcp.py:441-443` |
| MCP-07 | P2 | The privacy notice says no IP or client identity is recorded. True for the content log; production uvicorn keeps its access log with client IPs, joinable by the second. The SDK logs `input_value` excerpts of malformed requests. | Source, Observed | `Dockerfile:27`, `public_mcp.py:79-81` |
| MCP-08 | P2 | `TEMPO_MCP_ALLOWED_HOSTS` includes the Fly hostname, so clients can bypass Cloudflare. | Source | `scripts/deploy/fly/mcp-public.env` |
| MCP-09 | P2 | SDK-level errors echo internals (pydantic dumps with the library version, "maximum recursion depth exceeded", the 4300-digit integer limit). No paths, SQL or stack traces. Tool failures are clean. | Observed | SDK |
| MCP-10 | P2 | Protocol deviations from the SDK: JSON-RPC batch arrays get 400; unknown method `foo/bar` gets -32602; `id: null` or `1.5` get 202 with no body. GET and DELETE 405 (allowed). | Observed | SDK |

Not verified: memory on the 512 MiB Linux machine, Cloudflare or Fly rate limits, real claude.ai
and ChatGPT connectors, slow-body behaviour, the production access log lines.

## 5. Public MCP: answer correctness

Verified correct, in RO and EN: county populations 2025 (Cluj 697,374; Iași 780,271; București
1,709,191); the top-30 cities ranking (319 municipalities and towns, București once, no communes or
sectors); county population change 2012→2021 (Prahova −58,119; Teleorman −14.18%); the published
unemployment, wage and tourism recipe values; refusals for overlapping age levels, missing bands,
summed averages and indices, conflicting grain, mixed annual and monthly periods, a period
outside coverage, an unknown column and an unknown value. REST and `query_data` gave identical
values and verdicts on 12 selections including 7 refusals. Evidence links resolve and reproduce
the exact slice.

| ID | Pri | Finding | Evidence |
|---|---|---|---|
| AQ-01 | P1 | Sibling tables of different vintage give different numbers for the same year with no caveat. Births 2024: POP201A 148,916 (updated 2025-10) vs POP201D_localitate 157,270 (2026-09). Domicile population 2025: POP107A 21,739,373 vs POP107D 21,751,865. Discovery offers the older table. | Observed |
| AQ-02 | P1 | Births have no reviewed concept. RO "nașteri" returns a share of assisted births; "numarul nasterilor" returns pension tables. The two definitions differ by about 4% in 2024 and no clarification is offered. | Observed |
| AQ-03 | P1 | National registered unemployment is evasive and self-contradictory: the "registered" clarification has no action, `areas:["TOTAL"]` is refused, yet every recipe envelope carries the TOTAL aggregate (3.3 for 2025, equal to INS). `discovery_defaults.json` says the national rate "is not served". | Observed, Source |
| AQ-04 | P1 | Ties get distinct ranks with no tie marker and `top_k` cuts through a tie group (six localities at 0 ranked 1–6). | Observed, Source |
| AQ-05 | P1 | "Latest monthly inflation" ranks the annual table (ends 2024) first; the monthly one is sixth. The headline CPI Total is not in the corpus. Index values (previous month = 100) are labelled unit "Procente", type percentage. | Observed |
| AQ-06 | P1 | The offline Ask eval skips all 12 copied-corpus tasks: `ask_tasks.json` pins generation 9b3e065d. The 132 passes are synthetic with scripted tool choice. Two known unsafe acceptances remain (T11). | Observed |
| AQ-07 | P2 | Percent-change rankings are led by tiny bases (1→46 = +4,500%) with no warning. | Observed |
| AQ-08 | P2 | Messages: a national question gets "cannot answer a question about a smaller area"; the non-annual refusal names the wrong tool; rate refusals do not point to the matching recipe; `rank_entities` auto-pins a level without a warning. | Observed, Source |
| AQ-09 | P2 | AGR101B_judet gets `source_total_unchecked` from `query_data` and `conflicting_grain` from `rank_entities`; raw rows return `ok`. | Observed |
| AQ-10 | P2 | `run_recipe` carries no series-break warning (tourism 2019; the note sits only in provenance). | Observed |
| AQ-11 | P2 | Four `_judet` children cut from locality tables lose the locality column and have conflicting grain (AGR101B_judet, POP201D_judet, POP201K_judet, SOM101E_anual_judet). Tools refuse correctly. Pipeline, stage 12. | Observed |
| AQ-12 | P2 | REST `/data` returns 200 with empty rows for an unknown value or year; `query_data` gives a reason. Years must be JSON strings. EN messages keep RO unit labels. Discovery noise on "medici" and "doctors per county". | Observed |

## 6. Decisions taken

The owner asked the orchestrator to decide and to delegate what is possible. Decisions:

1. **Correctness over coverage.** The INS source-total gate moves from the headline KPI into
   `aggregation_policy.decide`, so tiles, `/data`, Ask and MCP inherit it (new reason
   `source_total_mismatch`). Pages of mismatch datasets lose summed tiles until a dimension is
   verified. This follows the AGENTS.md rule: a summed total needs the source's agreement.
2. **A Total is never a series beside its parts.** Composer slice and renderers both enforce it.
3. **One granularity per temporal tile**, with the latest-period pin on the same granularity.
4. **The composer calls the grain guard** and drops tiles it would refuse (A04 rule).
5. **Choropleth needs a Romanian geo level.** Selector ineligibility plus a renderer fallback.
6. **`has_time` is derived from the TIME_PERIOD options** when the profile flag is false; the
   pipeline profile bug goes to the backlog.
7. **MCP limits are per client** (Fly-Client-IP, else peer) under the existing global ceiling;
   the content log gets a size cap and logs refused calls as a hash and size.
8. **Ranking ties share a rank**, `top_k` splitting a tie is a warning; national registered
   unemployment becomes a runnable choice; births and CPI get reviewed concepts.
9. **No baseline is rebuilt without an explained diff.** No deployment, no corpus mutation.

Owner decisions left open (also in the backlog): hero tiles from `published_totals` (CH-15);
the Fly hostname in `TEMPO_MCP_ALLOWED_HOSTS` (MCP-08); access-log IP retention and the privacy
notice (MCP-07); stage-12 `_judet` splits (AQ-11); the pipeline cause of `has_time=False`
(CH-10); v1 yearly aggregation of stocks (CH-18); vintage caveats across sibling tables (AQ-01);
whether to gate `describe_dataset` by scan size (MCP-04).

## 7. Remediation status

Seven implementation packages were written by sub-agents in isolated worktrees on 2026-11-08 and
merged into `audit/charts-mcp-2026-11`, then into `fix/ask-answer-quality`. Per-package detail and
corpus before/after numbers are in the activity log entry of 2026-11-08. Nothing is deployed and
the corpus is unchanged.

| Finding | Status | Where |
|---|---|---|
| CH-01 Total stacked on parts | Fixed: composer slice excludes the Total series; stacked area, grouped bars and v1 stacks drop a Total; FOM104G stack equals the INS Total | composer, frontend |
| CH-02 mixed sex+residence partition | Fixed: `partition_kind`; policy refuses, `_stack_ok` never stacks it | policy |
| CH-03 prevalence additive | Fixed: rate-word rule for unknown units (TAV0212 flips) | policy |
| CH-04 INS-contradicted sums served | Fixed in the shared verdict: `source_total_mismatch` for tiles, `/data`, insights, Ask, MCP; SCL104A_judete refuses 88,736. 126 mismatch datasets keep sums whose summed dimension INS verifies | policy, structure loader |
| CH-05 mixed periodicity on one axis | Fixed for tiles and pins: one periodicity per temporal tile, badge shows what was left out. Insights KPIs and trend breaks still read mixed values (backlog) | composer, frontend |
| CH-06 winner from a hidden pin | Fixed: sentence names one pin, withheld for two or more | insights |
| CH-07 tooltip sum | Fixed: only on stacked views, Total excluded | frontend |
| CH-08 mixed grain on axis | Disclosed: visible badge. Restricting pyramids and bars to one band set is backlog | frontend |
| CH-09 choropleth for countries | Fixed: selector gate plus ranking-bar fallback | selector, frontend |
| CH-10 children without time | Fixed in the selector (derived from options) and in the classifier; the stored profiles need a scoped recompute on a copied generation (backlog) | selector, pipeline |
| CH-11 tiles `/data` refuses | Fixed: composer runs the grain guard and lists refused tiles under `suppressed` with the reason | composer |
| CH-12 empty cross-pins | Fixed: co-occurrence check re-picks the pin | composer |
| CH-13 v1 stacks rates | Fixed: no Area/Stacked for non-additive measures; no raw-row fallback | frontend |
| CH-14 stale eval | Baseline rebuilt over 4,110 datasets with the diff explained; a composer-layer eval with a hand-labelled set is backlog | eval |
| CH-15 hero from published totals | Owner: yes, next composer package (backlog) | — |
| CH-16…CH-22 | CH-17 fixed (no raw-row fallback); CH-18 v1 yearly toggle off by default; CH-21 small geo dims are series; the rest backlog | frontend, composer |
| MCP-01 global rate bucket | Fixed: per-client windows under the global ceiling; refused Origin/Host counts only against its client. Per-client keys behind Cloudflare need the real-IP header (owner: later) | public_mcp |
| MCP-02 uncapped content log | Fixed: 256 MiB cap, one rotation, argument-free refusal lines, off the event loop | public_mcp |
| MCP-03 one-shot deadline | Fixed: repeating interrupt; post-deadline answers become `query_timeout`, never cached | ask_guard, public_mcp |
| MCP-05 cache key | Fixed: validated model, sorted keys | public_mcp |
| MCP-06 hang-up | Fixed: disconnect cancels the token | public_mcp |
| MCP-07 privacy notice | Wording fixed; owner keeps the access log | public_mcp |
| MCP-04, 08, 09, 10, 11 | Backlog or accepted as is | — |
| AQ-01 vintage | Fixed: `newer_vintage` warning; discovery prefers the newest sibling unless its grain conflicts | tools |
| AQ-02, AQ-05 births and CPI concepts | Fixed: reviewed concepts; IPC102 reported as index (profile fix is backlog) | tools |
| AQ-03 national unemployment | Fixed: runnable from INS's TOTAL cell | tools |
| AQ-04 ties | Fixed: shared ranks, `tied_with`, `tie_split` | tools |
| AQ-06 eval pin | Fixed: 062bd2b0, 144/144, 0 skipped | eval |
| AQ-07…AQ-10, AQ-12 | Fixed except the REST empty-slice reason and EN unit labels (backlog) | tools |
| AQ-11 `_judet` splits | Fixed in stage 12 for the next run (child skipped unless a verified roll-up exists); the four live children stay until the parents are regenerated | pipeline |

Full test suite on the merged branch: 2,354 passed, 33 skipped (all pinned to another generation or a missing record), 1 failed. The failure was tests/test_fix02c_source_gate.py asserting the old headline-only scope of the INS gate; its expectation was updated to the extended rule (grouping by SEX is refused too, a full breakdown stays available) and the file passes.
