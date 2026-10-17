# AQ-01 — Public MCP capacity and scan admission

**Status: planned. 01A is implementation-ready; 01B depends on its measurements.
01C requires a reviewed design.** No production limit change is authorized here.

## Problem and required outcome

AT-05 can rank the national locality population through the shared tool, but
public MCP refuses the source at its default 1,000,000-row admission limit.
The copied generation used in AT-05 has a 3,898,870-row locality file. Treat that
as dated evidence, not a constant: read the candidate file's footer each run.

Deliver a reproducible answer to whether this workload can run on the configured
512 MiB, one-worker target, then encode/document only a measured operating
profile. Success must preserve the full eligible set, values, scope and refusals.
Raising a cap until a request returns HTTP 200 is not acceptance.

## Read these files

- `app/services/public_mcp.py`: `McpSettings`, `ScanEstimator`, `Gate._call`, cache,
  deadline/cancellation and `POLICY_VERSION`.
- `app/services/tools/ranking.py`, `period_changes.py`, `data_query.py`.
- `app/services/dataset_meta.py`: `_parquet_dim_values`, `get_aggregation_context`;
  `app/db.py` for DuckDB connection/resource configuration.
- `tests/at03_env.py`, `test_at03_resources.py`, `test_at05_ranking.py`.
- `scripts/mcp_probe.py`, `scripts/release-check.py`, `Dockerfile`, `fly.toml`.
- AT-04's existing [resource gate](../04-evaluation-and-release.md).

## 01A — Build a measurement harness; change no limits in the app

Add `scripts/benchmark-mcp.py` and focused tests for its report/accounting. It
must launch an isolated local candidate process with an explicit data directory,
unset provider keys in the child, and use the real MCP SDK client/lifespan. Do
not benchmark production or reuse an unrelated running server. Require an
explicit output directory and write a machine-readable report there.

Inputs: data directory, output directory, repeat count, explicit candidate MCP
scan/deadline/concurrency settings, and local/container execution mode. Existing
defaults form the control profile. A larger scan cap is allowed **only in the
benchmark child**, visibly recorded; production defaults stay unchanged.

Measure these distinct states, with five fresh-process repetitions for cold
cases and at least 20 samples for each warm case:

1. Cold startup → initialize/list → discover → describe → exact year city rank.
2. Direct rank as the first analytical call, so no prior metadata cache hides cost.
3. Same request from the result cache; then differing years/filters that miss the
   result cache while keeping metadata warm. Do not combine their percentiles.
4. Latest-year rank, explicit-year rank, county-filtered rank and top K = 1/30/100.
   Smaller K must not change the eligible set or permit capped input.
5. Oversized/unknown-source admission, simultaneous MCP calls, cancellation,
   a timed-out worker and the first request after it. Keep the slot until work ends.
6. Mixed MCP plus REST/search/export load, using the bounded phases in AT-04.
   A one-slot MCP gate does not limit independent REST/Ask requests.

Report code identity (commit plus dirty diff hash), generation/file fingerprints,
OS/runtime/container limit, all settings, row estimates, cold/warm/cache labels,
wall/CPU time, process-tree peak RSS and container memory peak, result/wire bytes,
cache hits, refusals, OOM/restarts and provider-call count (must be zero).
Normalize macOS/Linux RSS units; RSS alone is not total cgroup memory usage.
Bound the harness itself and always shut down its child/container on failure.

Numerical parity compares the MCP result with the direct shared-tool result for
the same selection/generation: rows/order, eligible/excluded counts, units,
source definitions, scope and warnings. Ignore request IDs/timing only.

### Acceptance for 01A

- Default profile reproduces `unavailable/query_budget` for an over-limit fixture
  and proves the expensive handler was never dispatched.
- Candidate fixture with a winner after row 200 and a larger commune preserves
  the correct city ranking and exclusions through the real MCP client.
- Tests cover report schema, percentile grouping, unit conversion, cleanup and
  timeout/error accounting. Missing measurements are null/not-run, never zero.
- Write a report even when Docker/corpus is unavailable; explicitly leave the
  Linux gate unrun. An unconstrained macOS success is not a 512 MiB pass.
- Run existing resource/ranking tests; add the harness command/report to the
  completion record. Stop here if assigned only 01A.

## 01B — Select a measured profile; preserve default-deny behavior

Use 01A's results on the exact candidate image/data. Candidate scan budgets must
also exercise worst admitted requests from every scan-gated tool, including
multi-source recipes and varied selections, not just one cached city rank.

Required gates: no OOM/restart, unexpected 5xx, lingering work or numerical
differences; hard deadlines enforced; warm p95 targets from AT-04 (<2 s metadata,
<5 s analytical calls); peak container memory at most 75% of its configured
limit during the measured mixed workload. This headroom is a proposed release
acceptance threshold, not an existing measured property. Record cold latency
separately and evaluate it against actual client timeouts in AQ-06.

If a profile passes, add an operator-facing candidate configuration and regression
tests for settings validation/admission/cache invalidation. Prefer existing
`TEMPO_MCP_*` settings; do not introduce a per-dataset bypass or silently raise
global defaults. A new admission policy needs `POLICY_VERSION` invalidation.
Document exact tested workload limits, rollback to the prior settings, and that
deployment/production enablement is still pending owner authorization.

If the 512 MiB profile fails, publish the failure and the measured alternatives:
a larger **local test container** or reducing work in 01C. Do not provision a
larger Fly machine or weaken the acceptance threshold to close the task.

## 01C — Conditional optimization design, not a cheap-model coding task yet

The current footer estimate counts source-file rows once; it is a conservative
source-footprint bound, not a count of every row visit. Cold aggregation context
can scan each dimension of the whole file, and period discovery also reads the
source. Therefore a `WHERE year=…` result count or row-group estimate for the final
SQL alone is **not** an admissible replacement for the existing bound.

If measurements demand optimization, submit a small design covering every
preflight/metadata/quality/query scan and cache-miss path. Choose either audited
bounded context acquisition plus conservative row-group pruning, or a
generation-bound precomputed result/context artifact built by the shared policy.
Do not implement both or write a second aggregation engine.

The design must specify source/artifact fingerprints, generation changes and
mid-call replacement, stale/missing artifact refusal, duplicate-key checks,
classification/version identity, build/staging/rollback, and the mathematical
upper bound used for admission. Missing/ambiguous statistics retain the full
bound or refuse. Only after review split it into fixture, implementation and
staging tasks. Rerun 01A/01B; caching one happy-path answer is not a capacity fix.
