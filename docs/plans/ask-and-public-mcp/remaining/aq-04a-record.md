# AQ-04A completion record: explicit, validated discovery defaults

Step 04A of [04-discovery-and-messages.md](04-discovery-and-messages.md) only. 04B (concrete
follow-up actions) and 04C (bilingual messages, caveats in the Ask page) are not started.
Implemented 2026-10-17 on branch `aq/04a-discovery-defaults`.

- Baseline: `ce472e9` (`fix/ask-answer-quality`, AT-05 + the remaining/ specs).
- Code commit: `16df903`. This record is added by the next commit; the code is unchanged by it.
- No corpus change, no baseline rebuild, no deployment, no provider call, no limit change,
  no new dependency. `answer_check.py` (AQ-03) is untouched.

## Status

| State | Result |
|---|---|
| Code-ready | Yes. Targeted + full suite pass; policy table pinned by tests |
| Validated on synthetic data | Yes, with the shipped concepts, policy and production dataset codes |
| Validated on a real corpus | Read-only, generation `9b3e065d2fe9bb1df9bae2131b7bdeae9be3426f3c82b9a9954f7e6dc8f45550` (copy `/Users/pax/devbox/gov2/tempo-gen-20261012/data`): discovery matrix, probes, corpus-marked tests, search and static parity |
| Model-validated (live provider, task fixtures) | `not_run`. No provider call was made; AQ-02 fixtures are not in this branch |
| Client-validated (hosted connector, browser) | `not_run`. No UI or client file changed |
| Deployed | No |

## What changed

| File | Change |
|---|---|
| `app/data/discovery_defaults.json` (new) | The reviewed mappings: population definitions and their naming terms, the generic default, the city ranking rule, the recipe route, and the clarify-only declaration for unemployment |
| `app/services/tools/discovery_policy.py` (new) | `load_policy` (validates shape at load, fails closed with `PolicyError`), `validate` (structure plus references to concepts, recipes and, optionally, corpus datasets/columns), `plan` (the one place that applies defaults, routes and refusals) |
| `app/services/tools/discovery.py` | `discover_indicators` takes its decisions from `plan`; unapplied-constraint reporting; the assumed-definition warning is only emitted for a default that produced a card |
| `app/services/tools/intent.py` | Vocabulary only: city plurals, `populate(d)`, top K forms, a bounded `constraints` list (sex, age, denominator). `explicit_population` is gone (now policy) |
| `app/services/tools/__init__.py` | Docstring mentions the new module |
| `tests/test_aq04a_discovery_defaults.py` (new) | 130 tests (129 run, 1 corpus probe) |

Not touched: `concepts.json`, `concept_search.py`, `recipes.json`, every static/JS file, `agent.py`,
`answer_check.py`, the tool schemas and the contract version (`tempo-tools/2`).

### Why a separate file instead of extending `concepts.json`

The spec prefers extending the concept catalogue. The existing tests (which must pass unchanged)
replace `CONCEPTS_PATH` with a synthetic catalogue, so a policy inside it would vanish in those
tests; and `concepts.json` is shipped to the static JS engine, so changing it would change the
static site and could not honour "raw concept search must not change". The policy references
concepts by id and is checked against the catalogue instead.

## Configuration

`app/data/discovery_defaults.json` (version 1):

| Key | Meaning |
|---|---|
| `population.definitions` | per definition: `terms` by which a question names it (a trailing `*` is any ending). A definition named by one of its specific catalogue aliases also counts |
| `population.default` | concept + folded `phrase` put in front of a generic population question (resident population) |
| `population.cities` | concept + `phrase`, the matched `alias`, `variants` (`locality`: `POP107D_grupe_localitate`), allowed `operations` (`rank` only), `entity_columns`, `entity_class` |
| `recipe_routes` | intent flag of `intent.interpret` -> recipe concept + phrase (`tourism_ratio` -> `tourism_intensity`) |
| `clarify_only` | concepts that must stay a clarification (generic unemployment). Validation rejects a default or route on them |

Validated at load: shape; levels and operations a level can serve (`SERVED`: a locality rule may
not claim `change` or `lookup`); unique non-time entity columns; `entity_class: cities` needs
`REF_AREA_2`; folded phrases; unique routes; clarify-only concepts without a default.
Validated against a catalogue (`validate(raw, concepts, recipe_ids=..., dataset_columns=...)`):
every concept exists, each phrase/alias is a specific alias of its concept (a generic alias is
rejected), a routed concept is a recipe concept whose recipe exists, locality datasets and entity
columns exist in a corpus. A rule whose concept is absent from the catalogue in use is inert.
`MAX_TOP_K = 100` equals `RankEntitiesArgs.top_k` (tested).

Additive contract fields (still `tempo-tools/2`): `interpretation.unapplied_constraints`
(`[{kind, text}]`), warning code `constraint_not_applied` (subject = kind), candidate note code
`constraint_not_applied`. Debug: `app.services.tools.discovery_policy` logs one `DEBUG` line per
decision (rule outcome and constraint kinds, never the question text).

## Policy table: preserved

Rows 1, 3, 5 and 6 are tests that also pass against the baseline code. Rows 2 and 4 pass there
for the Romanian wording and differ only where the next section lists it.

| Request | Behavior (unchanged) | Test |
|---|---|---|
| Generic population, county/region | resident default, `assumed_definition` warning, alternatives stay | `test_generic_population_is_resident_and_disclosed_with_alternatives`, `..._region_level` |
| Generic city population ranking | domicile default, disclosed; now also states what domicile counts | `test_generic_city_population_ranking_uses_domicile...` (message text differs from baseline; see below) |
| Explicit resident city population | unavailable, no substitution | `test_explicit_resident_or_july_city_population_is_unavailable_never_substituted` |
| Explicit domicile or July | respected, or unavailable at city level | `test_a_definition_named_in_the_question_...`, `test_explicit_domicile_city_population_is_respected` |
| Generic unemployment | `needs_clarification`, registered vs ILO, no default | `test_generic_unemployment_asks_registered_versus_ilo_and_assumes_nothing` |
| Stays per resident | `tourism_intensity` recipe, exact year/areas; other denominators unsupported | `test_stays_per_resident_reaches_the_reviewed_recipe...`, `..._other_denominators_...` |

## Behavior differences from the baseline (all deliberate, all reported)

Found by running a 75-question RO/EN matrix on the copied corpus before and after
(`ce472e9` snapshot vs this branch). 52 of 75 are identical apart from the additive
`unapplied_constraints: []`; 23 differ:

1. **Explicit definitions are not overwritten.** "registered population by county" and
   "mid-year population by county" used to get the resident default put in front, and a warning
   that resident was assumed while the domicile / July card came first. They now stay domicile / July
   with no assumption.
2. **English "domicile" at city level** ("top 10 cities by domicile population") was refused
   because the check looked for the substring `domicili`. It is respected now, as the policy says.
3. **Mixed explicit definitions at city level** (resident and domicile in one question) are
   unavailable; the baseline answered with domicile and dropped "resident". Design choice, see below.
4. **City ranking paraphrases.** "most populated cities", "cele mai populate 30 de orașe" were
   refused as "not population"; they are the generic city ranking. "orasele" / "municipiile" now read
   as cities, so "orasele care au pierdut populatie" is the documented unsupported city change
   (baseline: a county resident-population query) and "innoptari pe locuitor in orasele mari" is
   unavailable (baseline: the county recipe). A non-population city question gets its own message.
5. **Top K.** "largest 5 cities", "5 largest", "primele 10 orase" used K = 30; K is read.
   `top 0` is an explicit `invalid_input` (baseline: a null `next_call`). Above 100 unchanged.
6. **Unapplied constraints.** Sex, age, a non-recipe denominator and a county around a city ranking
   are reported (interpretation, one warning per kind, candidate note, message). No `query_data`,
   `rank_entities` or `run_recipe` call that ignores them is offered: a dataset candidate points at
   `describe_dataset`, a recipe candidate has no call. A constraint inside the matched concept's own
   alias ("population by age") is the concept and is not reported.
7. **Absent mappings.** A default whose concept is absent assumes nothing. A default whose source
   produced no card no longer warns "Definition assumed". An absent city concept, or a locality dataset
   missing from the generation, is `unavailable/level_unavailable` (baseline: county search results,
   or `no_match`).
8. **City disclosure text.** The `assumed_definition` warning for cities now includes the locality
   definition ("people with their legal address ...") and no longer claims that alternatives remain
   available. The `rank_entities` call is byte-identical to the baseline.

## Commands and results

Environment: `source ~/devbox/envs/240826/bin/activate`, Node 22.13.1, provider keys unset,
`PYTHONDONTWRITEBYTECODE=1`.

| Command | Result |
|---|---|
| `python -m pytest tests/test_at01_discovery.py tests/test_at05_quality.py -q -p no:cacheprovider` (unchanged files) | 59 passed, 10 skipped (baseline: 59 / 10) |
| `python -m pytest tests/test_aq04a_discovery_defaults.py -q -p no:cacheprovider` | 129 passed, 1 skipped (corpus probe) |
| `python -m pytest tests -q -p no:cacheprovider --tb=short` | **1307 passed, 74 skipped**, 7 existing FastAPI/openpyxl warnings, 0 failures (6 min 39 s) |
| `python -m pytest tests --collect-only -q` | baseline 1251 collected (1178 run + 73 skipped), branch 1381 (+130) |
| `TEMPO_DATA_DIR=<copy> python -m pytest tests/test_at01_discovery.py tests/test_at05_quality.py tests/test_aq04a_discovery_defaults.py -m corpus` | 11 passed (baseline files: 10 passed) |
| `pytest tests/test_static_parity.py` (synthetic) | 8 passed, 2 skipped (corpus) |
| `TEMPO_DATA_DIR=<copy> pytest tests/test_static_parity.py -m corpus` | 2 passed (static engine = server on a real sample, ~95 s) |

The 1,175 in the hand-off is the count before the three viewport regression tests that
AT-05 added later; the baseline collects 1,178 runnable tests.

Skips are the 73 corpus-marked tests (no corpus in the worktree) plus the new corpus probe on a
checkout without data. A skip is not a pass; the corpus-marked tests above were run on the copy.

### Do the new tests detect the old behavior?

The 93 behavior tests that do not need the policy module were run against the `ce472e9` source:
48 fail (the gaps listed above) and 45 pass (the preserved policy rows), so the file separates
"unchanged policy" from "hardening".

### Parity: raw concept search and the catalogue are unchanged

Method: `app.services.agent_eval.run_search_eval` over `data/eval/agent_questions.yaml` (the function
behind `tempo_eval_agent`) and `diff_against_baseline` against the committed baseline; the
catalogue's `GET /api/search` for all 17 questions x {ro, en} (full bodies, `generation` dropped);
`concept_search.match_concepts` for all 136 aliases/generic words. Same script, same copied corpus,
run once from an exported `ce472e9` tree and once from this branch (no baseline rebuilt):

- 17 questions x top 10, 34 API bodies, 136 alias cases: the two JSON files are byte-identical
  (sha256 `a325ff6df17bfe14...` both).
- The committed-baseline diff is the pre-existing drift already recorded in AT-05 (13 top-set and
  4 order changes) on both sides; not explained or rebuilt here.
- `concepts.json` and `concept_search.py` are not modified, and `test_catalogue_search_ignores_the_discovery_policy`
  shows `/api/search` is the same with the policy file valid or missing.
- The corpus copy was not modified: sizes, mtimes and the parquet listing hash were identical before
  and after (checked).

## Numerical examples

Synthetic (production dataset codes; resident 2023: Cluj 710, domicile 690, July 715):

- "population of Cluj in 2023" -> default resident -> `query_data` -> `[Cluj, 2023, 710.0]`.
- "overnight stays per resident in Cluj in 2023" -> `run_recipe` year `2023` -> `2130 / 710 = 3.0`;
  without a year the recipe answers its latest common year (2024).
- "top 3 cities by population" -> 2025: Cluj-Napoca 324,000; Iasi 290,000; Turda 55,000; the
  commune of 999,999 is excluded (`eligible_count` 4, `outside_class_count` 1). "in 2024": 320,000 first.

Real generation `9b3e065d` (read-only, `partial/unverified_total` as in AT-05):

- Cluj 2024: resident 693,413; domicile 744,031; population on 1 July 695,375.
- "cele mai populate 5 orașe" and "most populated 5 cities" produce the same `rank_entities` call:
  2026 Bucuresti 2,108,049; Iasi 370,437; Cluj-Napoca 324,860; Timisoara 292,819; Constanta 291,980
  (319 eligible cities, 2,862 outside the class). With "in 2025": Bucuresti 2,124,150 ... Constanta 295,767.
- "Câte înnoptări revin la un locuitor în Brașov, în 2025?" -> `2,751,439 / 560,277 = 4.910854809317534`.
- "populatia feminina Cluj 2024" -> default disclosed, sex reported, call = `describe_dataset POP105A_judete_grupe`.

## Decisions to review

1. Separate config file instead of `concepts.json` (above).
2. Mixed explicit definitions at city level are refused rather than silently dropping "resident".
3. Withholding the data call when a constraint is unapplied. It could instead be kept next to the
   warning; withholding was chosen because the figure would answer a different question.
4. The generic population default still applies at national level and with no level (baseline
   behavior: the county series is used and a `level_differs` note is attached). It is preserved, not
   endorsed; the policy table speaks only of county/region.
5. The sex/age/denominator vocabulary is a bounded heuristic; it errs towards reporting
   (e.g. "average age" reports an age constraint, which only matters when a concept card exists).
6. A county around a city ranking ("top 10 orase din Cluj") is reported, not applied. Applying a
   `REF_AREA` filter to `rank_entities` is possible (the locality file has the county in `REF_AREA`)
   but is a new capability, so it is left for a decision.
7. Noticed, unchanged: several years in one question ("2020 2024") pin only the last one in
   `concept_search.parse_query`. Changing it would change raw search.

## Rollback

`git revert 16df903` (and this record). No data, schema, contract-version or client change; the
configuration file is read per request (cached by mtime), so deleting it while the code is present
makes discovery fail closed (`execution_failed`), which is why they revert together.

## Remaining gates

- 04B and 04C (not started). Messages in `discovery_policy.py` and the new warnings are English
  only, like the existing discovery prose; 04C owns translation.
- Live-provider Ask run and AQ-02 task fixtures with these paraphrases: `not_run`.
- Whether Ask should also surface `constraint_not_applied` in the page table: 04C.
- Public-MCP admission for the national city ranking is unchanged (see AT-05).
