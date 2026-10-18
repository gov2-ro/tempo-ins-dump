# Discovery policy change record: a county narrows a city ranking; unemployment defaults by level

Two owner decisions of 2026-10-17, implemented in tool discovery only, as changes to the reviewed
AQ-04A configuration (`app/data/discovery_defaults.json`). They supersede the "generic unemployment: ask" row and the
"no new unemployment default" line of [04-discovery-and-messages.md](04-discovery-and-messages.md), and decision 6 of
[aq-04a-record.md](aq-04a-record.md) (a county around a city ranking is reported, not applied); those documents are left as written.
Implemented 2026-10-18 on branch `aq/discovery-county-unemployment`.

- Baseline: `9afa711` (`fix/ask-answer-quality`, AQ-01A ... 05A and their records).
- Code commit: `7e8e8ae`. This record is added by the next commit; the code is unchanged by it.
- No corpus change, no baseline rebuild, no deployment, no provider call, no limit change, no new dependency, no
  new tool. Contract stays `tempo-tools/2`; `concept_search.py`, `concepts.json`, `intent.py`, `period_changes.py`,
  `tools/changes.py`, `agent.py`, `routers/ask.py`, `ask.js`, `ask_present.py` and `answer_check.py` are untouched.

## Status

| State | Result |
|---|---|
| Code-ready | Yes. Targeted tests, the full suite (synthetic and on the copy), the AQ-02 runner and the catalogue-search parity pass |
| Validated on synthetic data | Yes: 127 new tests (124 run, 3 corpus-marked), twelve mutants of the new code all detected |
| Validated on a real corpus | Read-only, generation `9b3e065d2fe9bb1df9bae2131b7bdeae9be3426f3c82b9a9954f7e6dc8f45550` (copy `/Users/pax/devbox/gov2/tempo-gen-20261012/data`): the four owner probes and more, an independent DuckDB recomputation, the corpus-marked tests |
| Model-validated (live provider) | `not_run`. The AQ-02 runner replays scripted tool choices; it does not measure a model |
| Client-validated (browser, hosted connector) | `not_run`. No client file changed |
| Deployed | No |

## Decision 1: a county named in a city ranking narrows it to its cities

When exactly one county is named and it resolves to exactly one REF_AREA label of the locality series,
`discover_indicators` offers

    rank_entities  {dataset POP107D_grupe_localitate, entity_columns [REF_AREA, REF_AREA_2], entity_class cities,
                    filters {REF_AREA: [<exact label>]}, top_k, order, year}
    compare_periods (the AQ-05A city change) with the same filters

and discloses it with a `place_filter_applied` warning (subject: the exact label) and a note on each candidate that
carries it: "Cities in Cluj only: every eligible city of that county is ranked before the top K is cut, and the eligible and
outside-class counts are for that county alone." (RO: "Doar orașele din Cluj: ...", `messages.py`). The card's
`place_level_unavailable` note no longer applies and is dropped. The `assumed_definition` warning for the
domicile series is unchanged.

**No second mechanism.** The filter is the shared tools' own `filters`. `rank_entities` and `compare_periods` pass it to the one
validated query before the SIRUTA classification, eligibility, exclusions, ranks and top K, so `eligible_count`,
`outside_class_count` and `limits.total_rows` are within the county (tests call both tools directly:
`test_the_shared_tools_filter_before_eligibility_and_top_k`; filtering a national top K afterwards would return no Cluj
city at all).

| Question names | Result |
|---|---|
| one county with one exact label ("top 3 cities in Cluj", "orase din judetul Iasi") | narrowed; label is the series' own ("Iași", "Bistrita-Nasaud"), never the wording |
| two or more counties | reported as not applied (`geography`), call withheld (`describe_dataset`) |
| a county named like a city ("Cluj-Napoca", "orasul Cluj", "city Cluj") | reported (concept_search already flags it `city_not_county`) |
| **Bucharest ("Bucuresti", "Bucharest", "Municipiul București")** | **reported, never a filter (decision below)** |
| a county the series has no label for (Arad has a county series, no localities), or two labels for it, or a label list that cannot be read in full | reported, nothing guessed |
| a region or macroregion ("Nord-Vest", "regiunea Bucuresti-Ilfov") | reported (see "found on the way") |
| another unapplied constraint (sex, age, denominator) | the county is reported with it; no call is half-applied |
| no county | exactly as before (national ranking) |

**The Bucharest decision.** "București" is the name of a municipality and of the county-level unit "Municipiul București",
and that unit holds exactly one city (REF_AREA `Municipiul Bucuresti`: one locality, `179132 MUNICIPIUL BUCURESTI`).
Narrowing to it would answer a one-row ranking for a question that most likely means something else (the sectors, the
area around the capital), and picking a reading silently is what the owner ruled out. So the name is reported as not applied
exactly like "Cluj-Napoca". It is one configuration line: `place_filter.except` lists county slugs that are never used as a filter
(`["municipiul-bucuresti"]`). With `except: []` the same question offers `filters {REF_AREA: ["Municipiul București"]}` and ranks one city
(tested). "Ilfov" is an ordinary county (8 cities).

**Found on the way: a region around a city ranking was dropped without a word.** The baseline offered the national
`rank_entities` call for "top 5 cities in the Nord-Vest region" with no constraint reported, because `concept_search` parses
counties only. The owner's decision says a region "stays reported as not applied", so it is now reported: region and
macroregion names are read from `dimension_options_parsed` (`discovery_policy.read_geography`, 1 ms) and a region name is removed
from the text before counties are read (so "Bucuresti-Ilfov" is one region, not two counties). A name that is neither a county nor a
region ("orase din Turda") is still ignored; the same gap existed before and is listed under open points.

### Configuration

`population.cities.place_filter = {"level": "county", "column": "REF_AREA", "except": ["municipiul-bucuresti"]}`. Validated at load: level is
`county`; the column is one of `entity_columns`; `except` is a list of slugs; the city rule has the `rank` operation and `entity_class: cities`.
Rollback is removing the key: the geography is reported again and the data call withheld (tested for both tools).

## Decision 2: the generic unemployment rate defaults by level

`clarify_only` is replaced by `level_defaults`:

    {"topic": "unemployment",
     "definitions": {"registered_unemployment_rate": {"terms": ["inregistrat*", "registered", "anofm"], "phrase": "rata somajului inregistrat"},
                     "ilo_unemployment_rate": {"terms": ["bim", "ilo", "amigo", "lfs", "survey"], "phrase": "rata somajului bim"}},
     "levels": {"county": "registered_unemployment_rate", "national": "ilo_unemployment_rate"},
     "no_level": "clarify"}

| The question points at | Result |
|---|---|
| a county (named, or "pe județe" / "by county"), also "in Cluj, Romania" | registered; `assumed_definition` warning: "Definition assumed: Registered unemployment rate, taking the question at the county level. ILO unemployment rate (survey) has no county-level series in the reviewed catalogue (it covers: national, region). ..." |
| the nation ("România", "national", "la nivel național", "nationwide", "pe țară") | ILO; warning says "Registered unemployment rate has no national-level series in the reviewed catalogue (it covers: county, region, macroregion)" |
| a region or macroregion (by name or word) | clarification (registered vs ILO), unchanged |
| a county and a region together, or other mixed levels | clarification |
| **no place and no level word** ("somaj", "rata somajului 2023") | **clarification** (`no_level: clarify`; see "decisions to review") |
| a definition named by the question | respected, never replaced; naming both leaves the question to the user |

* The sentence is built from the catalogue (the other definition's level variants), so it cannot go stale. Both languages are in
  `messages.py` (`discover.assumed_level`, `discover.level_missing`, `discover.level_*`), in one block after `discover.assumed`.
* A named county or region is more specific than the country; two sub-national levels at once are ambiguous.
* **Explicit definitions.** A definition counts as named when the question carries one of its `terms`, in either language. The county-level aliases of
  the registered concept ("rata somajului pe judete", "unemployment by county", ...) carry none of them on purpose, so they are
  defaulted and disclosed instead of silently respected (a test pins that these six aliases are the only specific aliases without a term). A
  definition named by a term only ("rata somajului dupa ILO", "ANOFM", "AMIGO") used to ask which definition was meant
  (checked on the baseline tree); the policy now puts that definition's phrase in front, so the explicit wording is honoured.
* **One assumption per question.** A question that already gets the population default, a city series or the stays recipe is not given
  a second default.
* **Catalogue guard.** A default is applied only when the concept is in the catalogue in use, serves the level (`validate` checks
  the same against `concepts.json`) and its phrase is a specific alias there; otherwise it is inert and the question is asked.
* Validated at load and against the catalogue: at least two definitions, folded terms and phrases, levels in `{county, region, national}` that
  name a definition, `no_level` is `clarify` or one of the levels, no concept shared with another rule, every concept and phrase exists, every
  level exists in the concept's variants (a region level is served by a region or macroregion variant).
* Rollback: `level_defaults: []` restores the clarification (tested for county and national questions; explicit definitions never needed the rule).
  A single level can be dropped (`levels` without `national`, tested).

### Verified before applying the national rule

The instruction was to check that no national registered series exists in `concepts.json` or its variants, and to keep the clarification
at national level if one does. **None does** (registered: county, region, macroregion; ILO: national, region), so the rule is applied. But
a national registered rate does exist in the corpus outside the catalogue, and it matters to the owner's wording ("registered is not
available nationally in this corpus"):

* `published_totals` (metadata DB) holds INS's published SOM103A Total cell for `ref_area = 'TOTAL'`, 1991-2025: 2022 3.0, **2023 2.9**, 2024 3.3, 2025 3.3 (%).
* Nothing serves it: `SOM103A_*` parquets have counties, regions and macroregions only, no `concepts.json` variant is national, and
  `run_recipe registered_unemployment_county` reports `TOTAL` and `Romania` as `not_in_data`.

The warning therefore says "in the reviewed catalogue", not "in this data". If the owner prefers the clarification at national level, or wants
the published cell served by a recipe first, the change is one line (`levels` without `national`) or a separate recipe step.

### The national default does not reach a single figure

`AMG157A_anual` (the ILO national variant, 1996-2024) holds 12 five-year age bands by sex and no total; the all-ages series are other
matrices (`AMG157C_anual` "15 ani si peste", `AMG159A_anual` "15-74 ani") and none has a both-sexes row. Discovery therefore answers "rata somajului în
România 2023" with the ILO card and `describe_dataset AMG157A_anual` (`aggregation_unavailable`, a rate is not summed), the same card an explicit
ILO question gets today. The default is honest about the definition but the model still has to choose age band and sex to read a number.

## Decisions to review

1. **No place and no level word still asks.** The owner text lists "national level (no place, or România/national)" and also "level unknown/ambiguous ->
   keep the clarification". Read literally, "no place" would make a bare "rata somajului" national. The shipped reading is the cautious
   one: a question that points at no level has an unknown level, so it asks (and the four bare-question assertions of AQ-04A stay as they were).
   `no_level: "national"` flips it (tested: bare questions then default to ILO, disclosed; a region or two levels still ask).
2. **Term-only explicit definitions are routed, not only left alone** (above). It is a behaviour change from the baseline for "rata somajului dupa ILO".
3. **Region report** for city rankings (above) is a fix of a silent drop, within the intent of the decision.
4. **`place_filter_applied` is not in `ask_present.QUALIFYING_DISCOVERY`.** The county is the user's own wording, not an assumed definition, so the Ask page does not
   retain it; the result's table shows the REF_AREA column. `assumed_definition` (including the new level wording) is retained as before.
5. **The English prompt of X06 changed** (below): discovery reads "recent" as the latest period, so "evolved in recent years" returns one year.
   That is separate from the definition and was not changed.
6. `04-discovery-and-messages.md` and AGENTS.md still describe the old policy; they were not edited (shared docs).

## What changed

| File | Change |
|---|---|
| `app/data/discovery_defaults.json` | `population.cities.place_filter`; `clarify_only` replaced by `level_defaults`; the `about` text |
| `app/services/tools/discovery_policy.py` | `Geography`/`read_geography` (counties, regions, levels), `county_filter`, `_level_default`, `serves_level`; validation of both rules; `plan(..., geo=)` |
| `app/services/tools/discovery.py` | reads the geography once; `_place_filter` (label from the locality series), the county in the `rank_entities` and `compare_periods` calls, `_disclose_place_filter`, `_level_warning`; the region report |
| `app/services/tools/messages.py` | one block after `discover.assumed`: `discover.place_filter`, `discover.assumed_level`, `discover.level_missing`, `discover.level_{county,region,macroregion,national}` (RO and EN) |
| `tests/test_aq_discovery_county_unemployment.py` (new) | 127 tests (124 synthetic, 3 corpus-marked) |
| existing tests, `tests/aq02_env.py`, `data/eval/ask_tasks.json` | see the next two sections |

## Changed expectations (every one, with the reason)

| File / test | Change | Reason |
|---|---|---|
| `test_aq04a` `test_the_reviewed_table_is_pinned_in_the_configuration` | the pin of `clarify_only == [unemployment]` became pins of `level_defaults` (levels, `no_level`, definitions) and of `place_filter`; the "no default for unemployment concepts" assertion stays as "not a target of the population default, city rule or route" | the configuration key and the policy it pinned are the ones the owner changed |
| `test_aq04a` structural cases `clarify_only with a default`, `clarify_only without concepts` | replaced by `level_defaults with a population default`, `level_defaults without definitions` | same checks on the renamed key |
| `test_aq04a` reference case `clarify_only concept unknown` | replaced by `level_defaults concept unknown` | same |
| `test_aq04a` `test_a_county_around_a_city_ranking_is_reported_not_silently_dropped` | renamed `test_without_a_place_filter_...`; it now runs under a configuration without `place_filter`; assertions unchanged | the shipped policy narrows; this is the rollback test |
| `test_aq05a_city_change_discovery` `test_an_unapplied_constraint_withholds_the_change_call` | runs under a configuration without `place_filter`; the sex case and the assertions are unchanged | same |
| `test_aq04b` `test_corpus_choices_agree_with_their_cards_and_the_census_break_is_flagged` (corpus) | the ILO and registered choices of "somaj Cluj 2019" are read under `level_defaults: []` | the question no longer clarifies; the assertions about the choices are unchanged |
| `tests/aq02_env.py` | the fixture catalogue's two unemployment concepts gain the aliases `rata somajului inregistrat` and `rata somajului bim` | the shipped `concepts.json` has them and the rule's phrases must be aliases (inert otherwise); the fixture was missing two real aliases |
| `test_aq02_tasks.py` oracle | entries for `T02B` (Cluj 2020, 2021) and `X06B` (ILO 2020, 2021) | the new expected numbers are recomputed from raw cells |
| `test_aq04c_messages.py` | seven questions added to the RO/EN parity list (additive) | the new texts are checked for identical structure and localized prose |

Unchanged and still passing: `test_generic_unemployment_asks_registered_versus_ilo_and_assumes_nothing` (bare questions), all population, city
ranking, city change, stays, constraint, absent-mapping and catalogue-search tests of AQ-04A/05A/04B/04C and AT-01/AT-05.

## AQ-02 task file (`data/eval/ask_tasks.json`)

| Task | Change | Reason |
|---|---|---|
| T02B "unemployment rate in Cluj" | expects the registered default: `assumed_definition = registered_unemployment_rate`, then `query_data UNEMR` Cluj 3.0 (2020), 2.5 (2021), the ILO national figures forbidden, the answer states the assumption, the definition and that ILO has no county series | county level (decision 2); it asked before |
| X06 "unemployment rate in Romania" | one turn: ILO default, then `query_data UNEMI` 6.1 (2020), 5.6 (2021), registered figures forbidden; English prompt "over the last few years" (was "in recent years") | national level (decision 2); "recent" is read as the latest period in English only |
| X06B (new) | the previous X06: "What is the unemployment rate?" asks first, "The ILO definition." is then honoured (`somaj bim Romania`) | keeps the ask-first flow for the case that still asks |

Runner (`scripts/eval-ask-tasks.py --quiet`, `TEMPO_DATA_DIR` = the copy): baseline `9afa711` 142 executed, 142 passed; now **144 executed, 144 passed** (the two
added executions are X06B ro/en); negative controls unchanged: total 42, detected 30, known limitation 2, resolved 10, mismatch 0; hard failures 2 (the same two); verdict
`blocked_by_known_limitations` as before.

## Commands and results

Environment: `source ~/devbox/envs/240826/bin/activate`, Node 22.13.1 on PATH, `PYTHONDONTWRITEBYTECODE=1`, provider keys unset. The machine was busy with sibling worktrees.

| Command | Result |
|---|---|
| `pytest tests/test_aq_discovery_county_unemployment.py` | 124 passed, 3 skipped (corpus) |
| same with `TEMPO_DATA_DIR=<copy>` | 127 passed |
| the new file copied into the exported `9afa711` tree | 78 failed, 46 passed, 3 skipped: the failures are the new behaviour; the passes are the unchanged rows |
| `pytest tests -q` (no corpus) | **1943 passed, 88 skipped**, 7 existing FastAPI/openpyxl warnings (baseline 1812 / 85: +131 passed, +3 skipped = the 134 new test cases) |
| `TEMPO_DATA_DIR=<copy> pytest tests -q -rs` | **2030 passed, 1 skipped** (the AQ-03 endpoint-swap skip, as in the baseline); baseline 1896 / 1 |
| (first corpus run, started while the synthetic suite ran) | 2008 passed, 22 skipped, 1 failed: `test_aq01_benchmark.py::test_a_child_that_never_starts_listening...` (it uses the fixed port 8111; the other suite was running, which is the probable cause) and 21 skips more than the clean run, whose reasons were not captured (no `-rs`). Alone, that test file passes (51/51) and the isolated full rerun above is clean. Not related to this change |
| `pytest tests/test_static_parity.py` | 8 passed, 2 skipped (corpus), inside the full runs |
| `scripts/eval-ask-tasks.py --quiet --report-dir <scratch>/runner` | 144 / 144, controls 30 / 2 / 0 |

### Do the new tests detect a wrong implementation?

Twelve mutants of the new code, each run against the new file and the 05A discovery tests (baseline for the pair: 150 passed, 3 skipped); the thirteenth form of the `no_level` mutant was run on the unemployment and AQ-04A tests only:

| Mutant | Failing tests |
|---|---|
| county filter dropped from the `rank_entities` call | 8 |
| county filter dropped from the `compare_periods` call | 1 |
| explicit definitions overwritten by the level default | 14 |
| Bucharest not excepted | 5 |
| a city's name ("Cluj-Napoca") used as the county | 5 |
| regions never read | 10 |
| an unspecified level treated as national whatever the configuration | 10 (selected tests, see above) |
| the nation outranks a named county | 3 |
| two counties both applied | 1 |
| an unresolved label guessed from the wording | 4 |
| another unapplied constraint ignored when narrowing | 2 |
| a county default used for any unlisted level (region) | 8 |

(One mutant, `unspecified -> no_level` unconditionally, is equivalent while `no_level` is `clarify` and did not change behaviour; the stronger form above was detected.)

### Parity: catalogue search is unchanged

Same method as AQ-04A/04B (`agent_eval.run_search_eval` over `data/eval/agent_questions.yaml` and the committed-baseline diff, `GET /api/search` for 17 questions x {ro, en}
without `generation`, `concept_search.match_concepts` for 136 aliases and generic words), same copied corpus, run once from an export of `9afa711` and once from this branch:
17 questions, 34 API bodies, 136 alias cases; the two JSON files are **byte-identical** (file sha256 `b94d7777d994...`, comparison hash of the three sections `e381411a414c...`, the values the
04B record gives). `concept_search.py` and `concepts.json` are not modified. The corpus copy was not written to by any of this.

## Real generation `9b3e065d` (read-only), exact numbers

Cities of a county (`rank_entities`, cities, domicile series, year defaults to the latest, 2026):

| Question | Result |
|---|---|
| "top 5 orașe din Cluj" (as written, no measure) | unavailable `level_unavailable`, unchanged: a city question needs "populație" (the measure is not assumed) |
| "top 5 orase din Cluj dupa populatie" | call `filters {REF_AREA: ["Cluj"]}`, year 2026: 1 Cluj-Napoca 324,860; 2 Turda 51,377; 3 Dej 35,981; 4 Câmpia Turzii 25,468; 5 Gherla 21,677. `eligible_count` 6, `outside_class_count` 75, status `partial/unverified_total` as for the national ranking |
| "top 5 cities in Cluj by population in 2025" | 325,408; 51,846; 36,168; 25,715; 21,740 (same six eligible, 75 communes) |
| "top 3 cities in Bihor" | Oradea 212,775; Salonta 17,788; Marghita 16,304; 10 eligible, 91 outside the class |
| "top 10 cities in Ilfov in 2024" | Voluntari 47,428; Popești-Leordeni 47,171; Bragadiru 34,669; Pantelimon 32,143; Buftea 23,311; Otopeni 21,869; Chitila 16,231; Măgurele 13,512; 8 eligible, 32 outside |
| "top 3 cities in Cluj by population growth between 2020 and 2025" | `compare_periods` with the same filter: all six cities declined; best Huedin -456, Gherla -1,137, Câmpia Turzii -1,627; 6 eligible, 75 outside |
| national "top 5 cities by population" (unchanged) | București 2,108,049; Iași 370,437; Cluj-Napoca 324,860; Timișoara 292,819; Constanța 291,980; 319 eligible, 2,862 outside |
| Cluj and Bihor / Cluj-Napoca / București / Nord-Vest region / regiunea București-Ilfov | each reported as `geography` not applied, `describe_dataset` offered ("Regiunea Nord-Vest", "Regiunea Bucuresti-Ilfov" as one region) |

Independent check (plain DuckDB over the parquet, and the GOS102A catalogue for the class): Cluj county has 81 localities in 2026, Cluj-Napoca 324,860 and the five values above are the sums over AGE and
SEX; Bihor has 10 catalogue cities and 91 other localities and the same five-row top.

Unemployment (`discover_indicators`):

| Question | Result |
|---|---|
| "rata șomajului în Cluj 2023" | registered default; `run_recipe registered_unemployment_county` 2023 Cluj = **1.2** (the INS published cell, `published_totals`) |
| "rata șomajului în România 2023" | ILO default, `describe_dataset AMG157A_anual` (age bands by sex, no total); the registered national published cell is 2.9 (2023) but is not served |
| "unemployment rate Nord-Vest 2023" | clarification, registered vs ILO, no assumption |
| "unemployment rate by county 2023" | registered default, `run_recipe` all 42 counties (Vaslui 7.9, Teleorman 7.5, Dolj 7.3, Mehedinți 7.0, ...) |
| "rata somajului" | clarification |
| "rata somajului BIM in Cluj 2023" | ILO named: not replaced; `describe_dataset AMG157A_anual` with the existing county-level notes |

## Rollback

`git revert 7e8e8ae` (and this record). Or by configuration, without code: delete `population.cities.place_filter` (the county is reported again) and/or set
`level_defaults` to `[]` (unemployment asks again); one level is dropped by removing it from `levels`. No data, schema, contract-version or client change; the configuration
file is read per request (cached by mtime).

## Open points

- Unknown place names around a city ranking ("orase din Turda") are ignored without a word, as before; only counties and regions are read.
- The ILO national default needs an age band and a sex to give a number; a both-sexes, all-ages ILO cell is not in the downloaded series.
- The registered national rate (published cell `TOTAL`, 2.9 in 2023) is in the corpus but not served: the owner may want a recipe for it, after which the national default should be reconsidered.
- English "recent"/"current" are read as the latest period by `concept_search`; a "trend in recent years" question gets one year. Raw search is out of scope here.
- Live-provider Ask run with these paraphrases: `not_run`.

## Follow-up — 2026-10-18: national level keeps the clarification (owner)

The national ILO default gave no single figure (AMG157A_anual has age bands by sex, no all-ages
total) and the national registered rate is only a `published_totals` cell. `level_defaults`
now maps `county` only; national, region and unknown levels ask. The national mechanism stays
tested under a policy that restores it (`with_national`). AQ-02 X06 is back to its two-turn
flow (ask, then the chosen ILO definition is honoured); X06B keeps the no-level case. Runner on
the copy: 144/144, controls 30/2/0. Rollback: add `"national": "ilo_unemployment_rate"` back.
