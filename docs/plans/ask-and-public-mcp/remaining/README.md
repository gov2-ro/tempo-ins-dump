# Remaining Ask/MCP work: implementation handoff

Written 2026-10-17. **Status, later on 2026-10-17:** 01A, 02A/B, 03A/B, 04A/B/C and
05A are implemented on `fix/ask-answer-quality` (code-ready; completion records
`aq-*-record.md` in this folder). Not done: 01B/01C (need a Linux 512 MiB run),
02C (live runs need authorization), 05B–05D, AQ-06B/C. AQ-06A (separate-origin Ask)
is code-ready on `aq/06a-separate-origin` (2026-10-25). Nothing deployed.

Originally: implement one numbered step per session, then stop. These
packages break the remaining AT-04/backlog work into tasks suitable for cheaper
coding models; they do not authorize deployment or paid evaluations.

## The baseline to preserve

The implementation is in `.worktrees/ask-answer-quality`, branch
`fix/ask-answer-quality`, inside the main `tempo-ins-dump` checkout. Its base is
`22d9d4d`, but **use the later commit containing AT-05 and this handoff**, not
that base alone. The implementation and specs were initially uncommitted and
are saved together on this branch. A fresh branch at the base hash does not
contain AT-05. Preserve any subsequent working changes; never reset/clean the
worktree or reconstruct the feature from the older checkout. Before starting,
inspect status/history: later commits may supersede this note.

Already implemented, documented in [AT-05](../06-answer-quality.md):

- Eight shared tools under `tempo-tools/2`, including one-year `rank_entities`.
- Full-question tourism-ratio discovery, current-year/city intent and disclosed
  population defaults; no silent resident-to-domicile substitution.
- Explicit unit/year contradiction checks, partial unverified sums, readable
  tables, preview disclosure and generation-bound ranking JSON replay.
- Numerical, scripted Ask, native MCP and browser tests. Search/chart results
  match the starting code on the same corpus; old baseline drift is unrelated.

Validation is recorded precisely in AT-05, including the two stale seven-tool
assertions fixed after the full-suite run and the passing targeted reruns.
These are not live-provider, hosted-connector or 512 MiB acceptance results.

## Packages and order

| Package | Deliverable | Start condition | Suggested session size |
|---|---|---|---|
| [AQ-01](01-mcp-capacity.md) | Reproducible capacity measurements and a tested scan-budget profile | Ready: start with 01A | One step; do not invent a scan optimization |
| [AQ-02](02-task-evaluation.md) | Versioned task fixtures, deterministic replay, budgeted live runner | Ready: 02A/02B; live runs need explicit budget | Fixtures, runner, live adapter separately |
| [AQ-03](03-claim-verification.md) | Better value/entity/year/definition checks | Ready; preserve AT-05 tests | 03A, then 03B |
| [AQ-04](04-discovery-and-messages.md) | Reviewed defaults, actionable choices and bilingual messages | Ready; no new unemployment default | One subsection at a time |
| [AQ-05](05-analytical-extensions.md) | City-change classification, then reviewed joins/derived measures | 05A ready; other steps have data/design prerequisites | Never implement the whole file in one pass |
| [AQ-06](06-client-and-release.md) | Separate-origin integration and client/release evidence | Local code ready; exposure depends on capacity/quality gates | Code, local checks, external checks separately |

Recommended sequence: **01A → 02A → 02B → 03A → 03B → 04A/B/C**. Then use the
measured results for 01B and the task failures for the next product change.
City changes (05A) can follow independently. Density and correlations are not
prerequisites for a useful, bounded first release.

## Rules common to every package

- Read the target checkout's `AGENTS.md`, this page, the selected spec and AT-05.
  Read only the source/test files named for that step before expanding context.
- Preserve `data_query.run_query`, aggregation policy, grain guards, source-total
  checks, recipes and generation identity. No model SQL, joins, sums or ranking.
- Use temporary DuckDB/parquet fixtures. Real corpus checks are read-only against
  an explicitly selected copy; record its generation. Do not run rebuild scripts.
- Tests must assert values, definitions, exclusions and refusals, not only HTTP
  success. Do not rebaseline unexplained numerical or retrieval changes.
- Keep the existing shared contract/adapters in agreement. Additive optional
  fields may stay on v2; breaking input/result semantics require a separately
  documented version change across Ask, MCP, replay, links and smoke scripts.
- No unrelated refactoring, dependencies, new providers, production settings,
  live deployment, directory submission or paid calls as a side effect.
- Existing debug/provenance hooks should explain new decisions without logging
  keys or unrestricted user/provider content. Do not add an LLM judge by default.
- If a required environment/source is absent, finish the local engineering and
  report that specific gate as `not_run` or `blocked`; do not report it as passed.

## Definition of done for one step

Run its targeted tests and the repository checks applicable to the changes.
Before a commit, run `python -m pytest tests -q` in the documented virtualenv;
browser changes also need 320/390/1280 px checks. Search/chart/static changes need
the existing eval/parity checks with expected differences explained first.

Add a short completion record beside these specs with: step, baseline and final
working state/commit, changed files, exact commands/results/skips, numerical
examples, generation, configuration, rollback and remaining gates. Update
`docs/activity-history.md` and the matching backlog item only to the extent
proved. Code-ready, model-validated, client-validated and deployed are separate.

## Copy-paste prompt for a cheaper coding model

```text
Implement AQ-01 step 01A only, from
docs/plans/ask-and-public-mcp/remaining/01-mcp-capacity.md.

Use the AT-05 working tree in .worktrees/ask-answer-quality (fix/ask-answer-quality),
at the commit containing AT-05 and these specs. Inspect current status/history
first and preserve subsequent working changes. The base commit 22d9d4d alone
is insufficient. Preserve unrelated work.

Read AGENTS.md, remaining/README.md, 06-answer-quality.md and the selected spec.
Follow its file map and exact acceptance checks. Use synthetic fixtures and
read-only copied data. Do not change limits, deploy, make paid model calls or
implement later steps. If a prerequisite is missing, report it without guessing.

Finish the selected step, record validation and remaining gates, then stop.
```

Replace both the package path and step when assigning another task. A stronger
reviewer should assess changed statistical contracts or a new admission-bound
design; cheaper implementers should not silently choose those policies.
