# Prompt: Auto-Generated Dashboard System for Statistical Datasets

## Role

You are a senior product designer and frontend architect specializing in data visualization for institutional/government statistics.

## Context

I have ~1,800 statistical datasets from a national statistics institute (INSSE Romania, but the approach should generalize to any SDMX-compatible source). Each dataset is in long format:

```
dim1 [, dim2, ...], Perioade, UM, Valoare
```

Where:
- **Valoare** (Value): exactly 1 numeric column per dataset.
- **Perioade** (Periods): exactly 1 time column (annual in 87% of cases, quarterly ~2%, monthly ~5%, irregular/multi-year ~6%).
- **UM** (Unit of Measure): a metadata column with a single value per dataset (e.g. "Procente", "Numar persoane", "Milioane lei"). Not a filterable dimension — it describes what Valoare means.
- **0–1 geographic dimensions** (present in ~25% of datasets). When present, it's one of: Judete (counties, ~42 values), Macroregiuni/regiuni (8–42 values), Localitati (municipalities, potentially 3000+), or weather stations.
- **1–2 categorical dimensions** in 85% of datasets. 3+ categorical dimensions in only 15% of datasets. Maximum observed: 5–6 (very rare).

### Most common categorical dimensions (by frequency across corpus)
- Sexe (sex): 2–3 values
- Medii de rezidenta (urban/rural): 2–3 values
- Grupe de varsta (age groups): 5–20 values
- Forme de proprietate (ownership types): 3–8 values
- CAEN Rev.2 (industry classification): 10–80+ values
- Clase de marime (enterprise size classes): 3–5 values
- Niveluri de educatie (education levels): 5–10 values

### Unit types (determines Y-axis formatting and chart behavior)
- Counts: "Numar", "Numar persoane" — integers, no decimals
- Percentages: "Procente" — 0–100 range, 1 decimal
- Currency: "Milioane lei", "Lei" — localized number formatting
- Rates: "Casatorii la 1000 locuitori" — per-mille, 1 decimal
- Physical: "Km", "Ha", "Grade Celsius", "Tone" — domain-specific

## What I need

Design a system that **automatically generates a sensible default dashboard** for any dataset matching the schema above, with no user configuration required. The dashboard should also support **progressive disclosure** — advanced users can override defaults to reassign dimensions, change chart types, or add comparisons.

### 1. Dataset classification → chart template mapping

Define a small set of **dataset archetypes** based on structural features (not domain semantics), and map each to a default chart configuration. The classification inputs are:
- Number of categorical dimensions (0, 1, 2, 3+)
- Presence/absence of a geographic dimension
- Cardinality of each dimension (low: 2–5, medium: 6–20, high: 20+)
- Time granularity (annual, quarterly, monthly)
- Unit type category (count, percentage, currency, rate, physical)

For each archetype, specify:
- **Primary chart type** (line, bar, grouped bar, stacked bar, area, small multiples, choropleth/map)
- **Dimension-to-visual-role mapping**: what goes on X-axis, what becomes series/legend, what becomes a filter (with default selection)
- **When to show a secondary chart** (e.g., a bar chart alongside a time series for the latest period snapshot)

### 2. Filter panel logic

For the auto-generated view:
- Which dimensions become visible filters vs. are pre-set to "Total" or "All"?
- How to handle high-cardinality dimensions (e.g., 42 judete, 80 CAEN codes) — top-N with search? Grouped/hierarchical selectors?
- Default filter state: what should be selected on first load to produce a meaningful, uncluttered chart?

For the progressive disclosure layer:
- How does a user reassign a dimension from "filter" to "series" or "x-axis"?
- How does the chart type adapt when the user changes dimension assignments?

### 3. Specific chart behavior rules

- **Time series** (the dominant case): When is line vs. bar appropriate? How to handle sparse years or gaps?
- **Geographic data**: When to show a map vs. a ranked bar chart? (Consider: maps are pretty but bar charts are more readable for comparison. Also, not all geo levels are mappable.)
- **Stacked charts**: When are they appropriate (part-to-whole relationships like "Medii de rezidenta" or "Sexe") vs. misleading?
- **Small multiples**: When to facet instead of overlaying? (e.g., 8 regions × time is better as small multiples than 8 overlapping lines)
- **Single time point**: What to show when there's only 1 or 2 periods?

### 4. Edge cases

- Dataset with 0 categorical dimensions (just time + value): simplest case, just a single line/bar chart.
- Dataset with only 1 time point: cross-sectional bar chart.
- Dataset with Localitati (3000+ municipalities): must not render all at once. Requires search + progressive loading.
- Hierarchical geo (Macroregiuni contains Regiuni contains Judete): drill-down or level selector.
- Multiple UM values in one dataset (rare but exists via "Unitati de masura" column with multiple values): treat as a dimension selector, not a filter.

### 5. Layout

Describe the page layout for one dataset's auto-generated dashboard:
- Where does the chart go?
- Where do filters go?
- Where does the data table go?
- Where does metadata (title, unit, source, last updated) go?
- How does the layout adapt from the simple case (1 dim, annual, no geo) to the complex case (3 dims, geo, monthly)?

## Constraints

- Standard chart types only (line, bar, stacked bar, grouped bar, area, small multiples, optionally choropleth). No treemaps, sankeys, or sunbursts.
- The system should work for ~85% of datasets with zero ambiguity in the classification rules. The remaining 15% (high-dimensional edge cases) can fall back to a sensible default.
- Desktop-first, but filters should collapse reasonably on mobile.
- Chart library will be Recharts or a similar React-based library. Maps via Leaflet or similar if needed.

## Deliverable

A concrete specification I can implement:
1. A decision tree or rule table: dataset features → archetype → chart config.
2. For each archetype: exact chart type, dimension assignments, filter defaults.
3. Filter panel component spec: what controls, what states, what interactions.
4. Layout wireframe description (text-based is fine).
5. Progressive disclosure mechanics: what's hidden by default, how it's revealed.
