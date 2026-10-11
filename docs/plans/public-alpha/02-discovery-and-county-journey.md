# PA-02 — Find, understand and compare a county statistic

Status: proposed. Owner: retrieval, metadata presentation and web interaction.
Dependencies: PA-00 reviewed questions; PA-01 contract for integrated behavior.
Audit: A07, A10–A12. Builds on existing search, places, comparison and FIX-07.

## Outcome and scope

A first-time visitor can find Q1–Q3 in ordinary Romanian or English, understand
the selected concept, change place/period and compare counties without a TEMPO
code or model key. Extend existing pages; do not create another dataset viewer.

Entry points: `app/services/dataset_search.py`, `dataset_meta.py`,
`place_service.py`, search/metadata routers, `app/static/js/explore-app.js`,
`dashboard-v2.js`, `place-page.js`, `compare.js`, `site-chrome.js`,
`dims-explorer.js`, and dataset/place page templates. Verify current locations and
reuse the existing bilingual index and URL-state mechanisms.

## Required behavior

### Concept discovery

- Maintain a small reviewed alias set for Q1–Q4, including ordinary Romanian
  morphology, unaccented forms and English equivalents. Use official definitions
  to separate resident/domicile population, net/gross earnings and registered/BIM
  unemployment. Broad category matches must not displace strong concept matches.
- Group split datasets under their indicator family, preserving the ability to
  select geography, frequency, unit and breakdown variants. Keep exact-code lookup
  and direct child URLs. Do not fold distinct population definitions into one family
  merely because they share dimensions.
- Resolve place, geography level and time as explicit editable selections. Show
  “Cluj county” rather than an unexplained place token. An ambiguous county/city
  match requires a visible choice; ambiguous indicator meaning has a short definition
  choice. Clear intent proceeds without a redundant confirmation step.
- Show a short indicator name, plain definition, unit, geographic scope, actual
  periods/frequency and relevant quality restriction before selection. Keep official
  title/code accessible. Explain related datasets by relationship, not “100%” similarity.

### Actual coverage and options

Provide bounded, searchable, paginated dimension values with stable IDs, labels,
level where known, and an explicit continuation/truncation indicator. Validate
identifiers and limits through the shared boundary. Reuse the lookup for web,
optional Ask and later MCP; it must not depend on an LLM.

Distinguish catalog coverage from coverage for the effective slice. Period bounds
come from actual valid observations, and a minimum/maximum does not imply every
intermediate period exists. Latest-common-period selection consults availability
for the requested sources/places. Cache only with generation and selection identity.
Exercise both monthly options beyond the first page and long locality lists.

### One county journey

1. Home offers a question, a place or an indicator, with the reviewed guided
   questions visible and usable without Ask setup.
2. Choosing a county opens its profile with clear indicator definitions, observation
   dates and source update dates. Theme mapping uses stable category/context keys;
   bilingual labels are presentation, not grouping logic.
3. Opening a dataset carries the county into the effective query and URL. Unavailable
   coverage is explained; the app never silently switches to national data.
4. Comparison retains the indicator and offers Iași/Bucharest or other selected
   counties at a common compatible period. Explain any coverage exclusions.
5. Share/download carries the full selection into PA-03. Browser back/forward,
   reload and direct links restore that selection.

On the dataset page, lead with one useful chart and its place, period, unit and
definition. Keep structural chart controls available, with long categories and
secondary charts progressively disclosed. A top-N preview must disclose its limit
and allow access to the full valid selection without changing aggregation grain.
Single-period data should not present inapplicable temporal transformations.

### Mobile and accessible operation

At 320px and 390px, controls fit and long labels remain inspectable. Provide an
accessible mobile Dimension Browser selector, rather than hiding the only control.
Dialogs/drawers manage focus, support keyboard close and return focus to their
trigger. Filters have labels; changes/errors are announced appropriately; tables
offer the chart values without relying on color. Test keyboard operation and zoom
on the affected journey. If Ask is exposed, its settings panel meets the same checks.

### Canonical discovery and links

Choose one canonical public URL per dataset and preserve existing aliases. Render
the title, definition, unit, coverage and source in initial HTML; include canonical
and language metadata plus appropriate Dataset structured data. Generate a sitemap
from the served catalog and reviewed public pages. Remove `noindex` only after the
canonical content is ready. Keep arbitrary filter/comparison combinations out of
the sitemap and apply a deliberate duplicate-indexing policy.

Do not invent licensing or imply INS endorsement in attribution/structured data.
Carry source reuse terms where verified; unknown terms remain explicit. Meaningful
initial HTML and crawlability are testable; search-engine inclusion is not an alpha
acceptance claim. Reference: [Google Dataset documentation](https://developers.google.com/search/docs/appearance/structured-data/dataset).

## Functional increments

- PA-02a: reviewed aliases, family results, explicit selection and option lookup.
- PA-02b: county-to-dataset-to-comparison flow, definitions and mobile selectors.
- PA-02c: canonical initial HTML, aliases, metadata and sitemap.

Use current selection state and extend it through the PA-01 contract. Avoid
duplicating definitions between frontend config, Ask prompts and server metadata.

## Acceptance

- Each clear PA-00 phrase ranks the approved family first. For ambiguous phrases,
  the relevant distinct concepts appear in the first three family results with
  definitions; no silently chosen alternate population/unemployment concept.
- Evaluate concept selection separately from split ordering. All reviewed Q1–Q3
  phrases pass, with exact-code lookup and unrelated existing searches checked for
  regressions. Explain existing eval differences before rebaselining.
- Place/time selections are visible and editable; invalid or unsupported selections
  cannot be ignored. RO/EN names map to the same stable identities.
- The latest actual monthly period is discoverable beyond page one; option search
  returns a known late-list locality and discloses remaining results.
- Q1–Q3 run from home through county/dataset/comparison without a key. Reload and
  browser navigation preserve effective selections, definitions and language.
- The theme mapping test exercises canonical category IDs and legacy normalization;
  unknown categories remain visible with a fallback rather than disappearing.
- Direct/citation URLs return the intended dataset and slice. Canonical pages have
  meaningful HTML without JavaScript; the sitemap has no unbounded query variants.
- Browser smoke covers v1/v2/place/comparison/Dimension Browser and optional Ask,
  desktop plus 320/390px: inspect console, failed network requests, overflow,
  keyboard interactions, labels and chart/table agreement.

Real first-time task completion is evaluated in PA-04, not inferred from these
automated checks. Record the reviewed search judgments and screenshots in the
completion evidence. Rollback preserves old links and the PA-01 safety boundary.
