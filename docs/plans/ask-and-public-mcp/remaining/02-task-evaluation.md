# AQ-02 — Task-level quality evaluation

**Status: planned. Offline steps 02A/02B are ready. Build 02C locally; live calls
require explicit provider/model and budget authorization.** This implements the
evaluation subset of AT-04, not its release or publication work.

## Problem

The initial exploratory evaluation used a CLI as the model's tool interface and
relaxed MCP limits. AT-05's tests establish deterministic behavior, not that a
cheap model chooses the right tools or reliably states their caveats. Catalog
search drift is not an answer-quality score.

Read `scripts/mcp_eval_client.py`, `agent.py`, `llm_client.py`, `ask_context.py`,
`answer_check.py`, `ask_guard.py`, `tests/at02_env.py`, `tests/at03_env.py`,
`test_at02_loop.py`, `test_at05_quality.py`, `test_at05_ranking.py`,
[AT-04](../04-evaluation-and-release.md) and the
[historical experiment](../at-04-initial-mcp-eval.md).

## 02A — Versioned task set and independent expectations

Add `data/eval/ask_tasks.json` with stable IDs, RO/EN prompt variants, synthetic
fixture selection, expected tool/selection or refusal, mandatory qualifications,
forbidden claims and optional pinned-corpus expectations. Reuse existing fixture
builders. Store hand-checked expected numbers, not snapshots copied from a model
answer or from the implementation under test without independent calculation.

Minimum cases beyond AT-04's T01–T20:

| Case | Required outcome |
|---|---|
| Full-question Brașov stays per resident | Recipe and its ratio unit; never the count as per resident |
| Generic current county population | Disclosed resident default, actual resolved year |
| Current top cities | `rank_entities`, domicile label, full eligible set, communes excluded |
| Explicit resident city population | Limitation; never relabel domicile figures |
| Cities plus density | Current capability refusal; built-up hectares are not administrative area |
| Generic unemployment | Current definition clarification; no newly invented default |
| Births from two sources | Preserve each source/definition and unverified-total qualification |
| County change | Exact endpoints, complete ranking and stated excluded entities |
| Follow-up year/place | Same definition, changed coordinate, re-run against current generation |
| Wrong unit/year/sign/entity | Must not be reported as a verified claim |
| Default public scan refusal | `query_budget`, no numbers inferred from a preview |
| Election prediction | Out-of-scope answer without statistical invention |

The historical experiment's “current” ranking was pinned to 2025. Current AT-05
data resolves 2026. Pin explicit-year golden cases and assert latest-year
resolution separately. Never change expectations because a model chose another
year. Treat historical population-per-built-up-hectare calculations as that
specific measure, not general population density.

Acceptance: validate task JSON, IDs, fixture/source references and RO/EN pairs;
prove small fixture results by independent arithmetic (e.g. 120 stays / 60 people
= 2; winner after row 200; one larger excluded commune). Missing copied-generation
data skips only those cases, not all offline cases.

## 02B — Deterministic runner and report

Add `scripts/eval-ask-tasks.py`. Default to offline replay. Script provider
responses with the existing helpers but execute real tools and actual Ask
budget/context/verification logic. Exercise direct tools and native MCP transport
separately; record the surface, settings and whether tool choice was scripted.

Report per task: outcome/reason, source/definition/key/year/unit, numerical and
qualification checks, generation, dispatch/execution/cache counts, bytes,
latency, tokens when known, skipped prerequisites and failure category. Include
prompt/task/config versions and dirty code hash. Aggregate denominators must
exclude skips and distinguish unsafe answers from legitimate refusals.

Use deterministic assertions for structured data and known mandatory statements;
queue nuanced prose for human review rather than using an unbudgeted LLM judge.
Zero unsafe accepted claims, secret leaks or numerical deviations is required;
do not hide them behind an average score. Scripted tool choice must never be
labelled live-model quality. Reports default to metadata and redacted summaries;
contentful prompt/answer/trace retention requires an explicit option and consent.

Acceptance: all supported synthetic cases pass; intentionally wrong answers fail
for the right reason; missing usage/pricing is unknown; repeated refusals, failed
providers and cancellations produce reports and release resources. Run related
agent/transport tests. Do not rebuild search or chart baselines.

## 02C — Live-provider mode with hard budgets

Use the existing provider adapters and native tool calling. Do not add providers
or route inference through the public MCP server. Public-MCP client evaluation
is a separate mode: the client owns inference and uses the default public gate.

Require explicit live mode, model/provider, task IDs, repetitions, request/token
ceilings, and a declared spend ceiling with an explicit price schedule. Enforce
pre-dispatch worst-case reserves, include retries and reasoning/output allowances,
and settle against reported usage. Without a defensible upper bound, refuse the
paid mode; do not guess a price or interpret absent usage as free. Keys come from
the existing secure input/environment path and never enter report arguments.

Test this accounting offline with fake provider/clock/usage responses. Prepare
commands first. Actual runs occur only after authorization; compare at least
three repetitions of multi-step cases using the same task version/generation and
settings. Capture quality, cost and latency per selected model. A provider being
listed in configuration is not evidence that it passed.

Completion records must distinguish 02A fixture correctness, 02B loop behavior,
02C runner readiness, and separately authorized live results. Rollback removes
the optional runner/task additions; it must not require a corpus migration.
