# PA-04 — Validate the release and learn from users

Status: in preparation (2026-10-11). The candidate passes the strict release
check with an accepted, enforced restriction; workload, rollback and browser
smoke are recorded. The image/resource gate (no Docker here), the INS cells and
the user sessions remain. See the [release record](pa-04/release-record.md).
Owner: integration, release evidence and formative research.
Dependencies: integrated PA-01/02/03 and PA-00 baseline/answer records.
Extends FIX-05; does not authorize deployment or sending recruitment messages.

## Deliverables

One reviewable release record identifies code, corpus, search index, image and
configuration, links numerical/browser/resource evidence, records five formative
sessions, lists remaining restrictions, and provides deployment/rollback commands.
Build on `scripts/prepare-deploy-data.sh`, `scripts/release-check.py`, existing CI,
Dockerfile and Fly configuration. Do not create a second release runner.

## Release surface and data gate

Reconcile the PA-00 exposure inventory with the actual built image. Test direct
routes as well as navigation. Safe web capability may ship while Ask/MCP expansion
is deferred, but disabled functionality must not remain reachable through a hidden
API or BYOK path. Development MCP stays internal unless separately certified.

Known conflicting-grain files require either copied-corpus repair with migration
evidence or an enforceable restriction on affected analytical use. Keep discoverable
raw evidence labelled appropriately. If the existing release gate cannot express
that distinction, add a tested generation-bound restriction policy; do not globally
weaken the invariant or wave through a strict-gate failure. The release report lists
every accepted restriction and tests that each relevant consumer enforces it.

## Validation sequence

1. Freeze the candidate commit/configuration and quiescent copied generation. Check
   manifest/hashes and served file/index/profile consistency before staging.
2. Run the full synthetic suite, reviewed answer fixtures, read-only corpus checks,
   adapter parity tests and chart/search evaluations. Explain changed baselines
   before any rebuild; skips remain explicit.
3. Stage atomically using existing tooling, retaining the previous complete artifact.
   Build the actual intended deployment image. Verify generation identity and FTS
   availability inside it; a local source-tree server is not equivalent evidence.
4. Smoke Q1–Q5, representative v1/v2/place/comparison/Dimension Browser, RO/EN,
   complete exports, evidence downloads, canonical pages and optional Ask. Inspect
   console/network errors, direct links and effective selections.
5. Run the bounded resource workload below, then exercise rollback against a previous
   verified artifact locally/staged. Confirm source/index compatibility after rollback.
6. Conduct the formative sessions on a usable candidate. Fix recurring task blockers
   and all numerical misinterpretation defects; rerun affected automated checks and
   focused user tasks. Record the exact final candidate after changes.

## Resource workload and targets

Use the intended 512 MiB memory limit and one worker. Record CPU limit, platform,
image, network/browser conditions and warm/cold state; these are proposed test
conditions, not measured results. Run five concurrent scripted clients for ten
minutes mixing search, county queries and comparison, including a complete export
while interactive requests continue. Exercise the configured export concurrency
limit. Never run the workload against production.

Acceptance: no OOM, cross-request result leakage, corrupt exports or unexpected
5xx; expected resource-limit responses are explicit. Record latency percentiles,
peak memory and completed/rejected requests. Initial performance targets are warm
search/query p95 at most two seconds and a representative first useful mobile chart
within five seconds under declared conditions. Measure exports separately; they
must complete within documented server limits or fail explicitly without partial
success. Review target changes before signing off, with evidence and rationale.

If Docker/resource enforcement is unavailable, record that check as unperformed
and run it in a suitable CI/host environment. An unrestricted local pass cannot
substitute for the resource gate.

## Five formative sessions

Recruit participants matching the audience hypothesis, ideally mixing local
journalists and civic analysts unfamiliar with TEMPO codes. The maintainer arranges
participation; automated outreach requires a separate instruction. Prepare an
ordinary-language script and record consent for any session recording. Collect only
the notes needed to evaluate the tasks.

Give realistic tasks without teaching the navigation:

1. Find how Cluj's resident population changed and explain what “resident” means.
2. Compare its net earnings with Iași and Bucharest; identify the comparison period.
3. Find a county unemployment ranking and distinguish registered from BIM unemployment.
4. Interpret tourist stays per resident, inspect its population denominator and
   identify any excluded county.
5. Share one answer and download enough evidence for someone else to reproduce it.

Vary place/task order to reduce learning effects. For each task record completion
without help, completion with help, failure, time, wrong concept/period selections,
interpretation and share/export success. Ask the participant to explain the result
in their own words. Task five need not require a non-programmer to run code;
independent offline recomputation is an engineering acceptance check in PA-03.

Initial formative target: at least four of five participants complete each core
find/compare/share task without moderator instruction, and no unresolved interface
defect leads participants to confidently report the wrong concept or period. Record
all confusion and revise recurring blockers. Five sessions inform design; they
cannot establish a population-wide success rate or prove absence of usability issues.

If participants are unavailable, engineering readiness can be reported separately,
but user validation and milestone completion remain pending. Do not replace real
sessions with agent-generated personas or browser automation.

## Feedback and release communication

Provide a visible feedback route for a result with its public dataset/selection,
generation and page URL prefilled or copyable. Report submission is a user action;
do not automatically transmit browsing history or credentials. A simple issue/email
workflow is sufficient; an account system or analytics platform is unnecessary.

Publish release notes describing the usable questions, observation/update dates,
known restrictions and how to report an issue. Link corrections to the affected
generation/selection. Track failed searches and task friction using session evidence
first; any later telemetry needs a separately defined data/retention policy.

## Final release record and completion

The release record contains:

- Exact code commit, corpus/search generation, image digest and exposure settings.
- Verified Q1–Q5 answer versions and source-evidence references.
- Test/eval/browser/resource commands, outcomes, skips and reviewed differences.
- Quality restrictions and proof that alternate consumers cannot bypass them.
- Session findings, changes made and remaining usability limitations.
- Real provider smoke/claim evidence if Ask is enabled; explicit disabled-route
  tests otherwise. Each advertised provider/model must have measured validation.
- Prior verified artifact, rollback steps and demonstrated generation/index match.
- Exact proposed deployment command and a concise release decision.

Preparation, a green release gate and a completed specification do not themselves
publish the app. Invoke deployment only after explicit authorization. After an
authorized deployment, smoke the actual public image, verify its generation and
record the result; rollback uses the prior complete verified artifact if necessary.

The milestone's technical and user-validation gates can be complete before public
deployment. Report publication status separately so “ready” and “live” cannot be
confused. Follow-up ideas go in the existing backlog with evidence and scope.
