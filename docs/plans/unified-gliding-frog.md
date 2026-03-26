# Snapshot View Enhancements: Dimension Variants, Line Toggle, and Bubble Charts

## Context
The snapshot view currently lacks the exploratory flexibility of the timeline view:
1. **Dimensions like RESIDENCE are filter-only** — in timeline they're full chart variants ("by_RESIDENCE"), but in snapshot they're just pill filters with no chart representation
2. **No line chart in snapshot** — even though a mini-trend line for the selected dimension slice would be useful context
3. **Bubble chart is too restrictive** — only generated for datasets with 2+ `indicator`-type dimensions, but it should work with any 2+ non-singleton categorical dimensions

## Changes

### 1. Snapshot Variant Charts (like timeline's "by_" variants)
**File**: [generate_view_profiles.py:596-650](generate_view_profiles.py#L596-L650)

After the bar/pyramid/bubble generation, add variant bar charts that swap dimensions. For POP206G with dims [SEX, RESIDENCE, AGE]:
- Primary snapshot: AGE × SEX (grouped_bar)
- Variant: RESIDENCE × SEX (grouped_bar, variant="by_RESIDENCE")
- Variant: AGE × RESIDENCE (grouped_bar, variant="by_RESIDENCE_on_AGE")

Add between sections 3 (pyramid) and 4 (bubble):

```python
# --- 3b. Variant grouped bars (swap x_axis/series) ---
# Like timeline's by_ variants — show all dimension pairings
if len(non_singleton) >= 2:
    # Get the dims used by the primary bar/pyramid
    primary_bar = next((c for c in charts if c['chart_type'] in ('grouped_bar', 'bar_vertical', 'horizontal_bar')), None)
    primary_x = primary_bar['roles']['x_axis'] if primary_bar else None
    primary_s = primary_bar['roles'].get('series') if primary_bar else None

    for x_dim in non_singleton:
        for s_dim in non_singleton:
            if x_dim == s_dim:
                continue
            if x_dim['column'] == primary_x and s_dim['column'] == primary_s:
                continue  # Skip the existing primary
            if s_dim['option_count'] > 8:
                continue  # Series too large for grouped bar

            variant_chart = {
                "chart_type": "grouped_bar" if s_dim['option_count'] <= 6 else "horizontal_bar",
                "is_primary": False,
                "variant": f"by_{s_dim['column']}",
                "roles": {
                    "x_axis": x_dim['column'],
                    "series": s_dim['column'],
                },
            }
            charts.append(variant_chart)
```

This could generate too many combinations. Simplify: only create variants where the **series** dimension changes (keeping the same x_axis as primary), plus one variant per unused dim as x_axis with the primary series.

**User chose: All pairs** — generate all dimension pair combinations as separate chart groups.

```python
# --- 3b. Variant snapshot bars (all dim pairs) ---
if len(non_singleton) >= 2:
    primary_bar = next((c for c in charts
        if c['chart_type'] in ('grouped_bar', 'bar_vertical', 'horizontal_bar')), None)
    primary_x = primary_bar['roles'].get('x_axis') if primary_bar else None
    primary_s = primary_bar['roles'].get('series') if primary_bar else None

    for x_dim in non_singleton:
        for s_dim in non_singleton:
            if x_dim == s_dim:
                continue
            if x_dim['column'] == primary_x and s_dim['column'] == primary_s:
                continue  # Skip existing primary
            if s_dim['option_count'] > 8:
                continue  # Series too large
            ct = "horizontal_bar" if x_dim['option_count'] > 20 else "grouped_bar"
            variant = {
                "chart_type": ct,
                "is_primary": False,
                "variant": f"by_{s_dim['column']}",
                "roles": {
                    "x_axis": x_dim['column'],
                    "series": s_dim['column'],
                },
            }
            if 2 <= s_dim['option_count'] <= 4:
                variant["toggles"] = ["stacked_bar"]
            charts.append(variant)
```

### 2. Line Chart Toggle in Snapshot
**File**: [generate_view_profiles.py](generate_view_profiles.py) — snapshot bar chart section

Add `"line"` as a toggle on the primary bar chart. When clicked, it renders as a line chart with x_axis=AGE and series=SEX — showing the distribution curve rather than bars. This makes sense for continuous dimensions like age groups.

```python
# In the bar chart toggles section, add:
if bar_toggles is None:
    bar_toggles = []
bar_toggles.append("line")
```

No frontend changes needed — `chart-factory.js` already routes `line` to `createTimeSeriesChart()`, which works with any x-axis dimension (not just time).

### 3. Broaden Bubble Chart Criteria
**File**: [generate_view_profiles.py:621-635](generate_view_profiles.py#L621-L635)

Current rule: only `dim_type == 'indicator'` dims with `option_count >= 3`. This is too restrictive — most demographic datasets have no indicator-type dims.

**New rule**: any 2+ non-singleton dims with `option_count >= 3`. The bubble chart shows one dim as x-axis categories, another as series (color), with bubble size = value. This works for age × gender, age × residence, etc.

```python
# --- 4. Bubble/matrix ---
# Any 2+ non-singleton dims with enough categories
qualifying = [d for d in non_singleton if d['option_count'] >= 3]
if len(qualifying) >= 2:
    q_sorted = sorted(qualifying, key=lambda d: d['option_count'])
    bubble = {
        "chart_type": "bubble",
        "is_primary": False,
        "roles": {
            "x_axis": q_sorted[0]['column'],
            "series": q_sorted[1]['column'],
        },
    }
    if len(qualifying) > 2:
        bubble["dimension_pair_toggle"] = True
    charts.append(bubble)
```

The `dimension_pair_toggle` flag is already generated but not implemented in the frontend. Need to handle it in the UI.

### 4. Bubble Chart: Matrix Mode + Dimension Pair Toggle (Frontend)
**File**: [chart-new-types.js](app/static/js/chart-new-types.js) — `createBubbleChart()`

**User chose: Both (matrix + scatter) as toggle.**

Add a new **bubble matrix mode** for category×category data (no geo). When `x_axis_dim` and `series_dim` are both categories (not time/geo):
- X-axis = dim A categories (e.g. age groups)
- Y-axis = dim B categories (e.g. sex)
- Circle size = value
- Color = value intensity (viridis/blue gradient)

This is a true cross-tabulation bubble matrix. The existing scatter mode becomes a toggle.

```javascript
// In createBubbleChart, after geo-bubble mode:
// ---- Category bubble matrix mode ----
const xDim = config.x_axis_dim;
const sDim = config.series_dim;
const xIdx = xDim ? cols.indexOf(xDim) : -1;
const sIdx = sDim ? cols.indexOf(sDim) : -1;

if (xIdx !== -1 && sIdx !== -1 && geoIdx === -1) {
    const xLabels = labels[xDim] || {};
    const sLabels = labels[sDim] || {};
    const xVals = uniqueValues(rows, xIdx);
    const sVals = uniqueValues(rows, sIdx);
    // Filter totals
    const xCats = xVals.filter(v => !isTotalLabel(xLabels[String(v)] || String(v)));
    const yCats = sVals.filter(v => !isTotalLabel(sLabels[String(v)] || String(v)));

    // Build value matrix
    const dataPoints = [];
    let maxVal = 0;
    for (const row of rows) {
        const xi = xCats.indexOf(row[xIdx]);
        const yi = yCats.indexOf(row[sIdx]);
        if (xi === -1 || yi === -1) continue;
        const v = row[valueIdx] || 0;
        maxVal = Math.max(maxVal, v);
        dataPoints.push([xi, yi, v]);
    }

    chart.setOption({
        tooltip: { formatter: p => ... },
        xAxis: { type: 'category', data: xCats.map(v => xLabels[String(v)] || String(v)) },
        yAxis: { type: 'category', data: yCats.map(v => sLabels[String(v)] || String(v)) },
        visualMap: { min: 0, max: maxVal, inRange: { color: ['#eff6ff', '#1a56db'] } },
        series: [{ type: 'scatter', data: dataPoints, symbolSize: (val) => ... }],
    });
}
```

**Dimension pair toggle** in [dataset-page-v2.js](app/static/js/dataset-page-v2.js):

When `chart.dimension_pair_toggle` is true, render a `<select>` with all dim pairs. On change, update the chart's roles and re-render.

```javascript
if (chart.dimension_pair_toggle) {
    const cats = this.profile.dimensions.categories.filter(d => d.option_count >= 3);
    if (cats.length > 2) {
        const select = el('select', { className: 'dim-pair-select' });
        for (let a = 0; a < cats.length; a++) {
            for (let b = a + 1; b < cats.length; b++) {
                const opt = document.createElement('option');
                opt.textContent = `${cats[a].label} × ${cats[b].label}`;
                opt.value = `${cats[a].column}|${cats[b].column}`;
                select.appendChild(opt);
            }
        }
        select.onchange = () => {
            const [x, s] = select.value.split('|');
            this._bubbleRoles = { x_axis: x, series: s };
            this.fetchAndRender();
        };
        container.appendChild(select);
    }
}
```

## Files to Modify
1. **[generate_view_profiles.py](generate_view_profiles.py)** — Snapshot chart generation: add variant bars, line toggle, broaden bubble criteria
2. **[app/static/js/dataset-page-v2.js](app/static/js/dataset-page-v2.js)** — Dimension pair toggle UI for bubble chart
3. **[app/static/js/chart-new-types.js](app/static/js/chart-new-types.js)** — Bubble chart: add x_axis_dim fallback (like we did for stacked_bar) so it works with category dimensions, not just geo/time

## Verification
1. Regenerate view profiles: `source ~/devbox/envs/240826/bin/activate && python generate_view_profiles.py`
2. Check POP206G profile: `cat data/view-profiles/POP206G.json | python -m json.tool`
   - Snapshot should now have: grouped_bar, stacked_bar, by_RESIDENCE variant, pyramid, bubble, line toggle
3. Start server: `uvicorn app.main:app --reload --port 8080`
4. Open `http://localhost:8080/dataset.html?code=POP206G`, switch to Snapshot:
   - Should see variant "RESIDENCE" chart group
   - Clicking Grouped for RESIDENCE variant should show RESIDENCE on x-axis
   - Bubble chart should appear with AGE × SEX scatter
5. Test dimension pair toggle on a 3+ dim dataset
