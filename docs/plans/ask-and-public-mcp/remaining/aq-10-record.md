# AQ-10 record — "Din care" subsets are never summed with their parent

Brief: [10-din-care-subsets.md](10-din-care-subsets.md). Branch `aq-10-din-care`. Not merged, not deployed.
Measured read-only on the served generation `062bd2b0` (`data/corpus`).

## Label variants found

Option labels, folded (lower case, no diacritics), in `dimension_options`:

| Form | Options | Meaning |
|---|---|---|
| prefix `din care:` (also `din care :`, `din care,`, `din care`), with or without leading spaces or `- ` | 323 (208 indented) | a subset of the option before it |
| `..., din care:` after text (`Total, din care:`, `De capital, din care:`) | 291 | a Total or heading that introduces subsets; not a subset |
| `inclusiv`, `din acestea` inside a name | 1,690 / 120 | ordinary words in a product name; not a cue |

EN (`labels_i18n.label_en`) has `of which:`, `of which,`, `Of which:Meningitis`, one typo `of witch:`. The policy
reads the stored data value, the label and the SDMX value, so RO and EN agree.

The rule matches only the prefix forms: `^[\s\-–]*(din care|of which|of witch)\b` on folded text.
197 datasets (198 dimensions, parents and split children) carry such an option. The brief's 364 datasets
include the 291 `Total, din care:` labels, which are totals.

## The rule

Python `app/services/aggregation_policy.py`, mirrored in `app/static/js/engine/policy.js`:

- `is_subset_label` / `has_subset_option(eff)`: any effective option is a "Din care" option.
- Unfiltered sum over such a dimension (no Total to pin, no verified level): refused, reason `label_hierarchy`
  (the existing code and texts; no new reason, so no change outside the brief's folders). Applies in
  `_unprofiled_partition`, to curated `declared_partition_invalid`, and before the gender/residence shortcut.
- Explicit selection: `subset_with_parent(matched, eff)` is true when a chosen subset and the nearest earlier
  non-subset option (the dimension's own order) are both chosen. Refused as `label_hierarchy`. A selection of
  non-subset options sums as before. A subset with an unrelated option is allowed. One pinned subset is a slice.
- A dimension kept on the axis (grouped) is not summed and is not refused.
- No automatic "drop the subset and sum the rest" (owner decision, not taken).

## Recovery rule (`tools/query.py`)

`_plan_source_total` (source_total_mismatch, no_source_total, source_total_unchecked) offers a related dataset
only if `source_total_gate` passes on it too (`verified_alternatives(source_checked=True)`). Choice: the
candidate has its own `kpi_total_checks` row, or a verified/curated structure. No inheritance from the
children. Why: a row exists only where INS was compared; a parent's columns differ from the child's,
so a verdict cannot be carried over without a column mapping. A parent with no row is not offered.

## Impact (served generation, read only)

- Prefix-subset dimensions: 198 in 197 datasets; 167 datasets have an indented label in the metadata, yet the old
  policy still summed many of them (it judges the data values, which are probably trimmed; not verified).
  Only 31 dimensions (LOC104A-D, LOC105A, LOC106A,
  LOC107A and children, POP208D/H, ZCZ1113, TEI0451, AED103A/106A/314A) had no cue at all.
- Default-shape queries (group by time, by geo, by geo and time; no filter) over the 197 datasets:
  527 queries, 263 change. 232 go from a valid sum to a refusal (`label_hierarchy`), in 84 datasets
  (29 families, among them AGR111A-116A, AGR201A-203A, ADM101A, CDP102G/103B/D/G, LOC104-107, POP206C/F/I/L,
  SAN102B, SAN104A, SAN105A, SOM104A, ZCZ1113). 31 more only change the reason
  (`unverified_structure` or `missing_weights` become `label_hierarchy`); they were refused before.
  Of the 99 datasets with any change, 98 had no `kpi_total_checks` row: the sums were never checked.
- Dataset-page compositions (`chart_config.composition`, API result): 7 of 197 change. LOC104A, LOC104C, LOC105A,
  LOC106A and LOC107A lose 2-3 tiles each (choropleth, horizontal bar, line or small multiples) that summed
  the three sources. LOC104B_judet and GOS108B change only the suppression reason.
- Recorded `kpi_total_checks`: 24 of 301 mismatches are datasets with a "Din care" option (8%): the LOC104A-D,
  LOC105A-107A families, GOS108B children, AED103A, POP208D/H. So "Din care" explains a minority of the
  disagreements; the check was not run again (it calls INS).
- Curated figures: none change. No headline (`headline_config.json`), place KPI (`place_kpi_config.json`),
  recipe, published total or concept in `app/data` names a dataset in the affected sets. No stop condition applies.
  `dataset_notes.json` names LOC104B, GOS108A and GOS118A (notes only; unchanged).

## Evals

- Chart selector (`evaluate_all` against `data/eval/chart_selector_baseline.json`): 0 primary, top-set,
  confidence or score changes. The scorer does not call the policy. The corpus has 30 datasets the baseline lacks and
  3 it still has (older drift, not from this change); the baseline is not rebuilt.
- Offline Ask task replay (`scripts/eval-ask-tasks.py`): 144 passed, 0 failed, controls 30 detected, 2 known
  limitations, 10 resolved, 0 mismatches. Identical before and after the change (checked on the base commit).
- Agent/search eval: not run. It reads the search index, which this change does not touch.

## Tests

`tests/test_aq10_din_care.py` (38): label variants (RO, EN, diacritics, indentation, `Total, din care:` is not
a subset), refusal of the whole dimension, Total pin, explicit non-subset sum, subset plus parent, order, data
value judged apart from the label, gender dimension, `rank_entities` on a parent/child pair (no double count),
a refused child offers no unchecked parent (fails without the fix), a parent with its own passing check is
still offered, a parent with a failed check is not. A corpus probe on LOC104A (skips without the pinned
generation). `tests/test_static_parity.py::test_parity_for_din_care_subset_options` replays recorded cases
through the browser engine (fails without the JS mirror).

## Open points

- The profiler (`13-dimension-structure.py`) still labels these columns `flat`. A later package can mark a "Din care"
  option as nested so the structure is known (no pipeline change here).
- Recovery text for `label_hierarchy` is the generic "no verified structure; pin one value". It does not name
  the non-subset options. A dedicated message needs `messages.py` (inside `app/services/`) and the page strings
  in `utils.js` and `ask.js` (outside this brief).
- The static site must be rebuilt (recorded answers change) and the API deployed after merge.
