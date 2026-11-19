# AQ-09 — MCP usability: rank rates, common indicators, discovery messages, period bounds (brief)

Owner request, 2026-11-18: make the public MCP usable for ordinary questions. Revised 2026-11-19
after the 20-question sweep ([aq-09c-sweep-baseline.md](aq-09c-sweep-baseline.md): **8/20 answered
correctly**). This package takes the sweep's fixes #1, #2, #3 and #5, plus the audit item MCP-04, and
ends with a re-run of the same sweep. Fix #4 shipped with AQ-10. Fixes #6, #7, #9, #10, #11 and #12
are **out of scope** (#7, INS Total cells for non-additive datasets, waits for an owner decision).

Starting points:
- **Ask with DeepSeek** ("top 5 județe după PIB per capita, și pe suprafață"): six
  `discover_indicators` calls found no reviewed concept; `rank_entities` refused CON103H_judete
  (`unsupported_measure`, "additive measures only").
- Sweep causes, ranked: no reviewed concept (7 questions), a misleading or empty message (7), a
  refusal that is too strict for a rate (3).

## Setup (read this first)

- Work in your worktree on branch `aq-09-mcp-usability`, based on `main`.
- The worktree has no `data/`. Read the corpus through `TEMPO_DATA_DIR=/Users/pax/devbox/gov2/tempo-ins-dump/data`.
  It is the **served generation `be715608`**: open DuckDB with `read_only=True`, never run a
  pipeline script, never write under that folder.
- Python: `source ~/devbox/envs/240826/bin/activate`.
- Read: `AGENTS.md`, `../00-tool-contract.md`, `../06-answer-quality.md`, the sweep record and
  `aq-09c-sweep-questions.json`, `app/services/tools/ranking.py`, `app/services/period_changes.py`
  (the `unsupported_measure` gates), `app/services/aggregation_policy.py` (`decide`: measure semantics
  and `method`), `app/services/tools/discovery.py`, `app/services/tools/discovery_policy.py`,
  `app/services/tools/intent.py`, `app/services/tools/messages.py`, `app/data/concepts.json`,
  `app/services/concept_search.py`, `app/data/discovery_defaults.json`, `app/services/data_query.py`.

## A. Rank (and compare) a rate when each entity has one value (fix #1)

`rank_entities` refuses every non-additive measure before it queries (`ranking.py`, `rank.additive_only`).
That gate is redundant for safety: `aggregation_policy.decide` already refuses to sum a non-additive
measure (`missing_weights`), and the tool already refuses an approximation. The gate also blocks the
safe case: in a one-year, county-level selection of GDP per inhabitant, each county is one source
cell, and the ranking only sorts.

- Replace the up-front gate. Accept a non-additive measure when the query combined no values, that
  is, when the aggregation `method` is `single_row` or `aggregate_row`. Keep the refusal for
  `sum_partition`, an approximation and anything unverified. Confirm the method names in the code.
- A `weighted_mean` with aligned, verified weights is a real value too. **Stop and ask** before you
  accept it in a ranking.
- Reword `rank.additive_only` (RO and EN). It must say what is refused (combining several values of a
  rate), not "ranking a rate", and it must carry a `recovery`.
- `compare_periods`: apply the same rule to its `unsupported_measure` gate. For a percentage measure
  (unit type percent or rate), the `absolute` change is in percentage points. **Stop and ask** before
  you allow `metric: percent` on a percentage measure.
- Tests on synthetic fixtures: a rate with one cell per entity ranks; a rate that needs a sum across a
  dimension is still refused; the duplicate-key and approximation refusals still hold. One corpus test
  (skips without data): CON103H_judete, 2022, top 5 in both orders.

## B. Reviewed concepts for common indicators (fixes #2 and #3)

`concepts.json` holds the reviewed concepts. Questions outside them fall back to unverified family
search, and the model loops. Add reviewed concepts for:
- **GDP per inhabitant**, regional: CON103H (county, region, macroregion; current prices). Name the
  CAEN Rev.1 series (CON103B) as not comparable.
- **Total GDP**, regional: CON103I.
- **Life expectancy** (national and by region/county where published), **infant mortality**,
  **dwellings completed** (LOC104A family; respect the AQ-10 "Din care" rule), **pupils by education
  level** (SCL103 family; the levels overlap: name the non-overlapping ones in the note), **annual
  exports**.
- **EN aliases** for the existing earnings concepts ("wage", "salary", "earnings", "average gross
  monthly wage"): sweep Q05 found the concept only in RO.
- **County area**: find the source. AGR101A/AGR101B (fondul funciar total, ha) end in 2014. Check the
  corpus and `core-assets` (`/Users/pax/devbox/gov2/core-assets/docs/projects.md`; read only). Report
  the candidates and **stop and ask** before you choose one. No population density derived from
  population ÷ area in this package.

For each concept: aliases in RO and EN (with and without diacritics), variants per geographic level,
the period coverage, a note, alternatives and any discovery default. Verify every code, level and
period against the served generation; do not copy them from this brief. Follow the format and
review rules of the existing concepts, and update the files and tests that check the catalogue.
Where a concept's national value is a non-additive INS Total that the download lacks (life
expectancy, infant mortality), say so in the note; do not compute it (that is fix #7).

## D. Discovery messages (fix #5)

From the sweep (questions in brackets):
1. A measure's own denominator ("per capita" for GDP per inhabitant) is not an unapplied constraint:
   no `constraint_not_applied` warning in that case (Q01).
2. Drop filler words from the family-search query (question words, "care", "what", "how many", ...)
   (Q01, Q15, Q16).
3. Return a distinct "no match" signal when no family is close, instead of `status: ok` with
   unrelated families (Q15, Q16). **Stop and ask** if this needs a new status value or a contract
   change; a warning code inside the existing contract is preferred.
4. When the asked period exceeds a concept's coverage, warn and name the longer series in the same
   concept or its alternatives (Q04: resident population 2012+ vs domicile 1992+; Q14: 2011).
5. The density refusal runs before any family search and offers the tourism recipe (Q20). Search
   first; refuse only when no published series exists, and offer the population ranking only.

Messages go through `messages.py` in RO and EN. Codes never change with `lang`.

## E. Period bounds without a full scan (audit MCP-04)

`describe_dataset` and `discover_indicators` read the whole parquet for the first and last period
(POP107D, 22.3M rows: 1.8–2.4 s cold; the VPS runs Python about 2.8× slower than the Mac, and its
10 s deadline once timed out). See `discovery.py` (`describe_dataset`, `period_bounds`) and
`data_query.py` (`dimension_values` / period bounds). Read the bounds from the metadata the generation
already holds (time dimension options, or `dataset_coverage`) and fall back to the scan only when
the metadata has none. The answer must equal the scan's answer: add a corpus test that compares both
for a sample of datasets, including split children and sub-annual series.

`data_query` has a static-site twin. If you change `data_query.py`, keep
`tools/static-engine/parity.mjs` and `api-parity.mjs` passing (`tests/test_static_parity.py`).

## C. Re-run the sweep

Re-run the 20 questions of `aq-09c-sweep-questions.json` the same way as the baseline (same method,
same tools; see the baseline's Setup). Record per question: calls, dispatch count, outcome, and the
first response that misled or blocked. Report the new score next to 8/20 and explain every changed
outcome. Also re-run the DeepSeek question offline (scripted replay) and report its dispatch count.

## Verification

- Targeted tests while you work. Run the full `python -m pytest tests -q` once at the end, with
  `TEMPO_DATA_DIR` set, and never two full suites in parallel (`release-check.py` runs one too).
- Search eval and chart-selector eval (`scripts/` or the dev MCP) if discovery ranking changes.
  Explain any diff before you rebuild a baseline in `data/eval/`.
- `scripts/serve-mcp-test.sh` (local MCP on :8090) and `scripts/mcp_probe.py` against it, plus the
  CON103H ranking through the MCP.

## Stop and ask when

- A rule above would rank or compare values that are not one source cell per entity.
- A contract version bump, a new status value or a non-additive output-schema change would be needed.
- A concept needs a source you are not sure of (area, density, a national Total).
- Work is needed outside `app/services/`, `app/data/`, `tests/`, `data/eval/`, `tools/static-engine/`
  and this plan folder.

## Deliverables

Code, data files and tests, committed on branch `aq-09-mcp-usability` (do not merge, push or deploy).
`aq-09-record.md` in this folder: measurements, choices, assumptions, the sweep table before/after.
Do **not** edit `docs/BACKLOG.md`, `docs/activity-history.md`, `AGENTS.md` or `docs/CURRENT_STATE.md`:
return the proposed activity entry and backlog entries in your final report instead.
