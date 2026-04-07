# Fix ZAW0311 Bugs + Series Cap

## Context
Two bugs found on ZAW0311 (and 110 similar datasets), plus the series cap from before.

### Bug 1: Snapshot crash — "Cannot read properties of undefined (reading 'roles')"
When `snapshot.charts` is empty (`[]`), `getActiveChart()` returns `undefined`. Then `buildChartConfig()` accesses `chart.roles?.series` which crashes because `chart` itself is `undefined` — optional chaining on `.roles` doesn't help when the base object is undefined.

### Bug 2: Timeline shows single dot instead of line
ZAW0311 has two "time" columns: `TIME_PERIOD` (1 option — actually the indicator name) and `TIME_PERIOD_2` (10 actual year values). The profile generator picks `TIME_PERIOD` as the time dim because it matches first via `next()`. Result: all 10 rows map to the same x-value, chart shows 1 dot.

110 datasets have this pattern: `TIME_PERIOD` with 1 option + `TIME_PERIOD_2` with the actual years.

## Fixes

### 1. Guard against undefined chart in `buildChartConfig()` (dataset-page-v2.js:649)

Add null guard so empty `charts[]` doesn't crash:

```javascript
buildChartConfig() {
    const chart = this.getActiveChart();
    const chartType = this.getActiveChartType();
    const dims = this.profile.dimensions;

    const effectiveSeries = (chartType === 'horizontal_bar' && this._stackByDim !== undefined)
        ? this._stackByDim
        : (chart?.roles?.series || null);

    return {
        primary_chart: chartType,
        ranked_charts: [{
            chart_type: chartType,
            roles: {
                x_axis: chart?.roles?.x_axis || null,
                series: effectiveSeries,
                ...
                facet: chart?.roles?.facet || null,
            },
        }],
        ...
        max_series: chart?.max_series || null,
    };
}
```

Also guard `getActiveChart()` fallback and show a "no chart available" message for empty snapshot views instead of crashing.

### 2. Fix time dim selection in profile generator (generate_view_profiles.py:807)

When multiple dims are classified as `time`, prefer the one with the most options (not the first):

```python
# Line 807: instead of next(), pick the time dim with most options
time_dims = [d for d in classified if d['dim_type'] == 'time']
time_dim = max(time_dims, key=lambda d: d['option_count']) if time_dims else None
```

This fixes all 110 affected datasets. Then regenerate profiles.

### 3. Series cap (already implemented)
The stacked/grouped bar series cap from the previous plan is already in place.

## Files to modify
1. `app/static/js/dataset-page-v2.js` — null guard on `chart` in `buildChartConfig()` + `fetchAndRender()`
2. `generate_view_profiles.py` — prefer time dim with most options
3. `app/static/dataset.html` — cache bump `?v=21` → `?v=22` on dataset-page-v2.js

## After code changes
1. Regenerate view profiles: `source ~/devbox/envs/240826/bin/activate && python generate_view_profiles.py`
2. Verify ZAW0311: Timeline should show 10 connected points, Snapshot should not crash
3. Spot-check a few other affected datasets (ECC101A, TAP0133)

## Verification
1. `localhost:8080/dataset.html?code=ZAW0311` → Timeline: line with 10 points (2011-2020)
2. ZAW0311 → Snapshot: no crash (may show "no chart" message since snapshot has no charts)
3. ZAW0311 → Table: still works (already OK)
4. TAI0122 → Stacked: still capped at 8 series (prior fix)
5. POP108B → All views: still working
