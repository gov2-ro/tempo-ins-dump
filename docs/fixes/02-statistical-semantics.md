# FIX-02 — Verified aggregation and KPI provenance

Status: phase 1 implemented on fix/02-aggregation and merged to audit-fixes (not yet on main) (shared aggregation_policy, composer/insights/headlines migrated, provenance fields); phase 2 (grouped API queries, agent, frontend, FIX-03 profile backfill) not started. Priority: P0. Owner: shared statistical services.
Dependencies: FIX-03 repairs and expands profiles; immediate suppression can ship
first. FIX-06 and FIX-08 consume this contract.

## Problem and entry points

Live IND118A electricity headline is 115,962 million kWh for 2023, while the source
total is 57,981; custom headline SQL sums the total and its components. IPC102A
averages category indices without weights and describes the result as consumer
prices. These queries bypass verified structure rules.

POP107A v1/v2/insights report 129,072,774 people for 2025. Local structure lookup
is empty and the composed slice has no filters; both age grains and all geographic
levels are summed. Full-dimensional row keys are unique, so generic deduplication
will not fix this. `insights.py` also has a narrower AVG unit-type list than the
API/agent. An unweighted AVG of rates is not necessarily a valid total either.

Read `dashboard_composer.py`, `dimension_structure.py`, `dataset_meta.py`,
`query_builder.py`, `insights.py`, `headlines.py`, `headline_config.json`,
`dataset_data.py`, `agent.py` and both dataset frontend controllers.

## Required semantic contract

Create a shared aggregation decision used by composed charts, insights, curated
headlines, grouped API queries and agent tools. Keep SQL execution separate from
the semantic decision. It must resolve:

- Dataset, observation grain, unit, requested group_by and caller filters.
- Verified total versus a verified disjoint partition at one level.
- Non-additive quantities: rate, percentage, ratio, index and average-valued
  currency indicators. Currency units alone do not establish additivity.
- Whether weighting is required, which denominators/weights support it, and the
  policy when those are unavailable.
- Overlapping age/geographic/category levels and incompatible units.
- Outcome: valid total, valid explicit slice, labelled approximation, or unavailable
  with a machine-readable reason. Uncertainty must not become a total.

Prefer a verified aggregate row. Otherwise sum exactly one verified partition for
additive values. Use a weighted mean only with valid aligned weights. Unweighted
means may be exposed as explicitly named approximations, never as an official
national/county rate. Suppress uncertain totals while preserving raw table access
and valid user-selected slices. Unknown structure must be conservative for
overlapping domains; do not infer disjointness from absence of a Total label.

For grouped requests, validate dimensions being collapsed, not just dimensions on
an axis. Hierarchical dimensions on an axis also need one grain. Respect verified
`additive` and structure confidence rather than using the unit heuristic alone.
Use one shared non-additive policy and remove divergent lists in consumers.

## API/UI integration

Add provenance to KPI/insight payloads without removing existing fields: source
code, observation period, unit, selected filters/levels, method, verification
status, approximation flag and comparison basis (YoY/MoM/QoQ/points). Define exact
names in tests and document them before downstream agents integrate.

Curated headline configuration should describe slices/methods, not independent
unchecked SUM/AVG SQL. Migrate all existing cards and verify each. IND118A chooses
its real total. IPC102A chooses an actual aggregate source or explicitly becomes
category-specific; if neither is justified, omit the misleading composite card.
Do not manufacture weights to preserve card coverage.

Show a short reason when a previously visible total is unavailable. v1, v2 and Ask
must not independently recompute a suppressed total from raw rows. Keep complete
export semantics separate from chart-window semantics.

## Acceptance tests

Use synthetic fixtures with known answers:

1. Total=100 and components 40+60 produce 100, never 200.
2. Two complete age partitions and three geographic levels yield one valid total;
   unverified overlap suppresses the aggregate but permits a valid explicit slice.
3. Rates 10% and 20% with denominators 90 and 10 yield 11% with those weights;
   missing weights cannot produce a card labelled as a total at 15%.
4. Mixed units cannot aggregate; legitimate additive currency amounts and average
   wages are distinguished by indicator semantics, not identical unit labels.
5. API, composer, insight, headline and agent decisions agree for the same slice.
6. Changes use the declared period/denominator; zero/missing comparators have an
   explicit unavailable change rather than division errors or fabricated zeros.

Read-only real checks: IND118A, IPC102A, POP107A/POP107D, one rate/index dataset and
one mixed-unit dataset. Compare source rows, selected grain and output, not a
hardcoded guessed Romanian population. Baseline chart-pick stability alone is
insufficient. Explain all numerical changes and lost cards before rebaselining.

## Delivery and rollback

First deliver suppression/verified IND118A fix and regression fixtures. Then migrate
consumers behind the shared contract. FIX-03 may backfill structure in a copied
generation; this spec does not authorize overwriting the live corpus. Preserve old
generation artifacts for rollback and record changes in available KPI coverage.
