# AT-01 completion record: shared analytical tools

**Status (2026-10-15): implemented and verified locally on branch
`at/01-analytical-tools`. Owner review/acceptance pending.** The branch is not merged
into `pa/00-baseline` or `main`, not pushed and not deployed. No live provider, MCP
client or load test was run (none is part of AT-01). Ask still uses its old tools until
AT-02, and nothing exposes the tools over MCP until AT-03.

| | |
|---|---|
| Baseline | `pa/00-baseline` 8a9689d959637c47453bc25f1f1dd5c4cfb3f787 (clean; 7 commits ahead of its remote) |
| Final code | `at/01-analytical-tools`, code head 1b2b644; the documentation commit follows it |
| Worktree | `../tempo-at` (a worktree of the same repository as `../tempo-alpha`) |
| Copied generation (read-only probes) | `9b3e065d2fe9bb1df9bae2131b7bdeae9be3426f3c82b9a9954f7e6dc8f45550` |
| Corpus / tables changed | none |

## What was built

One entry point: `app/services/tools/registry.call_tool(name, arguments, *, conn=None)`.
It returns a `tempo-tools/1` envelope and does not raise for bad input, refusals or
failures. In order, it:

1. checks the arguments are at most 16 KiB of UTF-8 JSON;
2. validates them with strict Pydantic models (`schemas.py`: unknown keys rejected,
   no type coercion, AT-00 bounds) before any database work;
3. opens and closes its own cursor;
4. captures the generation before execution and re-checks it after
   (`generation_changed`);
5. maps failures to stable reasons without SQL, paths or exception text, and gives a
   request id for `execution_failed`;
6. drops recovery suggestions whose arguments do not validate (at most 3 kept);
7. fits the result into 32 KiB of UTF-8, through per-tool `shrink` hooks or
   `response_budget`.

`registry.input_schema` / `output_schema` publish JSON Schemas for the adapters.

| Tool | Module | Built on |
|---|---|---|
| `discover_indicators` | `tools/discovery.py` | `concept_search.search`, `grain_guard`, `scope`, `decide_grouped` preflight |
| `describe_dataset` | `tools/discovery.py` | `get_dataset_meta`, aggregation context, `dimension_values` bounds |
| `find_dimension_values` | `tools/discovery.py` | `data_query.dimension_values` |
| `query_data` | `tools/query.py` | one `data_query.run_query` call per tool call |
| `compare_periods` | `tools/changes.py` + `services/period_changes.py` | one `run_query` over the endpoint years |
| `run_recipe` | `tools/recipe.py` | `recipes.run` |
| `get_evidence_links` | `tools/links.py` | validation only; no query runs |

Shared, additive service changes:
- `services/scope.py`: which part of an age domain a grouped total covers. It is used
  by `run_query` (new `scope` field on executed grouped results), `insights` (KPI
  provenance), `static/js/engine/scope.js` (static parity) and the v1/v2 restriction
  badge (`utils.js scopeNoteHTML`).
- `generation.precondition(expected)`: the `/api/datasets/{code}/evidence` and
  `/api/recipes/{id}/evidence` routes accept an optional `expected_generation`. A
  mismatch gives 409 `generation_changed`, checked before the build and again before
  sending.
- `routers/changes.py`: `GET /api/period-changes` returns the tool envelope (live
  re-run). `GET /api/period-changes/evidence` returns a `tempo-evidence/1` ZIP with
  the complete ranking, every exclusion, the endpoint table and stdlib
  `recompute.py`. It is generation-preconditioned, takes an export slot and returns
  413/422 when it cannot certify. Params: `dataset`, `entity_columns` (JSON),
  `intervals` (JSON `[{"from","to"}]`), `filters` (JSON), `metric`, `order`, `top_k`,
  `lang`, plus `expected_generation` on the evidence route.
- `config.PUBLIC_BASE_URL` (`TEMPO_PUBLIC_BASE_URL`): the trusted origin for links.
  Unset gives root-relative links; links are never built from the request Host.

## Checks run

| Check | Result |
|---|---|
| `python -m pytest tests -q` (synthetic, no corpus) | **943 passed, 73 skipped** (baseline 634 passed / 55 skipped) |
| `TEMPO_DATA_DIR=…/tempo-gen-20261012/data python -m pytest tests -q` (read-only) | **1016 passed, 0 skipped** (baseline 689 passed) |
| New AT-01 tests | `test_at01_contract` 56, `_scope` 25, `_discovery` 51, `_query` 71, `_changes` 67, `_recipes_links` 54, `_integration` 3 |
| Static parity (`tests/test_static_parity.py`: `parity.mjs` + `api-parity.mjs`) | pass, including new synthetic age-domain datasets; the scope field is compared key by key |
| Browser smoke (v1 `index.html?code=`, v2 `dataset-v2.html`) on the copied generation | pass at 390 and 1280 px (Chromium, local :8093): no console errors, no 5xx, no horizontal scroll. The single-age v2 pages show "Vârste 0–84 ani (fără 85+)" / "Ages 0–84 (85+ not included)"; the grouped-age page shows none. The v1 headline for `POP105A_judete_varste` is refused (`source_total_mismatch`), so it has no value and no note |
| No network / model / DuckDB-writer access while running the seven tools | `test_at01_integration` (sockets, LLM client and file writers fail if touched) |
| Pre-existing response fields unchanged | `tests/at01_scope_golden.json` (answers recorded on c5eca0d) and the PA-01 parity cases |

The 3 integration tests chain discovery → describe → values → query → period changes
→ recipe → links. They follow each live link (values equal the tool's), fetch each
evidence ZIP (manifest generation = fixture generation), then swap the generation:
the same links give 409 and `get_evidence_links` refuses the old id.

## Numerical examples

Synthetic fixtures (asserted in tests):
- **Period changes**, spec table A/B/C/D, 1992→2002 absolute ascending: B −50, A −20,
  C 0, with D excluded (`no_observation`). 2010→2020: D −90, A −30, B −20, C +5.
  - Percent: A −20 and −33.33…, B −25 and −16.67…, D −100. C's percent is null
    (`zero_baseline`): it is kept in the absolute ranking and excluded from the
    percent ranking.
  - `top_k=1` gives B and D, ranked over all eligible entities.
- **Recipes:** stays 120 / population 60 = 2. Zero and missing denominators are
  excluded (status `partial`). Published 10 vs reconstruction 9.9: 10 is served, with
  a `check` max_abs_diff ≈ 0.1.
- **Additivity:** parts 60 + 40 with a Total = 100 row give 100, never 200. POPX's
  naive 220 never appears (`overlapping_levels`).
- **Single-age child (0–2 analogue):** 90 is returned as `partial` /
  `incomplete_domain`, labelled "Vârste 0–2 ani (fără 3 ani și peste)", with a
  recovery to the complete sibling (100, `ok`). An explicit age filter gives `ok`,
  labelled "(selecție explicită)".

Copied generation 9b3e065d (read-only, tests pinned to it):

| Case | Before AT-01 | After AT-01 |
|---|---|---|
| `POP107D_varste_localitate` grouped by time, 2026 | 21,179,764, `valid_total`, no qualifier | Same value; `scope` covered [[0,84]] of [0,null]; tool `partial`/`incomplete_domain` with recovery `POP107D` = 21,646,220 (difference 466,456 = 85+) |
| `POP107A` grouped by time | `overlapping_levels`, generic hint | Same refusal; recovery `POP107A_judete_grupe` (runs: 1992 = 23,143,860) |
| `TUR105E_judet`, REF_AREA=Cluj | `conflicting_grain`; Ask searched until out of budget | Same refusal; recoveries `TUR105E`, `TUR105E_localitate` |
| `POP108D_grupe_judet` with `AGE:["Total"]` | `slice_value_missing`, unhelpful hint | Explains the export has no Total row though INS metadata lists one; no-pin candidate + value lookup |
| AMG157G periods | Ask schema showed 20 of the 261 metadata periods, `time_range=null` | 270 actual periods 2004-01…2026-06; every one reachable by query or paging |
| Municipal decline, POP107D localities 2012→2021 | Not computable in Ask's budget | 3,181 localities ranked (county added to the key); top Brăila −22,470 |
| POP105A counties 2012→2021 | (none) | Prahova −58,119 (−7.63%), then Municipiul București −58,085, Teleorman −53,623 |
| Tourism intensity 2025 | Recipe REST only | `run_recipe`: 42 counties, Constanța 8.4751 |
| Net earnings 2024 | (same) | INS-published values; check over 42 counties, max_abs_diff 0.6497 |

`dataset_restrictions` flags 16 `*_varste*` children at [0,84], and POP201G, POP203A
and POP203B at [15,49].

## Intentional behavior changes (existing surfaces)

- **`/api/datasets/{code}/data`:** executed grouped results gain an additive `scope`
  field. Raw-row and unavailable responses, and every existing field, are unchanged.
  The static engine emits the same field.
- **`/api/datasets/{code}/insights`:** KPI provenance gains `scope`. Values are
  unchanged.
- **v1 headline, v2 KPI and tile badges:** show the restriction note when a total
  covers only part of the age domain. Cache-busters were bumped (`utils.js?v=32`,
  `dashboard-v2.js?v=33`, `explore-app.js?v=102`).
- **Evidence routes:** take the optional `expected_generation`. Requests without it
  behave byte for byte as before.
- **New routes:** `/api/period-changes` and `/api/period-changes/evidence`.
- **Dev dependency:** `jsonschema==4.23.0` (already installed via `mcp`) is pinned for
  the schema tests.

## Contract decisions and proposed AT-00 amendments

These are recorded here for review before AT-02/AT-03 wire the adapters.
1. **Provenance shape:** `provenance.aggregation` is run_query's decision verbatim,
   except `filters`/`levels`, which live once under `effective_selection`.
   `column_labels` lists only labels that differ from the value.
2. **Generation:** grouped `query_data`, `compare_periods`, `run_recipe` and
   `get_evidence_links` require a present generation (`generation_unverified`).
   Raw-row queries and the metadata tools run with a `generation_unverified` warning.
3. **New or carried-through reasons:**
   - `unknown_tool`;
   - `no_eligible_entities`;
   - `incomplete_domain`, also used for a `partial` recipe with excluded areas;
   - native recipe codes passed through: `unknown_recipe`, `no_common_year`,
     `no_published_data`, `source_unavailable`, `source_incomplete`,
     `source_approximation`, `duplicate_key`, `unsupported_unit`, `unsupported_period`;
   - HTTP-only `bundle_too_large` (413).
4. **Status rules:**
   - Excluded entities or areas make a result `partial`.
   - An empty ranking is `unavailable`.
   - `domain_complete: null` is "not verified", never a failure or a warning.
   - An approximation stays `ok`, labelled.
5. **Recipe candidates:** `Candidate.dataset` is null for a recipe candidate, and
   `Candidate.recipe` names it (changed at merge).
6. **Limits:** `limits.total_rows` is null for capped, windowed or period-dropped
   results.
7. **Row caps:** `compare_periods` caps rows per interval at
   `min(top_k, 200 // intervals)`; `preview_truncated` is true when only exclusion
   samples were cut.
8. **Extra fields:** additional data fields and warning codes were added within the
   open models; see each module's docstring.
9. **Language:** scope text and the recipe/link messages are ro/en. Discovery, query
   and period-change messages are English (backlog item).

## Remaining limitations

- **Coverage:** `domain_complete` is null for most real results (weak
  `metadata`/`profile_flat` partitions). Only age dimensions get numeric coverage.
- **Discovery:** it offers the county or all counties for a city-named place; it does
  not resolve a city. Family results are search hits marked unverified.
- **Recovery candidates:** they are metadata-checked candidates and can still be
  refused at execution (for example by a slice grain check).
- **Links:** validation is structural; filter values are not checked to exist. A
  generation that changes and changes back (A→B→A) during a build is not detected.
- **Period changes:**
  - The entity universe is the keys present at the queried endpoint years.
  - Suppressed parts inside a collapsed partition follow the shared SUM.
  - Boundary continuity is only warned about.
  - At most 500 period labels.
- **Latency:** cold first calls take 0.3–1.3 s on the real copy while shared contexts
  warm. No load or memory measurement was made (AT-04).
- **Not yet wired:** the scope note is not shown on the Ask, compare or place pages.
  Ask and MCP do not use the tools yet.

## Configuration and rollback

- **Configuration:**
  - `TEMPO_PUBLIC_BASE_URL` (optional, trusted HTTPS origin; unset gives
    root-relative links).
  - No switch enables the tools publicly: there is no transport yet.
  - Existing Ask/BYOK switches are untouched.
- **Rollback:**
  - Don't merge the branch, or revert its merge.
  - The REST changes are additive. To drop only the new routes, remove the `changes`
    router include in `app/main.py`.
  - To hide the badge, revert the `utils.js` / `dashboard-v2.js` / `explore-app.js`
    hunks and their cache-busters.
  - No corpus migration, regeneration or data repair is involved.
