# AQ-04C completion record: localized tool messages and caveats the page keeps

Step 04C of [04-discovery-and-messages.md](04-discovery-and-messages.md) only, plus the four follow-ups the AQ-05A and
AQ-04B records left to it. 04A and 04B are the baseline and are unchanged in behavior. Implemented 2026-10-17 on branch
`aq/04c-localized-messages`.

- Baseline: `fff5ccf` (`fix/ask-answer-quality` after the AQ-04B merge).
- Code commit: `0879ffd`. This record is added by the next commit; the code is unchanged by it.
- No corpus change, no baseline rebuild, no deployment, no provider call, no limit change, no new dependency, no new
  tool. The contract stays `tempo-tools/2`: every change below is prose, an additive optional field, or Ask-side. Catalogue
  search, `concepts.json`, `concept_search.py`, the AQ-02 task file and every limit are untouched.

## Status

| State | Result |
|---|---|
| Code-ready | Yes. Targeted, AQ-02 runner and full suite pass (numbers below) |
| Validated on synthetic data | Yes: both languages compared envelope by envelope on the AQ-04A/04B/05A corpora; a scripted model that omits every caveat; Chromium at 320, 390 and 1280 px |
| Validated on a real corpus | Read-only, generation `9b3e065d2fe9bb1df9bae2131b7bdeae9be3426f3c82b9a9954f7e6dc8f45550` (copy `/Users/pax/devbox/gov2/tempo-gen-20261012/data`): 239 RO/EN scenarios (every advertised call run in both languages) equal beyond prose; the AQ-02 runner; the whole suite with the corpus-marked tests; a browser smoke through the real router, agent and tools with only the model scripted |
| Model-validated (live provider, task fixtures) | `not_run`. No provider call. Whether a real model passes `lang` is unmeasured (the loop supplies it when the model does not) |
| Client-validated (hosted connector) | `not_run`. The browser checks above are the Ask page only |
| Deployed | No |

## What changed

| File | Change |
|---|---|
| `app/services/tools/messages.py` (new) | One catalogue, `t(lang, key, **values)`: 339 keys, each in Romanian and English with the same placeholders. Replaces the English literals of every tool `message`, warning and recovery |
| `app/services/tools/{contract,registry,query,discovery,discovery_policy,ranking,changes,recipe}.py`, `app/services/period_changes.py`, `app/services/public_mcp.py` | Prose comes from the catalogue; no code, subject, id, filter, value, count or call argument depends on `lang`. `shrink` hooks and `response_budget` take `lang`; `period_changes` judges what a population series counts on the source's Romanian words in both languages (below) |
| `app/services/tools/schemas.py` | `lang` gets one description for every tool; `find_dimension_values` gains the optional `lang` it lacked (its messages could not be asked for in English) |
| `app/services/agent.py` | Warnings the page lists are deduplicated by (code, subject) and written in the question's language; a tool called without `lang` gets the question's; the Ask prompt names `action`/`action_status` and `lang` |
| `app/services/ask_present.py` | `qualifications`: the discovery warning that changes the figures' meaning (the assumed definition) joins the page's list; a cut `compare_periods` top K is a ranking; excluded and outside-class counts reach the caption |
| `app/services/ask_context.py` | A validated period selection is re-dumped with its public field name (`from`, not `from_`) |
| `app/static/js/ask.js`, `app/static/ask.html` | Ranked-caption wording for entity-interval rankings, excluded and outside-class counts, the footer of a cut ranking (all with the page's `tr(ro, en)`); cache-buster `ask.js?v=7` |
| `tests/test_aq04c_messages.py`, `tests/test_aq04c_ask.py`, `tests/test_aq04c_browser.py` (new) | 34, 18 and 21 tests (below) |
| 16 existing test files | Wording asserts say which language they pin (below) |

## How it works

**Catalogue.** `messages.t` formats a template with values; keys are `area.name`. A value that is an identifier (a column,
a dataset code, a filter value, a period, a reason code) is a placeholder, so it is never translated. Tests guard the file: key and placeholder parity (and
the same leading/trailing space on both sides, for fragments that join), nothing left identical in both languages, and AST scans
that every key used in `app/` exists, no entry is dead, every call supplies the values its template needs (296 call sites), and
no tool module passes a prose literal as a `message` (`warning`, `recovery`, `ToolFailure`, `_note`, `_refuse`, `_unavailable`,
`_synthetic`, `_gate_envelope`). Kept outside the
catalogue because they were already localized: `recipe._TX`, `links._TX`, `contract._SCOPE_TEXT`, the curated notes
(`series_break` texts, `dataset_notes.json`) and the concept/dataset names from `concepts.json` and INS metadata.

**Not translated (passes through as the shared service wrote it).** `data_query.QueryError` texts and Pydantic validation
details stay English, except the four a tool user meets (`dataset not found`, `no data file`, `apply a filter`, `unknown
column`: `contract._QUERY_ERRORS`) and the frame of an argument-validation message. Deliberately stable in both languages:
`data.order` (`newest first`), measure and unit-type codes inside a sentence, `UNIT`/`REF_AREA` values, the evidence bundle's
own README and `CLASS_WARNING` (the bundle is English whatever the request's language; its `method.json` warnings follow
`lang`).

**A qualification that differed by language, found by the real-corpus run and fixed.** The `boundary_continuity_unverified`
warning says what a population series counts. It judged that on the dataset title in the request's language, and INS's English
title of POP107D is "LEGALLY RESIDENT POPULATION" (its Romanian title and definition say *domicile*): the English warning read
"resident (usual residence)" where the Romanian one said "domicile" (also at the baseline with `lang="en"`). A prose-masking
comparison cannot see it; the corpus-marked `test_real_localities_keep_county_and_locality`, run with English wording, did.
`period_changes.run` now judges the note on the source's own Romanian words in both languages (the sentence is still
translated); `test_what_a_population_series_counts_does_not_depend_on_the_language` fails on the old code.

**Ask.** The model's text is never the only carrier of a qualification. `display_table` and the turn's warnings come from the
tool results: every data tool's warnings (as before) plus the `assumed_definition` warning of a discovery result whose card
offered a dataset the displayed result stands on. They are listed once per (code, subject), the assumption first, in the
question's language (`lang` is filled in for a tool the model called without one; an explicit `lang` is respected and the
model's arguments are kept as sent in `tool_trace`). `constraint_not_applied` is deliberately not on the page: it tells the
model to apply a filter, and the page cannot tell whether it did.

**Captions.** `compare_periods` is ranked over every eligible entity of each interval before top K, so its table is marked
`ranked` with `eligible_count`, `interval_count`, `excluded_count` and (cities) `outside_class_count`; the caption reads
"3 of 233 eligible entities, ranked · 2 excluded · 2 outside the class (communes, totals), not ranked" (several intervals:
"eligible entity-interval pairs, ranked within each interval"). A cut ranking's footer says the complete ranking is in the
source links. A `query_data` preview keeps "Preview: first N rows; not a ranking".

## Examples (the same call in both languages; codes, subjects and values are identical)

| Text | English | Romanian |
|---|---|---|
| `assumed_definition` (subject `resident_population`) | Definition assumed: Resident population. State it explicitly; alternatives remain available. | Definiție presupusă: Populația rezidentă. Precizeaz-o explicit; alternativele rămân disponibile. |
| `constraint_not_applied` (subject `sex`) | The question asks for sex ('feminina') but discovery did not apply it; … Nothing was dropped silently. | Întrebarea conține o constrângere de tip sex ('feminina'), dar discovery nu a aplicat-o; … Nimic nu a fost omis în tăcere. |
| `classification_reference` | Cities are municipalities and towns in the referenced catalogue (INS GOS102A, SIRUTA keys). Membership does not prove historical city status or unchanged boundaries; places outside the catalogue (communes, totals) were not ranked. | Orașele sunt municipii și orașe din catalogul de referință (INS GOS102A, chei SIRUTA). Apartenența nu dovedește statutul istoric de oraș sau limite neschimbate; locurile din afara catalogului (comune, totaluri) nu au fost clasate. |
| `series_break` on `compare_periods` | Inside the compared interval 2020→2023: SERK breaks between 2021 and 2022 (test). | În intervalul comparat 2020→2023: Seria SERK se rupe între 2021 și 2022 (test). |
| choice `action_notes` (`period_unavailable`) | 2019 is outside the data of POPK_judete (2020–2024); the year was not applied and nothing was substituted. | 2019 este în afara datelor POPK_judete (2020–2024); anul nu a fost aplicat și nimic nu a fost înlocuit. |
| `query_data` refusal | No rows match: REF_AREA Nowhere does not exist in the data. … | Niciun rând nu corespunde: REF_AREA Nowhere nu există în date. … |

Real generation `9b3e065d`, the page through the real router, agent and tools (only the model scripted, its answers naming
no caveat): "cities that lost the most population 2015 to 2020" shows "10 din 319 entități eligibile, în ordine · … · 2862 din
afara clasei (comune, totaluri), neclasate" with the classification and boundary warnings, scope text and links; "Câți
locuitori are Cluj în 2023?" lists "Definiție presupusă: Populația rezidentă …" first above the one row (688,844); "Cluj
2020-2023" lists the 2021/2022 census break of POP105A.

## Existing tests that changed

Prose now follows `lang` and the default is `ro` (as it always was for names and scopes), so a test that asserted English
words on a default call needed to say which language it pins. No assertion about a status, reason, code, subject, value,
count or argument was weakened. Per file:

| Files | Change |
|---|---|
| `test_at01_query.py`, `test_at01_changes.py`, `test_at01_discovery.py`, `test_at01_contract.py`, `test_at01_recipes_links.py`, `test_aq05a_city_changes.py`, `tests/ask_adapter.py` | the English-wording calls pass `lang="en"` (a helper default in `q`, `cc`, `ask_adapter.ask`; per call elsewhere); the assertions that checked Romanian scope text or `lang: "ro"` arguments now pass `lang="ro"` or expect the language they ask for |
| `test_aq04a_discovery_defaults.py`, `test_aq05a_city_change_discovery.py` | parametrized by the question's language: a fragment is checked in that language (`said(text, lang, en, ro)` in `at01_fixtures.py`) |
| `test_aq04b_follow_up_actions.py`, `test_at02_loop.py`, `test_fix02b_agent.py`, `test_fix08_budgets.py` | a Romanian question yields Romanian warnings; the fragments are the Romanian ones (`excluse`, `reținut`, `APROXIMARE`, `limita de apeluri către instrumente`) or the call says `lang="en"` |
| `test_at03_mcp.py`, `test_at03_resources.py` | gate messages asked for in English (`"lang": "en"` in the call arguments) |
| `test_at01_changes.py` (incl. the two corpus-marked `test_real_*`) | the budget stub accepts the hook's new `lang` keyword; the real-corpus refusals and localities calls say `lang="en"`. The replay test in `test_aq05a_city_changes.py` asks the links for the language of the selection it replays |

## New tests

| File | Covers |
|---|---|
| `test_aq04c_messages.py` (34) | catalogue parity, placeholders, spaces, untranslated leftovers, no dead or missing key, every call supplying its template's values, run-time key families, no prose literal in a message; the same call in RO and EN on 24 discovery questions (04B), 11 default/refusal questions (04A), 11 `query_data` selections, 16 other tool calls, the registry's errors, cities (05A): masked envelopes equal, sentences localized; the required texts pinned in both languages; stored identifiers inside Romanian sentences; the shrink hooks; a population note that does not depend on the language |
| `test_aq04c_ask.py` (18) | a scripted model that omits the caveats still gets the assumed definition (RO and EN, first), the series break, the classification caveat, the excluded counts and a partial scope listed; a definition assumed for another dataset is not attached; one warning per (code, subject) across two languages; the language given to a tool called without one and an explicit one respected; a cut `compare_periods` top K is a ranking, several intervals, a preview stays a preview; the budget notice per language; `from` in the hint; the prompt and the tool description name `action` |
| `test_aq04c_browser.py` (21) | the real Ask response of those turns rendered at 320/390/1280 px in RO and EN: warnings, captions, scope text and `partial` badge, footer, links, no console error, no horizontal scroll (server port 8171) |

Do the new tests detect the old behavior? Run against an export of `fff5ccf`, 15 of the 18 Ask tests fail (no assumed
definition on the page, `from_` in the hint, `ranked` absent on a cut top K, English-only warnings, no `action` in the prompt,
no `lang` on `find_dimension_values`); the 3 that pass assert preserved behavior (a preview stays a preview, the Romanian
series-break text that already existed, no attachment of an unrelated definition). A mutation (a call that omits a template
value) is caught by `test_every_call_passes_the_values_its_template_needs`.

## Commands and results

All with `source ~/devbox/envs/240826/bin/activate`, `PYTHONDONTWRITEBYTECODE=1`, provider keys unset.

| Command | Result |
|---|---|
| `python -m pytest tests/test_aq04c_messages.py tests/test_aq04c_ask.py tests/test_aq04c_browser.py -q -p no:cacheprovider` | 73 passed |
| `python -m pytest tests -q -p no:cacheprovider --tb=short` (no corpus) | **1,812 passed, 85 skipped**, 7 existing FastAPI/openpyxl warnings, 0 failures (9 min 3 s). Baseline `fff5ccf`: 1,739 / 85, so +73 = the new tests; the 85 skips are the corpus-marked tests |
| the same with `TEMPO_DATA_DIR=/Users/pax/devbox/gov2/tempo-gen-20261012/data` | **1,896 passed, 1 skipped** (10 min 33 s). The skip is the AQ-02 self-skip ("the app now contains an endpoint swap"), as in the AQ-03B record |
| `TEMPO_DATA_DIR=<copy> python scripts/eval-ask-tasks.py --quiet --report-dir .../aq-reports/aq04c/runner` | 142 executed: **142 passed**, 0 failed, 0 known failures; controls 30 detected, 2 known limitations, 10 resolved, 0 mismatch; verdict `blocked_by_known_limitations` (the two T11 limitations of AQ-03B). No task-file edit: its qualification checks use warning codes and subjects, never prose |
| RO/EN comparison on the copy (`real_parity.py`: 20 discovery questions, every advertised call of each run in both languages, 19 direct calls) | 239 scenarios, 0 differences beyond prose |
| Chromium 320 / 390 / 1280 px, committed tests (`test_aq04c_browser.py`) | 7 tests per width (RO and EN city ranking, assumed definition, partial scope, wrapping) pass: warnings, captions, scope text and badge, links, no console error, no horizontal scroll |
| Chromium 320 / 390 / 1280 px, smoke on the copy through the real router, agent and tools (only the model scripted; port 8172) | 15 runs (5 questions x 3 widths): outcomes `answered`/`partial`, horizontal overflow 0, console errors 0; warnings, caption, scope, footer and links as in the examples above |

The first full run, before any test was touched, failed 79 of the 1,739 existing tests: English wording on a default (Romanian) call,
the budget stub's signature, a link replay in the other language, and the hook helper. None was a status, reason, value, count or
argument. A first corpus run also failed two corpus-marked tests of `test_at01_changes.py` for the same reason, which is how the
population-note defect was found.

### English did not change

The same 91 scenarios (24 discovery questions, 19 default/refusal questions, 11 `query_data`, 21 other tool calls,
links and registry errors, 10 city calls) run with `lang="en"` on an export of `fff5ccf` and on this branch: 84 envelopes are
byte-identical. The 7 that differ are explained: `find_dimension_values` (6) could not be told a language at the baseline, so
its sources URL and recovery `lang` argument now carry `en`; a non-object argument list has no `lang` to read, so its message
is the default Romanian. The one wording change in English is a unification: the "no data file" message of
`get_evidence_links` now reads like `data_query`'s ("— it may be published as sub-datasets").

### Parity of catalogue search

Method of AQ-04A/04B: `agent_eval.run_search_eval` over `data/eval/agent_questions.yaml`, `GET /api/search` for 17 questions x
{ro, en}, `match_concepts` for 136 aliases, run on the corpus copy from an export of `fff5ccf` and from this branch: the two
JSON files are byte-identical (sha256 `b94d7777d994…`, comparison hash `e381411a414c…`, the values 04B recorded). `concept_search.py`,
`concepts.json` and the static engine are not modified. The copy was not modified (sizes, mtimes and the listing hash of its
4,110 parquet files, `b01403a2…`, equal before and after).

## Decisions to review

1. **Prose is Romanian by default.** `lang` defaults to `ro` in every schema, so a caller that passes none now gets Romanian
   sentences where it used to get English ones. Mitigations: the `lang` description on every tool, the Ask prompt, the public
   MCP instructions, and the Ask loop supplying the question's language. Changing the schema default to `en` (or to
   request-based) is a product decision left open.
2. **`find_dimension_values` got an optional `lang`** (additive, still `tempo-tools/2`). Its recovery/`next_call` arguments do
   not carry one (that would change every pinned lookup argument); the Ask loop adds it.
3. **The page lists the assumed definition only when the discovery card offered a dataset the displayed result stands on**
   (so a model that moved to another definition does not inherit a stale caveat). `constraint_not_applied` is not shown (above).
4. **Deduplication keeps the first text of a (code, subject).** Two calls that warn the same code and subject in different
   languages, or with different numbers (`auto_pinned` on the same columns), show once; warnings with no subject are
   deduplicated by their text.
5. **`rank_entities` and `compare_periods` word the classification caveat differently** (as before); each is translated, not
   unified. Only the AQ-05A wording ("does not prove historical city status or unchanged boundaries") says membership is not
   historical status.
6. **Shared-service text stays English** (above). Translating Pydantic details or all of `data_query` would change the REST
   errors too.
7. **Existing tests changed by language, not by meaning** (table above). The alternative, defaulting test helpers to `en`
   globally, would have hidden which tests rely on Romanian search behavior.

## Rollback

`git revert 0879ffd` (and this record). No data, schema, contract-version or stored-state change. Stored Ask follow-ups
carry no prose. The catalogue file can be deleted only together with the code that imports it.

## Remaining gates

- Live-provider Ask run and AQ-02 task fixtures with RO/EN paraphrases: `not_run` (the offline runner is scripted: 142/142).
  Whether real models pass `lang`, and whether answers in the user's language follow Romanian tool prose, is unmeasured.
- Hosted-connector (ChatGPT/Claude) evidence for the localized MCP prose: `not_run`.
- Backlog candidates: `1 rânduri` in the Ask caption (plural of the existing string); the Romanian page texts of the Ask HTTP
  errors (`Ask is busy; retry shortly`); a Romanian rendering of Pydantic validation details if the REST errors are to follow.
