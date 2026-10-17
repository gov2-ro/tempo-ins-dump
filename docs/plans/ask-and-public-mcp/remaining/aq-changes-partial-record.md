# AQ record: `compare_periods` is partial for an unverified domain

Owner decision of 2026-10-17, implemented on branch `aq/changes-unverified-partial`. It closes the backlog item
"Harmonize partial status for unverified domains" and the 05A observation that a city change was `ok` where the
same domain in `rank_entities` was `partial/unverified_total`.

- Baseline: `9afa711` (`fix/ask-answer-quality`).
- Code commit: `23cca38`. This record is added by the next commit; the code is unchanged by it.
- No corpus change, no baseline rebuild, no deployment, no provider call, no limit change, no new dependency, no
  client (JS/HTML) change. The contract stays `tempo-tools/2`; `data/eval/ask_tasks.json` is unchanged.

## Decision

`compare_periods` returns `partial` with reason `unverified_total`, and an `unverified_total` warning, when the
selection's `scope.domain_complete` is `null`, exactly as `rank_entities` does (`tools/ranking.py`, the block that
builds `status`/`reason`). `false` keeps `partial/incomplete_domain`; `true` keeps `ok`. Excluded entities still make a
result `partial`. When both apply, the reason precedence is `rank_entities`': a domain reason (`incomplete_domain`,
then `unverified_total`) wins over the bare "excluded" `partial`, and the `entities_excluded` and `unverified_total`
warnings are both kept.

| `scope.domain_complete` | Nothing excluded | Some entities excluded | No entity ranked |
|---|---|---|---|
| `true` | `ok` (unchanged) | `partial`, reason `null` (unchanged) | `unavailable` / `no_eligible_entities` (unchanged) |
| `null` | **`partial` / `unverified_total`** + `unverified_total` warning (was `ok`) | **`partial` / `unverified_total`** + both warnings (was `partial`, reason `null`) | `unavailable` / `no_eligible_entities` (the warning is added, as `rank_entities` does) |
| `false` | `partial` / `incomplete_domain` (unchanged) | `partial` / `incomplete_domain` (unchanged) | `unavailable` / `no_eligible_entities` (unchanged) |

Values, ranks, eligible counts, exclusions, `limits` and the evidence bundle's `result.csv`, `exclusions.csv` and
`inputs/endpoints.csv` do not depend on the verdict (proofs below).

## What changed

| File | Change |
|---|---|
| `app/services/period_changes.py` | `run()` decides status/reason from `domain_complete` in the `rank_entities` order and appends the `unverified_total` warning (after `classification_reference`, as in `rank_entities`). It is the one runner the tool, `/api/period-changes` and the evidence bundle share, so all of them inherit it. Module docstring states the rule |
| `app/services/tools/changes.py` | One `elif`: the message gets `changes.unverified` when the domain is unverified (the sibling of `changes.restricted`) |
| `app/services/tools/messages.py` | Two RO/EN key pairs: `changes.unverified` (message fragment) and `changes.unverified_total` (warning text). The AQ-04C parity test (same keys, same placeholders) covers them |
| `tests/test_aq_changes_partial.py` (new) | 19 tests, 18 synthetic and 1 corpus-pinned |
| `tests/test_at01_changes.py` | One assertion changed (below) |

Not touched: `data_query`, `scope.py`, the aggregation policy, `rank_entities`, `change_evidence.py`, `routers/changes.py`,
`links.py`, `public_mcp.py`, `ask_present.py`, `agent.py`, `ask.js`, `answer_check.py`, `registry.py`, every static/JS file,
`data/eval/ask_tasks.json`.

## Where the status surfaces (each checked)

| Surface | Result |
|---|---|
| Shared tool envelope | Changed in `period_changes.run`; `status`, `reason`, `warnings`, `message` only |
| REST `/api/period-changes` | Calls `registry.call_tool("compare_periods")`: same envelope, HTTP 200 (`test_rest_returns_the_same_partial_envelope`) |
| `/api/period-changes/evidence` | Records no status or reason. `method.json` records `scope` and `warnings`, which now carry `domain_complete: null` and the `unverified_total` warning. Partial is certifiable (200, not 422). The three data files are byte-identical before/after on the real city run (sha256 below) and `recompute.py` exits 0 |
| MCP (`/mcp`) | Same registry call; the SDK client gets `structuredContent == text == service result`, `isError` false (`test_mcp_returns_the_same_partial_envelope`) |
| Links / replay | `get_evidence_links` has no verdict of its own (its scope is metadata). Its `live_selection` URL replays to `partial/unverified_total` with identical data and warnings, and the `evidence` URL returns the bundle |
| Ask | Needs no code: `agent._run_tool` lists every data tool's warnings on the page, `ask_present.display_table` carries `status: "partial"` and the scope, `ask.js` shows the "partial" badge and the scope note for `domain_complete !== true`, and the `unverified_total` reason text already existed. A turn's `outcome` does not follow a tool's `partial` for `rank_entities` either (AQ-02 pins `["answered", "partial"]` there); `test_an_ask_turn_treats_the_period_change_like_the_ranking` runs the same question shape through both tools on one unverified dataset and asserts equal `(outcome, reason)`, a partial table, and the warning on the page |
| Localized catalogue | RO and EN texts added (`changes.unverified_total`, `changes.unverified`); codes are language-neutral and compared across languages |
| Static engine | Does **not** mirror period changes or `rank_entities`: `app/static/js/engine/` and `tools/static-engine/{parity,api-parity}.mjs` have no `compare_periods`/`period-changes`/`rank_entities` reference (the engine mirrors `scope.domain_complete` for `/data` only, which is unchanged). Nothing to keep in agreement; `tests/test_static_parity.py` was run and passes |

## Tests whose expectation changed

| Test | Change and reason |
|---|---|
| `tests/test_at01_changes.py::test_real_counties_bundle_recomputes_offline` (corpus-marked, generation `9b3e065d`) | `t["status"] == "ok"` became `(status, reason) == ("partial", "unverified_total")` plus the warning. POP105A collapses SEX and RESIDENCE over partitions only the metadata vouches for, so its domain is unverified; this is the decision itself. The same test's eligible count (42), top row (Prahova 761,699 -> 703,580, -58,119) and its offline recompute are unchanged. The old assertion was confirmed to fail on the new code |

No other existing test or AQ-02 task changed. Every other `compare_periods` test uses a synthetic dataset whose domain is
verified (`true`) or stubs the scope. The AQ-02 task `X08` pinned on the copy (`POP105A`) accepts `["ok", "partial"]`, so
it passes before and after; its final tool status moved from `ok` to `partial/unverified_total` (visible in the report's
`final_tool_status`). It was left permissive on purpose (see "Not changed").

## New tests (`tests/test_aq_changes_partial.py`)

The three verdicts come from the real aggregation policy on synthetic corpora, not from a stub: `UNV*` collapses SEX over a
metadata-only partition (`null`), `REST*` holds ages 0 and 1 of a Total (0-999) domain (`false`), `FULL*` collapses nothing
(`true`); `*X` adds entity D with no 2020 row (one exclusion), `*C` does not.

- the verdict -> status/reason/warning table for all six combinations, with ranks, eligible and excluded counts asserted;
- the warning and message text in EN and RO, and that the codes are the same in both languages;
- no ranked entity stays `unavailable/no_eligible_entities` with an unverified domain;
- **values do not depend on the verdict**: the same data under `true`, `null` and `false` (verdict injected after the real
  query) differs only in status, reason, message, warnings and `provenance.scope` (the rest of the envelope compared as JSON,
  also with `top_k` cutting the list); `false` adds no warning, `null` adds exactly `unverified_total`;
- the same ranking and percent values across the three real-policy datasets; the verified default still `ok` with its old warnings;
- the city class (`entity_class: cities`, 230-city fixture): same data, limits and classification under `true` and `null`,
  `partial/unverified_total` with `classification_reference` + `entities_excluded` + `unverified_total`;
- REST, the evidence bundle (certified, `method.json` records the verdict, offline recompute passes, rows and exclusion as
  the fixture defines), links and replay, MCP through the real SDK client, an Ask turn compared with `rank_entities`;
- one corpus-pinned test of the real city decline and the real county change (status, warning, numbers).

Mutation checks (each applied to the code, the 18 synthetic tests run, then restored and compared byte for byte):

| Sabotage | New tests that fail |
|---|---|
| an unverified domain stays `ok`/exclusion-only (the old behavior) | 9 |
| the `unverified_total` warning is not added | 9 |
| exclusions win over the domain reason | 7 |
| `false` is treated like `null` | 3 |
| the message fragment is dropped | 3 |

## Commands and results

Environment: `source ~/devbox/envs/240826/bin/activate`, `PYTHONDONTWRITEBYTECODE=1`, provider keys unset. The copy was
read-only (`TEMPO_DATA_DIR=/Users/pax/devbox/gov2/tempo-gen-20261012/data`); a listing hash of its files (name, size, mtime)
was identical before and after the probe and the suites.

| Command | Result |
|---|---|
| `pytest tests/test_aq_changes_partial.py` | 18 passed, 1 skipped (the corpus-pinned test); 19 passed with the copy |
| 15 related files (`test_at01_changes`, `test_aq05a_*`, `test_aq04c_{messages,ask}`, `test_aq04b_*`, `test_at01_{contract,recipes_links,integration}`, `test_at02_{context,loop}`, `test_at03_{mcp,resources}`, `test_aq03{a,b}_*`) after the code change, before the new tests | 656 passed, 12 skipped (same as before the change) |
| `python scripts/eval-ask-tasks.py --quiet --report-dir <scratch>/runner-after` (copy) | **142 executed: 142 passed, 0 failed**; negative controls 42: 30 detected, 2 known_limitation, 10 resolved, **0 mismatch**. Same as the baseline run in the same session (`runner-before`); the per-task verdicts are identical, only X08's `final_tool_status` changed |
| `pytest tests -q` (synthetic, no corpus) | **1830 passed, 86 skipped** (baseline 1,812 / 85 + the 18 new synthetic tests passed + the 1 new corpus-pinned test skipped). 57 skips are "real corpus not present", 1 is the AQ-02 endpoint-swap skip |
| `TEMPO_DATA_DIR=<copy> pytest tests -q` | **1915 passed, 1 skipped** (baseline 1,896 / 1 + the 19 new tests; the skip is the AQ-02 endpoint-swap one) |
| `pytest tests/test_aq04c_browser.py tests/test_at02_browser.py tests/test_fix08_browser.py tests/test_pa01_frontend.py` | 71 passed, 0 skipped |

The first full synthetic run gave `1797 passed, 119 skipped`: 33 more skips than the clean count, browser tests whose fixed port
was held by a sibling session's server (seen directly: "port 8171 already in use", 21 tests in `test_aq04c_browser.py`). The
numbers in the table are from a clean rerun, and the four browser files were rerun alone (above).

A first full corpus run (`1914 passed, 1 failed, 1 skipped`) failed only `test_landing_summary.py::test_recent_updates_keep_30_days...`,
a date test that straddled midnight (`TODAY` at import, the 30-day window at request time); it passes alone and in the rerun above.

## Real-data probe (read-only copy, generation `9b3e065d`)

`probe-before.json` ran against an export of `9afa711` (`git archive`, scratch), `probe-after.json` against this branch,
same copy, same arguments. Everything except status, reason, message, warnings and `provenance.scope` was compared as one
JSON blob per case: identical in all three.

| Case | Before | After | Values |
|---|---|---|---|
| AQ-05A city decline: `POP107D_grupe_localitate`, `entity_class: cities`, 2015 -> 2020, ascending, top 10 | `ok` / `null`; warnings `boundary_continuity_unverified`, `classification_reference` | `partial` / `unverified_total`; + `unverified_total` | 319 eligible, 0 excluded, 2,862 outside the class; rank 1 Braila -12,827 (213,169 -> 200,342), 2 Ploiesti -9,943, 3 Timisoara -8,415; `limits` identical |
| County change: `POP105A`, 2012 -> 2021, top 3 | `ok` / `null`; warnings `boundary_continuity_unverified`, `series_break` | `partial` / `unverified_total`; + `unverified_total` | 42 eligible; Prahova -58,119, Municipiul Bucuresti -58,085, Teleorman -53,623 |
| Same city case, `lang: ro`, top 3 | `ok` | `partial` / `unverified_total` | identical |

`scope` is identical (`domain_complete: null`, "Domain completeness cannot be verified"); the aggregation decision for both
datasets is `valid_total / sum_partition / metadata` (POP107D_grupe_localitate: AGE `profile_flat`, SEX `metadata`; POP105A: AGE a
verified level, SEX and RESIDENCE `metadata`). REST `/api/period-changes` returned 200 `partial/unverified_total`. The evidence
bundle for the city case: 200, 115,330 bytes (115,243 before, +87 for the warning in `method.json`), `recompute.py` exit 0,
319 result rows, and `result.csv`, `exclusions.csv` and `inputs/endpoints.csv` have the **same sha256** as before. Cost on the
envelope: +346 bytes (8,082 -> 8,428) for the 10-row city result, +374 in Romanian; no preview was cut that was not cut before;
elapsed times unchanged (0.57 s for the national city run).

## Before / after, in words

City decline, English, `partial/unverified_total`:

> Per-entity change in Numar persoane for 1 interval(s) of POP107D_grupe_localitate: every eligible entity of the class
> 'municipalities and towns in the referenced catalogue' was ranked (319 ranked) and 10 row(s) are shown. 2862 source
> entities outside the catalogue (communes, totals) were not ranked. **Domain completeness is unverified, so these are not
> changes of an official complete total.** Rank is the ordinal position ...

Warning `unverified_total`: "The completeness of the collapsed domain behind these endpoint values is unverified; the
changes are exact for the stated selection, but do not claim they describe an official complete total." The Romanian
texts are "Completitudinea domeniului nu este verificată, deci acestea nu sunt schimbări ale unui total oficial complet." and
"Completitudinea domeniului colapsat din spatele valorilor de la capete nu este verificată; schimbările sunt exacte pentru
selecția indicată, dar nu pretinde că descriu un total oficial complet."

Synthetic (`UNVX`, A 100 -> 60, B 200 -> 150, C 50 -> 80, D no 2020 row): `partial` / `unverified_total`, warnings
`entities_excluded`, `boundary_continuity_unverified`, `unverified_total`; ranks B -50, A -40, C +30, D excluded
`no_observation`. Before the change the same call was `partial` / `null` (the exclusion) and `UNVC` (no D) was `ok`.

## Not changed, for the orchestrator

- **`false` still adds no warning in `compare_periods`.** `rank_entities` and `query_data` add an `incomplete_domain` warning
  with the scope description; `compare_periods` carries that case in the reason, the "Restricted domain" sentence of the
  message and the scope block only. The decision says `false` keeps `incomplete_domain`, so it was left. Adding the warning is
  one line plus a catalogue pair if wanted (the model-facing disclosure is already there).
- **AQ-02 task `X08` (pinned, `POP105A`) stays permissive** (`status: ["ok", "partial"]`). Tightening it to
  `["partial"]`, reason `["unverified_total"]`, warning `unverified_total` is a one-line expectation change that makes the
  eval catch a regression of this decision; it was not made because no task pinned `ok` alone.
- Shared docs that now describe the old behavior and were not edited: `docs/BACKLOG.md` ("Harmonize partial status for
  unverified domains", resolved by this branch) and the 05A record (status bullet 5 in "Policy decisions" and the
  "Remaining gates" line). The spec tables (`00-tool-contract.md`, `01-analytical-tools.md`) say nothing that conflicts.
- Any client that treated `compare_periods` `ok` as "no caveat" now sees `partial` for every collapsed-sum dataset
  (POP105A, the locality populations). That is the intent; nothing in this repository does so.

## Rollback

`git revert 23cca38`: one commit, no data, baseline, contract-version or file-format change. It removes the status rule, the
two RO/EN message pairs and the new test file, and restores the one assertion in `test_at01_changes.py`.
