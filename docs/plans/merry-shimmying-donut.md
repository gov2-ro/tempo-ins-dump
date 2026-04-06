# Housekeeping: Backlog, Activity History, Cleanup

## Context

The two-panel dashboard redesign just shipped (commit `6869299`). Several backlog items are now stale (done or obsolete), the activity history hasn't been updated since 2026-03-24, and debug screenshots from Playwright testing are scattered in `docs/misc/` (16 untracked) and project root (10 gitignored). Time to clean up.

## Tasks

### 1. Update `docs/BACKLOG.md`

**Mark as done:**
- "Dataset definition/methodology panel" → done (info panel in explore-app.js)
- "Loading states for chart switching" → done (chart-loading div + opacity transitions)

**Mark as obsolete / remove:**
- "Secondary chart lazy loading" → obsolete (secondary charts replaced by two-panel system)

**Update:**
- "v2 UI build" → partially done — two-panel dashboard shipped, category browse works, search works. Remaining: data table, export, responsive polish
- Merge "Filter persistence across navigation" and "URL deep-linking for filters" into one item

**Add new items:**
- URL state persistence (filters, chart type, period in URL for shareable views)
- Visual polish pass (x-axis label truncation, responsive breakpoints, chart transitions)
- Data table toggle in Lens dashboard
- Export (CSV data / PNG chart)

### 2. Update `docs/activity-history.md`

Add entries for work since 2026-03-24 (derived from git log):

**2026-03-24 — Corpus Normalization (Phases 1-7)**
- Corpus audit, canonicalization, i18n dictionary, sub-dataset profiling, v3-only simplification, corpus/ reorg, dimension label normalization

**2026-03-25–27 — Data Quality & Charts**
- Strip aggregate/total rows from 49 parquet files
- Add scatter/correlation chart type
- Fix AVG for percentages, heatmap roles, stale profiles

**2026-03-28–29 — Lens Observatory UI**
- Dark-themed data observatory prototype (Lens)
- Light/dark theme toggle, EN/RO language switcher
- Trend indicators on category cards, breadcrumbs, smart large dataset handling
- EN dataset names, info panel, chart loading states
- **Two-panel dashboard**: Trends (line/area/stacked) + Snapshot (grouped/heatmap/bubble/choropleth/bar) with period navigator and play animation

### 3. Clean up debug screenshots

**Delete 16 untracked PNGs in `docs/misc/`:**
- `POP301A 2026-03-29 at 15.27.37.png`
- `Screenshot 2026-03-29 at 11.19.*.png` (5 files)
- `two-panel-*.png` (10 files)

These are development debug screenshots, not documentation assets.

**Root-level PNGs** (10 files like `pop301a-fixed.png`, `tur105f-bubble.png`) are already gitignored — just delete them to keep the working directory clean.

### 4. Add `docs/misc/*.png` to `.gitignore`

Prevent future debug screenshots from showing as untracked:
```
docs/misc/*.png
!docs/misc/dimensions-browser-1.png
!docs/misc/nonstop-bv-ct.png
```

Or simpler: just add the debug screenshot pattern. The 2 existing tracked PNGs won't be affected (git doesn't untrack already-tracked files via gitignore).

### 5. Review edge cases (quick scan)

Open Lens in Playwright and spot-check:
- A `geo_only` or `categorical` dataset (no time panel) — verify snapshot-only layout
- A dataset with 0 non-time dims — verify graceful handling
- EN mode — verify translated panel labels

## Files Modified

| File | Change |
|------|--------|
| `docs/BACKLOG.md` | Update done/obsolete items, add new items |
| `docs/activity-history.md` | Add entries for 2026-03-24 through 2026-03-29 |
| `.gitignore` | Add `docs/misc/*.png` pattern |
| `docs/misc/*.png` (16 files) | Delete untracked debug screenshots |
| `*.png` (10 root files) | Delete Playwright test screenshots |

## Verification

```bash
# Confirm no untracked PNGs
git status

# Confirm backlog items are correctly marked
cat docs/BACKLOG.md | grep -E '^\- \[' | head -20

# Quick Playwright check for edge cases
npx playwright ... (spot-check 1-2 datasets)
```
