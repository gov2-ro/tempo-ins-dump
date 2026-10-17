# AQ-04B completion record: concrete follow-up actions without bypassing clarification

Step 04B of [04-discovery-and-messages.md](04-discovery-and-messages.md) only. 04A is the baseline and
is unchanged (its tests pass untouched); 04C (bilingual messages, caveats in the Ask page) is not started.
Implemented 2026-10-17 on branch `aq/04b-follow-up-actions`.

- Baseline: `955d81f` (`fix/ask-answer-quality` after the AQ-04A merge).
- Code commit: `8b41dd4`. This record is added by the next commit; the code is unchanged by it.
- No corpus change, no baseline rebuild, no deployment, no provider call, no limit change, no new
  dependency, no new tool. Contract stays `tempo-tools/2`; every change below is an additive field.
  `answer_check.py`, `changes.py`, `period_changes.py`, `ranking.py`, `schemas.py`, `change_evidence.py`,
  `links.py`, `ask_context.py`, `discovery_policy.py` and `discovery_defaults.json` are untouched.

## Status

| State | Result |
|---|---|
| Code-ready | Yes. Targeted and full suite pass (numbers below) |
| Validated on synthetic data | Yes: an acceptance walk executes every advertised call (RO and EN, 24 questions) |
| Validated on a real corpus | Read-only, generation `9b3e065d2fe9bb1df9bae2131b7bdeae9be3426f3c82b9a9954f7e6dc8f45550` (copy `/Users/pax/devbox/gov2/tempo-gen-20261012/data`): the whole suite (1,420 passed, none skipped, so every corpus-marked test ran), probes, search parity |
| Model-validated (live provider, task fixtures) | `not_run`. No provider call; AQ-02 fixtures are not in this branch |
| Client-validated (hosted connector, browser) | `not_run`. No UI or client file changed |
| Deployed | No |

## What changed

| File | Change |
|---|---|
| `app/services/tools/discovery.py` | choices carry a validated `action`; recipe candidates carry `area_lookup` and resolve places to exact labels; candidates, the headline and `describe_dataset` carry known series breaks; the clarification message says to ask first |
| `app/services/tools/recipe.py` | `run_recipe` offers a `find_dimension_values` label lookup for an area the source has no label for; `area_dataset` and `lookup_query` helpers |
| `app/services/tools/contract.py` | `envelope()` adds `series_break` warnings and `provenance.series_breaks` to a `query_data` result whose selected periods straddle a recorded break |
| `app/services/dataset_notes.py` | `series_breaks(code, ...)`: the recorded breaks that lie inside a selection |
| `tests/test_aq04b_follow_up_actions.py` (new) | 39 tests: 32 synthetic (the acceptance walk, choices, recipe areas, series breaks, budget) and 7 corpus-marked |

### Additive contract fields

| Where | Field | Meaning |
|---|---|---|
| `data.choices[]` (definition and place choices) | `action` | the validated call to run **after the user has picked** that choice: `query_data`, `rank_entities`, `run_recipe`, `describe_dataset` or a `find_dimension_values` period/area lookup; `null` when none is safe |
| | `action_status` | `ready` (complete, run it), `needs_clarification` (more interpretation: another ambiguity, or the named place cannot be applied at the picked definition's levels; only the restatement is offered), `unavailable` (cannot answer; the notes say why) |
| | `action_notes[]` | `{code, message, subject?}`, at most 4: the qualifications of the action (`series_break`, `constraint_not_applied`, `period_unavailable`, `period_not_single`) or the reason there is no action (`place_level_unavailable`, `level_differs`, `place_not_in_dataset`, `ambiguous_place`, `no_call`, `no_specific_wording`, `resolution_failed`) |
| | `recipe` | now the recipe of the card the choice leads to (an action `run_recipe` always agrees with it). Was the concept's own `recipe` only, so a concept routed to a reviewed total (`net_earnings` -> `net_earnings_county`) said `null` |
| | `dataset` | the dataset of a `query_data`/`rank_entities`/`describe_dataset` action |
| `data.concepts[].alternatives[]` | `recipe` | same rule (own recipe, else reviewed total route) |
| `data.concepts[].candidates[]` | `series_breaks[]` | recorded breaks inside the selection of that candidate's data call (`[]` = none recorded) |
| recipe candidates | `area_lookup` | `find_dimension_values` on the recipe's area dataset, `column REF_AREA`; with a named place its query |
| `data.series_breaks[]` (`describe_dataset`) | | recorded breaks inside the data the dataset holds |
| `provenance.series_breaks[]` (`query_data`) | `{id, dataset, between, areas?, continues?, continued_by?}` | machine-readable form of the warning below |
| warnings | `series_break`, subject = the note id | message = the note text in the request language. Same code and subject as `compare_periods` already uses, so 04C can deduplicate by code and subject |
| `run_recipe` recovery | `find_dimension_values` on the area dataset | for each (at most two) area reported `not_in_data`; after the existing "run for every area" step |

`choices[].next_call` is **unchanged**: still a `discover_indicators` restatement that returns the picked
concept's card. Only `action` is new (see decision 1).

## How the pieces work

**Choices (`_resolve_choice`).** The choice's restated question is run through `discover_indicators`
itself, one level deep (`limit=1`; nested clarifications are not resolved again), and the picked concept's
card is read back. `action` is that card's own `next_call` (or, for a card with no headline because a
constraint was withheld, its first candidate's `describe_dataset`), so a choice, the card it leads to and the
call that card makes cannot disagree. A named place that the picked definition cannot honour
(`place_level_unavailable`, `level_differs`, `place_not_in_dataset`) leaves `action` `null`, so no action
silently widens the place; a second ambiguity (a city next to a generic word) leaves the restatement as the
only call. Cards and candidates of a clarification still carry no call and no preferred candidate.

**Recipe areas.** `run_recipe` matches `areas` by `recipes.geo_id(label)` (accents, case, spacing). A
discovery recipe candidate now lists the area dataset's labels once (denominator of a reconstructed ratio,
first source otherwise, `recipe.area_dataset`), passes each named place as the exact source label, and
reports a place with no label (`place_not_in_dataset`). If every named place lacks one the candidate's call
is the label lookup, not a doomed run; if only some do, the run goes ahead and the recipe excludes the others
`not_in_data` with a lookup recovery. `lookup_query` chooses what to search for ("Cluj-Napoca" finds `Cluj`
because a label contains it); the lookup lists labels and never picks one.

**Series breaks.** `dataset_notes.series_breaks` returns a public `series_break` note when the selection
has data on both sides of `data.between` (pinned periods, else the span of the data it reaches; no
information at all -> not ruled out), and for an area-specific note only when the selected areas overlap.
Surfaced on: `query_data` results (envelope), `describe_dataset`, the candidate whose final data call
selects the periods (not a lookup, not a ranking year), the headline warnings of an `ok` discovery, and the
`action_notes` of a choice. `compare_periods` keeps its own handling; `rank_entities` and `run_recipe`
select one period. A dataset with no note has **unknown** continuity: the result is "none recorded"
(`series_breaks: []`, no warning, and nothing in the payload says stable or continuous).

## Decisions to review

1. **`action` is a new field; `next_call` was not changed.** The AQ-04A and AT-01 tests (which must pass
   unchanged) run a choice's `next_call` and expect a discover card. Replacing it would also be a breaking
   semantic change of an existing field, which the remaining/ README reserves for a versioned change.
   The cost is two calls per choice on the wire. If the orchestrator prefers `next_call` itself to become the
   concrete call, it is a small change plus those tests, and a contract note.
2. **Restating through discover to resolve a choice** (rather than rebuilding a card) guarantees agreement by
   construction and does not touch the ranking/withholding code that AQ-05A may also edit. Cost: a
   clarification runs the search up to 1 + (choices) times. Warm timings on the copied corpus, median of 5:
   `somaj` 16 -> 72 ms, `turism` 16 -> 49 ms, `salariu mediu Cluj 2023` 35 -> 117 ms, `Cluj-Napoca populatie`
   31 -> 81 ms; the non-clarification path is unchanged (`populatie Cluj 2019` 36 -> 37 ms).
3. **`level_differs` at card level is untouched.** A non-clarification card (e.g. the ILO series for a named
   county) still headlines a national `query_data` with `place_level_unavailable` and `level_differs` notes
   (AQ-04A decision 4; existing tests rely on it). Choices are stricter: they offer no action there.
4. **Series-break warnings on `query_data` are produced in `contract.envelope`** (tool == `query_data`
   only) so `query.py` is untouched. A selection of the whole series warns even when the user only looks at
   one side; that is deliberate (a break "cannot be ruled out").
5. **Partial place match runs.** "Cluj and Bihor" with Bihor missing from the recipe source still offers
   `run_recipe` for both; the recipe excludes Bihor (`not_in_data`) with a lookup recovery. Diverting to a
   lookup was kept for the case where nothing is left to run.

## Area identity: what a lookup cannot do (documented, no tool added)

The lookup lists the exact labels of one source dataset. It does not know that "Cluj-Napoca" is a city inside
county "Cluj", that an English or short name ("Bucharest", "Bucuresti") is "Municipiul București", or that two
sources label the same area differently: the recipe compares `geo_id(label)` only. Those mappings (and a
stable area key such as SIRUTA/NUTS across datasets) would be a new area-identity contract with its own review;
none is invented here. Until then the model must show the user the listed labels and let them choose.

## Validation

All with `source ~/devbox/envs/240826/bin/activate`, `PYTHONDONTWRITEBYTECODE=1`, provider keys unset.

| Command | Result |
|---|---|
| `python -m pytest tests/test_aq04b_follow_up_actions.py -q -p no:cacheprovider --tb=short` | 32 passed, 7 skipped (the 7 corpus-marked ones) |
| same, with `TEMPO_DATA_DIR=/Users/pax/devbox/gov2/tempo-gen-20261012/data -m corpus` | 7 passed |
| `python -m pytest tests/test_at01_discovery.py tests/test_aq04a_discovery_defaults.py tests/test_at01_recipes_links.py -q ...` (files unchanged by this step) | passed (`git diff 955d81f --stat` touches no existing test) |
| `python -m pytest tests -q -p no:cacheprovider --tb=short` | **1,339 passed, 81 skipped** (the 74 corpus-marked of the baseline plus this step's 7), 6 min 42 s, exit 0 |
| full suite with `TEMPO_DATA_DIR=/Users/pax/devbox/gov2/tempo-gen-20261012/data`, provider keys unset | **1,420 passed, 0 skipped**, 8 min 15 s, exit 0 |

Baseline for comparison: `955d81f` has 1,307 passed / 74 skipped; this step adds 39 tests, 7 of them
corpus-marked (skipped, not passed, on a checkout without data). Seven existing FastAPI/openpyxl/lxml
warnings are unchanged. One existing test
(`test_nothing_ranked_is_unavailable_and_keeps_the_reasons`) failed on the first full run because the new label
lookup shifted the recovery order; the code was changed to keep "run the recipe for every area" first, not the
assertion.

### Do the new tests detect the old behavior?

The new file was run against an export of `955d81f`: 29 of 32 fail (the missing `action`, `area_lookup`,
`series_breaks`, lookup recoveries, and `dataset_notes.series_breaks`), and the 3 that pass assert
behaviour that is preserved (the partial-source exclusion, a recipe year outside the sources, and the
unchanged `rank_entities`/`compare_periods` series-break handling).

### The acceptance walk

`test_every_advertised_call_validates_and_executes` runs 24 RO/EN questions (generic words, cities, years that
are absent, recipes, a place a recipe source lacks, unapplied constraints, ranking, series breaks). Every
`next_call`, `lookup`, `area_lookup`, `action` and `tool_call` recovery in each result (and, two levels down,
in the results of the discover calls among them) must pass `registry.precheck` (the registry schema) and
execute with `status` in ok/partial/needs_clarification/unavailable and a `reason` that is not
`invalid_input`, `unknown_*` or `execution_failed`. It also asserts that every action tool was executed
(`discover_indicators`, `describe_dataset`, `find_dimension_values`, `query_data`, `run_recipe`,
`rank_entities`) and every `action_status` was met.

### Parity: catalogue search is unchanged

Method (the one AQ-04A used): `agent_eval.run_search_eval` over `data/eval/agent_questions.yaml` and its
`diff_against_baseline`; `GET /api/search` for all 17 questions x {ro, en} (full bodies, `generation` dropped);
`concept_search.match_concepts` for all 136 aliases and generic words. The same script
(`.worktrees/aq-reports/aq04b/parity.py`), the same copied corpus, run once from an export of `955d81f` and once
from this branch (no baseline rebuilt): 17 questions, 34 API bodies, 136 alias cases, the two JSON outputs are
**byte-identical** (sha256 `b94d7777d994...` both; the comparison hash of the three sections `e381411a414c...`).
The committed-baseline diff is the pre-existing drift AQ-04A and AT-05 recorded (13 top-set and 4 order changes)
on both sides, not explained or rebuilt here. `concept_search.py`, `concepts.json` and every static/JS file are
not modified, and `tests/test_static_parity.py` (server/static engine parity on synthetic corpora) ran in the
full suite. The copy was not modified: sizes, mtimes and the parquet listing hash (4,110 files) were identical
before and after.

## Numerical examples

Synthetic (`tests/test_aq04b_follow_up_actions.py`; resident 2023: Cluj 730, Iasi 830, Bucuresti 1930;
domicile 710; stays 3/4/5 times the population; `SERK` breaks 2021/2022):

- "population of Cluj in 2023": two choices, actions `query_data` on `POPK_judete` (Cluj 2023 = 730.0) and
  `POPD_judete` (710.0).
- "castigul Cluj 2023": `earn_net` choice `recipe` = `earn_total` = its action's recipe (before: `null`);
  `earn_gross` has no route, so `describe_dataset` (a rate is not summed).
- "turism Cluj 2023": `run_recipe tk_intensity` Cluj 2023 = 3.0 (2190 / 730).
- `query_data` SERK Cluj 2020-2023: warning `SERK-break`; 2022-2023, 2018-2021, 2021 alone, 2023 alone: none.
  Iasi's own break (2019/2020) only for a selection that includes Iasi.
- `run_recipe` areas `[Cluj-Napoca, Cluj]` 2023: Cluj 3.0 ranked, `Cluj-Napoca` excluded `not_in_data`, recovery
  lookup `REF_AREA` query `Cluj` on `POPK_judete`; all areas: Arad (stays, no population) excluded
  `not_in_denominator`, ratios 3 / 4 / 5.

Real generation `9b3e065d` (read-only):

- "salariu mediu Cluj 2023": `net_earnings` choice `recipe` `net_earnings_county`, action
  `run_recipe` year 2023 areas [Cluj] -> Cluj **5,344** lei (was `recipe: null`).
- "somaj Cluj 2019": registered choice action `run_recipe registered_unemployment_county` 2019 Cluj -> **1.2**;
  ILO choice has no action (`place_level_unavailable`, `level_differs`).
- "turism": `tourist_overnight_stays` choice carries `series_break TUR105D-rented-rooms` (its action selects
  all years).
- `query_data` POP105A Cluj 2020/2021/2022/2023 = 709,872 / 710,664 / 683,028 / 688,844 with warning
  `series_break POP105A-census-break` and `provenance.series_breaks`; 2022-2023 alone: no warning.
- `run_recipe tourism_intensity` areas [Cluj-Napoca, Cluj] 2023: Cluj 1.8296 ranked, Cluj-Napoca `not_in_data`,
  lookup `REF_AREA` query `Cluj` on `POP105A_judete_grupe`.

## Configuration

None added. Limits (`FIT_BYTES`, `MAX_CHOICES`, `MAX_RECOVERY`, 32 KiB) are unchanged; new constants are
`MAX_ACTION_NOTES = 4`, `ACTION_NOTE_CHARS = 240` in `discovery.py`. Debug: `app.services.tools.discovery`
logs one `DEBUG` line per resolved choice (status, action tool, recipe, note codes; never the question).
Under the byte budget `_shrink_discover` cuts a choice's note prose to ~80 characters before anything else
(codes stay); the loop is tested to terminate at an impossible budget.

## Rollback

`git revert` the code commit (and this record). No data, schema or contract-version change; the new fields
are additive, so a client that ignores them keeps working. Nothing is stored.

## Remaining gates

- 04C: the new prose is English (like the rest of discovery); the Ask page already lists warning messages
  generically, so `series_break` texts (in the request language) reach the table, but retaining them when a
  model omits them is 04C.
- The Ask system prompt and the `discover_indicators` registry description do not yet mention
  `action`/`action_status` (`agent.py`, `registry.py` are outside this step's files): a model will use
  `next_call` until they do. Suggest one sentence in each.
- Live-provider Ask run and AQ-02 task fixtures with these choices: `not_run`.
- `alternatives[]` on a card keep their restatement only (they are not a pending clarification); their
  `recipe` field agrees with the rule above.
- Area identity beyond exact labels (above) is open.
