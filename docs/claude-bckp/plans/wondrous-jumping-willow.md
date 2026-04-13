# Plan: Monthly/Quarterly Data — Yearly Aggregation Toggle + Initial Zoom

## Context

90 monthly + 27 quarterly datasets render 200–416 data points on the x-axis, making charts unreadable. The x-axis labels pile up, seasonal noise obscures trends, and there's no way to see the long-term picture without manually zooming. Fix: (1) default the Trends chart to yearly-aggregated data for monthly/quarterly datasets, with a toggle back to raw resolution; (2) when the user switches to raw monthly view, default the zoom window to the last ~5 years instead of all 400 months.

All 90 monthly datasets use format `2024-01`; quarterly use `1995-Q1`; annual use `2024`. Aggregation is always client-side (data already fetched), no backend changes needed.

SUM for counts/currency; AVG for percentage/rate/time_unit — same rule already used in `renderInsightCards()` at explore-app.js:1995.

---

## Changes

### File 1: `app/static/js/explore-app.js`

#### 1a. UI labels — add to both `ro` and `en` blocks

**ro block** (after line 67, `yoyTooltip`):
```javascript
yearlyMode: 'Anual',
yearlyTooltip: 'Grupează datele pe ani',
```
**en block** (after line 135, `yoyTooltip`):
```javascript
yearlyMode: 'Yearly',
yearlyTooltip: 'Group data by year',
```

#### 1b. Initialize state in `loadDataset()` — after line 1123

```javascript
// Default to yearly aggregation for monthly/quarterly data
const gran = this.profile?.time_granularity;
this.timeGranularity = gran || null;
this.yearlyAgg = (gran === 'monthly' || gran === 'quarterly');
```

`this.yearlyAgg` is a boolean toggle. `true` = aggregate to yearly; `false` = raw resolution.

#### 1c. Yearly toggle button in `renderChartTypeButtons()` — after line 1448 (end of Index/YoY loop)

Only render the button when `this.timeGranularity` is `'monthly'` or `'quarterly'`:

```javascript
if (this.timeGranularity === 'monthly' || this.timeGranularity === 'quarterly') {
    const sep2 = document.createElement('span');
    sep2.className = 'ct-sep';
    sep2.textContent = '·';
    pills.appendChild(sep2);

    const btn = document.createElement('button');
    btn.className = 'ct-btn transform-btn' + (this.yearlyAgg ? ' active' : '');
    btn.textContent = this.ui.yearlyMode;
    btn.title = this.ui.yearlyTooltip;
    btn.addEventListener('click', () => {
        this.yearlyAgg = !this.yearlyAgg;
        btn.classList.toggle('active', this.yearlyAgg);
        this.renderTimeChart();
        this._syncURL();
    });
    pills.appendChild(btn);
}
```

#### 1d. URL state — `_syncURL()` (around line 1848) and URL restore (around line 1127)

In `_syncURL()`, after the `tmode` block:
```javascript
if (this.yearlyAgg === false && (this.timeGranularity === 'monthly' || this.timeGranularity === 'quarterly'))
    url.searchParams.set('tagg', '0');   // only store when user explicitly turned it off
else
    url.searchParams.delete('tagg');
```

In URL restore block (around line 1127), after `_urlTChart` restore:
```javascript
if (this._urlTAgg !== null) this.yearlyAgg = this._urlTAgg !== '0';
this._urlTAgg = null;
```

In URL parsing (wherever `_urlTChart` is read from `searchParams`, around line ~1080):
```javascript
this._urlTAgg = url.searchParams.get('tagg');
```

#### 1e. `_aggregateByYear()` method — add after `_applyTimeTransform()` (after line 2186)

```javascript
/**
 * Aggregate monthly/quarterly rows to yearly resolution.
 * Groups TIME_PERIOD by the year prefix ("2024-01" → "2024", "1995-Q1" → "1995").
 * Uses AVG for percentage/rate/time_unit, SUM for everything else.
 */
_aggregateByYear(data, timeDim, seriesDim) {
    if (!data || !data.rows.length) return data;
    const cols = data.columns;
    const timeIdx = cols.indexOf(timeDim);
    if (timeIdx === -1) return data;
    const seriesIdx = seriesDim ? cols.indexOf(seriesDim) : -1;
    const valIdx = cols.length - 1;

    const unitType = this.chartConfig?.primary_unit_type;
    const useAvg = unitType === 'percentage' || unitType === 'time_unit' || unitType === 'rate';

    // Key = seriesValue + '|' + year
    const sums = new Map();
    const counts = new Map();
    const firstRow = new Map(); // keep a template row per key

    for (const row of data.rows) {
        const period = String(row[timeIdx] || '');
        const year = period.slice(0, 4);  // "2024-01" → "2024", "1995-Q1" → "1995"
        const seriesVal = seriesIdx >= 0 ? row[seriesIdx] : null;
        const key = `${seriesVal}|${year}`;
        const v = row[valIdx];
        if (v == null) continue;
        sums.set(key, (sums.get(key) || 0) + v);
        counts.set(key, (counts.get(key) || 0) + 1);
        if (!firstRow.has(key)) firstRow.set(key, row);
    }

    const newRows = [];
    for (const [key, sum] of sums) {
        const cnt = counts.get(key);
        const template = [...firstRow.get(key)];
        const year = key.split('|').pop();
        template[timeIdx] = year;
        template[valIdx] = useAvg ? sum / cnt : sum;
        newRows.push(template);
    }

    // Sort by series then year
    newRows.sort((a, b) => {
        if (seriesIdx >= 0 && a[seriesIdx] !== b[seriesIdx])
            return String(a[seriesIdx]).localeCompare(String(b[seriesIdx]));
        return String(a[timeIdx]).localeCompare(String(b[timeIdx]));
    });

    // column_labels: year → year (identity, already human-readable)
    const newLabels = { ...data.column_labels };
    newLabels[timeDim] = Object.fromEntries(newRows.map(r => [r[timeIdx], r[timeIdx]]));

    return { ...data, rows: newRows, column_labels: newLabels };
}
```

#### 1f. Wire into `renderTimeChart()` — replace line 2285

```javascript
const translated = this._translateData(this.data);
// Yearly aggregation (default for monthly/quarterly; user can toggle off)
const aggregated = this.yearlyAgg
    ? this._aggregateByYear(translated, setup.timeDim, setup.timeSeriesDim)
    : translated;
const transformed = this._applyTimeTransform(aggregated, setup.timeDim, setup.timeSeriesDim);
```

Also pass `_yearlyAgg: this.yearlyAgg` in the `cfg` object so `chart-factory.js` knows whether to default the zoom:
```javascript
const cfg = {
    ...this.chartConfig,
    ...
    _yearlyAgg: this.yearlyAgg,
    _timeGranularity: this.timeGranularity,
};
```

---

### File 2: `app/static/js/chart-factory.js`

#### 2a. Default zoom window for dense raw monthly data — in `createTimeSeriesChart()`, replace `dataZoom` block (lines 258–261)

```javascript
// Default zoom: show last ~5 years for dense raw monthly data (not yearly-agg'd)
const isDenseRaw = !config._yearlyAgg && config._timeGranularity === 'monthly' && xData.length > 60;
const zoomStart = isDenseRaw ? Math.max(0, Math.round((1 - 60 / xData.length) * 100)) : 0;

dataZoom: [
    { type: 'inside', xAxisIndex: 0 },
    { type: 'slider', xAxisIndex: 0, start: zoomStart, end: 100 },
],
```

For IPC102A (416 months): `zoomStart = max(0, round((1 - 60/416)*100)) = 86` → shows months 357–416 (last 5 years) by default. User scrolls left to see the full history.

---

## Backlog entry to add

In `docs/BACKLOG.md` under `## Lens UI Improvements`:
```
- [ ] **Monthly/quarterly yearly aggregation toggle** — For monthly (90 datasets) and quarterly
  (27 datasets) data, default the Trends chart to yearly-aggregated values. Toggle button
  ("Yearly") in the chart type pill bar, same pattern as Index/Δ% transforms. Client-side:
  group TIME_PERIOD by year prefix, SUM for counts/currency, AVG for percentage/rate.
  Also: default dataZoom to last 5 years (60 months) when user switches to raw monthly view.
  See explore-app.js _aggregateByYear() + chart-factory.js dataZoom.start.
```

---

## Files to modify

| File | Lines | Change |
|---|---|---|
| `app/static/js/explore-app.js` | ~65, ~133 | Add `yearlyMode`/`yearlyTooltip` labels to ro + en UI objects |
| `app/static/js/explore-app.js` | ~1123 | Init `this.timeGranularity` + `this.yearlyAgg` after `selectedPeriodIdx` |
| `app/static/js/explore-app.js` | ~1448 | Add yearly toggle button after Index/YoY buttons (conditional on granularity) |
| `app/static/js/explore-app.js` | ~1848, ~1080, ~1127 | URL state: persist/restore `tagg=0` |
| `app/static/js/explore-app.js` | after ~2186 | New `_aggregateByYear()` method |
| `app/static/js/explore-app.js` | ~2284 | Wire aggregation into `renderTimeChart()` + pass cfg flags |
| `app/static/js/chart-factory.js` | ~258 | Smart `dataZoom.start` for dense raw monthly |

No backend changes. No new files.

---

## Verification

1. **IPC102A** (416 months, percentages): should default to yearly (34 bars, 1991–2024). Toggle to monthly → zoom shows ~2020–2025. Toggle back → yearly view returns.
2. **FOM106D** (308 months, currency): same pattern. Yearly SUM (or AVG? currency = SUM) → upward wage trend clearly visible.
3. **CON104P** (quarterly, percentages): should default to yearly AVG.
4. **SOM101A** (monthly, counts): yearly SUM aggregation.
5. **Annual dataset (any)**: no toggle shown, no zoom shift — zero regression.
6. URL: `?tagg=0` persists when user turns off yearly mode; absent when on.

```bash
npx playwright screenshot --browser chromium "http://localhost:8080/?code=IPC102A" /tmp/after-ipc102a.png --wait-for-timeout 6000
npx playwright screenshot --browser chromium "http://localhost:8080/?code=FOM106D" /tmp/after-fom106d.png --wait-for-timeout 6000
```
