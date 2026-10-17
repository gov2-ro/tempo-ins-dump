# AQ-05A completion record: city-only changes over the full classified endpoint set

Step 05A of [05-analytical-extensions.md](05-analytical-extensions.md) only. 05B (joinable-measure audit),
05C (derived measure / two-entity comparison) and 05D (correlations) are not started.
Implemented 2026-10-17 on branch `aq/05a-city-changes`.

- Baseline: `955d81f` (`fix/ask-answer-quality`: AT-05 + AQ-04A).
- Code commit: `56bc561`. This record is added by the next commit; the code is unchanged by it.
- No corpus change, no baseline rebuild, no deployment, no provider call, no limit change, no new
  dependency, no client file change. `answer_check.py` (AQ-03), `recipe.py`, `contract.py`,
  `dataset_notes.py` (AQ-04B) and `intent.py` are untouched.

## Status

| State | Result |
|---|---|
| Code-ready | Yes. Targeted + full suite pass; the default class is byte-identical to the baseline (below) |
| Validated on synthetic data | Yes: every acceptance fixture of the spec, plus mutation checks |
| Validated on a real corpus | Read-only, generation `9b3e065d2fe9bb1df9bae2131b7bdeae9be3426f3c82b9a9954f7e6dc8f45550` (copy `/Users/pax/devbox/gov2/tempo-gen-20261012/data`): one city decline run, an independent DuckDB recomputation, the REST evidence bundle and its offline recompute, corpus-marked tests |
| Model-validated (live provider, task fixtures) | `not_run`. No provider call; AQ-02 fixtures are not in this branch |
| Client-validated (hosted connector, browser) | `not_run`. No JS/HTML changed, so no 320/390/1280 px check was required; the qualification reaches the Ask page through the existing warnings list |
| Deployed | No |

## What changed

| File | Change |
|---|---|
| `app/services/tools/schemas.py` | `entity_class: all\|cities` (default `all`) on `compare_periods` and its citation selection; `cities` needs `REF_AREA_2` among `entity_columns`; the normalized request omits the default; optional `CompareData.entity_class` / `outside_class_count` |
| `app/services/tools/ranking.py` | The GOS102A resolver is now shared: `classify_cities` (full-key classification, `member` / `outside_class` / `aggregate_row`, exact-SIRUTA refusals), `members_of`, `classification_entry`. `rank_entities` uses them and is behaviorally unchanged |
| `app/services/period_changes.py` | Loads the catalogue before the query, classifies the FULL endpoint table, drops non-members before `compute`, so eligible counts, exclusions, ranks and top K are over the class. Adds the `classification_reference` warning and `provenance.classification` |
| `app/services/tools/changes.py` | Class wording in the message, `data.entity_class` / `data.outside_class_count` (class only) |
| `app/services/change_evidence.py` | Link parameter; for the class: `inputs/city_catalogue.csv`, `classification.csv`, a `method.json` `entity_class` block, GOS102A in `attribution.json`, README text, and `recompute.py` that re-derives the classification before ranking |
| `app/routers/changes.py` | `entity_class` query parameter on `/api/period-changes` and `/api/period-changes/evidence` |
| `app/services/tools/links.py` | `entity_class` in the live/evidence URLs; GOS102A as a cited source of a class selection |
| `app/services/ask_context.py` | Compaction keeps `entity_class`, `outside_class_count` and `provenance.classification` |
| `app/services/tools/discovery_policy.py`, `app/data/discovery_defaults.json` | `change` is now a served locality operation, only through the cities class; the one supported meaning is parsed here (`city_change`) |
| `app/services/tools/discovery.py` | One delimited block: `_change_calls` + two call sites + the qualification warning |
| `app/services/tools/registry.py`, `app/services/agent.py` | One sentence in the tool description / Ask prompt |
| `tests/test_aq05a_city_changes.py`, `tests/test_aq05a_city_change_discovery.py` (new) | 28 tests (27 synthetic, 1 corpus-marked) and 27 tests respectively |
| `tests/test_aq04a_discovery_defaults.py` | Three assertions changed because the policy they pinned is the one this step lifts (below) |

Not touched: `data_query`, the aggregation policy, grain guard, `public_mcp.py` and its limits, `concepts.json`,
`concept_search.py`, every static/JS file, `ask_present.py`, `answer_check.py`, the contract version (`tempo-tools/2`).

## Contract (additive, still `tempo-tools/2`)

| Where | Field |
|---|---|
| Request (tool, MCP, REST query string, citation selection) | `entity_class` `all` (default, omitted from every normalized request/link/bundle) or `cities` |
| `data` (class only) | `entity_class: "cities"`, `outside_class_count` (communes, totals) |
| `provenance.classification` (class only) | `dataset` GOS102A, `key` SIRUTA, `class` municipalities_and_towns, `temporal_status` catalogue_not_historical, `generation`, `applied`, `catalogue_count`, `member_count`, `outside_class_count` |
| `provenance.sources` | GOS102A with `role: entity_classification` |
| `warnings` | `classification_reference` (same code as `rank_entities`) with the qualification |
| Evidence ZIP (class only) | `inputs/city_catalogue.csv` (SIRUTA, label), `classification.csv` (class of every entity of `inputs/endpoints.csv`), `method.json.entity_class`, extended `recompute.py` |

The default request, result, link and bundle are byte-identical to the baseline: see "Default class parity".

## How the class is applied

1. The shared query returns the endpoint table of the exact annual endpoints for every entity of the
   selection (full `REF_AREA` + `REF_AREA_2` key; a locality-only request gets its county added).
2. Totals are flagged by the existing rule over the whole table.
3. `classify_cities` maps each key to its SIRUTA (the leading integer of the locality value) and to
   `member` / `outside_class` / `aggregate_row`. A locality value without an exact SIRUTA, or one SIRUTA under
   two entities, refuses with `identity_ambiguous`; the catalogue absent or repeating a SIRUTA under two
   labels refuses (`classification_unavailable` / `identity_ambiguous`).
4. Only members enter `compute`: eligibility, exclusions (`no_observation`, `value_missing`, `zero_baseline`),
   ranks, ties (full key ascending) and `top_k` are over the class. Nothing is filtered after a top K.
5. Absent or NULL endpoints are exclusions, never zero (unchanged `compute`).

## Policy decisions (for review)

Each of these is a statistical-contract choice made without a reviewer; none is a limit or production default.

1. **Membership is applied to the whole endpoint table, by exact SIRUTA, before anything is counted.** Communes and
   totals are *outside the class*: counted in `outside_class_count`, never listed as exclusions (same as
   `rank_entities`). In class mode a total row is therefore not an `aggregate_row` exclusion.
2. **A catalogue city with no row at either endpoint is not listed** (there is no county to key it by; the national
   listing in `rank_entities` carries none either). It is visible only as `catalogue_count - member_count` in
   `provenance.classification` and in the bundle's `inputs/city_catalogue.csv` vs `classification.csv`.
3. **Identity failures refuse the whole request, no partial ranking:** a locality value without an exact SIRUTA, one
   SIRUTA under two full keys (also when a locality is renamed between the endpoint years), a missing catalogue, a
   catalogue that repeats a SIRUTA under two labels. In generation 9b3e065d none occurs (3,181 keys, 0 SIRUTA with
   more than one key, 319 of 319 catalogue cities present, labels equal).
4. **The default is invisible, the class is explicit.** `entity_class: "all"` is dropped from every normalized
   request, link, bundle and follow-up (a pydantic wrap serializer on `_PeriodChanges`), so existing callers, stored
   selections and bundles keep their exact bytes; `cities` always appears. `rank_entities` shows its class always,
   so the two tools differ here on purpose.
5. **Status is not stricter in class mode.** The real city run is `ok` although `scope.domain_complete` is `null`
   ("cannot verify the domain is complete"), exactly as the same query without the class. `rank_entities` returns
   `partial/unverified_total` for the same condition. Harmonizing it would change the default's status, so it is
   left for a decision (backlog candidate).
6. **Wording and qualification.** "municipalities and towns in the referenced catalogue" (INS GOS102A, SIRUTA keys);
   "membership does not prove historical city status or unchanged boundaries" is a `classification_reference`
   warning (also in the message, `method.json`, the bundle README, the discovery result and the Ask page's warning
   list), in addition to the existing `boundary_continuity_unverified` warning. `provenance.classification.temporal_status`
   stays `catalogue_not_historical`.
7. **Discovery: the exact supported meaning** = cities (municipalities/towns), the domicile series, exactly two
   distinct years in the question (sorted, earlier to later), a direction (decline: most negative first;
   growth: largest first), absolute change or percent change when the question says so, top K as for rankings.
   Refused with `unsupported_operation`, nothing defaulted: none/one/three years, no direction or both,
   "bottom/smallest/lowest" wording, and anything asking for historical status or constant boundaries.
   The earlier refusals still come first (resident/July definition, density, non-population, K out of range).
   Sex/age/denominator/county constraints still withhold the data call.
8. **Direction vocabulary lives in `discovery_policy.py`, not `intent.py`** (owned elsewhere in this wave): a city
   question with a stem such as `scad*`, `pierd*`, `cresc*`, `declin*`, `lost`, `grew`, `increase` is treated as a change
   question, so "scaderea populatiei" is refused or answered as a change instead of silently becoming a plain
   ranking. The historical/constant-boundaries detector is a bounded phrase list, not a proof: wording it does not
   list is not caught.
9. **Evidence is larger for the class.** The bundle keeps every entity of the endpoint table (members and others) so
   the classification can be reproduced: 115,272 bytes for the national run (3,181 entities, 319 members); the
   existing 200,000-row bundle limit still applies.
10. **`ask_context.compact` now keeps `provenance.classification`** for every result that has one, so compacted
    `rank_entities` city results also gain it (4 keys of provenance, no row data).
11. **Three AQ-04A assertions changed** because they pinned the policy this step lifts: the shipped `operations` is
    `["rank", "change"]`; the invalid-structure case "change at the locality level" became "change without
    `entity_class: cities`"; the fail-closed test uses `["rank", "lookup"]` as its invalid configuration.
    `lookup` is still not served at the locality level.

Observed and deliberately not changed:

- `ask_context.validate` re-dumps a period selection with `from_` instead of `from`; it still validates (the schema
  accepts both) so follow-ups work, but the hint text shows `from_`.
- `ask_present` marks only `rank_entities` tables as ranked, so a truncated `compare_periods` top K (class or not) is
  captioned "Preview: first N rows; not a ranking" in the Ask table although it was ranked over every eligible
  entity. The caption understates the result; fixing it is a client change.
- The national city change through the public MCP is refused by the unchanged admission limit: the estimate for
  `POP107D_grupe_localitate` is 3,898,870 rows, the default limit 1,000,000 (`query_budget`). The class itself adds no scan.

## Commands and results

Environment: `source ~/devbox/envs/240826/bin/activate`, Node 22 on PATH, provider keys unset,
`PYTHONDONTWRITEBYTECODE=1`. The machine was busy with sibling worktrees (load average ~10); one early full-suite
attempt was stopped by me before the last discovery edit and re-run from scratch on the final code.

| Command | Result |
|---|---|
| `python -m pytest tests/test_aq05a_city_changes.py tests/test_aq05a_city_change_discovery.py -q -p no:cacheprovider` | 54 passed, 1 skipped (the corpus-marked test) |
| `python -m pytest tests/test_aq04a_discovery_defaults.py tests/test_at01_discovery.py tests/test_at05_quality.py tests/test_at05_ranking.py -q` | 200 passed, 11 skipped (before the last discovery edit; re-run inside the full suite) |
| `python -m pytest tests -q -p no:cacheprovider --tb=short` (final code, `56bc561`) | **1361 passed, 75 skipped**, 7 existing FastAPI/openpyxl warnings, 0 failures (6 min 36 s). Baseline `955d81f`: 1307 passed / 74 skipped; +54 passed and +1 skipped = the 55 new tests |
| `python -m pytest tests --collect-only -q` | 1436 collected (baseline 1381, +55) |
| `TEMPO_DATA_DIR=<copy> python -m pytest tests/test_aq05a_*.py tests/test_at01_changes.py tests/test_at01_discovery.py tests/test_at05_quality.py tests/test_aq04a_discovery_defaults.py tests/test_at05_ranking.py -m corpus` | 15 passed (the new pinned city test among them) |
| Real-corpus probe (`real_probe.py`, `real_independent.py` in the reports directory) | the numbers below; the corpus copy's file sizes, mtimes and parquet listing hash were identical before and after (checked) |

Skips are the corpus-marked tests (no corpus in the worktree) plus the new corpus test without data; the corpus-marked
tests above were run on the copy.

### Do the tests detect a wrong implementation?

Four sabotages of the code, each followed by the new synthetic tests (then restored and compared byte for byte):

| Sabotage | New tests that fail |
|---|---|
| the class is ignored (every entity ranked) | 10 |
| the class is applied after top K (rows of the all-entities top K filtered) | 9 |
| the links drop `entity_class` | 1 (replay) |
| the offline `recompute.py` skips the classification | 2 (bundle, tampered inputs) |

### Default class parity (no `entity_class`)

`default_parity.py` runs 9 `compare_periods` requests (counties, localities with a full key, a locality-only
ambiguity, percent/descending, filters, an unavailable year, invalid input), their `get_evidence_links`, 4 REST
bodies and 4 evidence bundles (every file; `created_at` dropped from the manifest) on a synthetic corpus, once
against an exported `955d81f` tree and once against this branch. The two JSON dumps (23 entries, 157,106 bytes) are
byte-identical (checked on the final code). The offline script of a bundle without a class is also pinned in a test by
its sha256 (`b6ff242f...`, the baseline's).

## Numerical examples

Synthetic fixture `CHG` (230 catalogue cities CITY000..CITY229 with 2015 -> 2020 change of -i; the commune
`9999 COMUNA GIANT` 90,000 -> 1,000; a `Total` row; two cities named VALEA in Alba (-150) and Bihor (-10); GONE with
no 2020 row; NULLED with a NULL 2020 value; ZERO 0 -> 50):

- Without the class the first row is the commune (-89,000), then CITY229 (-229), CITY228 (-228).
- `entity_class=cities`, `top_k=3`: CITY229 (-229), CITY228 (-228), CITY227 (-227): three rows. Filtering the
  all-entities top 3 would have returned two. `eligible_count` 233 (230 cities + 2 VALEA + ZERO), 2 exclusions
  (GONE `no_observation`/`to`, NULLED `value_missing`/`to`; neither is zero: as zero GONE would lead with -2,000),
  `outside_class_count` 2 (commune and total), `limits.total_rows` 233.
- The winner CITY229 is the last row of the file: the 200-row raw `query_data` preview of year 2020 does not contain it.
- The two VALEA localities stay separate (`{"REF_AREA": "Alba", "REF_AREA_2": "2001 ORAS VALEA"}` -150,
  `{"REF_AREA": "Bihor", "REF_AREA_2": "2002 ORAS VALEA"}` -10).
- 2010 -> 2015: VALEA -200 and -100, then four -3 ties in full-key order (Alba CITY000, CITY002, CITY004, CITY006).
- Percent ranking excludes ZERO (`zero_baseline`) while its absolute change (+50) is valid.
- Discovery corpus (Cluj-Napoca +4,000, Iasi +5,000, Turda +2,000, Harlau +500, commune +99,999): growth 2024 -> 2025
  ranks Iasi, Cluj-Napoca, Turda, Harlau with the commune excluded (`outside_class_count` 1); percent growth ranks
  Harlau 5.5556, Turda 3.7736, Iasi 1.7544.

Real generation `9b3e065d` (read-only copy), `POP107D_grupe_localitate` (population by domicile on 1 January; AGE and SEX
collapsed by the shared policy, `scope.domain_complete` null), cities with the largest decline 2015 -> 2020,
`entity_class=cities`: 319 eligible catalogue cities, 0 exclusions, 2,862 outside the class, 0.8 s.

| Rank | County | Locality | 2015 | 2020 | Change | Percent |
|---|---|---|---|---|---|---|
| 1 | Braila | 42682 MUNICIPIUL BRAILA | 213,169 | 200,342 | -12,827 | -6.0173 |
| 2 | Prahova | 130534 MUNICIPIUL PLOIESTI | 235,114 | 225,171 | -9,943 | -4.2290 |
| 3 | Timis | 155243 MUNICIPIUL TIMISOARA | 333,998 | 325,583 | -8,415 | -2.5195 |
| 4 | Constanta | 60419 MUNICIPIUL CONSTANTA | 319,351 | 311,512 | -7,839 | -2.4547 |
| 5 | Dolj | 69900 MUNICIPIUL CRAIOVA | 307,401 | 300,223 | -7,178 | -2.3351 |
| 6 | Buzau | 44818 MUNICIPIUL BUZAU | 136,827 | 131,231 | -5,596 | -4.0898 |
| 7 | Caras-Severin | 50790 MUNICIPIUL RESITA | 89,685 | 84,567 | -5,118 | -5.7066 |
| 8 | Mehedinti | 109773 MUNICIPIUL DROBETA-TURNU SEVERIN | 110,821 | 105,734 | -5,087 | -4.5903 |
| 9 | Tulcea | 159614 MUNICIPIUL TULCEA | 90,542 | 85,594 | -4,948 | -5.4649 |
| 10 | Satu Mare | 136483 MUNICIPIUL SATU MARE | 123,484 | 118,932 | -4,552 | -3.6863 |

- Independent check (DuckDB over the parquet and the GOS102A catalogue, no application code): 3,181 localities,
  319 catalogue cities with both endpoints; the top 10 and the eligible count equal the tool's. Braila by hand:
  2015 = 111,901 + 101,268 = 213,169, 2020 = 105,867 + 94,475 = 200,342.
- The decline top 10 contains no commune, so the class changes nothing there. Where it matters, growth 2015 -> 2020,
  top 5: without the class Bucuresti 44,526, Vaslui 37,645, Iasi 29,455, **Floresti (commune) 16,590**, Popesti-Leordeni
  14,695; with the class Bucuresti, Vaslui, Iasi, Popesti-Leordeni 14,695, **Suceava 9,966**.
- The discovery question "top 10 cities by population decline between 2015 and 2020" yields
  `compare_periods(POP107D_grupe_localitate, [REF_AREA, REF_AREA_2], cities, 2015 -> 2020, absolute, asc, top_k 10)`;
  its result equals the direct call. The live-selection link replays an equal `data` and `classification`.
- Evidence bundle (REST, `expected_generation` set): 200, 115,272 bytes, 11 files; `python recompute.py` exits 0:
  "recomputed 319 ranked rows and 0 exclusions ... result.csv matches, exclusions.csv matches" and
  "classified 3181 entities (319 municipalities/towns in the catalogue); classification.csv matches".

## Configuration and rollback

- `app/data/discovery_defaults.json` `population.cities.operations`: `["rank", "change"]`. Setting it back to
  `["rank"]` restores the previous discovery refusal ("City-only change rankings are not yet supported")
  with no code change; `entity_class` stays available to direct callers. Tested.
- `git revert 56bc561` (and this record) removes everything; no data, schema, contract-version or client change.
  Stored Ask follow-ups carry no class for old selections and validate unchanged.
- No new environment variable. The public MCP limits (`TEMPO_MCP_*`) are not touched.

## Remaining gates

- Live-provider Ask run and AQ-02 task fixtures with city-change paraphrases: `not_run`. The vocabulary heuristics
  (direction stems, historical-wording detector, bottom/smallest) are unproven against real model phrasing.
- Hosted-connector / browser evidence: `not_run` (no client file changed). The `compare_periods` table caption
  ("not a ranking" for a ranked top K) should be fixed with the client work, 06 / AQ-04C.
- Public MCP: the national city change is refused by the unchanged scan limit; raising it needs deployment-target
  memory and latency evidence (AQ-01), not this step.
- Status for an unverified collapsed domain differs between `compare_periods` (ok) and `rank_entities`
  (partial/unverified_total); decide and harmonize separately.
- Historical membership / constant boundaries: still unavailable; needs a reviewed source.
- 05B, 05C, 05D: not started.
