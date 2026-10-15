# AT-01: Shared discovery and analytical tools

## Problem and ownership

**AT-01: implemented 2026-10-15, owner review pending** ([record](at-01-record.md)). Implement the shared tool service and its numerical tests.
This package is useful before any model or MCP transport is enabled.

Reuse these target-checkout services:

| Existing code | Reuse |
|---|---|
| `concept_search.search`, `dataset_facts` | Reviewed concepts, interpretations, families, actual coverage |
| `dataset_meta.get_dataset_meta`, `get_aggregation_context` | Metadata, measure, structure and quality |
| `data_query.dimension_values` | Actual searchable/paginated values and period bounds |
| `data_query.run_query` | Validated selections, legacy mapping, aggregation and grain decisions |
| `recipes.load_recipes`, `recipes.run` | Existing reviewed recipes and published source totals |
| `evidence.dataset_bundle`, `recipe_bundle` | Existing reproducible bundle format and export bounds |
| `generation`, `grain_guard`, `dataset_notes` | Identity, repeated-key refusals and caveats |

A focused service module plus a small period-change calculator is reasonable;
file names are implementation choices. Do not call HTTP endpoints through
TestClient from production tools, import the dev MCP, duplicate metadata SQL or
start another DuckDB writer. Take a request-owned cursor and close it in `finally`.
Keep all source reads within the configured copied/deployed corpus.

## Tool behavior

### 1. discover_indicators

Adapt `concept_search.search` rather than the old Ask keyword-search handler.
Return at most `limit` concept/family cards with:

- definition, unit, actual period bounds and available geographic levels;
- parsed places/period/level, consequential ambiguities and labelled alternatives;
- reviewed recipe id where applicable, plus its actual parameter coverage;
- candidate dataset codes with grain/domain restrictions and a suggested next
  tool call using valid arguments.

Group split variants under their family. Prefer a queryable variant matching the
requested grain and scope; do not automatically favor a county child known to
have conflicting keys. A parent may remain the safest queryable source. Resolve
candidate safety through current metadata, generation evidence and actual
coverage, not a blanket `_judet` suffix preference or hard-coded corpus counts.

Generic "population" or "unemployment" must not silently choose a materially
different official definition. Consequential city/county ambiguities also require
clarification. Return useful candidates with `needs_clarification`; selecting a
definition is a separate step. Never fetch a fresh INS dataset during discovery.

### 2. describe_dataset

Return dimensions with canonical column names, type, count, up to five example
actual values, `values_truncated`, option-search arguments and verified structure
where relevant. Examples are not an exhaustive allowlist. Include:

- definition, measure kind, unit, source update date and source/app URLs;
- actual first/last periods, frequency and supported geographic entity keys;
- parent/split relationships, grain status, domain scope and applicable notes;
- real aggregate availability; explain when metadata Total options are absent
  from the actual data rather than suggesting a nonexistent Total filter.

Get actual bounds from the existing dimension-values service or its shared
bounded helper; the old `coverage.time_min_year` fallback is not authoritative.
Metadata-only split parents can be described with their children even when they
have no parquet. Unknown columns/absent files in a data lookup remain explicit.

### 3. find_dimension_values

Adapt `dimension_values`: use actual data values, canonicalized columns and
accent-insensitive search. Preserve stable ordering, actual `period_bounds`,
`offset`, `next_offset`, total if known, and `values_truncated`. Time values are
newest first; filtering an exact old period must reach it without paging through
every newer period. Retain exact values for later queries, separately from labels.

Do not mutate cached dataset metadata while cutting examples/options. Fixture
test: describing a large dimension must not shorten a later REST metadata result.

### 4. query_data

Call `run_query` with the normalized request and caller limit. Return the new
envelope around its response; preserve all native flags and verdicts. A raw
sample is labelled raw, not a verified total. Do not broaden missing/empty values.

Return actionable recovery for common refusals:

- A missing Total value: explain that the source export has no such row, offer a
  reviewed recipe/source-total route or a policy-checked query without that pin.
  Do not promise that removing Total will necessarily make the sum safe.
- Conflicting child: offer a verified candidate parent/locality variant if the
  requested operation can be expressed there; otherwise explain the restriction.
- Overlapping AGE: offer the explicit verified level or a compatible complete
  child; do not sum all levels.
- Unknown place/period: use actual option/bounds lookup, never nearest-year or
  national fallback without an explicit new request.

Implement shared scope disclosure for incomplete domains, especially the known
single-age children: when 85+ exists only in the complete grouped-age source,
label the single-age result `0–84 years` and `domain_complete=false`. Discovery
and Ask cannot present it as an all-ages population answer. A direct explicit
0–84 request can succeed with that scope. Use metadata/actual levels; if scope
cannot be established, state unknown and avoid the full-population claim.

This is a runtime/shared-provenance change, not authorization to regenerate age
splits or rewrite corpus tables. Additive REST fields and relevant existing UIs
must preserve the scope note so the same response is not misleading elsewhere.

### 5. compare_periods

This is the bounded deterministic operation currently missing from Ask. Input:

```json
{
  "dataset": "COUNTX",
  "entity_columns": ["REF_AREA", "REF_AREA_2"],
  "intervals": [{"from": "1992", "to": "2002"}, {"from": "2010", "to": "2020"}],
  "filters": {},
  "metric": "absolute",
  "order": "asc",
  "top_k": 20,
  "lang": "ro"
}
```

V1 supports exact annual periods and additive count/amount measures only. Refuse
means, rates, indices, mixed/unknown units and monthly/quarterly periods with a
specific reason. Existing reviewed rate/earnings recipes remain available through
`run_recipe`; do not invent a generic rate-change unit policy in this package.

Rules:

1. Normalize/check each interval: exact distinct years, `from < to`; 1–4
   intervals. Reject a TIME_PERIOD filter that conflicts with the intervals.
   Other filters are validated normally. No implicit "latest" endpoint here.
2. Validate the requested entity columns and full geographic key. If a locality
   name can collide across counties, require county+locality or a verified stable
   source id. Report level, names and all key components. Display labels alone
   never establish equivalence between changed/merged places.
3. Query the union of endpoint years grouped by full entity key plus time,
   through `run_query`. Apply its policy and quality gates before calculation.
   Internal result cap is the existing service cap, never unlimited. Refuse
   truncated, time-windowed, dropped-period or unsafe source results.
4. There must be at most one finite value per entity/year. Reject duplicate
   endpoint keys even if values agree. For each interval use only complete
   endpoint pairs; list other entities and their missing/suppressed endpoint
   reasons. Do not fill missing observations with zero.
5. Compute `absolute = to_value - from_value` in the declared unit;
   `percent = 100 * absolute / from_value` only when baseline is positive.
   A zero baseline has valid absolute change but null percent with
   `zero_baseline`; a negative baseline yields `nonpositive_baseline` for percent.
   Values remain unrounded in API/tool/bundle outputs.
6. Rank separately for each interval by requested metric and order; tie-break
   deterministically by the full entity key. `rank` is ordinal position, not a
   claim of statistical significance. `top_k` means requested output size, not
   a cap applied before calculating/ranking the complete eligible entity set.
7. Return each interval's rows (`entity`, `from_value`, `to_value`, `absolute`,
   `percent`, `rank`), eligible/excluded counts, exclusion records, definition,
   scope, unit, full source query, known breaks and generation. If exclusion
   details exceed the envelope, return reason counts and a bounded sample, with
   `exclusions_truncated=true` and an evidence route for the full list.
8. Administrative/series breaks must be visible. Refuse unresolved key collisions
   and known incompatible boundary definitions. If source labels/ids are stable
   but historical boundary continuity is not verified, say so; do not claim that
   the data proves like-for-like territory or that domicile means resident count.

This handles multiple requested intervals, not arbitrary transformations, joins,
regressions or user-written code. No cross-dataset joins beyond reviewed recipes.
Do not promise that all real municipal 1992–2020 tasks will be answerable; source
definition, periods, keys and grain must first support them.

### 6. run_recipe

Adapt only ids in `recipes.load_recipes`. Discovery returns ids, so a separate
public list-recipes tool is unnecessary. Pass supported `year` and `areas` into
`recipes.run`. Keep recipe/version, actual year, published-versus-reconstructed
value source, all source definitions/units, exclusions and generation.

Do not send raw `inputs` or the full reconstruction to the model. Include a
bounded cross-check summary and evidence links; bundle generation retains full
inputs under its existing limits. Unknown recipe/year/area has structured
recovery. A recipe result with missing counties must disclose eligibility and
exclusions, not silently present the preview as the whole country.

### 7. get_evidence_links

Input `selection` is a tagged union:

- `kind=dataset`: dataset, filters, group_by, approximate;
- `kind=recipe`: recipe, year, areas;
- `kind=period_changes`: the normalized compare-periods request.

Require the result's generation id and validate all fields. Return typed links
(`dataset`, `live_selection`, `csv`, `evidence`, as supported) with descriptions
of live rerun versus snapshot behavior. Use a configured trusted public base URL;
never use a caller's arbitrary destination or unvalidated Host header. If a URL
would exceed 4 KiB after encoding, return `link_too_long` with a narrower-selection
suggestion; do not remove filters to create a shorter misleading URL.

Extend existing evidence endpoints with an optional expected-generation
precondition and check it at download execution, not just tool invocation. On
mismatch return 409 `generation_changed`. Old requests without that precondition
retain their documented behavior. Keep source observations complete-or-413.

For period changes add a thin read-only evidence route and a `tempo-evidence/1`
bundle containing selection, result, exclusions, source provenance and the
validated entity/year endpoint table, plus `recompute.py`. Recompute absolute,
percent and rankings from that table. Label these as aggregated endpoints, not
raw INS observations; independent verification of endpoint aggregation still
uses the declared source queries. Refuse oversized bundles through existing
export gates. Route/path choices are internal; document the actual paths.

## Numerical fixtures

Use temporary DuckDB/parquet files and the real shared services. Do not write
tests that merely mock the final calculator output. Reuse PA-01/03 fixtures.

| Entity | 1992 | 2002 | 2010 | 2020 |
|---|---:|---:|---:|---:|
| A | 100 | 80 | 90 | 60 |
| B | 200 | 150 | 120 | 100 |
| C | 100 | 100 | 0 | 5 |
| D | 100 | missing | 90 | 0 |

Required expectations:

- Absolute ascending 1992→2002: B -50, A -20, C 0; D excluded for missing 2002.
- Absolute ascending 2010→2020: D -90, A -30, B -20, C +5.
- Percent changes for A: -20 and -100/3; B: -25 and -100/6; D's second: -100.
  C's second percent is null/zero_baseline, not infinity/0. A percent ranking
  excludes it with an explicit reason while absolute ranking retains it.
- Asking `top_k=1` still calculates over all eligible entities, returning B for
  the first interval and D for the second; no pre-ranking truncation.
- Add tied values in another case and assert deterministic order by full key.
- Two counties both containing a locality named `X` remain separate. Omitting a
  required county component gives `identity_ambiguous`, not merged observations.
- Add a duplicated full-dimensional observation and exercise grain refusal
  through real policy/query code. No rank is calculated from refused input.
- Sum two disjoint complete categories, 60 and 40: 100, not 200. Add a Total=100
  row: the shared policy selects the total or valid partition exactly once.
- A child covering 0–84 has 90 people; a compatible parent/grouped level has
  10 aged 85+ as well. The child cannot be promoted as all-ages 100 or as an
  unqualified all-population 90; explicit 0–84 remains a valid restricted answer.
- Incompatible units, missing year, suppressed value, negative/zero baseline,
  mixed time frequency, source cap, unknown generation and changed generation
  each exercise the specified outcome. Never mutate the corpus to create them.
- Existing recipe fixture stays 120/population 60 gives 2; a zero/missing
  denominator is excluded; source published 10 versus reconstructed 9.9 serves
  10 with 9.9 as the cross-check.
- Download a change bundle, verify its file hashes and run its offline
  recomputation on the fixture; every unrounded change/order matches the result.

## Integration and acceptance

Implement in functional increments: discovery/schema/options; query/scope;
period-change calculator and evidence; recipes and link adapters. Keep the REST
statistical services authoritative throughout. Add service tests and thin-adapter
parity tests, including complete evidence preconditions and immutable caches.

Acceptance evidence includes:

1. All above fixtures plus the target checkout's required pytest suite pass.
2. New contracts validate; byte budgets and recovery arguments validate too.
3. REST/static existing parity passes; explain any intentional additional scope
   warnings and preserve old response fields. If changing a service mirrored in
   `app/static/js/engine/`, update its equivalent semantics and parity cases.
4. Read-only corpus probes (if available): recipe discovery for tourism intensity;
   current/old options outside the first 20; shared POP107A overlap and TUR105E
   grain refusals; single-age scope warning. Report generation-specific numbers,
   never bake them into production conditionals or tests lacking a generation pin.
5. No INS fetch, writer connection, model call, arbitrary SQL or remote URL fetch
   is necessary to execute the tools. Source query/recipe caching is bounded and
   generation-aware; no new global cache retains an entire corpus of raw results.

Record remaining real-source limitations honestly. A correct refusal can satisfy
an unsupported real task; synthetic supported tasks must compute their answer.

