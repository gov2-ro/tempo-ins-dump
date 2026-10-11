# PA-01 — One selection, one statistical decision

Status: proposed. Owner: shared query services and rendering correctness.
Dependencies: PA-00 baseline and source fixtures. Audit: A01–A06, A08, A09;
A13/A14 if Ask is included. Builds on FIX-01/02/03/06/08.

## Problem and scope

The audit demonstrates divergent behavior across REST, Ask and development MCP,
silently ignored filters, lost chart series, stale responses and unintended period
alignment. Existing REST aggregation safeguards are the starting point. Extend
their reach and missing checks rather than replacing them with another policy.

Entry points: `app/services/request_validation.py`, `aggregation_policy.py`,
`query_builder.py`, `dataset_meta.py`, `agent.py`, `answer_check.py`,
`app/routers/dataset_data.py`, `app/static/js/dashboard-v2.js`, `compare.js`,
`ask.js`, and `tools/tempo-dev-mcp/server.py`. PA-00 identifies additional custom
headline/composer/export paths. Verify current symbols at the chosen commit.

## Shared boundary

Use one service to validate the request, resolve an effective selection, decide
statistical validity, execute a bounded or complete query, and return evidence.
Transport adapters handle HTTP/tool serialization; callers must not independently
choose SUM/AVG, drop a filter, broaden an empty query or override a refusal.

The following are logical fields; map them to existing response fields where
possible and lock a versioned serialized schema in tests before PA-02/03 integrate.

| Request meaning | Required content |
|---|---|
| Source | Dataset identity and requested generation if supported |
| Selection | Typed filters, geography identity/level, requested period policy |
| Operation | Raw slice, approved aggregation or supported transformation; grouping |
| Result window | Valid bounded limit/pagination or explicit complete export |
| Approximation | Explicit opt-in; default false across every adapter |

| Response meaning | Required content |
|---|---|
| Identity | Contract version, source generation, effective selection and resolved periods |
| Decision | `ok`, `unavailable`, or invalid-request error; stable reason and blocking dimensions |
| Values | Rows, column roles, full series identity, units/scale and observation grain |
| Method | Source total/partition/weights/transformation, evidence references and warnings |
| Completeness | Complete/truncated state, limit/cursor and counts when known |
| Provenance | Source codes/definitions, reference dates, source update date if known |
| Recovery | Valid alternative selection where deterministically known; never fabricated advice |

Unknown columns, invalid shapes and unsupported operations fail before execution.
Unknown dimension values must fail or yield an explicit empty selection, never be
ignored. Distinguish invalid input, a legitimate empty slice and an unsafe operation.
Bind values and paths; validate identifiers against the resolved schema. Apply this
to MCP sampling as well as analytical queries. Preserve existing HTTP contracts
unless a necessary change is documented and adapter-tested.

## Statistical and quality requirements

- Reuse source-total, disjoint-level and non-additive measure rules. Validate both
  collapsed dimensions and dimensions displayed on axes. A rate/mean is not
  additive because its unit resembles a count/currency.
- Reject unfiltered time collapse for stocks/means/indices unless a supported,
  explicitly named operation defines it. Latest selection must resolve to actual
  compatible data, not a metadata label beyond available observations.
- Bind total/partition verification to its applicable periods, selection and
  generation. An old dataset-wide check cannot certify a changed slice.
- Conflicting full keys and overlapping partitions are different conditions.
  Guard both. Use generation-bound quality evidence with enough coverage to prove
  the requested slice, or a bounded query-time check with explicit resource limits.
- Where evidence is only file-wide, conservatively withhold analytical operations
  until the selected slice is verified. Raw observations may remain accessible with
  their conflict status; never deduplicate or silently choose one conflicting value.
- Absent/stale quality evidence cannot become implicit approval. A generation
  switch invalidates decisions/caches tied to the previous generation.
- No ranking, correlation, normalization or recipe may consume truncated inputs
  while presenting its output as complete. Raw downloads retain FIX-04 semantics.

## Rendering and comparison

1. Give each tile/request a monotonically changing selection version. Rendering,
   loading/error state and URL/label updates must agree on that version. Abort when
   useful, but check version on completion even if cancellation fails. Invalidate
   on dataset, filter, period and view changes and component disposal.
2. Chart series identity includes every remaining dimension, including geography
   and units where relevant. Repeated chart keys require explicit representation
   or refusal. Chart and table must preserve the same selected observations.
3. Scatter comparison uses stable geographic identities at the same level and the
   latest common compatible period by default. Assert one observation per joined
   key; show matched/excluded areas. No implicit lag or nearest-year fallback.
   Lag controls are deferred; incompatible comparisons explain the restriction.
4. Constant axes or fewer than two valid pairs yield unavailable correlation,
   never zero. Report sample size; reject nonfinite values and distinguish excluded
   missing observations. Association is not labelled as a causal effect.
5. Citations resolve to the canonical current dataset route, language and effective
   slice. Maintain old URL aliases where applicable; test the actual destination.

## Functional increments

- PA-01a: typed shared query boundary and REST/Ask/MCP adapter parity; safe samples.
- PA-01b: slice/generation quality enforcement, custom-consumer inventory closure,
  and completeness checks. Corpus repairs remain separate FIX-03 work.
- PA-01c: response ordering, series identity, comparison alignment and citations.

Each increment is independently testable. Optional debug logging records decision
reasons, request versions and timings without keys or unbounded row payloads; use
the existing debug controls. Keep ordinary responses useful without debug mode.

## Acceptance fixtures

| Fixture | Required result |
|---|---|
| Unknown `BOGUS` filter / malformed filter list | Rejected through every adapter before querying |
| Source total 100 plus components 40, 60 | Approved total 100, never 200 |
| Overlapping age/geographic partitions | Same refusal/effective slice across consumers |
| Rates 10%, 20% weighted by 90, 10 | 11% with valid weights; no official 15% average |
| Duplicate full key with values 10, 11 | Conflicting-grain decision; no arbitrary selection |
| Conflict outside a separately verified slice | Valid slice allowed only with sufficient evidence |
| Same selection after generation changes | Previous verification cannot silently carry over |
| Stock observations in two years | No sum across time under an ordinary county ranking |
| Cluj 10, 11 and Iași 20, 21 over two years | Two series; all four values agree with table |
| Older response completes after newer selection | Latest label, values, URL and loading/error state agree |
| Different latest years, one common earlier year | Common year selected; no common year is unavailable |
| Constant scatter axis / insufficient pairs | Correlation unavailable, with matching count |
| Apostrophe/adversarial filter literal | Bound as data or rejected; no SQL structure change |
| Truncated result | Explicitly marked; complete analytical consumers cannot use it |

Read-only regressions include the audit's POP107A policy discrepancy, the Ask
invalid filter, FOM106F delayed year response, and PA-00 answers. Use synthetic
fixtures for deterministic numerical assertions; do not freeze guessed live totals.
Run the full suite and relevant chart/search evals; smoke affected v1/v2/place,
comparison and optional Ask paths at desktop and 320/390px.

## Optional Ask gate and exit

If Ask is exposed, also use authoritative server configuration, searchable options
and actual coverage from PA-02. Require real provider/tool smoke evidence for each
advertised combination. Every displayed factual claim must bind to a selected
result row or supported deterministic calculation; do not claim semantic
verification from numeric presence alone. Preserve all cited results across turns,
or visibly restrict the supported workflow. Full conversational derivations may
remain deferred by excluding Ask from the release.

Exit: all exposed consumers pass parity/quality checks and cannot bypass them via
another route. Internal MCP exceptions must be explicitly tracked and remain
unadvertised; they do not count as completed PA-01 adapter work.
Rollback must not restore a known unsafe analytical path: disable the affected
capability or return to a previously verified complete code/data combination.
