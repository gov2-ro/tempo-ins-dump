# Agent 3A: IA & Navigation Designer

**Type:** `general-purpose`
**Phase:** 3 (needs all Phase 1 + Phase 2 tables complete)
**Output:** `docs/app-spec-v2.md` (markdown document, ~800 lines)
**Runtime:** ~9 minutes (33 tool calls — reads data + writes spec)

## What it does

A research + writing agent that reads all enriched metadata tables, analyzes the actual data distribution, and produces a comprehensive information architecture specification for the v2 UI. It:
- Quantifies what the enriched data enables (e.g., "566 datasets have full choropleth support")
- Designs a discovery-first page hierarchy and navigation model
- Inventories all UI components with file paths and descriptions
- Produces ASCII wireframes for every page
- Specifies data flow (pre-computed JSON bundles vs live DuckDB queries)
- Documents interaction patterns, badge system, and chart carousel design

## Output Document Structure

```
1. Design Philosophy (principles, non-goals)
2. Page Hierarchy & URL Structure
3. Navigation Model (header, breadcrumbs, cross-links, back navigation)
4. Component Inventory (global, page-specific, chart, filter components)
5. Data Flow (pre-computed bundles, runtime queries, API endpoints)
6. Page Designs with ASCII wireframes:
   - / Landing / Discovery Hub
   - /explore Tag Cloud Explorer
   - /datasets Dataset Catalog
   - /dataset/{code} Dataset Detail View
7. Interaction Patterns (filters, language toggle, chart carousel)
8. Badge System (quality, freshness, trend, geo coverage badges)
9. Implementation Phases
```

## Enriched Tables It Reads

| Table | Key stats to extract | Used for |
|-------|---------------------|---------|
| `dataset_value_profiles` | Distribution shape counts, magnitude distribution | Axis scaling spec, magnitude badge |
| `dataset_coverage` | fill_rate distribution, freshness distribution, geo_county_count histogram | Completeness badges, "show full county coverage" filter |
| `dataset_trends` | trend_direction counts, breakpoint_years stats | Trending filter, auto chart annotations |
| `dataset_tags` | Top 50 EN tags by frequency | Tag cloud sizing, facet design |
| `dataset_relationships` | relationship_type distribution, avg similarity | "Related datasets" sidebar spec |
| `dataset_chart_recs` | chart_type distribution | Chart carousel spec, chart availability filters |
| `matrix_profiles` | archetype counts | Archetype filter design |
| `matrices` | Total dataset count | Navigation scale |
| `contexts` | Context hierarchy depth + breadth | Category tree design |

## Prompt Template

```
You are Agent 3A: Information Architecture Designer for a statistical data explorer.

**Environment:**
- Working dir: {{PROJECT_DIR}}
- DuckDB: {{DB_PATH}} (read-only)
- Country: {{COUNTRY_NAME}} (e.g., "Romania")
- NSI name: {{NSI_NAME}} (e.g., "INS TEMPO")
- Total datasets: {{DATASET_COUNT}}
- GeoJSON available: {{GEOJSON_PATH}}

**Enriched tables in DuckDB** (Phase 1 + 2 pipeline outputs):
- dataset_value_profiles — statistical value profiles
- dataset_coverage — time/geo coverage and sparsity
- dataset_trends — temporal trend patterns
- dataset_tags — bilingual topic tags
- dataset_relationships — cross-dataset relationships
- dataset_chart_recs — data-driven chart recommendations

**Existing app (v1):**
- FastAPI + DuckDB backend
- Vanilla JS + ECharts frontend
- 4 archetypes: time_series, geo_time, demographic, time_residence
- Basic dataset list + single chart per dataset + filter panel
- Files in: app/main.py, app/static/js/, app/templates/

**Task:**
1. First, query the DuckDB to understand what the enriched data actually enables:
   - Count datasets by archetype, trend_direction, fill_rate bucket, freshness
   - Find top 20 EN tags by frequency (from dataset_tags where source != 'indicator')
   - Count datasets with geo_county_count >= {{GEO_UNIT_COUNT_70PCT}} (choropleth-ready)
   - Count datasets with has_seasonality = TRUE
   - Count chart_type distribution from dataset_chart_recs

2. Using the actual numbers, design a v2 information architecture spec.
   Write it to docs/app-spec-v2.md. Include:

   a. **Design philosophy**: 4-5 core principles based on what the enriched data enables.
      Include non-goals to scope the work.

   b. **Page hierarchy + URL structure**: List all routes with descriptions.
      Design for discovery: landing, faceted explore, catalog, dataset detail, compare.

   c. **Navigation model**: Persistent header design, breadcrumbs, cross-link map
      (every navigable surface should link to at least 2 others).

   d. **Component inventory**: Table listing every UI component, its file path, and description.
      Group by: global, page-specific, chart modules, filter/badge components.

   e. **Data flow**: Specify which data is pre-computed JSON (served as static bundles)
      vs live DuckDB queries. Pre-computing navigation metadata is critical for performance.
      List the API endpoints needed.

   f. **Page designs**: For each major page, provide:
      - ASCII wireframe showing layout
      - List of components used
      - Data required (which pre-computed bundle or API call)
      - Key interaction patterns

   g. **Badge system**: Define visual quality/freshness/trend badges using the enriched data.
      Specify thresholds: e.g., fill_rate >= 0.75 → "Complete" badge.

   h. **Chart carousel spec**: How the dataset_chart_recs table drives the chart switcher UI.
      Specify the pill/tab design, primary vs secondary chart, config_json usage.

   i. **Implementation phases**: Break into 3-4 phases, each deployable.
      Phase 1 should be the minimum to replace v1; later phases add discovery features.

3. Throughout the document, use the actual statistics you queried in step 1.
   For example: "566 datasets (30%) have ≥30 counties and time data → choropleth-ready"

4. End the document with a verification checklist:
   "Before shipping, verify: [list of key things to check]"

Write the complete spec to docs/app-spec-v2.md. Use markdown with clear headings.
Include ASCII wireframes (use box-drawing characters or +--+ style).
Target length: 600-1000 lines — thorough enough to hand to a developer.
```

## Adaptation Notes

- **`{{GEO_UNIT_COUNT_70PCT}}`**: 70% of your total geo unit count. For Romania (42 counties): 30. For Germany (16 states): 11. Used to identify "choropleth-ready" datasets.
- **Output location**: The agent writes to `docs/app-spec-v2.md` by default. Change if your docs folder is elsewhere.
- **v1 description**: Update the "Existing app (v1)" section to describe your current stack. The agent uses this to make recommendations that build on — rather than replace — existing work.
- **Language**: The spec will be written in English. If you need it in another language, add "Write the entire document in [language]" to the prompt.
- **ASCII wireframes**: The agent produces `+--+` style wireframes well. If you prefer Mermaid diagrams or Figma-style description instead, specify that.
- **Implementation phases**: For an NSI project starting from scratch (no v1), remove the "Phase 1 = minimum to replace v1" framing and replace with "Phase 1 = data browsing MVP".

## What Makes a Good Spec

The agent produces better output when the actual data numbers are large and varied. The key insight from INS TEMPO:
- 566 geo_time datasets → justified a full choropleth map component
- 976 time_series → justified the line chart carousel
- 92K tags → justified the tag cloud explorer page
- 18K relationships → justified the "related datasets" sidebar

If your dataset has fewer enriched results (e.g., 50 datasets with tags), the IA should be simpler — the agent will recognize this from the queried statistics.
