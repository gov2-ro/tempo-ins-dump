# AQ-03B completion record: wording-anchored claim binding

**Status (2026-10-17): implemented and verified locally on branch `aq/03-claim-verification`.
Review pending.** Not pushed, not merged, not deployed. No provider call, no corpus write, no
baseline rebuild. Builds on [AQ-03A](aq-03a-record.md) (`fefb5d5`), which is reviewable on its own.

| | |
|---|---|
| Spec | [03-claim-verification.md](03-claim-verification.md), step 03B |
| Baseline | `fix/ask-answer-quality` ce472e9; 03A on top of it: `fefb5d5` |
| Final state | the commit "feat(ask): AQ-03B wording-anchored claim binding" on `aq/03-claim-verification` (this record is part of it; `git log` has the hash) |
| Worktree | `.worktrees/aq-03-claim-verification` |
| Corpus / tables / tool contract | none changed (`tempo-tools/2` envelopes untouched; no provenance field added) |

## What changed

| File | Change |
|---|---|
| `app/services/answer_check.py` | `find_numbers` decides by context what is a claim; `bind_claims` binds each number through the wording around it (`_mentions`, `_sentence_contexts`, `_resolve`). `_entity_named`, `_year_verdict` and `_semantic_conflict` (03A / AT-05) are replaced by per-stage verdicts; `uncited_numbers` shares the new `find_numbers`. |
| `app/services/agent.py` | `verification.claim_reasons` (reason -> count), a `claims` debug event, `metrics.claim_codes`. The withholding rule is unchanged (`answer_check.CONTRADICTIONS`). |
| `app/services/ask_guard.py` | `claim_codes` joins `refusal_codes` in the metrics whitelist (code-shaped keys, integer counts; omitted when no claim was checked). |
| `tests/test_aq03b_binding.py` | 176 tests, table-driven RO/EN (below). |
| `tests/test_aq03a_evidence.py` | two edits to my own 03A tests, see "Test edits". |

`ask_present.py`, the frontend and every tool are untouched: the visible states are the same
(`verified`, `unverified_numbers` -> `partial`, `claim_mismatch` -> withheld prose), so no browser scenario was added.
All AT-05 / AT-02 / FIX-02b tests (`test_at05_quality.py`, `test_at02_loop.py`, `test_fix02b_agent.py`, `test_at02_privacy.py`,
`test_at02_guard.py`) are unchanged and pass.

## How a number becomes a claim

`find_numbers(text, ignore_text, codes)` replaces the blanket omission of small integers, years and numbers from the
question by context. Skipped: a date; a rank or list position ("locul 2", "Top 10", "1."), a code after "cod"/"SIRUTA"/"id" or
equal to a numeric code in a result's entity labels; the base of a rate ("la 1000 de locuitori"); "30 de orașe"-style item
counts (<= 100); a year with no unit after it; a plain integer <= 31 with neither a unit after it nor a cue before it
("rata este", "ratio of", "valoarea"); and a number repeated from the question only when a scope word comes first
("pentru 5000", "for 5000", "nu sunt 4000"). Kept as claims: "2 înnoptări pe locuitor", "0 persoane", "rata este 2", and
"Da, sunt 5000 de persoane" even when the question said 5000. A written sign (`-40`, `−2,5%`, `+8%`) is read and kept
(`sign`); `2020-2025` and `Cluj-55` have none. `raw` keeps its shape ("7,9 %") for `uncited_numbers`.

## How a claim is bound

Each number is judged on the text between its neighbours, not on the whole sentence.

| Anchor | Rule |
|---|---|
| Entity | The names of the cells in the trace are searched in the sentence (accent/case-insensitive, Romanian endings *-ului, -ul, -ei*...; a place-type word such as *județul / municipiul / county of* belongs to the mention; a one-letter code must stand alone in its own case). The mention just before the number is its entity, else one attached by a locative right after it ("300000 în Cluj"), else the previous number's in an enumeration, else the sentence's. Names joined by *și/and/,* before one number are a group. A name followed by `-` and a letter (Cluj-Napoca) is not the county Cluj; *județul X* is a county and cannot verify a locality row of it. |
| Year | Years in front of the number, the year attached after it by a preposition or parenthesis ("în 2020", "(2025)", "în 2020-2025"), the previous number's in an enumeration, the sentence's only year. A year attached to the number, or the only year of the sentence, can contradict; a year earlier in a sentence with other years, or an inherited one, can only make the claim unverified (a source date is not the number's year). |
| Direction / sign | A written sign decides. Otherwise the direction word before the number ("a scăzut cu", "scădere: B, cu", "fell by", "a loss of") must agree with the cell, and a negative cell needs such evidence. "la / to / de la / from" make the number a level and carry no direction. A direction word carries through an enumeration. |
| From / to | "de la 140 la 100", "from 140 to 100": the first number is the from endpoint, the second the to endpoint. |
| Unit | The words after the number (else before it) up to the next number; 03A's normalized-unit rules. |
| Definition | A definition named before/after the number, else the sentence's single definition; or the question's explicit request for a population claim. |

`_resolve` narrows the cells that hold the number through these stages in order (entity, unit, period/role, sign,
definition). The first stage that leaves nothing gives the claim's `reason`; a candidate that is merely unverifiable outranks
one that contradicts. A number printed exactly as one cell's value belongs to that cell: another within the loose 0.5 %
tolerance is not a candidate (so the swapped near-equal pair in the corpus probe below is caught). Cells are then reduced to
distinct coordinates (dataset, full key, period, metric class, unit): the same cell cited by two calls, or an observation
and the same series' endpoint of that year, are one. **More than one distinct coordinate, or one number for a group of names,
is `unverified` / `ambiguous_binding` with `candidates: n`; the first match is never chosen.**

Matched claims keep `semantic_check: no_explicit_conflict` and add `metric` and `anchors` (what the wording fixed:
`entity` stated/inherited/sentence, `period` stated/sentence/inherited/unstated, `unit` stated/unstated/source_unknown,
`direction` stated/sign for a negative cell, `definition`, and `complete`: true only when the entity, year, unit and
(for a reviewed population series) definition were all fixed by the claim's own words). A match still means "a cell holds
the number and nothing the checker understands contradicts it"; the flags say how much was actually pinned down, so a
claim with no year or unit stays `matched` (as in AT-05) but is not `complete`. `claim_summary` keeps its shape
(`{matched, unverified}`); the `claims` debug event also carries the number of `complete` claims.

## Reasons

`CONTRADICTIONS` (withhold prose, unchanged): `unit_mismatch`, `period_mismatch`. Every other reason leaves the prose and
makes the turn `partial` / `unverified_numbers`:

| Reason | Meaning |
|---|---|
| `ambiguous_binding` | several distinct cells (or a group of names) remain possible |
| `entity_mismatch` / `entity_unstated` | the number sits with another cell's entity, e.g. swapped values or a county for a city / no entity of the cell is named for it |
| `period_unverified` / `endpoint_mismatch` | a non-explicit year does not fit / de la X la Y reversed |
| `direction_mismatch` / `direction_unstated` | "fell by 40" for +40, "-40" for +40 / a negative cell needs direction evidence |
| `unit_unverified`, `scale_mismatch`, `definition_mismatch`, `definition_unverified` | from 03A |
| (none) | no cell holds the number |

## Debug counts and logging

`verification.claim_reasons` ({reason: count}), the `claims` debug event ({matched, unverified, reasons}) and
`metrics.claim_codes` ({matched, unverified, reasons...}) carry counts and stable codes only. The ordinary metrics line gets
`claim_codes` only when claims were checked. No answer text, entity or number is logged beyond what already was
(`verification.claims[].text` is the existing client response field, not a log).

## Numerical examples

Synthetic (`tests/test_aq03b_binding.py`):

| Cells | Sentence | Result |
|---|---|---|
| Cluj-Napoca 250,000; Iași 300,000 (2025) | "Cluj-Napoca are 250000 de locuitori, iar Iași 300000." | both matched, rows 0 and 1 |
| same | "... 300000 ..., iar Iași 250000." / "Cluj-Napoca has 300000 people, while Iasi has 250000." | both `entity_mismatch` |
| same | "Cluj-Napoca and Iasi have 250000 and 300000 people respectively." | both `ambiguous_binding` |
| Cluj 1000 (2020), 1000 (2021); Iași 1000, 880 | "Cluj avea 1000 de persoane." | `ambiguous_binding`, 2 candidates |
| same | "... în 2021." / "Iași ... 1000 ... în 2021." | matched `rows/1` / `period_mismatch` |
| 100 (2020) -> 140 (2025), +40, +40 % | "de la 140 la 100 între 2020 și 2025" | `endpoint_mismatch` x2 (prose kept) |
| same | "avea 140 de persoane în 2020 și 100 în 2025" | `period_mismatch` x2 (withheld) |
| same | "a crescut cu 40" / "cu 40 de persoane" / "cu 40%" | `ambiguous_binding` / `/absolute` / `/percent` |
| 140 -> 100, -40 | "a scăzut cu 40" / "a crescut cu 40" / "variație de 40" / "-40" | matched / `direction_mismatch` / `direction_unstated` / matched |
| stays 2,751,439 (count) + ratio 4.9108548 | "2751439 înnoptări, adică 4,91 înnoptări pe locuitor" | both matched; "2751439 înnoptări pe locuitor" -> `unit_mismatch` |
| ratio 2.0 and 0.0 | "2 înnoptări pe locuitor", "0 înnoptări pe locuitor" | matched `/value` (previously unchecked) |
| 1010 / 1012 / 1013 (2021-23) | "1010 de persoane" / "1,01 mii" | matched 2021 / `ambiguous_binding` (3) |
| county Braila + city 42682 MUNICIPIUL BRAILA | "Județul Brăila are 197232" / "Municipiul Brăila ..." | `entity_mismatch` / matched |

Read-only probe on the copied corpus (generation `9b3e065d2fe9bb1df9bae2131b7bdeae9be3426f3c82b9a9954f7e6dc8f45550`,
`TEMPO_DATA_DIR=/Users/pax/devbox/gov2/tempo-gen-20261012/data`, provider keys unset, real tools via `registry.call_tool`):

| Real result | Sentence | Result |
|---|---|---|
| `compare_periods POP105A 2012->2021`: Prahova 761,699 -> 703,580 (-58,119); Municipiul Bucuresti -58,085 | "Prahova a scăzut cu 58.119 ..., de la 761.699 în 2012 la 703.580 în 2021, iar Municipiul Bucuresti cu 58.085." | 4 matched (absolute, from, to, Bucuresti absolute) |
| same | "Prahova a scăzut cu 58.085 ..., iar Municipiul Bucuresti cu 58.119." (the two figures 0.06 % apart, swapped) | both `entity_mismatch` |
| same | "Between 2012 and 2021 Prahova went from 703.580 to 761.699 residents." | `endpoint_mismatch` x2 |
| same | "... de la 761.699 la 703.580 de locuitori (populația rezidentă / după domiciliu)." | matched / `definition_mismatch` x2 (POP105A is the reviewed resident series) |
| `rank_entities POP107D cities 2021` (Cluj, Iași, Brașov filter): Iași 390,832; Cluj-Napoca 328,108; Brașov 288,493; Turda 54,832 | "În 2021: Iasi (390.832), Cluj-Napoca (328.108), Brasov (288.493), Turda (54.832)." | 4 matched; rotated values -> 4 `entity_mismatch`; "Județul Iasi are 390.832" -> `entity_mismatch`; list numbers and "SIRUTA 95060" create no claims |

## Commands and results

All with `source ~/devbox/envs/240826/bin/activate`, `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider --tb=short`.

| Command | Result |
|---|---|
| `pytest tests/test_aq03b_binding.py tests/test_aq03a_evidence.py tests/test_at05_quality.py tests/test_at02_loop.py tests/test_fix02b_agent.py -q` | 297 passed (176 new 03B + 50 03A + the 71 AT-05 / AT-02 loop / FIX-02b tests, unchanged) |
| `pytest tests -q` (provider keys unset; real-server/browser tests included, port 8098 free) | **1,404 passed, 73 skipped**, 7 existing FastAPI/openpyxl warnings, 372 s (baseline at ce472e9: 1,175 passed / 73 skipped, plus the 3 browser tests added after that run = 1,178; +226 new = 1,404). All 73 skips are `corpus`-marked tests ("real corpus not present") |
| read-only corpus probe above | as tabulated |

No browser change, so no 320/390/1280 px run beyond the existing Ask scenarios in the full suite.

## False positives and false negatives (review)

False negatives (a correct answer is `unverified`, shown as partial): enumerations of several names with one list of numbers
("A și B au X și Y respectiv"), or one number true for both names; the same quantity retrieved in two shapes (with and
without a Total sex/age key column); a bare `Alfa: 2` or an unlabelled value; names in a different stem or an
abbreviation (Constanța / Constanței, Cluj-N.); sex, age or activity labels as anchors when a place column exists;
quoting the numerator or denominator of a recipe (only `value` is a cell: `stays`, `population`, `count_total` are not);
derived numbers (sums, differences, shares); a direction word with no connective before the number ("a scăzut, având 1010").

False positives (a wrong claim is `matched`): the loose 0.5 % tolerance still accepts a lone near value when no cell holds
the printed number exactly; a level claim with an unrelated direction word ("a scăzut, ajungând la 100" matches a level
that rose); an unanchored value for a series pinned to one place by the filter; a sentence-level single year or entity;
an unstated unit or year is not verified, only not contradicted (the `anchors` flags say so).

## Unsupported language patterns (they degrade to `unverified`, never to a match)

1. "respectively" / positional enumeration of several names with several numbers; one number for several names.
2. Spelled-out or compound numbers ("trei milioane", "un milion", "2 milioane 751 mii"), fractions, ordinals ("a doua").
3. Relative or partial time ("anul trecut", "mid-2025", months, quarters: only the 4-digit year is read; "între" before years does not
   attach them to a number; the second year of a range after a number is read only for "-", "–", "to", "la", "și", "and").
4. Names in a different case stem, nicknames, abbreviations; entity names inside longer proper nouns other than the hyphen rule.
5. Non-geographic dimension labels (sex, age band, activity) as anchors when the cell has a place.
6. Negation and hedging beyond the scope-word list ("nu a scăzut", "not more than", "approximately" has no extra tolerance).
7. Comparatives with a number ("cu 5 mai mult decât") and derived figures.
8. Direction nouns and verbs not in the list, or without "cu / de / by / of" before the number, and "spor" (neutral).
9. Units outside 03A's table (tone, kWh, km...): no unit check; `unit_unverified` for strict claimed units.
10. A bare `Alfa: 2` style value without a unit or a cue; Markdown rows work, but a row with several numbers uses the same windows.
11. Languages other than Romanian and English.
12. Recipe component columns (`stays`, `population`, `weight_total`, `reconstructed`) are not cells.

## Test edits (03A tests, my own)

`test_a_stated_definition_must_be_the_cells_reviewed_definition` now says "resident population": a plain "residents" is no longer
read as a definition statement (it is how English says inhabitants; it produced `definition_unverified` on any person count of an
unreviewed series). `test_only_explicit_contradictions_withhold_prose` sets `on_event = None` on its hand-built `_Run`
(`emit` is now called by `_check_answer`). No AT-05 / AT-02 / FIX-02b test was changed.

## Configuration, rollback, remaining

No setting, dependency, limit or default changed. Bounds: `MAX_CLAIMS` 20 (unchanged), `MAX_LEAVES` 50,000 cells and
`MAX_NAMES` 5,000 distinct names searched per sentence with claims; a 3,000-name trace with a 60-sentence answer binds in well under a second.
Rollback: revert this commit (03A stays) or both; no data migration, the tool contract and the frontend are untouched.
The population mapping reads `family` and the ids `resident_population`, `resident_population_july`, `domicile_population` from
`concepts.json`; renaming those would silently turn definitions into "unclassified" (checked: unverified, not a contradiction).

Policy choices for the reviewer (not decided by the spec): (1) every new reason is non-withholding; only `unit_mismatch` /
`period_mismatch` withhold, and a year earlier in a multi-year sentence cannot contradict; (2) one number for several names is
`ambiguous_binding` even when it is true for all of them; (3) the exact printed number outranks the 0.5 % tolerance; (4) a
negative cell with no direction evidence is unverified (`direction_unstated`); (5) plain "residents" is not a definition;
(6) bare small integers stay unchecked unless a unit or cue is present; (7) `unit_unverified` instead of `unit_mismatch` for an unknown source unit.

Remaining gates: model-validated (AQ-02 task fixtures or a live run), client-validated and deployed are all **not run**; the
checker is deterministic and covered by synthetic and read-only-corpus checks only. The AT-02 record's sentence "A sign is not
compared" describes the earlier behaviour and is superseded by this record (shared docs were not edited here).

## Follow-up: AQ-02 task-set regressions (`aq/03-fixups`, from merge 488b6b3)

The offline runner (`scripts/eval-ask-tasks.py`, scripted answers, no model) on the merged head showed 135 passed / 5 failed /
2 known failures: correct scripted answers came back `partial / unverified_numbers`. Every unverified claim was traced to its
reason code; all were genuine false positives of the first 03B binding (not vague wording), so the checker was fixed and the
task file only lost the two declarations that now resolve. Scripted tool choice and answers: this measures the deterministic
system, not a model.

| Task | Unverified claim (reason) | Cause | Fix |
|---|---|---|---|
| T10 en | `0`, `4` of "(ages 0–4)", then the year `2025` (small integers with no cell) | the unit search for a small integer crossed the next number: "…0–4) the 2025 population is 110 persons" lent "persons" to the `0` (RO has a comma and was spared) | `_states_unit` stops at the next digit (a "la 1000 de locuitori" rate base still counts) |
| T11 ro, en | `0`, `2` of "ages 0–2 (33 persoane…)" | the same | the same |
| T08 en | `200`, `150`, `-20` (`ambiguous_binding`) | "from 200 to 150" is not an enumeration in English (*from*, *then* were not connectors), so the sentence fallback made B and A a group; and `-20` fits A's absolute change and A's percent change (100 → 80 is -20 and -20 %) | connectors *from, then, apoi, until, with*; a bare value inside an enumeration prefers the metric already bound in it (`anchors.unit: inherited`, never `complete`), only when that leaves exactly one cell |
| T08 ro | `-20` (`ambiguous_binding`) | the same abs/percent coincidence | the same |
| T07 ro, en | `9,9` / `9.9` | (1) `rows[].reconstructed` was not a cell; (2) the `;` split put the reconstruction in a clause with no *Alfa* and no year; (3) once it is a cell, the printed `10` also rounds `9.9` | (1) a `reconstruction` cell, citable only when its sentence says *reconstrucție / verificare / reconstruction / cross-check* (so "valoarea 9,9" as the published figure is `metric_mismatch`, the `reconstruction_as_published` control stays detected); (2) a clause after `;` that names no entity or year inherits the previous clause's (a full stop does not); (3) the printed figure picks the cell that holds it exactly (10.0) over a cell it only rounds to (9.9) |
| T01 off-by-one control | `1011` matched `1010` | the 0.5 % tolerance applied to every figure | it applies only to a figure that looks rounded (ends in a zero digit: 2.751.000, 4,90); `1011`, `58.085`, `4,92` are meant exactly. Printed digits still define rounding (`4,91` for 4.9108548, `2,75 milioane` for 2,751,439). The control is now `flagged` |

Left as is, for the coordinator: **T11 `ages_0_2_as_total`** (the `33` is a real cell of an `incomplete_domain` result; nothing ties the
word "total" to a partial scope — a new check, not a binding fix; still `unsafe_claim_accepted`, documented, 2 hard failures
in the runner).

Choices to review: (1) the rounded-looking rule changes which near figures match (an exactly written integer that is not a
cell now needs the digits to agree); (2) `reconstruction` cells need a cross-check word, otherwise `metric_mismatch`;
(3) a clause after `;` inherits entity and year softly (a carried year never withholds); (4) recipe component columns
(`stays`, `population`, ...) were tried as cells and dropped: they turn the T06 / X01 `count_presented_as_ratio` controls from
`flagged` into `withheld` (a real unit contradiction), which the task file declares as `flagged`; they are a separate change.

Task file (`data/eval/ask_tasks.json`): removed `T07.known_failure` and the `figure_off_by_one` known limitation (now declared
`flagged`). The other declarations the merge already resolves (`T06`; `X03 domicile_relabelled_resident`; `X10` two; `X10B` two;
AQ-04's `X03B`, `X04B`) are still declared and the runner lists them as resolved: `tests/test_aq02_runner.py` uses `T06` and
`X10B increase_for_a_decrease` as its vehicles. `test_a_documented_known_failure_is_listed_apart_and_a_resolved_one_is_noted`
was already failing on 488b6b3 (checked: `test_every_supported_task_passes_and_known_limitations_are_the_only_blockers` and
`test_runs_are_repeatable` failed there too, on the five regressions; this one expected `T06` without its declaration to fail,
which 03B had fixed); it now makes `T06` fail with its own wrong scripted answer. All three pass. No AT-05, AT-02 or FIX-02b test and no adversarial control was changed.

| Runner | Before (488b6b3) | After |
|---|---|---|
| with `TEMPO_DATA_DIR=…/tempo-gen-20261012/data` | 142 executed: 135 passed, 5 failed, 2 known failures; controls 28 detected, 4 known limitations, 10 resolved | 142 executed: **142 passed**, 0 failed, 0 known failures; controls 30 detected, 2 known limitations (T11 `ages_0_2_as_total` ro/en), 10 resolved, 0 mismatch; verdict `blocked_by_known_limitations` |
| without it | not run | 130 executed: 130 passed, 12 skipped (the pinned cases need the generation); the same controls |

Tests: `tests/test_aq03c_followup.py` (31 cases: age ranges, T08 enumerations in RO/EN with the swap still caught, the T07
reconstruction clause and its misuse, `;` versus full stop, the rounded-looking rule in `bind_claims` and `uncited_numbers`, the
exact-over-rounding preference); the targeted set including `test_aq02_*` passes; the full suite: **1,653 passed, 77 skipped**
(76 `corpus`-marked, 1 AQ-02 self-skip "the app now contains an endpoint swap"), 442 s.
