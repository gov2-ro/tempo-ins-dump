# AQ-05 — Remaining analytical capabilities

**Status: planned. 05A is a scoped implementation task. 05B is a source/contract
audit; 05C/05D require its reviewed output.** These are optional capability
increments, not a license to implement arbitrary SQL or model arithmetic.

## 05A — City-only changes using the full classified endpoint set

Problem: `compare_periods` ranks changes, but AT-05 deliberately refuses a
city-only change request because classification is not wired through that tool.
Read `period_changes.py`, `tools/changes.py`, `tools/ranking.py`, `schemas.py`,
`change_evidence.py`, `tools/links.py`, `ask_context.py` and tests
`test_at01_changes.py`, `test_at05_ranking.py`.

Add an optional `entity_class: all|cities` selection to period changes, default
`all` to preserve current callers. Share the existing GOS102A SIRUTA catalogue
resolver with one-year rankings. Apply membership **before** computing eligible
counts and top K; use full county+locality keys and exact annual endpoints.
Never filter the already-truncated top-K result and call it a city ranking.

Carry the class/reference/generation and exclusions through schemas, direct
tools, MCP, REST, Ask follow-ups, links and the evidence ZIP/recompute path.
Published evidence must include sufficient membership input to reproduce the
classification offline. Definition/unit changes across endpoints must remain
warnings/refusals under the existing policy.

Use “municipalities and towns in the referenced catalogue” wording. GOS102A
membership does not prove historical city status or unchanged boundaries.
Requests explicitly requiring historical membership/constant boundaries remain
unavailable without a reviewed source. Permit discovery's current refusal to
be lifted only for the exact supported meaning, with this qualification visible.

Acceptance fixtures: a commune with the largest decline is excluded; the winning
city lies beyond a raw preview; same-named localities in two counties remain
separate; absent endpoint is excluded, not zero; unknown/ambiguous SIRUTA identity
refuses; class/period/generation survive replay and ZIP recomputation; default
`all` reproduces existing values. Public admission/deadline limits still apply.

## 05B — Audit joinable measures before adding arithmetic

Read existing recipes/recipe evidence and the source/definition metadata. Produce
a reviewed, machine-readable candidate map, not an exposed generic join tool.
For each pair record exact dataset/columns, entity keys and level, time convention,
unit/scale, population definition, aggregate treatment, completeness, boundary
caveats and source-total evidence. Read only a copied corpus; cite its generation.

Start with the already-used tourism ratio and the proposed population/area pair.
GOS102A contains **intravilan (built-up) area**, not administrative UAT area.
Ordinary population density remains unavailable without an appropriate new area
source and a separately reviewed ingestion plan. Do not relabel population per
built-up hectare as administrative density.

Output: approved pair(s), rejected pair(s) with reasons, exact candidate schemas,
independent small numerical fixtures and the next implementation task. If none
meet the requested meaning, finish the audit and retain the refusal.

## 05C — One reviewed pair/derived measure, then two-entity comparisons

Prerequisite: 05B approval of the specific measure and its contract. Prefer
extending the recipe mechanism for one named measure. No arbitrary expressions,
user SQL, automatic name joins or “closest” year/definition substitutions.

Query each source through the shared policy; enforce exact keys, level, time and
unit compatibility. Join the complete eligible inputs before sorting/limiting;
report matched, missing-left, missing-right, duplicate-key and excluded counts.
Missing values are not zero. Null/zero denominators cannot yield a ratio.
Carry each source and its scope/quality; a derived measure cannot upgrade an
unverified input into a verified official total.

For a two-entity difference or ratio, return the arithmetic as a tool figure with
the two input values, explicit ordered operands, common definition/year/unit and
result unit. A model must not compute it from table cells. Ask cannot subtract
different definitions just because their units match.

Acceptance fixtures: 120/60=2; reversed operands; zero/missing denominator; unequal
years, levels, units or population definitions refuse; duplicate keys cannot
multiply rows; missing entities are disclosed; top K applied after the join; exact
evidence replay. Include Ask context, MCP and presentation in the same contract
change. Do not expose the operation until all adapters agree.

## 05D — Descriptive correlations, only after complete joined observations

Prerequisite: 05C's reviewed complete pair and a separately accepted operation
schema. Initial scope: unweighted Pearson correlation of two fixed named measures
across matched entities in one exact year. No automatic variable mining,
regression, causal claims or model-selected “interesting” subsets.

Compute from all eligible finite pairs before any preview/top K. Return n,
excluded counts/reasons, units/definitions/year, method and both source scopes.
Refuse constant series or n<3. Mark n<10 as a small-sample result and require
explicit descriptive/non-causal and ecological-inference qualifications. These
thresholds are product guardrails, not proofs of statistical reliability. Stronger
inference, weighting or time-series dependence needs a different specification.

Tests: exact +1/−1 and hand-computed nontrivial correlation, constant inputs,
missing pairs, duplicates, ordering invariance and proof that changing output
top K cannot change the coefficient. Evidence must retain the full paired input.
Do not implement this as a side task while fixing the MCP cap.

## Shared completion requirements

One step per record; preserve generation/quality checks, resource limits and
numerical evidence. Re-run relevant tool/recipe/evidence tests and AQ-02 tasks.
Version breaking contracts consistently; document disable/rollback and any
artifact migration. New data acquisition, publication and production enablement
are separate actions. Unknown source semantics stop the affected operation.
