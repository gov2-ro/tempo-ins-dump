# AQ-09 — MCP usability: rank rates, common indicators, a question sweep (brief)

Owner request, 2026-11-18: make the public MCP usable for ordinary questions. Two live tests on
2026-11-18 set the starting point:
- **Claude Desktop** (cities by population change 2016→2026): correct, but it had to recover from a
  refused first query.
- **Ask with DeepSeek** ("top 5 județe după PIB per capita, și pe suprafață"): failed. It used all
  12 dispatches: six `discover_indicators` calls found no reviewed concept; `rank_entities` refused
  CON103H_judete (`unsupported_measure`, "additive measures only"); a correct `query_data` table
  (42 counties, 2022) was hidden by the Ask page.

Run this brief **after AQ-08** (chart hints) is merged. Both touch `ranking.py`, `period_changes.py`
and `messages.py`.

Read first: `AGENTS.md`, `00-tool-contract.md`, `06-answer-quality.md`, `app/services/tools/ranking.py`
(`rank_entities`), `app/services/period_changes.py` (the `unsupported_measure` gates near line 425
and 491), `app/services/aggregation_policy.py` (`decide`: measure semantics and `method`),
`app/data/concepts.json`, `app/services/concept_search.py`, `app/data/discovery_defaults.json`.

## A. Rank (and compare) a rate when each entity has one value

`rank_entities` refuses every non-additive measure before it queries. That gate is redundant for
safety: `aggregation_policy.decide` already refuses to sum a non-additive measure
(`missing_weights`), and the tool already refuses an approximation. The gate also blocks the safe
case. In a one-year, county-level selection of GDP per inhabitant, each county is one source cell.
The ranking only sorts the values; it adds nothing.

- Replace the up-front gate. Accept a non-additive measure when the query combined no values, that
  is, when the aggregation `method` is `single_row` or `aggregate_row`. Keep the refusal for
  `sum_partition`, an approximation and anything unverified. Confirm the method names in the code.
- A `weighted_mean` with aligned, verified weights is a real value too. **Stop and ask** before you
  accept it in a ranking.
- Reword `rank.additive_only` (RO and EN). It must say what is refused: combining several values
  of a rate, not ranking a rate.
- `compare_periods`: apply the same rule to its `unsupported_measure` gate. For a percentage measure
  (unit type percent or rate), the `absolute` change is in percentage points. **Stop and ask**
  before you allow `metric: percent` on a percentage measure (a percent change of a percentage).
- Tests on synthetic fixtures: a rate with one cell per entity ranks; a rate that needs a sum
  across a dimension is still refused; the duplicate-key and approximation refusals still hold.
  Add one corpus test (it skips without data): CON103H_judete, 2022, top 5 in both orders.

## B. Reviewed concepts for common indicators

`concepts.json` has 13 concepts. Questions outside them fall back to unverified family search,
and the model loops. Add reviewed concepts for:
- **GDP per inhabitant**, regional: CON103H (county, region, macroregion; 2000–2022; current prices).
  Name the CAEN Rev.1 series (CON103B, 1993–2008) as not comparable.
- **Total GDP**, regional: CON103I.
- **County area**: find the source. AGR101A/AGR101B (fondul funciar total, ha) end in 2014. Check
  the corpus and `core-assets` (see `../core-assets/docs/projects.md`; read only) for an official
  total area per county. Report the candidates and **stop and ask** before you choose one.
- **Population density**, only if a published series exists. Do not derive one from population ÷
  area in this package.

For each concept: aliases in RO and EN (with and without diacritics), variants per geographic level,
a note, alternatives and any discovery default. Follow the format and review rules of the existing
concepts, and update the files and tests that check the catalogue.

## C. A question sweep through the MCP

Write 20 realistic questions, RO and EN, that a journalist or student would ask. Mix rankings,
time series, comparisons, county, city and national questions, and two questions with no data.
Include the two questions of 2026-11-18. Run each through the tools as a model would. Use
`scripts/eval-ask-tasks.py` if it fits, otherwise a local MCP (`scripts/serve-mcp-test.sh`).
For each question record: the calls, the dispatch count, the outcome, and the first tool response
that misled or blocked. Group the failures by cause. **Fix nothing from C in this package**: the
owner prioritizes the list.

Add the questions to `data/eval/ask_tasks.json` only if they fit its format and checks; otherwise
keep them in the record.

## Verification

- Targeted tests while you work. Run the full `python -m pytest tests -q` once at the end, and
  never two full suites in parallel.
- Chart-selector and search evals (`tempo_eval_agent` or the scripts) if discovery ranking changes.
  Explain any diff before you rebuild a baseline.
- `scripts/mcp_probe.py` against a local MCP, plus the CON103H ranking through the MCP.
- Re-run the DeepSeek question offline (the scripted replay) and report the dispatch count.

## Stop and ask when

- A rule above would rank or compare values that are not one source cell per entity.
- A contract version bump or a non-additive output-schema change would be needed.
- A concept needs a source you are not sure of (area, density).
- Work is needed outside `app/services/`, `app/data/`, `tests/`, `data/eval/` and this plan folder.

## Deliverables

Code, data files, tests, `aq-09-record.md` (measurements, choices, assumptions, the sweep table),
an activity entry and backlog entries for the sweep's failures. Commit on a branch; do not deploy.
