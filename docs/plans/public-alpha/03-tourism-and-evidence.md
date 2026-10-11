# PA-03 — Tourism intensity and reproducible evidence

Status: implemented (2026-10-11), pending the Q4 source gate. The recipe,
evidence bundles and tests are in place; the county denominators still need the
INS reference cells. See the [PA-03 record](pa-03/record.md).
Owner: deterministic analysis and current-view export.
Dependencies: approved PA-00 Q4 sources; PA-01 query/quality contract; PA-02
selection state. Extends existing per-capita, comparison, URL state and PNG export.

## Outcome and boundary

Answer “Which counties have the most tourist overnight stays per resident?” with
inspectable sources, a deterministic calculation and a portable evidence bundle.
The same export capability serves the single-source Q1–Q3 results.

One recipe is sufficient for this milestone. Do not implement general-purpose
joins, arbitrary formulas, a separate metadata database or salary purchasing power.
Use a small versioned recipe configuration referencing existing source metadata.
The candidate source families in PA-00 are not verified inputs until its Q4 gate passes.

## Minimal recipe specification

Record recipe identity/version, source query specifications, concept definitions,
unit scales, geographic level/code mapping, period/reference-date rules, allowed
aggregation, quality requirements, formula, exclusion policy and display rounding.
Expose these through the shared analysis result rather than recomputing in JavaScript.

Proposed formula, subject to PA-00 source approval:

```text
intensity(county, year) = annual_overnight_stays(county, year)
                         / resident_population(county, 1_January_of_year)
unit = overnight stays per resident
```

This combines an annual flow with a declared start-of-year stock. Matching year
labels alone does not establish compatible reference dates. The result must show
that denominator choice and the numerator's accommodation/visitor coverage. Do
not describe it as resident travel participation or substitute domicile population.

## Execution rules

1. Resolve each source through PA-01, with explicit total/category selections and
   complete results. Inspect quality before any join. Do not SUM raw observations
   after joining them.
2. Reduce to one verified `(geo_id, year)` key per source. Geography joins use
   stable county identities and declared boundary compatibility, not fuzzy label
   matching. Assert one-to-one cardinality; report conflicting keys as unavailable.
3. Choose the latest common compatible year for the declared comparison universe.
   If complete coverage is unavailable, explain it and require a visible subset
   choice. A selected-year analysis may display partial coverage with explicit
   exclusions; never mix independent latest years to fill it.
4. Convert declared unit multipliers before dividing. A positive population is
   required. Zero stays with a valid positive denominator yields zero intensity;
   missing stays, missing population, zero/negative population or nonfinite input
   yields an explicit unavailable result.
5. Preserve unrounded calculation values. Apply recorded display rounding only
   for presentation; exports retain sufficient source precision for recalculation.
6. Return included/excluded areas, reasons, counts, effective query specs, actual
   reference dates, units, method/version and generation for both sources. No
   nearest-year substitution, silent zero fill or hidden approximation.

Existing per-capita controls that can reach these reviewed indicators must use the
same rules or clearly disable unsupported transformations. A safer recipe page must
not leave an alternate control silently applying a nearest-year denominator.

## User flow

Extend existing comparison/dataset controls with the approved tourism question.
The user chooses counties/year and sees intensity, numerator and denominator in a
table alongside the chart. Source links open the exact effective slices. Explain
why a county is missing and offer a valid selection where known. Show the measure's
definition next to the result, not only in an export or tooltip.

No account is required. Reuse current share/PNG controls; chart downloads include
title, places, period, unit and source attribution. The evidence download is a
separate explicit action so a PNG is not mistaken for the reproducibility artifact.

## Portable evidence contract

Use a versioned downloadable bundle, for example ZIP with the following logical
contents; exact filenames are finalized with the export tests:

| Content | Requirement |
|---|---|
| Manifest | Schema version, creation time, code/recipe versions, actual generation IDs, hashes of bundled data/spec files |
| Selection | Original intent where available, effective query specs, resolved periods, filters and transformations |
| Result | Complete rows for the chosen analytical scope, stable IDs, labels, units and unrounded values |
| Inputs | Exact source slices required to recompute the result, with their grain and precision |
| Method | Definitions, formula, denominator reference date, exclusions, missing-value policy and rounding |
| Attribution | Source codes/URLs, known publication/update dates, reuse terms where established and a readable citation |

For a single-source answer, the result may also be the input; avoid needless
duplication. For a derived answer, include the validated input series and any
aggregation evidence needed to explain them. State whether reproduction starts
from approved source series or raw source observations; do not imply a full corpus
snapshot. Preserve hashes/references to original source evidence when available.

Respect FIX-04 concurrency and resource limits. A bundle is complete for its named
selection or returns a clear resource-limit error; never silently export a chart
preview as the full selection. Raw full-dataset download remains a separate option.
No keys, private filesystem paths or internal logs belong in the public bundle.

### Live links versus preserved evidence

A live link contains a versioned selection, language and transformation. Preserve
whether the user requested a fixed period or `latest`; resolve and display it
honestly. Fixed-period links can still reflect source revisions. On a later
generation, display the current provenance rather than claim the old result is
unchanged. Unsupported state versions produce an explanatory error or tested
migration, never silent filter loss.

The downloaded bundle preserves the actual answer. It must remain usable without
network access or the original app. Hosted historical snapshots and permanent
result IDs are deferred; do not put an unavailable historical generation into a
URL and promise it will be replayed.

## Functional increments and acceptance

- PA-03a: current-view evidence schema and export for a single-source answer.
- PA-03b: validated tourism calculation and evidence inputs, integrated into existing
  comparison/discovery, with source links and visible exclusions.

Required synthetic tests:

| Inputs / situation | Expected behavior |
|---|---|
| County A: 120 stays / 60 residents; B: 50 / 100 | Intensities 2 and 0.5; ranking A then B |
| 1.2 thousand stays / 600 residents | Multiplier applied; intensity 2 |
| Zero stays / positive population | Valid zero |
| Missing stays, absent/zero population | Unavailable with the distinct reason |
| Duplicate geo/year in either input | Join refused before many-to-many multiplication |
| Different latest years | Common compatible year or explicit unavailable result |
| Same name at county and locality levels | No accidental join |
| Overlap/conflicting grain or truncated source result | Calculation refused |
| Source revision with unchanged query | Live view reports new provenance; old bundle remains unchanged |

Acceptance also requires PA-00 Q4 source-backed values; independent offline
recalculation from the bundle within declared precision; Q1/Q4 share-state round
trips; displayed/exported/charted values agreeing; source links preserving slices;
and clear treatment of missing/invalid inputs. Test export limits and incomplete
downloads explicitly. Run full tests, relevant evals and browser smoke.

Rollback can hide the recipe while keeping supported single-source exports.
Previously downloaded schema versions remain documented/readable. Any source
repair requires separate generation/migration evidence under FIX-03.
