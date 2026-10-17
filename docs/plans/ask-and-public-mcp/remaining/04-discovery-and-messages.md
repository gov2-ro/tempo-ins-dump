# AQ-04 — Discovery policy, next actions and bilingual messages

**Status: planned. Three independent bounded steps; preserve current statistical
choices.** Do not use this work to invent a new default for unemployment. *(Superseded 2026-10-17 by an owner decision: level-scoped unemployment defaults and county-scoped city rankings, see `aq-discovery-county-unemployment-record.md`.)*

## Read first

`app/data/concepts.json`, `concept_search.py`, `tools/intent.py`,
`tools/discovery.py`, `tools/recipe.py`, `tools/contract.py`, `dataset_notes.py`,
`agent.py`, `ask_present.py`, `static/js/ask.js`; tests
`test_at01_discovery.py`, `test_at05_quality.py`, `test_at02_browser.py`.

## 04A — Make the current defaults explicit and testable

AT-05 currently prefixes a canonical phrase and injects a locality population
variant in discovery code. Move these reviewed mappings to a small explicit
configuration structure, preferably extending the existing concept catalog.
Validate referenced concepts/datasets and allowed level/operation combinations.
Avoid introducing another general query language or a second search service.

Preserve this policy exactly:

| Request | Behavior |
|---|---|
| Generic population at supported county/region level | Resident default, disclosed with alternatives |
| Generic city population ranking | Domicile default, disclosed with locality definition |
| Explicit resident city population | Unavailable at this reviewed level; no substitution |
| Explicit domicile or July population | Respect it or report unavailable; never overwrite it |
| Generic unemployment | Ask registered versus ILO; default remains a product decision |
| Stays per resident | Reviewed tourism-intensity recipe with exact denominator/year |

Preserve all consequential constraints in the **original** question, including
age, sex, geography, year and denominator. Unsupported constraints must be
reported, never silently dropped because a default alias matched. Out-of-range
top K and unsupported operations stay explicit. Missing configured mappings
must not create an assumption warning about a source that was not selected.

Acceptance: RO/EN paraphrase matrix, explicit/default collisions, unsupported
age/sex constraints, generic unemployment, absent mappings, county/city ambiguity
and latest/exact-year behavior. Compare catalog search and static/server parity:
new policy applies to tool discovery unless a separate UI behavior change is
explicitly included. Do not accidentally change raw concept search globally.

## 04B — Make follow-up actions concrete without bypassing clarification

After a definition is chosen, use a validated `describe_dataset`, value lookup,
`query_data`, `rank_entities` or `run_recipe` action when its coordinates are
known. Keep `discover_indicators` rewording only when more interpretation is
actually needed. Before a consequential place/definition choice, no action may
silently choose one for the user. Every advertised call must validate under the
registry schema and must be executed before presenting its figures.

Make `choices[].recipe` and the selected concept's recipe/next-call agree. Provide
an actionable way to look up recipe areas using existing tools and exact source
labels. Prefer an existing `find_dimension_values` action; if area identity needs
a new contract, document that separately rather than adding an unreviewed tool.
Surface known series-break notes as machine-readable warnings on the affected
selection. Unknown boundary continuity remains unknown, not certified stable.

Acceptance: walk each returned choice in synthetic data; it executes or produces
an intentional next clarification, never a schema error. Include absent periods,
missing area aliases, partial sources and series breaks. Keep byte budgets and
truncation behavior; do not flood the model with full option catalogs.

## 04C — Localize visible explanations and preserve qualifications

Translate tool `message`, warning and recovery text into RO/EN using the existing
language mechanism. Stable reason/warning codes, dataset identifiers, filters,
values and definitions must not change with translation. Consolidate repeated
strings in one small translation map rather than branching throughout SQL logic.

Ensure Ask's table/answer visibly retains source-changing qualifications even
when a model omits them: assumed population definition, unverified/partial scope,
excluded entities, historical classification caveat and source series breaks.
Reuse existing warning/table rendering; deduplicate by stable code and subject.
Do not describe a mere preview as a ranking or a matched number as a full proof.

Acceptance: both languages retain identical structured selections/results and
use localized prose. Script a provider that omits caveats and verify the UI still
shows them. Browser smoke at 320/390/1280 px checks warnings, captions, links,
console errors and overflow. Never translate stored identifiers in a filter.

## Stop and record

Each step has its own validation/record. Run discovery/quality/browser tests as
applicable, plus AQ-02 cases when present. No corpus change or contract major
version is expected for these scoped steps. A broader new interpretation engine
or default policy needs a separate decision; leave it open rather than guessing.
