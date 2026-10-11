# Public alpha: five dependable questions

Status: proposed implementation plan, 2026-10-11. No package has passed its
acceptance checks. Writing these specifications does not establish data readiness
or authorize a deployment, corpus replacement, or user recruitment.

## Outcome and audience

Help a journalist or civic analyst find a county statistic, understand its
definition, compare it fairly, and take away reproducible evidence. This audience
is an initial hypothesis to test in formative sessions, not an established user
research finding. Ordinary web tasks must work without an account or model key.

The milestone delivers five reviewed tasks, one coherent county journey, one
validated cross-dataset recipe, and a release candidate exercised with real users.
Cluj is the initial example; verify portability to Iași and Bucharest.

| Task | User outcome | Specification |
|---|---|---|
| Q1 | Understand how resident population changed in a county | [Answer key](00-baseline-and-answer-key.md#q1--resident-population-over-time) |
| Q2 | Compare average net earnings across selected counties | [Answer key](00-baseline-and-answer-key.md#q2--county-net-earnings-comparison) |
| Q3 | Find counties with the highest registered unemployment rate | [Answer key](00-baseline-and-answer-key.md#q3--registered-unemployment-ranking) |
| Q4 | Compare tourist overnight stays per resident | [Answer key](00-baseline-and-answer-key.md#q4--tourism-intensity) |
| Q5 | Share the selection and independently reproduce its result | [Answer key](00-baseline-and-answer-key.md#q5--share-and-reproduce) |

These are candidate questions. Exact source codes, filters, periods and expected
values must be established in PA-00; plausible family names are not approvals.

## Evidence and baseline

- Primary evidence: [11 October local audit](../../reports/2026-10-11-public-alpha-audit.md)
  and its [compact evidence](../../reports/2026-10-11-public-alpha-evidence.json).
- Audited implementation: `feat/structural-bar-toggle`, commit
  `6a727a2f10b10c0d46e4ae1a5acf2a6ca6d0605c`, including `integ/fix02-fix03` at
  `2e6fec2`. Worktree presence/HEAD was checked when writing this plan; its current
  runtime behavior was not re-audited.
- Audited copied generation:
  `a6737a263a34bf83b69dde1c8a0366f584396d28a78a716f0ce55563fdbdbb90`.
  Its availability and hashes must be checked in PA-00.
- The checkout containing this plan was `fix/03-corpus-repair` at `1c62741`.
  Do not assume it already contains the audited feature work.
- The older production deployment is not the implementation baseline.

Preserve the existing structural chart choices, sliders/playback, comparison,
place profiles, per-capita controls, URL state, PNG export, complete-export work,
search coverage and aggregation safeguards. Reuse the
[FIX packages](../../fixes/README.md); old problem descriptions are historical,
and completed work must not be implemented again.

## Packages and order

| Package | Deliverable | Dependencies | Completion evidence |
|---|---|---|---|
| [PA-00](00-baseline-and-answer-key.md) | Reproducible baseline and reviewed answers | None | Source-backed answer records and exposure inventory. **In progress:** [baseline](pa-00/baseline.md), [records](pa-00/answer-records.md) |
| [PA-01](01-consistent-answers.md) | Consistent query decisions and rendered facts | PA-00 baseline; answer fixtures as they are verified | Numerical parity, quality refusals and browser race tests. **In progress:** [record](pa-01/record.md) |
| [PA-02](02-discovery-and-county-journey.md) | Find, understand and compare the reviewed indicators | PA-00 answers; PA-01 contract before integration | Reviewed search results and complete county journeys. **In progress:** [record](pa-02/record.md) |
| [PA-03](03-tourism-and-evidence.md) | Tourism intensity and portable evidence | Q4 source approval; PA-01 contract; PA-02 selection state | Independent recalculation and share/export round trips |
| [PA-04](04-release-and-user-validation.md) | Tested release candidate and formative user evidence | Integrated PA-01/02/03; PA-00 manifest | Image/resource checks, session findings and release record |

Execute small functional increments in this order:

1. PA-00 baseline/exposure record, then Q1–Q3 source verification. Investigate Q4
   feasibility immediately so data problems cannot surface only at the end.
2. PA-01 query boundary and quality guards, then rendering/alignment corrections.
3. PA-02 concept search and selections, then the county journey and canonical pages.
4. PA-03 evidence export and the single approved recipe.
5. PA-04 integrated validation and user sessions. Prepare the session script and
   image harness earlier; report failures against the integrated release candidate.

Do not block core correctness work on recruiting participants. Do not mark the
milestone complete if the required sessions or release checks remain unperformed.

## Launch boundary

Default candidate: catalog/search, places, existing dataset views, comparison,
reviewed guided questions, current-view evidence export and tourism intensity.
The wider catalog remains available with appropriate quality restrictions.
No unsafe analytical path is exempt because it is outside the five featured tasks.

Ask is optional. Default to excluding it from this milestone unless its complete
exposure gate passes. Exclusion means a clear unavailable UI and rejection at the
route for both hosted and BYOK calls; the existing hosted `enabled` setting alone
does not establish that BYOK is disabled. Existing pages should explain availability
and link to manual exploration rather than become dead links.

Development MCP remains internal; its validation/sampling repairs belong to PA-01
but remote hosting and public-client certification are deferred. A documented
internal-only MCP adapter follow-up may be carried past the web release gate;
it cannot be described as fixed or advertised publicly until its tests pass.

Deferred: a second recipe (salary versus prices), public MCP hosting, general AI
joins, embeddings, accounts, subscriptions, a universal series registry, external
data providers, a graph UI, and hosted historical snapshot browsing. Preserve
future extension points without building those systems now.

## Cross-cutting decisions

- Extend existing metadata and statistical policy services. Any small reviewed
  indicator/recipe configuration references them; it must not become a second
  independently maintained metadata catalog.
- Version the selection/evidence contract. Exact serialized field names are locked
  in PA-01 with adapter tests; existing clients retain compatible response fields.
- Quality decisions depend on source generation, selected slice and operation.
  A file-wide label cannot by itself certify every slice or every aggregation.
- A shared live link re-executes its selection; a downloaded evidence bundle
  preserves the observed result and calculation inputs. Make this distinction clear.
- Complete exports and bounded chart/tool results have distinct completeness
  semantics. Never compute a national ranking, correlation or recipe from a
  silently capped result.
- Numerical truth fixtures and search relevance judgments are separate from
  existing regression baselines. Do not rebaseline away a wrong answer.

## Audit traceability

| Audit findings | Owner and disposition |
|---|---|
| A01, A02, A04, A08 | PA-01: shared validation, generation-aware quality, safe MCP samples |
| A03, A05, A06, A09 | PA-01: series identity, response ordering, alignment, citations |
| A07, A10, A11, A12 | PA-02: option lookup, mobile selectors, relevance, canonical discovery |
| A13, A14 | PA-01/PA-04 Ask gate; full conversational evidence work may follow the web alpha |
| Existing FIX-03 conflicting-grain repair queue | PA-00 assesses affected candidates; PA-01 gates use; repairs stay separately scoped |
| FIX-05 deployment/resource evidence | PA-04 uses existing staging/release tooling |

## Completion and handoff

All five question records must be verified or replaced through an explicit scope
decision with equivalent acceptance coverage. A blocked candidate must not quietly
become an approximation. Every exposed path must pass its correctness gate; user
sessions must produce actionable evidence; the staged image must pass PA-04.
Deployment is a separate explicit action after the release candidate is reviewable.

For each implementation increment record: scope, commit, generation, reproduction,
before/after behavior, commands and outcomes, expected evaluation differences,
remaining restrictions, and rollback. Update package status only with linked
evidence; add activity entries and link newly discovered work in the existing
[backlog](../../BACKLOG.md). Keep this README as the milestone index.

Start with [PA-00](00-baseline-and-answer-key.md), not a dashboard redesign.
