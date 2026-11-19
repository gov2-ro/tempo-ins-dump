# AQ-09 record — MCP usability

Brief: [09-mcp-usability.md](09-mcp-usability.md). Branch `aq-09-mcp-usability`. Not merged, not deployed.
Measured read-only on the served generation `be715608` (`TEMPO_DATA_DIR` = the main checkout's `data/`).
Raw sweep calls: [aq-09c-sweep-after.jsonl](aq-09c-sweep-after.jsonl). Baseline: [aq-09c-sweep-baseline.md](aq-09c-sweep-baseline.md).

## A. A rate is ranked or compared when each entity is one source cell

- `rank_entities` and `compare_periods` no longer refuse a non-additive measure before the query. They read the
  aggregation `method` of the query result: `single_row` and `aggregate_row` pass (no value was combined).
  Every other method is refused as `unsupported_measure` (`period_changes.rate_values_combined`).
  The query itself still refuses a sum of a rate (`missing_weights`), an unverified structure and an approximation.
- `weighted_mean` is **not** accepted in a ranking (owner question, see below). `decide` returns it only for aligned,
  verified weights; today the tools refuse it.
- `rank.additive_only` now says what is refused (combining several values of a rate, average or per-capita measure)
  and carries a `recovery` (the reviewed recipe if one exists, else "pin every other dimension").
- `compare_periods` with `metric: percent` on a measure of unit type `percentage`, `rate` or `ratio` is refused
  (`unsupported_measure`, recovery "use metric absolute: the change is in percentage points"). A per-capita amount in
  currency still accepts `percent`. `absolute` is the change in points.
- CON103H_judete, 2022: top 5 = Municipiul București 209,362; Cluj 108,301; Timiș 94,170; Gorj 91,954; Constanța 86,065.
  Bottom 5 = Vaslui 30,377; Botoșani 31,902; Giurgiu 34,217; Călărași 37,792; Suceava 38,825. Same figures through the
  local MCP (`serve-mcp-test.sh`, :8090).
- Effect on other rates (measured): `FOM106E_judete` and `SOM103A_judete` still refuse when a dimension has no Total.
  The reason is now `missing_weights` (from the query) instead of `unsupported_measure`; the reviewed recipe stays the
  first recovery in both tools (`compare_periods` now adds it to the query's refusal, as the old gate did). The
  pinned corpus tests accept both reasons. `POP209B_judete` with RESIDENCE pinned (Urban) ranks.

## B. Reviewed concepts

Eight concepts added to `app/data/concepts.json`; coverage checked against the served generation by a corpus test.

| Concept | Family | Levels | Period | Note |
|---|---|---|---|---|
| `gdp_per_inhabitant` | CON103H | county, region, macroregion | 2000–2022 | NACE Rev.1 series (CON103B) named as not comparable |
| `gdp_regional` | CON103I | same | 2000–2022 | by branch: CON103J (to 2023) |
| `life_expectancy` | TCP0341 | same | 2008–2023 | by sex; no both-sexes and no national value in the download |
| `infant_mortality_rate` | POP209B | same | 2012–2024 | usual residence; urban/rural only, no Total |
| `infant_mortality_domicile` | POP209A | same | 1990–2024 | longer series; the alternative of the above |
| `dwellings_completed` | LOC104A | same | 1990–2025 | "Din care" rule: pin one source and one residence area |
| `pupils_by_education_level` | SCL103F | same | 1990–2024 | names the non-overlapping levels |
| `exports_annual` | EXP101G | national (EUR child) | 2006–2024 | sum of the 10 SITC sections |

EN aliases added to `gross_earnings` and `net_earnings` ("average gross monthly wage", "…salary", "…earnings",
"wage" as a generic of net). Sweep Q05 now finds the concept in EN.

Findings:
- `EXP101A` ("Export value - Total") holds only the row "Proprietate privata" in the download; its Total row is gone.
  It is not usable as the annual total. `EXP101G` (SITC sections, a complete partition) is: its yearly sums equal the
  yearly sums of the monthly `EXP101I` exactly (2013: 49,562; 2014: 52,466; 2015: 54,609; 2023: 93,094 million EUR).
  The result still carries `unverified_total`.
- Infant mortality: two concepts as for births, but only `infant_mortality_rate` has generic aliases, so a plain
  question does not ask for a choice. The domicile series is reached as its alternative (longer series warning).
- Life expectancy and infant mortality have no national value in the download (Total cells absent). The notes say so.
  Nothing is computed (that is sweep fix #7).
- `exports_annual` has no generic alias: "exporturi pe tari" must stay "no concept" (an existing judgment).

### County area (open, owner decision)

No source chosen. Candidates found:
1. `AGR101A` (land fund by usage, ha, county level, 1990–2014). The download holds only "Proprietate privata"
   (FORME_DE_PROPRIETATE has no Total), and the series ends in 2014. Not usable as total area.
2. `TAZ0221` (land registered in the land book, 2009–2023, thousand m²). It is registered land, not territory area.
3. `core-assets`: `data/geo/romania-counties.geojson` (county polygons, no area attribute), `judete.csv` (no area),
   `siruta-2025.csv` (no area). An area computed from the polygons would be approximate (simplified geometry) and
   not an INS figure.
4. External INS figure (Anuarul Statistic, area of the territory by county, km²). Not in TEMPO.

Recommendation: add a small reviewed reference table "county area, km²" (INS yearbook figures, with the year) to
`core-assets`, owned there, and let a concept read it. Do not derive it from simplified polygons for a ranking.

## D. Discovery messages

1. Own denominator: a matched concept whose name carries "pe locuitor / per capita / per inhabitant" drops the
   `denominator` constraint (`_own_denominator`). A denominator the concept lacks is still reported (test).
2. Filler words ("top", "daca poti", "mici", "many", "list", …) are added to the stop list of the family query.
3. No close match: warning code `no_close_match` (inside the contract, status stays `ok`) plus a `clarify`
   recovery, when no concept matched and no family title holds the longest content word and half of the content
   words (`_close_family`). When the family search finds nothing at all, the existing `no_match` warning applies
   (Q16 after the filler change).
4. Period outside the coverage: `longer_series_available` names the alternative whose series covers the asked years
   (with dataset code, coverage and a recovery to ask for it); "ultimii N ani" / "the last N years" is read
   (`intent.last_years`); with no longer series, `period_beyond_coverage` says so.
5. Density: searched first. Refused only when no family or concept name holds "densit"; the refusal offers the
   population ranking only. A city density question and a correlation question are still refused at once
   (messages without the tourism recipe). The tourism text stays for the tourism denominators.

Messages are in `messages.py` (RO and EN). Codes do not change with `lang`.

## E. Period bounds

`data_query.period_bounds` reads the first and last period from the parquet footer statistics when the footer proves
no NULL value (the AQ-07B check) and the period column is text; it counts periods from `dataset_coverage` when the
years agree (annual series) and else from one read of the period column. Otherwise it falls back to
`dimension_values`. `describe_dataset` and `dataset_facts` use it. `dimension_values` and its static-site twin are
unchanged, so `parity.mjs` is untouched.

Measured on the Mac, warm cache, POP107D (22.3M rows): `dataset_facts` 0.117 s → 0.04 s; the `dimension_values` call
in `describe_dataset` (0.02 s) is gone. The brief's cold figures (1.8–2.4 s) were not reproduced here: the cold-read
cost cannot be measured without clearing the OS cache. The footer read itself takes 5 ms. The rest of
`describe_dataset POP107D` (about 0.5 s) is dimension and policy work, not period bounds.
Corpus test: 40+ datasets (parents, split children, monthly, quarterly), `period_bounds` equals the scan and equals
`dimension_values(...)["period_bounds"]`.

## C. Sweep (20 questions, same method as the baseline; in-process `call_tool`, generation `be715608`)

Method note: the author acts as a careful model, as in the baseline. Per question: `discover_indicators` with the
full text, then the offered `next_call`, `recovery` or `choice`. Calls: baseline 70, now 56 (Q18 includes one
verification call).

| # | Baseline outcome (calls) | Now (calls) | Change |
|---|---|---|---|
| 01 | partial (9) | partial (4) | GDP top 5 and bottom 5 in 3 calls, no model sorting; the area half has no source (open) |
| 02 | answered (3) | answered (3) | none |
| 03 | answered (2) | answered (2) | none |
| 04 | answered, partial (4) | answered (3) | `longer_series_available` names domicile 1992+; a recovery asks for it; no guess |
| 05 | failed (5) | failed (3) | EN finds the concept; no all-activity Total cell exists, so no ranking |
| 06 | clarification, answered (2) | same (2) | none |
| 07 | answered after guess (5) | same (5) | none (fix #6 out of scope): Cluj-Napoca 328,108; Iași 390,832 |
| 08 | answered (2) | answered (2) | none |
| 09 | clarification, partial (3) | same (3) | none (fix #10 out of scope) |
| 10 | partial (4) | partial (3) | none in substance |
| 11 | failed (4) | partial (4) | a ranking per residence area works (Urban 2024: Suceava 12.2 first); no total across areas |
| 12 | failed (4) | failed (3) | concept found; only county, region by sex; no national value |
| 13 | answered after guess (5) | answered (4) | concept note names the non-overlapping levels; Iași liceal = 12,898 + 11,191 = 24,089 |
| 14 | answered (3) | answered (3) | the longer series is offered as a recovery, not guessed; Prahova −79,126 first |
| 15 | no data (2) | no data (1) | `no_close_match` warning, message says so |
| 16 | no data (1) | no data (1) | `no_match` (no unrelated families any more) |
| 17 | answered, probably wrong (5) | partial, safe (4) | no double count; the note says pin source and area; private+urban 2023: București 13,834 |
| 18 | partial (3) | answered (3) | annual totals 2006–2024 (sum of SITC sections); equals the monthly sums of EXP101I exactly |
| 19 | answered (2) | answered (2) | none |
| 20 | no data (2) | no data (1) | refusal offers the population ranking only |

Score: **9/20 answered correctly** (02, 03, 04, 07, 08, 13, 14, 18, 19) against **8/20** (the baseline's 8 plus Q18).
Q01, Q11 and Q17 are better but not counted (partial). Q06, Q09, Q10 still need a user choice or guess.
Why not more: Q05, Q10, Q11 and Q12 need INS Total cells that the download lacks (fix #7, owner decision); Q01 needs
a county area source; Q07 and Q09 are fixes #6 and #10 (out of scope).

DeepSeek question ("top 5 județe după PIB per capita, și pe suprafață"), scripted replay with the real tools:
discover (finds `gdp_per_inhabitant`, `next_call` = `rank_entities` CON103H_judete, top 5 desc), rank (ok), one
discover for the area (no area series). **3 dispatches.** The live run needed 6 `discover_indicators` calls and ended in
a refusal.

## Verification

- Targeted: `test_aq09_rates.py`, `test_aq09_period_bounds.py`, `test_aq09_concepts.py`, `test_aq09_discovery.py`.
- Search eval (`agent_eval.run_search_eval`): identical output with the old and the new `concepts.json`; the diff
  against `data/eval/agent_search_baseline.json` (17 top-set changes) is the same before and after my change, so it
  comes from the generation, not from this package. Baseline not rebuilt. Chart-selector eval not run: no chart code
  changed.
- Local MCP on :8090, `mcp_probe.py`: ok; CON103H ranking through the MCP returns the figures above.
- Full suite: see the final report of the session.

## Assumptions

- `measure` is binary (`additive` / `non_additive`) in `get_aggregation_context`; the gate now keys on `non_additive`.
- Tests marked `corpus` that are pinned to older generations (`062bd2b0`, `9b3e065d`) skip on `be715608`. I
  could not run them. `test_rate_refusals_route_to_the_published_recipe` now accepts `missing_weights` as well.
- "Closeness" of a family (`_close_family`) is a heuristic on title words (first five letters). It only adds a warning.
