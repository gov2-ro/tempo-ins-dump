# Audit remediation specifications

Status (2026-10-05): FIX-01 phases 1–2, FIX-03 phase 1 and FIX-05 phase 1 merged to the
`audit-fixes` integration branch (not yet on main, not deployed); the rest are in progress
or not started. Each spec's Status line is authoritative. Based on the
2026-10-03 audit. Current behavior: [operating reference](../CURRENT_STATE.md).
Priorities: [backlog](../BACKLOG.md). Historical evidence: [activity log](../activity-history.md).

## Work packages

| ID | Priority | Deliverable | Dependencies | Main ownership |
|---|---|---|---|---|
| [FIX-01](01-api-safety-and-sdmx.md) | P0 safety; P1 SDMX | Safe requests and consistent SDMX contracts | None for safety; coordinate export limits with FIX-04 | API routers, query boundary |
| [FIX-02](02-statistical-semantics.md) | P0 | Verified aggregation shared across all consumers | None for suppression; repaired profiles from FIX-03 for coverage | Composer, insights, headlines, semantic policy |
| [FIX-03](03-pipeline-and-corpus.md) | P1 | Retryable pipeline and validated corpus generations | FIX-02 policy for overlap/additivity | Pipeline, import/classification, split repair, audit |
| [FIX-04](04-complete-exports.md) | P1 | Complete exports with honest limits | FIX-01 request models; coordinate query builder changes | CSV/XLSX/SDMX export behavior |
| [FIX-05](05-release-and-regression-gates.md) | P1 | Reproducible, validated deployment with search | FIX-03 manifest; tests from each package | Staging, Docker, CI, FTS |
| [FIX-06](06-place-indicators.md) | P1 | Correct place indicator identities, dates and changes | FIX-02 aggregation policy | Place services/config/UI |
| [FIX-07](07-responsive-dataset-ui.md) | P2 | Usable dataset controls and chart labels | FIX-02 warnings/provenance payload for disclosure | v1/v2 frontend and CSS |
| [FIX-08](08-ask-budgets-and-privacy.md) | P2 | Bounded Ask requests and explicit persistence/logging | FIX-01 request validation; FIX-02 safe tools | Ask router, agent, LLM client, chat UI |

Dependencies identify integration order, not a requirement to start every package
at once. Land FIX-01's safety patch first. FIX-02 may immediately suppress unsafe
headlines before corpus repairs. FIX-03 and FIX-02 must agree on the meaning of
verified structure; uncertainty must remain visible rather than becoming a total.

Each package is intended for one coding agent and an independently reviewable PR.
FIX-01 and FIX-04 both touch dataset/SDMX routers; FIX-02 and FIX-03 both affect
structure semantics. Sequence those shared-file edits or agree on contracts first.
The index describes possible delegation, not authorization to publish production
changes or run several writers against the same corpus.

## Handoff instructions

Give the agent AGENTS.md, the package spec, and this index. Ask it to:

1. Reproduce the relevant failure against a temporary fixture or copied corpus.
2. Implement the smallest coherent behavior change and its meaningful tests.
3. Preserve existing URLs and response fields except documented, necessary changes.
4. Produce before/after evidence, migration/rollback instructions where relevant,
   and a description of remaining uncertainty.
5. Update the package status, backlog and activity log only after acceptance checks
   pass. Keep code implementation and corpus publication as distinct operations.

Use source contents and actual schema rather than fixed line numbers or historical
corpus counts. Do not silently rebaseline numerical changes or delete untracked
parquets. Do not run deprecated `12-parquet-to-sdmx.py` as a repair.

## Common acceptance contract

- Unit tests use small temporary DuckDB/parquet fixtures and do not require a
  maintainer's corpus, network, provider key, or absolute home-directory path.
- Numerical tests assert known totals, filters, grain, units and periods. A chart
  rendering or an HTTP 200 alone does not establish correctness.
- Real-corpus checks run read-only first; repair reports distinguish registered,
  canonical, parent, split, leftover and unavailable datasets.
- Browser changes require representative v1/v2/place/Ask smoke checks as applicable.
- Run `python -m pytest tests -q` in the configured environment and the relevant
  chart/search evals. Explain expected changes before updating baselines.
- A completed package does not automatically clear release blockers in other
  packages. FIX-05 collects their checks into the publication gate.

## Baseline evidence, 2026-10-03

38 tests passed with 3 deprecation warnings. Chart eval: 1,986 existing baseline
cases unchanged, 2,116 additions. Search eval: 17 result sets unchanged, 2 ordering
changes. Scan: 4,274 readable parquet files, 4,102 matrices, 179 files without
metadata, 7 metadata rows without files, 3,679 view profiles, 596 files without
profiles, 1 profile without a file. There were 57 files with NULL dimensions and
162 whose distinct TIME_PERIOD values failed the supported-format threshold.
These directory counts include leftovers; they are not published-defect counts.

No implementation, production repair, deployment or paid Ask call is included in
this specification change. Historical run reports remain evidence, not commands
to reproduce against production.
