# AS-01 — An age band that spans the others is the total (brief, revision 2)

Owner decision, 2026-11-22: do both fixes below. Development may run now in a worktree; the release
follows the batch 2 data refresh (generation `5e226fc3`). **Revision 2 (2026-11-22):** the first run
stopped as directed (see "Findings of the first run"); Fix 1 now pins the band by metadata and never
sums its parts.
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


## Findings of the first run (verified by Opus)

- The stored structure lacks `15 - 24 ani` because `13-dimension-structure.py` samples only the 3 latest
  periods, and that band ends at 2026-06. This affects every dimension of every dataset; it is a separate
  backlog item, **out of scope here**.
- AMG130M's parts do not add up to the span: `15 - 24 ani` is a quarterly estimate repeated over three
  months, and gaps reach 12.4% (2020-02, Masculin: 75,316 + 189,269 against 301,893). A corpus scan found
  9 label matches; only AMG130O sums within 1.1%; AMG157G/H/I, SAR119C, TFA0494 and TLH1019 are not
  additive at all (likely rates). Scan: `scan.py`/`scan.json` from the first run.
- Conclusion: `15 - 74 ani` is INS's own estimate for the whole range. Showing it needs a **pin**, not a
  proof that parts sum. Options labelled "Total" are already pinned on their label without a sum check.

## Fix 1 — pin a spanning age band as the aggregate option (main fix)

Rule, in `aggregation_policy` (query time, metadata only; no profiler change):

1. Applies only to `dim_type='age'` dimensions where every option has parsed `age_min`/`age_max`
   (an open-ended band such as "65 ani si peste" has no `age_max`: then the rule does not apply).
2. Exactly one option S contains every other option's range: `S.min <= o.min` and `o.max <= S.max` for
   all others, and at least one other option exists. Two or more such options: the rule does not apply.
3. Then S is the aggregate option: `_is_total_option` (or the code that calls it) treats S like a
   Total-labelled option, so an unfiltered request pins S with method `aggregate_row` ("rând total din
   sursă"), exactly as for a "Total" label today.
4. The other bands stay unverified. Never sum them, never mark them as a partition, never compare their
   sum to S. A request that explicitly selects several bands keeps today's behaviour
   (`overlapping_levels` when they overlap).
5. A `dimension_structure.aggregate_value` that names another option wins over this rule.

Because nothing is summed, the rule is safe for rates and percentages (it returns INS's own value for
the span). Keep the rule in one function and use it from every caller of the policy.

Scope check: list every canonical dataset where the rule now pins a band (code, column, band, unit), and
the 9 matches from the first run with their new outcome. For AMG130M give the latest-period value now
returned by `/api/datasets/AMG130M/insights` and by `query_data`, next to the `15 - 74 ani` cell(s).
Note: AMG130M has no "Total" sex option in the data, so the SEX dimension decides on its own; report
what the tile shows and why.

Consumers: the v2 and v1 pages, insights, Ask, the public MCP tools (through `data_query`), place
profiles, and the static engine, which mirrors the policy in `app/static/js/engine/` (find the JS
counterpart of `_is_total_option` / `age_ranges_overlap` and change it the same way). `scope.py` and
`static/js/engine/scope.js` describe age-domain coverage: keep their output consistent with the pin.

## Fix 2 — no whole-dataset refusal next to a selection (small UI fix)

`dashboard-v2.js` `renderInsights`: the insight cards describe the whole dataset (PA-02b), and with a
selection they carry "întregul set (fără selecție)". When a selection is active and the `latest` total
is in `suppressed`, do not render its refusal card next to the "Selecția ta" card: hide it, or show a
muted one-line note. Without a selection, keep the refusal card (it explains the missing headline
number). Apply the same rule to v1 (`explore-app.js`) if it shows the same card. Both languages.

## Verification

- Synthetic fixtures for the rule: one span over two bands (pins S, value equals the S cell even when
  the parts do not sum to it); a rate unit (pins S, no sum); two spanning candidates (no pin); an
  open-ended band (no pin); bands without parsed ages (no pin); an `aggregate_value` naming another
  option (that option wins); an explicit multi-band selection (unchanged `overlapping_levels`); a
  non-age dimension (unchanged).
- Numerical check on the copied generation: AMG130M latest period, unfiltered, returns the `15 - 74 ani`
  cell(s), never a sum; `query_data` and `/api/datasets/AMG130M/insights` agree.
- Static parity: `tests/test_static_parity.py` (`parity.mjs`, `api-parity.mjs`) must pass.
- Chart-selector and agent evals (dev MCP `tempo_eval_chart_selector`, `tempo_eval_agent`): explain
  diffs before rebuilding baselines.
- Browser smoke: AMG130M v2 with and without the `AGE` filter, both languages; one dataset that still
  has no total (the refusal card shows without a selection, is hidden with one).
- Full `python -m pytest tests -q` once at the end; never two full suites at once.

## Data

No pipeline stage runs: the fix is query-time. Use an APFS clone of the served generation `5e226fc3`
(`cp -c -R`, skip `data/_archive`) only as `TEMPO_DATA_DIR` for tests and checks. Never write to the
repository's `data/`. Promotion and deploy are the owner's step.

## Stop and ask when

- The rule needs a new `method` in `aggregation_policy`, a contract version bump, or a change to how
  `overlapping_levels` is decided for non-age dimensions.
- A dataset in the scope check pins a band that is clearly not the whole population of the dataset
  (for example a span that INS labels as a subgroup), or the static engine cannot mirror the rule.
- Work is needed outside `app/services/` (`dimension_structure`,
  `aggregation_policy`, `scope`), `app/static/js/` (`dashboard-v2.js`, `explore-app.js`, `engine/`),
  `scripts/build-static.py`, `tools/static-engine/`, `tests/`, `data/eval/` and this plan folder.

## Deliverables

Code and tests on branch `as-01-age-span-total` from `main` (do not merge, push or deploy). The copied
generation's path. `record.md` in this folder: the rule as built, the scope-check list, the AMG130M
numbers, eval diffs, browser smoke, and assumptions. Do not edit `docs/BACKLOG.md`, `docs/activity-history.md`, `AGENTS.md` or
`docs/CURRENT_STATE.md`: return proposed text in the final report.
