# AQ-03A completion record: evidence coordinates for claim checking

**Status (2026-10-17): implemented and verified locally on branch `aq/03-claim-verification`.
Review pending.** Not pushed, not merged, not deployed. No provider call, no corpus write, no
baseline rebuild. Step 03B (wording-anchored binding) is a separate commit and is not part of this one.

| | |
|---|---|
| Spec | [03-claim-verification.md](03-claim-verification.md), step 03A |
| Baseline | `fix/ask-answer-quality` ce472e9 (AT-05 + the remaining/ specs) |
| Final state | the commit "feat(ask): AQ-03A explicit evidence coordinates for claim checking" on `aq/03-claim-verification` (this record is part of it; `git log` has the hash) |
| Worktree | `.worktrees/aq-03-claim-verification` |
| Corpus / tables / tool contract | none changed; `tempo-tools/2` envelopes are unchanged (no provenance field was added) |

## What changed

`app/services/answer_check.py`, `app/services/agent.py` (one line), `tests/test_aq03a_evidence.py` (50 tests).
`ask_present.py`, the frontend and every tool are untouched: no visible status changed.

### Leaves carry their own coordinates

`numeric_leaves` keeps the real JSON Pointer (`path`) and now also the call id (`call`) and, additively:

| Field | Meaning |
|---|---|
| `metric` | `observation`, `from_value`, `to_value`, `change_absolute`, `change_percent` |
| `period`, `period_from`, `period_to` | an endpoint carries its **own** year (`from_value` 2020, `to_value` 2025); a change keeps the label `2020→2025` and both endpoints. Before, all four fields of a compare row shared the interval label, so "100 in 2025" could not be told from "100 in 2020". |
| `key` | the full entity key `{column: value}`, sorted by column (independent of dictionary or column order). Compare/rank rows use the same finest-geography naming as query rows: the locality (`REF_AREA_2`) names a locality row, its county no longer does. |
| `unit_norm` | `{measure, currency, scale, denominator, known}` from `normalize_unit` |
| `scaled` | the value in base units when the source unit has a scale (560.3 `Mii persoane` -> 560 300) |
| `population` | `resident` / `domicile` / `None` |
| `dataset`, `tool` | provenance of the cell |

Only value cells are leaves. Ranks, `eligible_count`, `outside_class_count`, SIRUTA codes and other
numeric dimension columns are not measurement claims and never become leaves.

### Unit normalization (source side only)

`normalize_unit(text, unit_type)` maps the source unit (INS `UNIT_MEASURE`, the reviewed recipe unit, a row's own
unit, a pinned `UNIT_MEASURE` filter) by full match on the folded text, after an optional scale word. It never
reads the model's words.

| Source text | measure | currency | scale | denominator |
|---|---|---|---:|---|
| `Numar persoane`, `Mii persoane` | persons | | 1 / 1,000 | |
| `Numar` | count | | 1 | |
| `Procente`, `%` | percent | | 1 | |
| `Lei`, `Milioane lei RON`, `Miliarde lei` | currency | RON | 1 / 1e6 / 1e9 | |
| `Milioane EURO`, `Mii dolari (USD)` | currency | EUR / USD | 1e6 / 1e3 | |
| `Lei / persoana` | currency | RON | 1 | person |
| `înnoptări pe locuitor`, `overnight stays per resident` | stays | | 1 | person |
| `Hectare` / `Kilometri patrati` | area_ha / area_km2 | | 1 | |
| `Decedati la 1000 locuitori` | (unknown) | | | thousand_persons |

Anything else (`Kilometri`, `Mii`, `Tone`, `Persoane la 100000 locuitori`, price-basis units) is `known: False`
and every field `None`. Percentage points are not percent (an absolute change of a `Procente` series is
`percentage_points`; a relative change is `percent`), hectares are not km², two currencies never match, and there
is no conversion between them. The profile `unit_type` is only a hint when no unit text exists (`percentage` ->
percent, `count` -> count).

### Population definition

Carried only from reviewed mappings: the `family` of a reviewed concept in `concepts.json`
(`resident_population`/`resident_population_july` -> resident, `domicile_population` -> domicile), a recipe
source's reviewed `concept`, and `POP107D` (the locality series AT-05 selects as domicile population). A title or
definition text containing "domiciliu" or "rezident" classifies nothing (tested with an unmapped dataset whose
metadata says "Populația după domiciliu").

### Claim side (what the new coordinates change)

`_semantic_conflict` now compares the claim's words with the normalized unit, the endpoint-specific period and the
population definition. Verdicts and their reasons:

| Reason | Meaning | Withholds prose? |
|---|---|---|
| `unit_mismatch` | stated unit is not the cell's (currency, percent vs persons, per-resident vs total, ha vs km², points shown as percent, a ratio phrased as a count) | yes (unchanged) |
| `period_mismatch` | one stated year is not a year the cell covers (endpoint-specific now) | yes (unchanged) |
| `unit_unverified` | the cell's unit is unknown while the claim states a strict one, or a bare "%" meets a percentage-point change | no |
| `scale_mismatch` | the claim dropped the source scale (560,3 persoane for `Mii persoane`) | no |
| `definition_mismatch` / `definition_unverified` | stated, or explicitly requested for a population claim, definition differs from / is not established by the source | no |

`answer_check.CONTRADICTIONS = {unit_mismatch, period_mismatch}` is the single set `agent._check_answer` withholds on
(it was a literal tuple). Promoting a reason to a withholding one is a one-line change there. Everything new is
reported as an unverified claim (`status: unverified_numbers`, `outcome: partial`), which is the existing visible state.
A candidate that is merely unverifiable outranks one that contradicts when a claim has several, so an unknown unit
never turns into an accusation.

Number matching also accepts the base-unit reading of a scaled source (`result_values`, so `uncited_numbers` agrees
with `bind_claims`). Matched claims additionally carry `metric`.

## Numerical examples

Synthetic (hand-built envelopes, `tests/test_aq03a_evidence.py`): Cluj from=100 (2020), to=140 (2025), absolute 40,
percent 40.

| Claim | Result |
|---|---|
| "avea 100 de persoane în 2020" | matched `/from_value` |
| "avea 140 de persoane în 2025" | matched `/to_value` |
| "avea 100 de persoane în 2025" / "140 ... în 2020" | `unverified`, `period_mismatch` (withheld) |
| "a crescut cu 40 de persoane" / "cu 40%" | matched `/absolute` / matched `/percent` |
| the same with absolute=7 / percent=7 | `unit_mismatch` |
| Procente series 50 -> 84: "cu 34 puncte procentuale" | matched `/absolute` (points) |
| ... "cu 34%" | `unit_unverified` (not an accusation); "cu 68%" matched `/percent` |
| ... "cu 68 de puncte procentuale" | `unit_mismatch` |
| 33.0 `Milioane lei`: "33 milioane lei" / "33000000 lei" | matched |
| ... "33 milioane euro" | `unit_mismatch`; "33 lei" -> `scale_mismatch` |
| 560.3 `Mii persoane`: "560,3 mii", "560 300 de persoane", "560.3 thousand people" | matched |
| ... "560,3 persoane" | `scale_mismatch` |
| two cities with value 100 under different counties | each claim binds to its own row; a county name binds neither |
| domicile sentence, `POP105A_judete_grupe` / unmapped dataset | `definition_mismatch` / `definition_unverified` |

Read-only probe on the copied corpus (generation `9b3e065d2fe9bb1df9bae2131b7bdeae9be3426f3c82b9a9954f7e6dc8f45550`,
`TEMPO_DATA_DIR=/Users/pax/devbox/gov2/tempo-gen-20261012/data`, provider keys unset; real tools through
`registry.call_tool`, nothing written):

| Real result | Leaf coordinates |
|---|---|
| `compare_periods POP105A REF_AREA 2012->2021`, Prahova | from 761,699 (2012), to 703,580 (2021), absolute -58,119, percent -7.630 %; unit `Numar persoane` -> persons; `population: resident` |
| "Prahova avea 761699 de persoane în 2012." | matched `/from_value` |
| "... în 2021." (same number) | `period_mismatch` |
| "Prahova a scăzut cu 58119 ..." / "cu 7,6%" | matched `/absolute` / `/percent` |
| "Prahova a scăzut cu 58119%." | `unit_mismatch` |
| `compare_periods POP107D REF_AREA_2 2012->2021`, Braila | key `{REF_AREA: Braila, REF_AREA_2: 42682 MUNICIPIUL BRAILA}`; entity named by the locality; `population: domicile`; values 219,702 -> 197,232, -22,470 |

## Commands and results

All with `source ~/devbox/envs/240826/bin/activate`, `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider --tb=short`.

| Command | Result |
|---|---|
| `pytest tests/test_aq03a_evidence.py tests/test_at05_quality.py tests/test_at02_loop.py tests/test_fix02b_agent.py -q` | 121 passed (the 71 pre-existing tests are unchanged and green; 50 new) |
| `pytest tests/test_at01_{changes,contract,discovery,integration,query}.py tests/test_at02_{context,guard,privacy,loop}.py tests/test_at03_mcp.py tests/test_at05_{quality,ranking}.py tests/test_fix02b_agent.py tests/test_ask_{debug,providers}.py tests/test_aq03a_evidence.py -q` | 458 passed, 16 skipped (`corpus`-marked tests without a corpus), 149.9 s |
| read-only corpus probe above | as tabulated |

The complete repository suite is run once before the final (03B) commit and recorded in the 03B record.

## Configuration

None. No new setting, dependency, limit or default. `CONTRADICTIONS` is a module constant.

## Rollback

Revert the 03A commit. There is no data migration and no change to the tool contract, to any stored result or to
the frontend; the previous AT-05 checker returns unchanged.

## Remaining

- **Code-ready, not yet model-validated:** none of this was exercised with a real provider; the verdicts are pinned by
  synthetic and read-only-corpus checks only.
- 03B (wording-anchored binding): claims are still bound sentence-wide here, so a sentence with two years or two
  places is not yet resolved by wording; ambiguous equal values still pick the first matching cell; small integers
  (<= 31) and numbers repeated from the question are still skipped.
- The profile `unit_type` fallback and the reviewed unit table cover the common INS units; the 200-odd long-tail units
  stay `unknown` (claims against them are `unit_unverified`, never a contradiction). Adding a unit is one table row.
- Policy choices for the reviewer: (1) unknown source unit plus a strict claimed unit is now `unit_unverified`
  (it was `unit_mismatch`, i.e. withheld, in AT-05); (2) the new reasons (`scale_mismatch`, `definition_*`,
  `unit_unverified`) do not withhold; (3) a bare "%" against a percentage-point change is unverified, not a
  contradiction.
