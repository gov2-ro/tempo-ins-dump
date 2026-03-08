You are an experienced UX designer and data visualization expert.

I am building a *generic* web UI for exploring official statistical tables coming from various national or international statistical agencies.

Assume the data is in a “long” tabular format with these characteristics:

- There is exactly one column for numeric values (the statistical measure).
- There is exactly one column for the time period (e.g., year, quarter, month, or date).
- There may be one column for geography (e.g., country, region, province, city).
- All remaining columns (at least 1, at most 4 in most real datasets) are categorical dimensions: e.g., sex, age group, industry, income quintile, education level, etc.
- Each row is one observation (a single value for a given combination of time, geo, and category levels).

**My goals**

- Design a UI that works for *any* dataset with this schema, regardless of the specific dimension names or codes.
- Make it easy for non-technical users to:
  - Pick a dataset.
  - Choose which dimensions go on which visual encodings (x-axis, series/legend, small multiples, filters).
  - Explore time series (focus on time on the x-axis) and cross-sectional views (focus on comparing categories or geographies at a point in time).
- Support desktop first, but the patterns should degrade reasonably on tablet and mobile.

**Constraints and assumptions**

- Up to 4 categorical dimensions beyond time and geo.
- Time can be yearly, quarterly, monthly, or daily.
- Geographical dimension can be absent in some datasets.
- Datasets can be fairly large (tens or hundreds of thousands of rows), so the UI should not rely on rendering huge tables all at once.
- I am fine with using standard chart types (line, bar, stacked bar, area, small multiples) rather than exotic visualizations.

**What I want from you**

1. Propose a high-level UI layout for a “generic statistical explorer” page:
   - Where filters and dimension selectors go.
   - Where the main chart goes.
   - How a supporting table or details panel fits into the layout.

2. Describe a set of reusable interaction patterns for:
   - Mapping dimensions to: x-axis, series/legend, faceting (small multiples), and filters.
   - Switching quickly between:
     - Time-series view (time on x-axis, category or geo as series).
     - Cross-sectional view (category or geo on x-axis, time picked via a slider/dropdown).
   - Handling the geo dimension differently when it is present vs when it is absent.

3. Recommend sensible default chart types for the most typical combinations, for example:
   - Time vs one category dimension.
   - Time vs geo.
   - Geo vs one or two category dimensions at a single point in time.
   - One or more category dimensions with no time.

4. Explain how to prevent overwhelming the user when there are many category values (e.g., 50+ countries or 100+ industries):
   - Strategies like ranking, top-N + “Other”, search/autocomplete, highlighting, and small multiples.
   - How these strategies would actually appear in the UI.

5. List important edge cases and how the UI should handle them:
   - Missing geo or time.
   - Only one time point available.
   - Only one category dimension present.
   - Very sparse data (many combinations with no values).
   - Multiple measures (if I later decide to support more than one value column).

Make your answer concrete and implementation-friendly: describe the layout in words (e.g., “left column filter panel, right main chart with tabs for Chart/Table/Metadata”) and give specific examples of control types (dropdowns, pill selectors, checkboxes, etc.).
