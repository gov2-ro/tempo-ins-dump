# AQ-13 — INS published Total cells for non-additive indicators (brief)

Owner decision, 2026-11-19: serve INS's own Total cells for a curated set of non-additive indicators
(phase 1). A systematic fetch of totals for every non-additive dataset (phase 2) is decided later,
from live MCP refusal counts. This is fix #7 of the AQ-09C sweep
([aq-09c-sweep-baseline.md](aq-09c-sweep-baseline.md); questions 05, 10, 11, 12).

**Run after AQ-09 is merged.** Both packages touch `ranking.py`, the discovery code and `concepts.json`.

## Why the cells are missing

`6-fetch-csv.py` drops every "Total" option when a dimension has alternatives
(`encode_query_parameters(include_totals=False)`), to avoid double counting and INS's cell limit.
For counts the app rebuilds a total by summing. For rates, averages and indices it cannot:
`aggregation_policy.decide` refuses with `missing_weights` / `non_additive_measure`, and some
datasets carry the note "INS also publishes the total… our download does not include it". In the
served generation, 579 canonical datasets are rates or percentages with a dropped Total option;
averages in lei (wages) come on top. Today `published_totals` holds 2 matrices (FOM106E, SOM103A),
used only by the reviewed recipes.

## Owner decisions (2026-11-19)

1. **Indicators (phase 1):** life expectancy (national, by sex), infant mortality (national), the
   overall CPI, average gross and net monthly wage (all activities), unemployment rates (national, by
   sex), GDP per inhabitant (national). Verify each matrix code, unit and period in the served
   generation; do not take codes from this brief.
2. **Presentation:** a published cell is never mixed into the rows of a parquet result. It appears
   separately and labelled as "INS published total", with its provenance. Follow the existing recipe
   pattern: the national value sits in `aggregates` (key `TOTAL`), not in `rows` (sweep Q19).
3. **Refresh:** cells are fetched per generation. The orchestrator re-fetches a listed matrix when INS
   updates it (`update-pipeline.py`, "INS published totals (if listed)"). Confirm this with a test.

## Work

### 1. Spec and schema

- Extend `app/data/published_totals.json` with one query per indicator. Use the existing `select`
  picks (`total`, `all`, `years`).
- The table key is `(matrix_code, ref_area, time_period)`: every dimension except area, year and unit
  is pinned to Total. "By sex" needs one more key. **Recommendation:** add a column `breakdown`
  (canonical JSON of the non-Total pinned dimensions, for example `{"SEX":"Feminin"}`; `''` when all are
  Total) and put it in the primary key. `load-published-totals.py` keeps validating that every other
  dimension is Total. Readers must accept a generation without the column (existing rows mean `''`).
  **Stop and ask** if you prefer another design.

### 2. One shared lookup

- Add the lookup to an existing service (`recipes.py` already reads the table; prefer a small function
  there or in `data_query.py` over a new module). Signature in the spirit of
  `published_cell(conn, code, ref_area, period, breakdown) -> value + provenance | None`.
- Tools call it **only** when the policy refused a combination because the measure is non-additive and
  the needed Total was dropped. Never when a parquet value exists for the same cell.

### 3. Tools

- `query_data`: a request for the total over a dimension whose Total was dropped returns the published
  cell (when present) instead of `missing_weights`, with a warning code naming the source (for example
  `published_total`) and its provenance.
- `rank_entities` / `compare_periods`: entities keep coming from the parquet (AQ-09 rule: one cell per
  entity). The national reference, when published, goes into `aggregates`.
- `describe_dataset` / `discover_indicators`: say that a published national value exists, and for which
  years and breakdowns. Update the AQ-09 concept notes that say "not in the download".
- Messages through `messages.py`, RO and EN; codes never change with `lang`.
- Prefer an optional field or warning inside the current contract. **Stop and ask** before a contract
  version bump or a new `method` value in `aggregation_policy`.

### 4. Static site

The static site answers `/api` paths in the browser. If a REST answer changes (the `/data` endpoint or
any recorded path), keep `tools/static-engine/parity.mjs` and `api-parity.mjs` passing
(`tests/test_static_parity.py`) and make `scripts/build-static.py` carry the cells.

### 5. Data

- Fetching the cells calls INS (`scripts/fetch-ins-reference-cells.py`; 30,000-cell limit per request).
  Keep `--delay` polite.
- Load the cells **only into a copied generation**: an APFS clone of the served data
  (`cp -c -R /Users/pax/devbox/gov2/tempo-ins-dump/data <scratch>/data`), outside the repository. Never
  write to the repository's `data/`. Promotion and deploy are the owner's step.
- Check every loaded value against the INS site for at least one area and year per indicator; record
  the comparison.

## Verification

- Synthetic fixtures for the schema, the loader (`breakdown` validation), the lookup and each tool path:
  the published cell appears only after a non-additive refusal, never inside `rows`, never when a parquet
  value exists.
- Corpus tests on the copied generation (skip without it).
- Re-run the 20 sweep questions (`aq-09c-sweep-questions.json`, method of the baseline). Report the score
  next to the AQ-09 result, and explain each changed outcome (expected: 05, 10, 11, 12).
- Full `python -m pytest tests -q` once at the end; never two full suites at once (`release-check.py`
  runs one too). Search and chart evals only if discovery ranking changes; explain diffs first.
- `scripts/serve-mcp-test.sh` against the copied generation, and `scripts/mcp_probe.py`.

## Stop and ask when

- An indicator has no published Total cell for the asked level, or its INS Total differs in definition.
- The schema design above does not fit, or a contract version bump / new policy method is needed.
- A rule would place a published cell inside parquet rows, or rank published cells against parquet values.
- Work is needed outside `app/services/`, `app/data/`, `scripts/load-published-totals.py`,
  `scripts/fetch-ins-reference-cells.py`, `scripts/build-static.py`, `tools/static-engine/`, `tests/`,
  `data/eval/` and this plan folder.

## Deliverables

Code, spec, tests, on branch `aq-13-published-totals` from `main` after AQ-09's merge (do not merge,
push or deploy). The copied generation with the cells loaded, and its path. `aq-13-record.md` in this
folder: the indicator table (matrix, levels, breakdowns, years, INS-site check), choices, assumptions,
sweep before/after. Do not edit `docs/BACKLOG.md`, `docs/activity-history.md`, `AGENTS.md` or
`docs/CURRENT_STATE.md`: return proposed text in the final report.
