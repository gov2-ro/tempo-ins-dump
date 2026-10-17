# AQ-03 — Conservative claim verification

**Status: planned. Implement 03A before 03B.** This extends AT-05's bounded checks;
it does not promise general natural-language entailment.

## Problem and file map

`answer_check.py` currently matches numbers with tolerance, checks entity names
at sentence level and detects recognizable unit/single-year contradictions.
Small integers/years/question numbers can be skipped; multiple years and equal
values across entities remain ambiguous. Change endpoints currently share an
interval period label. A value appearing somewhere in a trace is insufficient.

Read `numeric_leaves`, `find_numbers`, `_matches_value`, `_entity_named`,
`_semantic_conflict`, `bind_claims`; `agent._Run._check_answer`; `ask_present.py`;
`test_at05_quality.py`, `test_at02_loop.py`, `test_fix02b_agent.py` and current
tool provenance schemas. Preserve all passing count-versus-ratio tests.

## 03A — Correct evidence coordinates before parsing more prose

Give each numeric leaf explicit metric semantics while retaining its real JSON
pointer and call ID. `from_value` has the from-year, `to_value` the to-year;
absolute/percent change spans both endpoints and carries its metric. Ranking
values retain their full entity key, independent of dictionary/column order.

Normalize supported source units into separate fields for measure, scale and
denominator: persons, count, stays, currency, percent, percentage points,
per-person and per-thousand. Do not equate percentage points with percent or
built-up hectares with administrative km². Unknown units remain unknown.
Use reviewed source metadata/recipe definitions, never the model's asserted unit.

Carry population definition only when a reviewed concept/recipe/source mapping
establishes it. A metadata title containing a word is not a universal classifier.
An unclassified source cannot prove an explicitly requested definition.

Acceptance fixtures: from=100 in 2020 and to=140 in 2025; 100 cannot be verified
as the 2025 endpoint. A +40 change is distinct from +40%; two currencies and
percent versus percentage points remain distinct. County/locality keys and
resident/domicile evidence cannot be swapped merely because numbers coincide.
Metadata-only fields, row ranks and SIRUTA codes are not measurement claims.

## 03B — Bind only what the wording actually identifies

Work incrementally with table-driven RO/EN tests. Limit parsing to recognizable
clauses, explicit entity mentions, number spans, unit suffixes/prefixes and years.
Use those anchors to narrow candidate leaves. If more than one distinct semantic
coordinate remains possible, mark `unverified/ambiguous_binding`; do not choose
the first matching number. Multiple references to the exact same cell may dedupe.

Replace unconditional omission of small integers and numbers repeated in the
question with contextual handling: a numbered list position/year/SIRUTA code is
not a measured value, but “2 înnoptări pe locuitor” is. Preserve decimal/thousands
and scale handling. Keep sign for signed observations/changes; “fell by 40” may
refer to −40 only when explicit direction/metric evidence supports it.

Do not infer absent years, units or definitions from vague text and call them
verified. Existing `semantic_check: no_explicit_conflict` is weaker than complete
semantic verification. Add backward-compatible detail flags as needed; missing
context yields unverified/partial, not a fabricated contradiction. Explicit
contradictions continue to withhold prose through the current Ask path.

Mandatory adversarial tests:

- Same sentence, two cities and two values: swapped assignments cannot match.
- Same value for multiple places/years: explicit anchors resolve it or it remains
  ambiguous; mention of one county cannot verify a city within it.
- Multiple years, endpoint swap, signed changes and a raw count phrased as a rate.
- Correct mixed count+ratio sentence stays valid; decimal comma and scaled values
  work in RO/EN; units are associated with their own statistic.
- Small ratio=2, zero observations and a question repeating the eventual figure
  still receive checks. List numbering and identifiers do not create false claims.
- No numeric claim without evidence becomes matched. Deliberately vague wording
  is unverified without falsely accusing a correct source of contradiction.

Keep the claim cap and bounded work for long answers/traces. Add debug counts and
stable reasons through existing safe logging; do not persist answer text by
default. No parser dependency, extra model call, provider protocol migration or
free-form structured-answer redesign in this package.

## Completion and rollback

Run `test_at05_quality.py`, `test_at02_loop.py`, `test_fix02b_agent.py`, related
context/presentation tests and AQ-02's tasks when available. If visible statuses
change, add a browser scenario explaining partial versus withheld prose. Review
false positives as well as false negatives. Revert this package to restore AT-05;
there is no data migration. List unsupported language patterns in the record.
