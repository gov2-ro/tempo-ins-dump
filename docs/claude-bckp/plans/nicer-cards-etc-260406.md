Design an implementation plan for the following changes to an INS statistical data explorer (FastAPI + DuckDB backend, Vanilla JS + ECharts frontend). 

## Context from code exploration

### Current state
- **Landing page**: 8 themed KPI sections using CSS `columns: 2` masonry, each theme has 1-3 indicator cards with sparklines
- **Card CSS**: `.headline-card` has `min-height: 120px`, `padding: 14px 16px 12px`, background/border, sparkline at bottom (30px height)
- **Cards grid**: `.headline-cards` uses `grid-template-columns: repeat(auto-fill, minmax(140px, 1fr))` — auto-fills
- **Headlines config**: Python dict `HEADLINE_CONFIG` in `app/services/headlines.py` (lines 16-306), consumed by `compute_headlines()` function
- **Dataset count badge**: In topbar `<span class="badge" id="dataset-count">` — populated from category tree which counts ALL matrices (including non-canonical splits). The browse-subtitle count comes from corpus/summary which filters `WHERE is_canonical = TRUE`. This causes different numbers.
- **Theme drill-down**: Sub-categories rendered as flat rows (`.ds-row.ds-row-subcat`): 3-column grid (code, name, badge). Datasets as flat rows too (`.ds-row`): 3-column grid (100px code, 1fr name, auto badges)
- **No grid/list toggle exists** for dataset listings

### File structure
- `app/services/headlines.py` — HEADLINE_CONFIG dict + compute_headlines() function
- `app/routers/categories.py` — /api/categories (category tree with counts), /api/corpus/summary, /api/categories/{code}/summary
- `app/routers/datasets.py` — /api/datasets (list with search/filter, returns matrix_code, matrix_name, context_code, ultima_actualizare, row_count, archetype, has_geo, time_range, primary_unit_type, time_granularity, is_split)
- `app/static/js/explore-app.js` — LensApp class with renderHeadlines(), drillCategory(), renderThemeHeadlines(), showCategoryGrid(), renderRecentlyUpdated()
- `app/static/css/explore.css` — all CSS styles
- `app/static/index.html` — HTML structure

## User's requests

1. **Landing cards nicer, more compact**: Design a system where each theme can have 2-5 cards. The user wants to choose the number of cards per theme so that on one row either 1 or 2 themes fit. Cards should be more compact.

2. **Extract headline config to JSON file**: Move HEADLINE_CONFIG from headlines.py to a standalone JSON file. The compute_headlines() function should load from it.

3. **Remove dataset count from topbar**: The badge in the language switcher area shows a different count than the subtitle because the category tree counts all matrices while corpus/summary counts only canonical ones. Fix: just remove the topbar badge entirely.

4. **Sub-theme listing as compact grid/cards**: When drilling into a category, the sub-categories are currently flat rows. Make them compact card grid instead.

5. **Dataset listing grid/list toggle**: Add a toggle between list view (current flat rows) and grid view (cards). Default should be grid.

## Design guidelines
- Use CSS custom properties (dark/light theme support via `var(--bg-1)`, `var(--text-0)` etc.)
- Keep vanilla JS, no frameworks
- Responsive design (860px breakpoint for single column)
- Store user preferences in localStorage
- Keep it simple, minimal code changes