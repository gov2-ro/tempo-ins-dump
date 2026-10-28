# Ask and public MCP implementation handoff

**Current handoff (2026-10-17):** use [remaining work](remaining/README.md) for the
next implementation session. AT-05 and this handoff are saved together on `fix/ask-answer-quality` in the isolated
quality worktree; the older baseline/prompt below is historical and must not be
used to recreate completed work. The new packages are specifications only.

## Status and outcome

Original specification dated 2026-10-15. The implementation records below describe
subsequent completed work; the current next-step handoff is linked above.

Implementation status: **AT-01 implemented 2026-10-15** on branch
`at/01-analytical-tools` (from `pa/00-baseline` 8a9689d), awaiting owner review.
See [at-01-record.md](at-01-record.md), including the proposed AT-00 amendments.
**AT-02 and AT-03 implemented 2026-10-16** on branch `at/02-ask-runtime`, built on the
owner-reviewed integration branch `integ/at01-ui-rhythm` (81030f5), awaiting owner review:
[at-02-record.md](at-02-record.md) (bounded, recoverable Ask over the shared tools),
[at-03-record.md](at-03-record.md) (public read-only MCP at `/mcp`, disabled by default).
Neither is deployed, pushed or merged; no live provider, client or Fly run has happened.
Formal AT-04 acceptance (task evaluations, onboarding, resource/cost evidence) is pending.
The [exploratory CLI evaluation](at-04-initial-mcp-eval.md) is not native-provider acceptance.
The hosting split and cutover steps are in [05-hosting-and-cutover.md](05-hosting-and-cutover.md).

People should be able to ask a supported statistical question, clarify its
definition, obtain a correct bounded calculation or an actionable refusal, and
open the underlying evidence. They should also be able to use these capabilities
from their existing ChatGPT/Claude accounts without providing model API keys to
INS+. The public MCP supplies data and deterministic calculations; the chat
client supplies model inference.

Implement shared analytical tools first, then their Ask and public-MCP adapters.
Improving the tools is necessary for both interfaces. MCP transport alone does
not fix discovery, missing options, incomplete data or numerical mistakes.

Answer-quality follow-up: [AT-05](06-answer-quality.md), on `fix/ask-answer-quality`
from `22d9d4d`: eight tools under `tempo-tools/2`, full-question discovery, explicit claim
contradictions and one-year entity rankings. Not deployed; native-provider evaluation and
public capacity sizing remain open.

## Historical AT-01 baseline and source of truth

The code to extend is **`pa/00-baseline`**, inspected at
`8a9689d959637c47453bc25f1f1dd5c4cfb3f787`, local worktree
`/Users/pax/devbox/gov2/tempo-alpha`. It includes the integrated FIX-02/03,
structural charts, PA-01/02/03, static engine and the Oct 15 Ask changes.

These specs are authored in the older `tempo-ins-dump` worktree on
`fix/03-corpus-repair`. **Do not implement against that older application's
source or against `main` merely because this document is there.** The local
alpha branch also contains commits absent from its remote-tracking branch.
Before work, inspect `git status`, worktrees and ancestry, record the actual
baseline, and use an isolated branch based on the alpha code. On another
machine, obtain that code before proceeding. Copy this spec directory into the
implementation checkout; no absolute path above is a runtime dependency.

Read the target checkout's `AGENTS.md` first. Then read these target documents:

- `docs/activity-history.md`, especially Oct 12–15;
- `docs/plans/public-alpha/pa-01/record.md` and `pa-03/record.md`;
- `docs/plans/public-alpha/pa-00/answer-records.md` and `answers.json`;
- `docs/plans/public-alpha/pa-04/release-record.md`;
- the Oct 15 entries in `docs/BACKLOG.md`.

The inspected copied generation is `9b3e065d2fe9bb1df9bae2131b7bdeae9be3426f3c82b9a9954f7e6dc8f45550`
at `../tempo-gen-20261012/data` (since 2026-10-28 the repo's `data/` holds its successor `062bd2b0`, same corpus). Corpus tests must verify their generation and
skip explicitly if it is unavailable. CI must work using synthetic fixtures.

Observed failures, for reproduction rather than permanent corpus constants:

| Evidence | Consequence |
|---|---|
| Three completed DeepSeek runs in the retained log stop at 12 tools, 8 model calls, or an empty `length` response | Search/refusal loops and incomplete provider output become unusable answers |
| A 2,732-row result is 186,658 characters; category output is 49,232 | Large results are repeatedly sent back to the model |
| The 22 traced tool executions total 974 ms; the longest is 248 ms | Increasing the HTTP timeout is not the first remedy for this sample |
| Ask schema exposes 20 of AMG157G's 261 periods, `time_range=null` | The model cannot reach recent values through its advertised tools |
| Ask ignores the site's concept-search and recipe services | Reviewed answers already available to the web UI are harder to reach through Ask |
| A fake arbitrary-format key survives in debug logs while HTTP output is redacted | Redaction must happen before logging, including non-`sk-` keys |
| Single-age population county results omit 85+ but say `valid_total` | A structurally valid partition can still be an incomplete population scope |

The retained log is `data/_archive/gen-20261012/reports/uvicorn-8080.log`. Treat it as
potentially credential-bearing: extract whitelisted fields, never paste the raw
log into an issue, test fixture or prompt. Two Anthropic 401s in it are distinct
authentication failures, not evidence of analytical incapability. This small
sample does not estimate an overall answer-success rate.

## Packages and integration order

| ID | Specification | Deliverable | Depends on |
|---|---|---|---|
| AT-00 | [00-tool-contract.md](00-tool-contract.md) | Versioned tool inputs, results, provenance and limits | Baseline for AT-01 and adapters |
| AT-01 | [01-analytical-tools.md](01-analytical-tools.md) | Shared discovery/options/query/recipe/change/evidence tools and numerical tests | Contract |
| AT-02 | [02-ask-runtime.md](02-ask-runtime.md) (done: [record](at-02-record.md)) | Bounded, recoverable Ask using AT-01; safe logs and follow-ups | AT-01 |
| AT-03 | [03-public-mcp.md](03-public-mcp.md) (done: [record](at-03-record.md)) | Disabled-by-default public MCP with seven read-only tools and resource bounds | AT-01 |
| AT-04 | [04-evaluation-and-release.md](04-evaluation-and-release.md) | Task evaluations, package/onboarding artifacts and release evidence | AT-01/02/03 |

Use small functional commits within each package. AT-01 includes fixtures and
adapter tests; do not defer all testing until AT-04. AT-02 and AT-03 both touch
configuration and application startup: integrate sequentially or reconcile the
shared changes explicitly. Implement one scoped package at a time. Do not
upgrade every dependency or refactor the dashboard as part of this work.

## Decisions and boundaries

- Preserve `data_query.run_query`, aggregation policy, grain guards, recipes,
  evidence and generation identity as the statistical authorities. New tools
  call them; adapters must not recreate their SQL/aggregation decisions.
- Keep the existing `/api/ask` and NDJSON-debug response fields compatible.
  Version new tool contracts; adapt the old data-panel/chart shape explicitly.
- Public MCP v1 is anonymous public-data access, with resource limits. No
  INS account, model key, OAuth server, billing system or personal data is needed.
  OAuth/personal quotas may be a later package if actual abuse requires them.
- No LLM call, MCP sampling request, arbitrary SQL, Python execution, filesystem
  access, general URL fetch or dev endpoint dispatcher is a public MCP tool.
- Preserve the dev MCP for local development. Publishing it wholesale is outside
  scope. Its current stdio process is not the public HTTPS endpoint.
- The analytical and Ask changes do not alter corpus files/tables. Any corpus
  repair or source-total refresh requires a separate copied-generation plan.
- Existing static query/search/evidence parity must remain passing. The static
  site does not host MCP or server-funded Ask; it may link to the Fly MCP. A new
  dynamic analytical UI need not be ported to JavaScript in this milestone.
- Do not add more providers/models unless needed to fix a verified adapter bug.
- Fly deployment, changes to machine size/billing, publication in a directory,
  provider purchases and user recruitment need separate explicit authorization.
  Produce reviewable artifacts and local evidence first.

The intended first distribution is an INS statistics MCP plus a ChatGPT plugin
package and Claude setup instructions. Plugin publication is a later operational
step, not a prerequisite for locally implementing AT-01/02/03.

## Completion evidence

Each package must leave a completion record with baseline and final code refs,
changed files, checks run, numerical before/after examples, intentional behavior
changes, remaining limitations, configuration, and rollback instructions. A
skipped test, mock-provider conversation or inspected manifest is not a live
provider/client/load pass. Keep implementation, client validation and production
release statuses separate. Never rebaseline unexplained numerical changes.

## Historical AT-01 handoff prompt (superseded for new work)

```text
Implement AT-01 from docs/plans/ask-and-public-mcp/, then stop with its completion
record. Read README.md, 00-tool-contract.md, 01-analytical-tools.md and the target
checkout's AGENTS.md first; read the other packages to preserve integration.

Start from pa/00-baseline including 8a9689d959637c47453bc25f1f1dd5c4cfb3f787
(currently ../tempo-alpha), not this older fix/03-corpus-repair checkout or main.
Inspect worktree state and newer commits before selecting an isolated branch.
If this baseline is unavailable, report the missing code rather than rebuilding
already completed PA work from an older checkout.

Use small temporary DuckDB/parquet fixtures for numerical tests. Read the real
corpus only when needed; never modify it as a test. Reuse the existing shared
query/policy/grain/recipe/evidence services. Preserve REST/static compatibility.
The tools must make source, definition, geography, period, unit, coverage,
completeness and generation explicit. Refusals must suggest a safe next action.

Do not deploy, publish a plugin, make paid model calls, repair the corpus, or
change production configuration. Implement and verify the requested package,
update its status only with evidence, and report what is ready for review.
```

For a later session, replace `AT-01` and its spec filename with the next accepted
package. To authorize all engineering packages, explicitly say AT-01 through
AT-04; the publication/spend boundaries above still apply.

