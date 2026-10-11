# PA-00 — Establish the baseline and reviewed answers

Status: in progress (2026-10-11). Baseline, generation check, tests/evals and the
exposure inventory are recorded in [pa-00/baseline.md](pa-00/baseline.md). The
[answer records](pa-00/answer-records.md): Q1 and Q4 are `candidate` (Q4 feasible),
Q2 and Q3 are `blocked` on missing INS total cells, and none is verified.
Owner: baseline and numerical verification.
Dependencies: none. Unlocks PA-01 and source-dependent work in PA-02/03.

## Deliverable

Produce one baseline record and five answer records, identified as Q1–Q5, with
machine-readable expectations where applicable. Keep source evidence and exact
commands beside the records. Use the existing tests/eval/report conventions rather
than introducing another testing framework. Large corpus artifacts remain outside
git; small synthetic fixtures and portable query specifications are tracked.

## Baseline procedure

1. Inspect worktree status and ancestry. Start an isolated implementation worktree
   from the audited feature commit or a documented descendant containing that work.
   Record any intervening changes. Preserve unrelated modifications and untracked
   audit evidence in the current checkout.
2. Resolve the copied corpus explicitly, validate its manifest and hashes, and
   run the read-only corpus audit. Record app, test and staging data paths.
   Resolve parquet by code, never stale absolute `parquet_path` values.
3. Record the exact code commit, full generation identity, Python/dependency
   versions, active settings, search mode, manifest and audit report locations.
   Check that every actual server/test consumer uses the recorded generation.
4. Inventory public entry points: home/place headlines, v1/v2 chart queries,
   comparison, REST, SDMX, downloads, Ask hosted/BYOK and MCP. Name the service
   enforcing validation/aggregation and any bypass for each. Record which routes
   will be exposed in the candidate.
5. With the repository environment activated, run `python -m pytest tests -q`.
   Run corpus-marked checks against the verified copy and existing chart/search
   evals. Record skips and differences without rebuilding baselines.

If the recorded generation is unavailable, reconstruct a copied baseline and
assign its actual identity. Do not claim equivalence to the audited generation
without evidence. No pipeline rebuild or source refetch is implicit in this step;
necessary repair becomes a scoped prerequisite using the FIX-03 workflow.

## Answer record format

Each record must contain:

| Field | Required content |
|---|---|
| Identity | Q ID, record version, status (`candidate`, `verified`, `blocked`), reviewer/date |
| User intent | RO/EN questions, ambiguity and intended definition |
| Sources | Exact parent/child codes, source URLs, definitions and source evidence location/hash |
| Selection | Stable place IDs and level, exact dimension filters, grouping and period policy |
| Meaning | Unit/scale, stock/flow/rate/mean semantics, population/category universe, reference dates |
| Expected result | Exact selected cells/series, missingness, units, ordering/ties, changes and rounding |
| Verification | Independent source comparison or calculation, allowed tolerance and reason |
| Quality | Unique grain, selected levels, total/partition evidence and generation identity |
| Interaction | Expected chart/table, editable choices, link state, citation/export behavior |
| Negative cases | Ambiguous concepts, unavailable periods, invalid filters, unsafe totals and missing values |

Do not use the application result as its own independent oracle. Prefer retained
INS source exports/metadata with provenance; if independent evidence is unavailable,
mark the record blocked rather than guessed. Floating-point tolerance follows
source precision and the approved calculation, not a blanket percentage allowance.

Separate two kinds of test: a frozen-generation numerical answer and a synthetic
latest-period test where adding a new valid period changes the selection. A corpus
refresh requires re-review of affected answer records; changing a golden number
without explanation is not maintenance.

## Q1 — Resident population over time

- RO: “Cum a evoluat populația rezidentă a județului Cluj?”
  EN: “How has Cluj county's resident population changed?”
- Candidate: POP105 family; approve the exact county slice and 1 January reference
  definition. POP106/POP107 are not interchangeable substitutes.
- Show an annual series over a declared available window and latest observation;
  changes compare compatible reference dates. Record absent years rather than
  connecting them as if complete. Preserve total population without summing
  overlapping age/sex/geographic partitions.
- Check Cluj, Iași and Bucharest. A locality sharing a county name must not resolve
  silently to the wrong geographic level.
- Expected refusal/clarification: domicile versus resident population; an
  unavailable year; collapsing a stock across years; an unsafe age aggregation.

## Q2 — County net earnings comparison

- RO: “Cum se compară salariul mediu net în Cluj, Iași și București?”
  EN: “Compare average net earnings in Cluj, Iași and Bucharest.”
- Candidate: FOM106 family; confirm the precise statistic, unit, geographic basis,
  total activity/employee scope and annual or monthly frequency from source metadata.
- Default to the latest common available compatible period for all requested
  counties. Show that period and the official definition next to the comparison.
- Use a source total/approved weighted calculation; never add or simply average
  industry means. Label nominal earnings; purchasing-power adjustment is deferred.
- Negative cases: gross versus net, monthly versus annual, a missing county-period,
  and collapsing economic-activity means without weights.

## Q3 — Registered unemployment ranking

- RO: “În ce județe este cea mai mare rată a șomajului înregistrat?”
  EN: “Which counties have the highest registered unemployment rate?”
- Candidate: SOM103 family. Verify a total-sex rate or aligned source weights;
  the existing approximation is not sufficient evidence for this question.
- Rank the approved county universe, including Bucharest with a clear label, in
  the latest common compatible period. Declare membership before period selection.
  If complete coverage is impossible, state missing areas and require an explicit
  change of scope; never silently rank independent latest observations.
- Display percent units and deterministic ties. Changes in rates use percentage
  points unless a separately named relative change is requested.
- Negative cases: BIM unemployment, unweighted sex rates, absent observations,
  incomplete result windows and constant-axis correlation.

## Q4 — Tourism intensity

- RO: “Ce județe au cele mai multe înnoptări turistice pe locuitor?”
  EN: “Which counties have the most tourist overnight stays per resident?”
- Candidates: TUR105 family plus an approved POP105 resident-population slice.
  Verify both sources before approving a formula implementation.
- Proposed definition: annual overnight stays in accommodation establishments
  located in the county, divided by residents on 1 January of the same year.
  Accept this start-of-year denominator only after reviewing source definitions;
  name it explicitly. It is not an annual-average population estimate.
- Both sources must reduce to one row per county/year using permitted operations.
  Keep the numerator's establishment coverage and tourist coverage explicit.
- Missing/zero denominators produce unavailable results; conflicting observations
  block affected calculations. No nearest-year substitution or silent zero filling.
- Output is stays per resident, not the share of residents taking holidays.
  PA-03 specifies calculation and export acceptance.

## Q5 — Share and reproduce

- RO: “Pot distribui rezultatul și verifica ulterior calculul?”
  EN: “Can I share this result and reproduce the calculation later?”
- Exercise a single-source answer and Q4. A live URL reconstructs the effective
  selection; its displayed generation and resolved period may change if it requests
  latest data. A fixed period link retains that period but may reflect source revisions.
- Downloaded evidence preserves actual values, exact input slices, query specs,
  definitions, formula version, generation, source attribution and rounding.
- Independently recompute Q4 from the bundle without app/network access. Reopening
  a live link must never claim to serve a retained historical snapshot unless that
  snapshot is actually available.

## Acceptance and exit

- Baseline inventory distinguishes known audit evidence from freshly observed results.
- Every featured numerical answer has reviewed cells and independent evidence;
  no invented expected population, salary or unemployment figures.
- At least two ordinary RO and two EN formulations per numerical question are
  recorded, including unaccented RO input and relevant ambiguity cases.
- Q4 feasibility is decided before PA-03 starts. A source defect is either a
  bounded repair dependency or an explicit milestone scope decision.
- Cluj, Iași and Bucharest selections are verified where the source covers them.
- Q5 has a concrete evidence checklist; its implementation acceptance remains PA-03.

PA-00 does not require future UI features to exist. It establishes the answer and
the test target. Hand PA-01 the baseline, exposure inventory and verified fixtures;
record unresolved source issues in the existing corpus-repair backlog.
