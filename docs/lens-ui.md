# Lens — Dark-Themed Data Observatory

## Overview

Lens is a standalone data exploration UI prototype at `/explore.html`. It reuses the existing FastAPI API and chart modules (ECharts) but wraps them in a bold, dark-themed interface with modern UX patterns.

**URL:** `http://localhost:8080/explore.html`

## Architecture

Three new files, zero backend changes:

| File | Lines | Purpose |
|------|-------|---------|
| `app/static/explore.html` | 90 | Entry point — loads Inter font, ECharts, existing chart modules, new app JS |
| `app/static/css/explore.css` | ~750 | Dark theme CSS with custom properties, animations, responsive breakpoints |
| `app/static/js/explore-app.js` | ~660 | `LensApp` class — browse, dashboard, search, chart switching, filters |

### Design Decisions

**Reuse over rewrite.** Lens doesn't duplicate the chart rendering logic. It imports the same `chart-factory.js`, `chart-geo.js`, `chart-demographic.js`, and `chart-new-types.js` scripts that power the existing dataset page. The dark theme is applied by registering a custom ECharts theme and monkey-patching `echarts.init` to always use it.

**No build step.** Plain ES6 classes, no bundler, no framework. Consistent with the rest of the project.

**API-driven.** All data comes from existing endpoints:
- `GET /api/categories` — category tree for browse view
- `GET /api/datasets?ancestor=X` — datasets in a category
- `GET /api/datasets?q=X` — search
- `GET /api/datasets/{code}` — metadata + chart_config
- `GET /api/datasets/{code}/data` — chart data with filters and group_by
- `GET /view-profiles/{code}.json` — view profile

## Features

### Browse View
- Hero section with gradient text ("Observatory" in purple-pink gradient) and radial glow
- Category grid: 3-column responsive grid, each card has a colored accent bar (cycling through 16 colors), dataset count, subcategory pills
- Category drill-down: click a card to see its datasets sorted by last updated, with code, name, time range, archetype badge, row count
- Staggered entrance animations (`fadeInUp` with incremental delay)

### Dashboard View
- **Header**: dataset name, metadata pills (archetype, time granularity, date range, row count, last updated, code). The "Updated" pill is green-tinted.
- **Insights row**: 4 cards — Latest Value (with trend arrow showing % change from previous data point), Average, Range, Data Points (with "of N total" subtitle). Trend uses green ↑ or red ↓.
- **Primary chart**: rendered by `createChart()` from chart-factory.js, automatically themed via the monkey-patched ECharts init.
- **Chart toolbar**: pill buttons for each ranked chart type. Clicking switches the primary chart and re-fetches data with appropriate `group_by`.
- **Filter strip**: auto-generated dropdowns for non-role dimensions. Time dimensions default to latest value. Changing a filter triggers re-fetch.
- **Secondary charts**: up to 2 alternative chart types rendered below the primary chart in a responsive grid.
- **Choropleth**: for `geo_time` datasets, a "Map" button is auto-injected into the toolbar. Clicking it loads Romania GeoJSON and renders a county/region choropleth.

### Search
- Triggered by clicking the search bar, pressing `/`, or `Cmd+K` / `Ctrl+K`
- Full-screen modal with backdrop blur
- Debounce-free live search (on every keystroke after 2 chars)
- Keyboard navigation: ↑↓ to move, Enter to open, Esc to close
- Results show dataset code (accent-colored), name, and time range

### Navigation
- `pushState` URL management: `?code=X` for dashboard, no param for browse
- `popstate` handler for browser back/forward
- "← Explore" button in topbar to return to browse

## CSS Architecture

Dark theme built on CSS custom properties:

```
--bg-0: #09090b    (page background)
--bg-1: #111114    (card/chart background)
--bg-2: #18181c    (elevated surfaces)
--bg-3: #222228    (pills, hover states)
--border: rgba(255,255,255,0.06)
--accent: #818cf8  (indigo — primary accent)
--green: #4ade80   (positive trends, "updated" badge)
--red: #f87171     (negative trends)
--amber: #fbbf24   (warnings)
```

Key techniques:
- `backdrop-filter: blur(12px)` on topbar for frosted glass effect
- `radial-gradient` glow behind hero title
- Staggered `animation-delay` on cards (0.03s increments)
- Skeleton loading with `shimmer` animation (moving gradient)
- Custom scrollbar styling

## ECharts Themes

Two themes are registered — `lens-dark` and `lens-light` — sharing the same 12-color palette but differing in axis/tooltip/text styling. The active theme is selected dynamically via a monkey-patched `echarts.init`:

```js
const _origInit = echarts.init.bind(echarts);
echarts.init = (dom, _theme, opts) => {
    const themeName = document.body.dataset.theme === 'light' ? 'lens-light' : 'lens-dark';
    return _origInit(dom, themeName, opts);
};
```

This means ALL chart modules automatically render in the correct theme without any changes to their code. When the user toggles theme, active charts are disposed and recreated with the new theme.

## Light / Dark Theme

Toggle via the sun/moon button in the topbar. Persists to `localStorage` (`lens_theme`).

- **Dark** (default): `--bg-0: #09090b`, dark surfaces, light text
- **Light**: `--bg-0: #f8f9fb`, white surfaces, dark text

Both themes use CSS custom properties defined in `explore.css`. The light theme is activated by setting `data-theme="light"` on `<body>`.

## Language Switcher (EN/RO)

Toggle via the language button in the topbar. Persists to `localStorage` (`lens_lang`).

- UI strings are defined in a `UI` object with `ro` and `en` keys (40+ strings each)
- Category names come from the API via `?lang=en` parameter — the `contexts` table has `context_name_en` translations
- Dataset names in browse/search come from `?lang=en` on the datasets endpoint
- Dashboard dataset names remain in Romanian (the `get_dataset()` endpoint doesn't support `lang` yet)

Backend: `categories.py` accepts `lang` param and uses `COALESCE(context_name_en, context_name)` for English.

## Known Limitations

- **Large datasets (>50k rows)**: The backend requires at least one filter. Lens shows the error message but doesn't auto-suggest which filter to pick.
- **Choropleth on large geo datasets**: Switching to Map mode on datasets with >50k rows can fail if the unfiltered county data exceeds the limit. Works fine for smaller geo datasets.
- **No table view**: The browse/dashboard flow is chart-focused. For tabular data, use the existing dataset page at `/dataset.html?code=X`.
- **Dashboard dataset names**: The `get_dataset()` endpoint doesn't support `lang` yet, so dataset names on the dashboard page are always in Romanian.
- **No persistence**: Filter selections and chart type choices are not saved across navigation.
