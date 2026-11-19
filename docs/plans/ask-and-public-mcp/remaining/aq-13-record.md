# AQ-13 record — INS published Total cells for non-additive indicators

Brief: [13-published-totals.md](13-published-totals.md). Branch `aq-13-published-totals` (from `main`, after AQ-09).
Not merged, not deployed. The cells are loaded only into a copied generation (see section 6).

## 1. Indicators (measured)

Served generation `be715608`; INS metadata read from `data/2-metas/ro`. Every query is one INS pivot request
(`scripts/fetch-ins-reference-cells.py`, delay 1.5 s). "INS check" is a second, independent single-cell pivot request
for the same cell, compared with the loaded row (`published_totals`). All 16 compared cells are equal.

| Indicator | Matrix (query id) | Levels | Breakdown | Periods | Cells | INS check (INS = ours) |
|---|---|---|---|---|---|---|
| Life expectancy | TCP0341 (`TCP0341-total`) | country, 4 macroregions, 8 regions, 42 counties | SEX (both, M, F) | 2008–2023 | 2,640 | TOTAL 2023 both 75.5; F 79.15 |
| Life expectancy, longer | POP217A (`POP217A-total`), residence Total | same | SEX | 1990–2025 | 5,772 | TOTAL 2025 M 73.88 |
| Infant mortality, domicile | POP209A (`POP209A-total`), residence Total | same | none | 1990–2024 | 1,925 | TOTAL 2024 6.1 |
| Infant mortality, usual residence | POP209B (`POP209B-total`), residence Total | same | none | 2012–2024 | 715 | Cluj 2024 6.4 |
| Consumer prices, month on month | IPC102A (`IPC102A-total`), category Total | country | none | 1991-01 – 2026-05 | 425 | 2024-01 101.1 |
| Consumer prices, on December | IPC102B (`IPC102B-total`) | country | none | 1991-01 – 2026-05 | 425 | 2024-12 105.14 |
| Consumer prices, year on year | IPC102E (`IPC102E-total`), TOTAL | country | none | 2001-01 – 2026-05 | 305 | 2026-05 110.85 |
| Gross monthly wage, all activities | FOM107E (`FOM107E-total`), both sexes | same areas | none | 2008–2024 | 935 | Cluj 2024 9,636; TOTAL 2023 7,042 |
| Net monthly wage, all activities | FOM106E (`FOM106E-total`, existing) | same areas | none | 2008–2024 | 935 | TOTAL 2024 4,959 |
| Registered unemployment rate | SOM103A (`SOM103A-total`, widened) | same areas | SEX (both, M, F) | 1991–2025 | 5,757 | TOTAL 2025 F 3.5; Timis 2024 1.1 |
| ILO unemployment rate | AMG157A (`AMG157A-total`), all ages, annual | country | SEX | 1996–2024 | 87 | TOTAL 2024 M 5.7 |
| GDP per inhabitant | CON103H (`CON103H-total`) | same areas, plus "Extra-regiuni" (0) | none | 2000–2022 | 738 | TOTAL 2022 72,669.5; Cluj 2021 88,417.6 |

Every indicator has a published Total for the level the owner named. No stop-and-ask point arose from a missing Total.
Definitions: the Total is INS's own cell, so it has INS's definition. Registered unemployment (SOM103A) and ILO
unemployment (AMG157A) are different statistics; both are loaded and each keeps its own concept. The both-sexes and
all-activity cells are the ones the data file lacks.

Cross-checks on the loaded cells:
- TCP0341 and POP217A (two matrices) agree on all 2,640 shared cells.
- FOM107E (gross) is above FOM106E (net) on all 935 shared cells.
- SOM103A: 1,464 of 1,464 sex cells that the data file also holds are equal to the published cell.
- TCP0341: 607 of 672 male cells that the data file also holds are equal; 65 differ by 0.01–0.05 years, all in 2022 and
  2023. INS revised these two years after the corpus was fetched (the published cells are the newer vintage; the
  matrix says "updated 17-02-2025"). Nothing mixes the two (see 4). A refresh of the data file removes the gap.

## 2. Design

- **Table.** `published_totals` gets a column `breakdown` (VARCHAR, NOT NULL, default `''`): canonical JSON of the
  non-Total dimensions, for example `{"SEX":"Feminin"}`; `''` when every other dimension is Total. It is part of the
  primary key `(matrix_code, ref_area, time_period, breakdown)`. This is the recommended design; no other was used.
- **Spec** (`app/data/published_totals.json`). One query per matrix. A query may name `breakdown` (`{"SEX": 1}`, the
  position in `select`) and `area` (position of the area dimension, or `false` for a matrix without one; its rows are
  filed under area `TOTAL`). `fetch-ins-reference-cells.py` copies both keys to `manifest.json`.
- **Loader.** Validates that every dimension except area, period and unit is Total, unless the spec names it as a
  breakdown. Periods go through `sdmx_labels.parse_time_period` (`2024`, `2024-01`, `2024-Q2`), so they equal the
  data file's `TIME_PERIOD`. It rebuilds an older table that has no `breakdown` column (old rows mean `''`).
- **Readers** accept a generation without the column or without the table (`recipes._pt_query`). The recipe reader
  `_published_cells` takes only rows with `breakdown = ''`; before this change a sex row would have replaced the
  both-sexes cell in `run_recipe`.
- **Lookup** (`app/services/recipes.py`): `published_cell(conn, code, ref_area, period, breakdown)` (value and
  provenance, or None), `published_coverage(conn, code)` and `published_selection(conn, code, filters, group_by, ...)`.
  A split child reads its parent's cells. `published_selection` maps a request to cells only when the request touches
  nothing but the area, the period and the breakdown dimensions. Any other dimension must be left out (it is then
  collapsed, which is what INS's Total means) or be named Total. A non-Total pin on another dimension gives None.
  No period gives None. An area left out means the country (`TOTAL`).
- **Refresh.** `update-pipeline.py` already re-fetches and re-loads the listed queries of an updated matrix. A test
  (`test_aq13_published_refresh.py`) runs the orchestrator for each of the 12 listed matrices and checks the fetched
  query ids, the load and the stage outcome.

## 3. Tools

All inside `tempo-tools/2`. No contract version change. No new `method` value in `aggregation_policy` (the module is
untouched). New in the envelope: the warning code `published_total` and the optional data fields `value_source`
(`ins_published`) and `published_total`, and `provenance.sources[0].published_total` (matrix, breakdown columns,
fetch id, fetch time, file hash, INS update date). `provenance.aggregation` of a published answer says
`method: single_row`, `source: ins_published_total` (an existing method value: one source cell, nothing combined).

- `query_data`. The shared policy runs first. The published cell replaces the refusal only when (a) the reason is
  `missing_weights`, `non_additive_measure` or `unverified_structure` and the measure is not additive, or (b) a raw
  request names a Total value the file lacks (the empty selection) on a non-additive measure, and it names every other
  dimension. The result has status `ok`, the cells in `data.rows` (columns `REF_AREA, TIME_PERIOD, [breakdown],
  UNIT_MEASURE, OBS_VALUE`), the message "INS published total" and the warning. When the file holds the value, the
  file answers and no published cell is looked up. A count is never served from the table.
- `rank_entities`. A ranking the query refused for a dropped Total ranks the published cells of the dataset's own
  areas, when the dataset has no reviewed published recipe (a recipe keeps its route). All values are INS cells; none
  comes from the file. When the file ranks, `data.aggregates` carries the national cell of the same selection. It is
  never ranked with the rows.
- `compare_periods`. `data.aggregates` lists the national endpoints of each interval. A refusal for a dropped Total
  stays a refusal (see 7).
- `describe_dataset`, `discover_indicators`. A `published_total` note and a data field say which periods, how many
  areas, whether a national value exists, and which breakdowns. Concept notes (life expectancy, infant mortality,
  consumer price index) no longer say that the value does not exist.
- The generated dataset note "INS also publishes the total ... our download does not include it" adds a sentence
  only when the generation holds the cells.
- Messages: RO and EN through `messages.py`; codes do not change with `lang`.

## 4. Rules kept

- A published cell is not put inside the rows of a data-file result. The answers that carry published cells in `rows`
  (`query_data`, a published ranking) have no data-file row at all. A parquet ranking or comparison carries the country
  beside its rows in `aggregates`.
- Published cells are not ranked against data-file values.
- The cells are not used when the policy answered (counts, pinned slices, a cut with no cell).
- One known vintage gap: a ranking from the data file with a national `aggregates` cell can mix INS's older (file) and
  newer (cell) vintages for the revised years (TCP0341 2022–2023). The warning names the cell's INS update date.

## 5. Static site

No REST answer changes: `/data` (the shared query) is untouched, and the static engine does not read
`published_totals`. `tests/test_static_parity.py` (9 passed, 2 skipped) passes. `scripts/build-static.py` needs no change.
The concept note text and the generated note text come from data files that the build reads.

## 6. Data

Copied generation: `/Users/pax/devbox/gov2/tempo-gen-aq13/data` (APFS clone of the served `data`, generation `be715608`).
Held by the clone and not by the served generation: `published_totals` rebuilt with the `breakdown` column and
20,659 cells for 12 matrices; the fetched CSVs and `manifest.json` in `data/published-totals/`. Nothing else differs.
Promotion and deploy are the owner's step. The served `data/` was only read.

## 7. Open points

- `compare_periods` does not rank published cells (its refusal for a dropped Total stays). The change between two
  published years per county would be a second use of the same lookup.
- `discover_indicators` still reports `no_verified_candidate` for these concepts (the candidate check is about the
  data file); the published note and `describe_dataset` lead to the call.
- Three more concept families have the same gap (see the backlog entries in the report).

## 8. Sweep (20 questions, same method as the baseline)

Replay of all 56 recorded AQ-09 calls on the copied generation with the new code: 5 differ.

| # | AQ-09 | Now | Why |
|---|---|---|---|
| 01 | partial | partial | same rows; the GDP ranking now carries INS's national value (72,669.5 for 2022) in `aggregates` |
| 05 | failed | answered | discover, describe `FOM107E_judete`, `rank_entities`: Bucuresti 11,002; Cluj 9,636; Timis 8,975 (2024, lei) of 42 INS cells; national 8,061 beside them |
| 10 | partial | answered after the user's choice | the choice (month on month or on December) stays; the overall index for 2024 is now returned (12 values: 101.1, 100.81, 100.42, ...) |
| 11 | failed | answered | `rank_entities POP209B_judete` 2024: Mures 13.0; Ialomita 12.7; Suceava 10.7 per 1,000 live births (INS cells, residence Total) |
| 12 | failed | answered | `query_data TCP0341_judete group_by TIME_PERIOD, SEX`: national life expectancy by sex 2008–2023; both sexes by `group_by TIME_PERIOD` (2023: 75.5) |

Score: **13/20** (AQ-09: 9/20). Counted as answered: 02, 03, 04, 05, 07, 08, 10, 11, 12, 13, 14, 18, 19.
Still not counted: 01 (no county area source), 06 and 09 (a user choice or guess), 15, 16, 20 (no data), 17 (partial).
Q10 counts like Q06: it needs the user's choice, then it answers.

## 9. Verification

- New tests: `test_aq13_published_loader.py` (10), `test_aq13_published_refresh.py` (13), `test_aq13_published_tools.py`
  (16, synthetic), `test_aq13_published_corpus.py` (2, copied generation).
- Static parity: `tests/test_static_parity.py`: 9 passed, 2 skipped.
- Local MCP (`serve-mcp-test.sh` against the copy, then `mcp_probe.py`): ok; `rank_entities FOM107E_judete` and
  `query_data TCP0341_judete` through `/mcp` return the cells above.
- Search and chart evals not run: no ranking, alias or chart code changed (concept notes only).
- Full suite with `TEMPO_DATA_DIR` = the copied generation: 2533 passed, 63 skipped, 0 failed.

## 10. Assumptions

- "INS site" check means INS's TEMPO pivot service (the service behind the site), asked again for one cell. The site's
  own page was not opened.
- Registered unemployment (SOM103A) and ILO unemployment (AMG157A) both count as "unemployment rates (national, by sex)".
- "CPI overall" means the three monthly indices with the overall category (month on month, on December, year on year).
- Net wage (FOM106E) was already loaded; it was re-fetched and compared, not changed.
