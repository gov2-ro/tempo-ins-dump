# AS-01 — An age band that spans the others is the total (brief)

Owner decision, 2026-11-22: do both fixes below. **Run after batch 2 of the 2026-11-20 data refresh is
deployed**, so that the policy change does not ship in the same release as the data refresh.

## The problem

On `ins.gov2.ro/dataset/AMG130M/?f={"AGE":["15 - 74 ani"]}` the KPI row shows:

- "Selecția ta: 15 - 74 ani" = 515,764 (correct; computed in the page from the selected series);
- "Ultima valoare" = "Total indisponibil: niveluri de vârstă suprapuse".

AMG130M's `AGE` has three options: `15 - 24 ani`, `15 - 74 ani`, `25 - 74 ani`. The `15 - 74 ani` band
spans the other two, so it *is* the total, but INS does not label it "Total". `dimension_structure` has
`confidence='flat'`, `additive=None`, `aggregate_value=None`. The policy therefore detects overlapping
age ranges from the labels (`aggregation_policy._metadata_overlap` → `age_ranges_overlap`) and refuses
with `overlapping_levels`. The refusal is correct for an unverified structure; the gap is that a
verifiable total is not recognised.

Observed detail to explain first: the stored `levels` for AMG130M `AGE` list only
`["15 - 74 ani", "25 - 74 ani"]` (n=2), not `15 - 24 ani`. Find out why (missing data, a filter in
`13-dimension-structure.py`, label normalisation) before designing on top of it.

## Fix 1 — recognise a spanning band as the total (main fix)

Where: the structure profiler, not query time. `13-dimension-structure.py` already writes
`aggregate_value` and `aggregate_verified`, and `aggregation_policy._is_total_option` already pins the
option named by `dimension_structure.aggregate_value`. Prefer setting those two fields over a new policy
rule.

Rule (age dimensions only, `dim_type='age'`, parsed `age_min`/`age_max` on every option):

1. One option S spans exactly the union of the others: `S.min = min(others.min)`,
   `S.max = max(others.max)`, and the others tile [S.min, S.max] without gaps or overlaps. When the
   others contain several levels (bands and single years), each level must tile S on its own.
2. The data confirm it: for every observed key (all other dimensions fixed), the sum over one tiling
   level equals S's value within a tolerance. Survey data are rounded (often to thousands), so use a
   tolerance relative to S and the number of summed cells; record the tolerance and the worst
   observed gap. Missing cells: a key with any missing part does not count as confirming. Require a
   minimum share of keys to confirm (propose a value) and zero keys that contradict beyond tolerance.
3. Then set `aggregate_value = S` and `aggregate_verified = true`, and record the tiling level(s) as
   verified levels so a summed breakdown can use them.

Never mark S as the total from labels alone. Open-ended bands ("65 ani si peste") have no `age_max`;
treat them as ending at the domain end only if the other options agree. Otherwise skip.

Scope check: list every canonical dataset whose age dimension gains an `aggregate_value` under the rule
(expected: the AMG family and other labour series with 15–64 or 15–74 bands), with the worst gap per
dataset. Report datasets where the label rule matches but the data do not confirm.

Consumers that change: the v2 page, v1, `/api/datasets/{code}/insights`, Ask, the public MCP tools
(through `data_query` and the policy), place profiles and the static engine (the static build carries
`dimension_structure` in its per-dataset policy files; check `scripts/build-static.py` and
`app/static/js/engine/`). `scope.py` (age-domain coverage, mirrored in `static/js/engine/scope.js`) may
already describe such bands: reuse it if it fits, and keep both copies in agreement.

## Fix 2 — no whole-dataset refusal next to a selection (small UI fix)

`dashboard-v2.js` `renderInsights`: the insight cards describe the whole dataset (PA-02b), and with a
selection they carry "întregul set (fără selecție)". When a selection is active and the `latest` total
is in `suppressed`, do not render its refusal card next to the "Selecția ta" card: hide it, or show a
muted one-line note. Without a selection, keep the refusal card (it explains the missing headline
number). Apply the same rule to v1 (`explore-app.js`) if it shows the same card. Both languages.

## Verification

- Synthetic DuckDB/parquet fixtures for the profiler rule: exact tiling, rounded tiling within
  tolerance, a contradicting key, a gap in the bands, two levels (bands and single years), an
  open-ended band, a non-age dimension (no change).
- Policy tests: with the verified aggregate, a request without an `AGE` filter pins S (method
  `aggregate_row`); without it, the refusal stays `overlapping_levels`.
- Numerical check on a copied generation: AMG130M latest period gives S's value (2026-09, both sexes),
  and `query_data` / `/api/datasets/AMG130M/insights` agree.
- Static parity: `tests/test_static_parity.py` (`parity.mjs`, `api-parity.mjs`) must pass.
- Chart-selector and agent evals (dev MCP `tempo_eval_chart_selector`, `tempo_eval_agent`): explain
  diffs before rebuilding baselines.
- Browser smoke: AMG130M v2 with and without the `AGE` filter, both languages; one dataset that still
  has no total (the refusal card shows without a selection, is hidden with one).
- Full `python -m pytest tests -q` once at the end; never two full suites at once.

## Data

Run the profiler only on an APFS clone of the served data
(`cp -c -R`, skip `data/_archive`; `TEMPO_PIPELINE_DATA_DIR`, `TEMPO_STRUCTURE_DB`,
`TEMPO_STRUCTURE_PARQUET_DIR` as needed). Never write to the repository's `data/`. Promotion and deploy
are the owner's step.

## Stop and ask when

- The `15 - 24 ani` level gap (above) points to a profiler bug with wider effects.
- The rule needs a new `method` in `aggregation_policy`, a contract version bump, or a change to how
  `overlapping_levels` is decided for non-age dimensions.
- More than a handful of datasets match by label but fail the data check, or the tolerance needed is
  larger than INS's rounding explains.
- Work is needed outside `13-dimension-structure.py`, `app/services/` (`dimension_structure`,
  `aggregation_policy`, `scope`), `app/static/js/` (`dashboard-v2.js`, `explore-app.js`, `engine/`),
  `scripts/build-static.py`, `tools/static-engine/`, `tests/`, `data/eval/` and this plan folder.

## Deliverables

Code and tests on branch `as-01-age-span-total` from `main` (do not merge, push or deploy). The copied
generation with the re-profiled structure, and its path. `record.md` in this folder: the rule as built,
the tolerance and why, the dataset list with worst gaps, the non-confirming matches, eval diffs, and
assumptions. Do not edit `docs/BACKLOG.md`, `docs/activity-history.md`, `AGENTS.md` or
`docs/CURRENT_STATE.md`: return proposed text in the final report.
