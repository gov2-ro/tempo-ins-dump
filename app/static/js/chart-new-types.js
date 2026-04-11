/**
 * New chart renderers: population_pyramid, horizontal_bar, stacked_bar, heatmap,
 *                      bubble, small_multiples, ranking (bump), distribution (box+scatter)
 */

// ---------------------------------------------------------------------------
// Shared: metadata-aware dimension value ordering
// ---------------------------------------------------------------------------

/**
 * Return ordered unique values for a dimension column, using metadata option
 * ordering when available.  Handles both v2 (integer nomItemId) and v3 (string
 * label) data transparently.
 *
 * @param {Array} rows       – data rows
 * @param {number} colIdx    – column index in rows
 * @param {string} dimName   – dimension column name (e.g. "VARSTA")
 * @param {object} metadata  – full metadata object with .dimensions[]
 * @returns {Array} ordered unique values present in data
 */
function orderedDimValues(rows, colIdx, dimName, metadata) {
    if (colIdx === -1) return [];
    const dataVals = new Set(rows.map(r => r[colIdx]).filter(v => v !== null && v !== undefined));
    if (dataVals.size === 0) return [];

    const dimMeta = metadata && metadata.dimensions
        ? metadata.dimensions.find(d => d.dim_column_name === dimName)
        : null;

    if (!dimMeta || !dimMeta.options || dimMeta.options.length === 0) {
        return uniqueValues(rows, colIdx);
    }

    const sampleVal = [...dataVals][0];
    const isStringData = typeof sampleVal === 'string' && isNaN(Number(sampleVal));

    let ordered;
    if (isStringData) {
        // v3: data has string labels, metadata has nomItemIds — match by label
        ordered = dimMeta.options
            .map(o => o.label || o.option_label)
            .filter(lbl => lbl && dataVals.has(lbl));
        // Append any data values not in metadata
        for (const v of dataVals) {
            if (!ordered.includes(v)) ordered.push(v);
        }
    } else {
        // v2: nomItemIds match data values
        ordered = dimMeta.options
            .map(o => o.nom_item_id)
            .filter(id => dataVals.has(id));
        for (const v of dataVals) {
            if (!ordered.includes(v)) ordered.push(v);
        }
    }
    return ordered;
}

// ---------------------------------------------------------------------------
// Population Pyramid
// ---------------------------------------------------------------------------

function createPopulationPyramidChart(container, config, data, metadata) {
    const chart = echarts.init(container);

    const cols = data.columns;
    const labels = data.column_labels;
    const rows = data.rows;
    const valueIdx = cols.length - 1;

    const ageDim    = config.x_axis_dim || config.age_dim;
    const genderDim = config.series_dim || config.gender_dim;
    const timeDim   = config.time_dim;

    const ageIdx    = ageDim    ? cols.indexOf(ageDim)    : -1;
    const genderIdx = genderDim ? cols.indexOf(genderDim) : -1;
    const timeIdx   = timeDim   ? cols.indexOf(timeDim)   : -1;

    if (ageIdx === -1 || genderIdx === -1) {
        return createTimeSeriesChart(container, config, data, metadata);
    }

    const ageLabels    = labels[ageDim]    || {};
    const genderLabels = labels[genderDim] || {};
    const timeLabels   = labels[timeDim]   || {};

    // Pick latest time point
    const timeIds = timeIdx !== -1 ? uniqueValues(rows, timeIdx) : [null];
    const latestTime = timeIds[timeIds.length - 1];

    const activeRows = latestTime !== null
        ? rows.filter(r => r[timeIdx] === latestTime)
        : rows;

    // Identify the two gender IDs (exclude totals)
    const genderIds = uniqueValues(activeRows, genderIdx);
    const nonTotalGenders = genderIds.filter(id => {
        const lbl = (genderLabels[String(id)] || '').trim().toLowerCase();
        return lbl !== 'total' && lbl !== 'toate' && lbl !== 'ambele sexe';
    });
    // Use first two (M/F)
    const [g1, g2] = nonTotalGenders.length >= 2
        ? nonTotalGenders.slice(0, 2)
        : genderIds.slice(0, 2);

    // Age groups in order (exclude "Total" age) — use metadata ordering
    const ageIds = orderedDimValues(activeRows, ageIdx, ageDim, metadata).filter(id => {
        const lbl = (ageLabels[String(id)] || '').trim().toLowerCase();
        return lbl !== 'total' && lbl !== 'toate';
    });

    // Build value maps
    const mapG1 = {}, mapG2 = {};
    for (const row of activeRows) {
        if (row[genderIdx] === g1) mapG1[row[ageIdx]] = row[valueIdx] ?? 0;
        if (row[genderIdx] === g2) mapG2[row[ageIdx]] = row[valueIdx] ?? 0;
    }

    const g1Label = genderLabels[String(g1)] || String(g1);
    const g2Label = genderLabels[String(g2)] || String(g2);
    const ageData = ageIds.map(id => ageLabels[String(id)] || String(id));
    const g1Data  = ageIds.map(id => -(mapG1[id] ?? 0));  // left side = negative
    const g2Data  = ageIds.map(id =>  (mapG2[id] ?? 0));

    const maxVal = Math.max(...ageIds.map(id =>
        Math.max(Math.abs(mapG1[id] ?? 0), Math.abs(mapG2[id] ?? 0))
    ));

    // Timeline subtitle
    let subtitle = '';
    if (latestTime !== null) {
        subtitle = (timeLabels[String(latestTime)] || String(latestTime))
            .replace(/^Anul\s+/, '');
    }

    const option = {
        title: subtitle ? { text: subtitle, textStyle: { fontSize: 13, fontWeight: 'normal', color: '#666' }, left: 'center', top: 4 } : undefined,
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'shadow' },
            formatter(params) {
                const age = params[0].name;
                let html = `<b>${age}</b><br/>`;
                for (const p of params) {
                    html += `${p.marker} ${p.seriesName}: <b>${formatNumber(Math.abs(p.value))}</b><br/>`;
                }
                return html;
            },
        },
        legend: { data: [g1Label, g2Label], bottom: 0 },
        grid: { left: 100, right: 20, top: subtitle ? 40 : 20, bottom: 40 },
        xAxis: {
            type: 'value',
            min: -maxVal * 1.05,
            max:  maxVal * 1.05,
            axisLabel: {
                fontSize: 11,
                formatter: v => formatNumber(Math.abs(v)),
            },
        },
        yAxis: {
            type: 'category',
            data: ageData,
            axisLabel: { fontSize: 11 },
        },
        series: [
            {
                name: g1Label,
                type: 'bar',
                stack: 'pyramid',
                data: g1Data,
                itemStyle: { color: '#1a56db' },
                label: { show: false },
            },
            {
                name: g2Label,
                type: 'bar',
                stack: 'pyramid',
                data: g2Data,
                itemStyle: { color: '#e74694' },
                label: { show: false },
            },
        ],
        animationDuration: 300,
    };

    chart.setOption(option);
    return chart;
}


// ---------------------------------------------------------------------------
// Horizontal Bar (ranking chart)
// ---------------------------------------------------------------------------

function createHorizontalBarChart(container, config, data, metadata) {
    const chart = echarts.init(container);

    const cols     = data.columns;
    const labels   = data.column_labels;
    const rows     = data.rows;
    const valueIdx = cols.length - 1;

    const catDim = config.x_axis_dim || config.geo_dim || cols[0];
    const catIdx = cols.indexOf(catDim);
    const catLabels = labels[catDim] || {};

    const seriesDim = config.series_dim;
    const seriesIdx = seriesDim ? cols.indexOf(seriesDim) : -1;

    // --- No series: single-color bars (original behavior) ---
    if (seriesIdx === -1) {
        const totals = {};
        for (const row of rows) {
            const key = row[catIdx];
            totals[key] = (totals[key] || 0) + (row[valueIdx] || 0);
        }
        const items = Object.entries(totals)
            .map(([id, val]) => ({ name: catLabels[String(id)] || String(id), value: val, id }))
            .filter(d => { const l = d.name.trim().toLowerCase(); return l !== 'total' && l !== 'toate'; })
            .sort((a, b) => b.value - a.value)
            .slice(0, 40)
            .reverse();

        chart.setOption({
            tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
                formatter: params => `${params[0].name}<br/>${params[0].marker} <b>${formatNumber(params[0].value)}</b>` },
            grid: { left: 160, right: 20, top: 10, bottom: 30 },
            xAxis: { type: 'value', axisLabel: { fontSize: 11, formatter: v => formatNumber(v) } },
            yAxis: { type: 'category', data: items.map(d => d.name), axisLabel: { fontSize: 11, width: 145, overflow: 'truncate' } },
            series: [{ type: 'bar', data: items.map(d => d.value), itemStyle: { color: '#1a56db' },
                label: { show: items.length <= 20, position: 'right', fontSize: 10, formatter: p => formatNumber(p.value) } }],
            animationDuration: 300,
        });
        return chart;
    }

    // --- Stacked horizontal bars by series dimension ---
    const seriesLabels = labels[seriesDim] || {};
    const TOTAL_RE = /^(total|toate|ambele sexe|ambele|urban\s*\+\s*rural|m\s*\+\s*f)$/i;

    const allSeriesIds = uniqueValues(rows, seriesIdx);
    const seriesIds = allSeriesIds.filter(id => !TOTAL_RE.test((seriesLabels[String(id)] || '').trim()));

    // Build data: { catId: { seriesId: value } }
    const dataMap = {};
    const catTotals = {};
    for (const row of rows) {
        const cat = row[catIdx];
        const ser = row[seriesIdx];
        if (!seriesIds.includes(ser)) continue;
        if (!dataMap[cat]) dataMap[cat] = {};
        dataMap[cat][ser] = (dataMap[cat][ser] || 0) + (row[valueIdx] || 0);
        catTotals[cat] = (catTotals[cat] || 0) + (row[valueIdx] || 0);
    }

    const catIds = Object.keys(dataMap)
        .filter(id => !TOTAL_RE.test((catLabels[String(id)] || '').trim()))
        .sort((a, b) => (catTotals[b] || 0) - (catTotals[a] || 0))
        .slice(0, 40)
        .reverse();

    const yData = catIds.map(id => catLabels[String(id)] || String(id));
    const COLORS = ['#1a56db', '#e74694', '#0ea5e9', '#f59e0b', '#10b981', '#8b5cf6', '#ef4444', '#64748b'];

    const series = seriesIds.map((sid, i) => ({
        name: seriesLabels[String(sid)] || String(sid),
        type: 'bar',
        stack: 'total',
        data: catIds.map(cid => dataMap[cid]?.[sid] ?? null),
        itemStyle: { color: COLORS[i % COLORS.length] },
    }));

    chart.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
            formatter(params) {
                let html = `<b>${params[0].name}</b><br/>`;
                for (const p of params) {
                    if (p.value !== null && p.value !== undefined) {
                        html += `${p.marker} ${p.seriesName}: <b>${formatNumber(p.value)}</b><br/>`;
                    }
                }
                return html;
            } },
        legend: { show: series.length > 1 && series.length <= 20, type: 'scroll', bottom: 0, textStyle: { fontSize: 11 } },
        grid: { left: 160, right: 20, top: 10, bottom: series.length > 1 ? 50 : 30 },
        xAxis: { type: 'value', axisLabel: { fontSize: 11, formatter: v => formatNumber(v) } },
        yAxis: { type: 'category', data: yData, axisLabel: { fontSize: 11, width: 145, overflow: 'truncate' } },
        series,
        animationDuration: 300,
    });
    return chart;
}


// ---------------------------------------------------------------------------
// Stacked Bar
// ---------------------------------------------------------------------------

function createStackedBarChart(container, config, data, metadata) {
    const chart = echarts.init(container);

    const cols     = data.columns;
    const labels   = data.column_labels;
    const rows     = data.rows;
    const valueIdx = cols.length - 1;

    // x_axis = time, series = small categorical (gender/residence/indicator with ≤4)
    const timeDim   = config.time_dim;
    const seriesDim = config.series_dim;

    const timeIdx   = timeDim   ? cols.indexOf(timeDim)   : -1;
    const seriesIdx = seriesDim ? cols.indexOf(seriesDim) : -1;

    if (timeIdx === -1 || seriesIdx === -1) {
        return createTimeSeriesChart(container, config, data, metadata);
    }

    const timeLabels   = labels[timeDim]   || {};
    const seriesLabels = labels[seriesDim] || {};

    const timeIds = uniqueValues(rows, timeIdx);
    const xData   = timeIds.map(id => {
        let lbl = timeLabels[String(id)] || String(id);
        return lbl.replace(/^Anul\s+/, '');
    });

    // Series IDs — exclude totals
    const allSeriesIds = uniqueValues(rows, seriesIdx);
    const seriesIds = allSeriesIds.filter(id => {
        const lbl = (seriesLabels[String(id)] || '').trim().toLowerCase();
        return lbl !== 'total' && lbl !== 'toate' && lbl !== 'ambele sexe';
    });

    // Cap high-cardinality series — keep top N by sum
    const MAX_SERIES = config.max_series || 8;
    if (seriesIds.length > MAX_SERIES) {
        const sums = {};
        for (const row of rows) {
            const sid = row[seriesIdx];
            if (seriesIds.includes(sid)) sums[sid] = (sums[sid] || 0) + (row[valueIdx] || 0);
        }
        seriesIds.sort((a, b) => (sums[b] || 0) - (sums[a] || 0));
        seriesIds.length = MAX_SERIES;
    }

    const COLORS = ['#1a56db', '#e74694', '#0ea5e9', '#f59e0b', '#10b981', '#8b5cf6', '#ef4444', '#64748b'];

    const series = seriesIds.map((sid, i) => {
        const seriesLabel = seriesLabels[String(sid)] || String(sid);
        const dataMap = {};
        for (const row of rows) {
            if (row[seriesIdx] === sid) {
                dataMap[row[timeIdx]] = row[valueIdx];
            }
        }
        return {
            name: seriesLabel,
            type: 'bar',
            stack: 'total',
            data: timeIds.map(tid => dataMap[tid] ?? null),
            itemStyle: { color: COLORS[i % COLORS.length] },
        };
    });

    const option = {
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'shadow' },
            formatter(params) {
                let rows = '';
                let total = 0;
                for (const p of params) {
                    if (p.value !== null && p.value !== undefined) {
                        rows += `${p.marker} ${p.seriesName}: <b>${formatNumber(p.value)}</b><br/>`;
                        total += p.value;
                    }
                }
                return `<b>${params[0].axisValue}</b><br/>∑ <b>${formatNumber(total)}</b>`
                    + `<hr style="margin:4px 0;border-color:currentColor;opacity:0.15"/>`
                    + rows;
            },
        },
        legend: { type: 'scroll', bottom: 0, textStyle: { fontSize: 11 } },
        grid: { left: 60, right: 20, top: 20, bottom: 50 },
        xAxis: {
            type: 'category',
            data: xData,
            axisLabel: { fontSize: 11, rotate: xData.length > 20 ? 45 : 0 },
        },
        yAxis: {
            type: 'value',
            axisLabel: { fontSize: 11, formatter: v => formatNumber(v) },
        },
        dataZoom: [
            { type: 'inside', xAxisIndex: 0 },
            { type: 'slider', xAxisIndex: 0 }
        ],
        series,
        animationDuration: 300,
    };

    chart.setOption(option);
    return chart;
}


// ---------------------------------------------------------------------------
// Heatmap
// ---------------------------------------------------------------------------

function createHeatmapChart(container, config, data, metadata) {
    const chart = echarts.init(container);

    const cols     = data.columns;
    const labels   = data.column_labels;
    const rows     = data.rows;
    const valueIdx = cols.length - 1;

    // Pick x/y dims: prefer user-assigned roles, fall back to auto-detect by cardinality
    const dims = metadata.dimensions.filter(d =>
        !['time', 'unit'].includes(d.dim_type) && cols.includes(d.dim_column_name)
    );
    dims.sort((a, b) => b.option_count - a.option_count);

    const userChoseTimeAsX = config.x_axis_dim && config.x_axis_dim === config.time_dim;
    let xDim = config.x_axis_dim || (dims[0] || {}).dim_column_name || cols[0];
    let yDim = config.series_dim || (dims[1] || {}).dim_column_name || cols[1 < cols.length - 1 ? 1 : 0];

    // Dedup: ensure x and y are different dimensions
    if (xDim === yDim) {
        // Try to find a different dim for y
        const altDim = dims.find(d => d.dim_column_name !== xDim);
        if (altDim) {
            yDim = altDim.dim_column_name;
        } else {
            // Only 1 qualifying dim — use time as the other axis if available
            const timeDim = config.time_dim;
            if (timeDim && cols.includes(timeDim) && timeDim !== xDim) {
                yDim = timeDim;
            } else {
                // Cannot make a heatmap with < 2 dims — fall back
                container.innerHTML = '<div class="chart-loading">Not enough dimensions for heatmap</div>';
                return chart;
            }
        }
    }

    const xIdx = cols.indexOf(xDim);
    const yIdx = cols.indexOf(yDim);

    const xLabels = labels[xDim] || {};
    const yLabels = labels[yDim] || {};

    // Aggregate by (x, y) — take latest time if present, unless user chose time as x-axis
    const timeDim = config.time_dim;
    const timeIdx = timeDim ? cols.indexOf(timeDim) : -1;
    const timeIds = timeIdx !== -1 ? uniqueValues(rows, timeIdx) : [null];
    const latestTime = timeIds[timeIds.length - 1];

    const activeRows = (latestTime !== null && !userChoseTimeAsX)
        ? rows.filter(r => r[timeIdx] === latestTime)
        : rows;

    const xIds = uniqueValues(activeRows, xIdx).filter(id => {
        const lbl = (xLabels[String(id)] || '').trim().toLowerCase();
        return lbl !== 'total' && lbl !== 'toate';
    });
    const yIds = uniqueValues(activeRows, yIdx).filter(id => {
        const lbl = (yLabels[String(id)] || '').trim().toLowerCase();
        return lbl !== 'total' && lbl !== 'toate';
    });

    // Limit to 30×30 for readability
    const xSlice = xIds.slice(0, 30);
    const ySlice = yIds.slice(0, 30);

    const xSet = new Set(xSlice);
    const ySet = new Set(ySlice);

    const cellMap = {};
    for (const row of activeRows) {
        const x = row[xIdx], y = row[yIdx];
        if (xSet.has(x) && ySet.has(y)) {
            cellMap[`${x}__${y}`] = row[valueIdx];
        }
    }

    const heatData = [];
    let minVal = Infinity, maxVal = -Infinity;
    for (let xi = 0; xi < xSlice.length; xi++) {
        for (let yi = 0; yi < ySlice.length; yi++) {
            const v = cellMap[`${xSlice[xi]}__${ySlice[yi]}`] ?? null;
            if (v !== null) {
                heatData.push([xi, yi, v]);
                if (v < minVal) minVal = v;
                if (v > maxVal) maxVal = v;
            }
        }
    }

    if (heatData.length === 0) {
        chart.setOption({
            title: { text: 'No data for selected dimensions', left: 'center', top: 'center',
                     textStyle: { fontSize: 14, color: '#999' } },
        });
        return chart;
    }

    const xData = xSlice.map(id => {
        const lbl = xLabels[String(id)] || String(id);
        return lbl.length > 20 ? lbl.slice(0, 18) + '…' : lbl;
    });
    const yData = ySlice.map(id => {
        const lbl = yLabels[String(id)] || String(id);
        return lbl.length > 20 ? lbl.slice(0, 18) + '…' : lbl;
    });

    const option = {
        tooltip: {
            position: 'top',
            formatter(p) {
                return `${xData[p.data[0]]}<br/>${yData[p.data[1]]}<br/><b>${formatNumber(p.data[2])}</b>`;
            },
        },
        grid: { left: 120, right: 80, top: 20, bottom: 80 },
        xAxis: {
            type: 'category',
            data: xData,
            axisLabel: { fontSize: 10, rotate: 45, interval: 0 },
            splitArea: { show: true },
        },
        yAxis: {
            type: 'category',
            data: yData,
            axisLabel: { fontSize: 10, width: 110, overflow: 'truncate' },
            splitArea: { show: true },
        },
        visualMap: {
            min: minVal,
            max: maxVal,
            calculable: true,
            orient: 'vertical',
            right: 0,
            top: 'center',
            textStyle: { fontSize: 10 },
            formatter: v => formatNumber(v),
            inRange: { color: ['#e8f4fd', '#1a56db'] },
        },
        series: [{
            type: 'heatmap',
            data: heatData,
            label: { show: xSlice.length <= 15 && ySlice.length <= 15, fontSize: 9 },
            emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' } },
        }],
        animationDuration: 300,
    };

    chart.setOption(option);
    return chart;
}


// ---------------------------------------------------------------------------
// Bubble chart
// Two modes:
//   geo bubble  — geo sorted by value, bubble size = value
//   scatter bubble — time × category, size = value
// ---------------------------------------------------------------------------

function createBubbleChart(container, config, data, metadata) {
    const chart = echarts.init(container);

    const cols     = data.columns;
    const labels   = data.column_labels;
    const rows     = data.rows;
    const valueIdx = cols.length - 1;

    const geoDim    = config.geo_dim;
    const timeDim   = config.time_dim;
    const seriesDim = config.series_dim;

    const geoIdx    = geoDim    ? cols.indexOf(geoDim)    : -1;
    const timeIdx   = timeDim   ? cols.indexOf(timeDim)   : -1;
    const seriesIdx = seriesDim ? cols.indexOf(seriesDim) : -1;

    const geoLabels    = labels[geoDim]    || {};
    const timeLabels   = labels[timeDim]   || {};
    const seriesLabels = labels[seriesDim] || {};

    // ---- Category bubble matrix mode (dim × dim) ----
    // Check this FIRST: if the profile explicitly assigned x_axis + series roles,
    // use category matrix even for geo datasets.
    const xAxisDim = config.x_axis_dim;
    const xAxisIdx = xAxisDim ? cols.indexOf(xAxisDim) : -1;
    const catSeriesIdx = seriesIdx !== -1 ? seriesIdx : -1;

    if (xAxisIdx !== -1 && catSeriesIdx !== -1) {
        const xLbls = labels[xAxisDim] || {};
        const sLbls = labels[seriesDim] || {};

        const xVals = orderedDimValues(rows, xAxisIdx, xAxisDim, metadata);
        const yVals = orderedDimValues(rows, catSeriesIdx, seriesDim, metadata);

        // Filter out "Total"-like values
        const isTotal = lbl => {
            const l = (lbl || '').trim().toLowerCase();
            return l === 'total' || l === 'toate' || l === 'ambele sexe';
        };
        const xCats = xVals.filter(v => !isTotal(xLbls[String(v)] || String(v)));
        const yCats = yVals.filter(v => !isTotal(sLbls[String(v)] || String(v)));

        const xCatLabels = xCats.map(v => xLbls[String(v)] || String(v));
        const yCatLabels = yCats.map(v => sLbls[String(v)] || String(v));

        // Build value matrix
        const dataPoints = [];
        let maxVal = 0;
        for (const row of rows) {
            const xi = xCats.indexOf(row[xAxisIdx]);
            const yi = yCats.indexOf(row[catSeriesIdx]);
            if (xi === -1 || yi === -1) continue;
            const v = row[valueIdx] || 0;
            if (v > maxVal) maxVal = v;
            dataPoints.push([xi, yi, v]);
        }

        if (dataPoints.length > 0) {
            const maxSize = Math.min(50, Math.max(500 / Math.max(xCats.length, yCats.length), 12));
            chart.setOption({
                tooltip: {
                    formatter: p => {
                        const [xi, yi, v] = p.value;
                        return `<b>${xCatLabels[xi]}</b> × <b>${yCatLabels[yi]}</b><br/>${formatNumber(v)}`;
                    },
                },
                grid: {
                    left: Math.min(140, 12 * Math.max(...yCatLabels.map(l => l.length))),
                    right: 60, top: 20,
                    bottom: xCatLabels.some(l => l.length > 6) ? 80 : 40,
                },
                xAxis: {
                    type: 'category', data: xCatLabels,
                    axisLabel: { fontSize: 11, rotate: xCatLabels.length > 8 ? 35 : 0, interval: 0 },
                },
                yAxis: {
                    type: 'category', data: yCatLabels,
                    axisLabel: { fontSize: 11 },
                },
                visualMap: {
                    show: true, min: 0, max: maxVal, dimension: 2,
                    orient: 'vertical', right: 0, top: 'center',
                    textStyle: { fontSize: 10 },
                    formatter: v => formatNumber(v),
                    inRange: { color: ['#eff6ff', '#3b82f6', '#1a56db'] },
                },
                series: [{
                    type: 'scatter',
                    data: dataPoints,
                    symbolSize: val => {
                        const v = Array.isArray(val) ? val[2] : val;
                        return 4 + maxSize * Math.sqrt(v / (maxVal || 1));
                    },
                }],
                animationDuration: 300,
            });
            return chart;
        }
    }

    // ---- Geo bubble mode ----
    if (geoIdx !== -1) {
        const timeIds = timeIdx !== -1 ? uniqueValues(rows, timeIdx) : [null];
        const latestTime = timeIds[timeIds.length - 1];
        const activeRows = latestTime !== null
            ? rows.filter(r => r[timeIdx] === latestTime)
            : rows;

        const geoTotals = {};
        for (const row of activeRows) {
            const gid = row[geoIdx];
            geoTotals[gid] = (geoTotals[gid] || 0) + (row[valueIdx] || 0);
        }

        const items = Object.entries(geoTotals)
            .map(([id, val]) => ({ id, val, name: geoLabels[String(id)] || String(id) }))
            .filter(d => {
                const lbl = d.name.trim().toLowerCase();
                return lbl !== 'total' && lbl !== 'toate'
                    && !lbl.startsWith('macroregiunea') && !lbl.startsWith('regiunea');
            })
            .sort((a, b) => b.val - a.val);

        if (items.length === 0) {
            // No geo data after filtering — fall through to scatter mode
        } else {

        const maxVal = Math.max(...items.map(d => d.val));
        const minVal = Math.min(...items.map(d => d.val));
        const subtitle = latestTime !== null
            ? (timeLabels[String(latestTime)] || String(latestTime)).replace(/^Anul\s+/, '')
            : '';

        chart.setOption({
            title: subtitle ? { text: subtitle, textStyle: { fontSize: 13, fontWeight: 'normal', color: '#666' }, left: 'center', top: 4 } : undefined,
            tooltip: { formatter: p => `<b>${p.name}</b><br/>${formatNumber(p.value[1])}` },
            grid: { left: 120, right: 20, top: subtitle ? 40 : 20, bottom: 30 },
            xAxis: { show: false, min: 0, max: items.length - 1 },
            yAxis: {
                type: 'category',
                data: items.map(d => d.name).reverse(),
                axisLabel: { fontSize: 11, width: 110, overflow: 'truncate' },
            },
            visualMap: {
                show: true, min: minVal, max: maxVal, dimension: 1,
                orient: 'horizontal', bottom: 0, left: 'center',
                textStyle: { fontSize: 10 },
                formatter: v => formatNumber(v),
                inRange: { color: ['#bfdbfe', '#1a56db'] },
            },
            series: [{
                type: 'scatter',
                data: items.map((d, i) => ({
                    name: d.name,
                    value: [i, d.val],
                    symbolSize: 10 + 40 * Math.sqrt((d.val - minVal) / (maxVal - minVal + 1)),
                })).reverse(),
                encode: { x: 0, y: 1 },
            }],
            animationDuration: 300,
        });
        return chart;
        } // end else (items.length > 0)
    }

    // ---- Scatter-bubble mode (time × category) ----
    const timeIds = timeIdx !== -1 ? uniqueValues(rows, timeIdx) : [];
    const xData = timeIds.map(id =>
        (timeLabels[String(id)] || String(id)).replace(/^Anul\s+/, '')
    );
    const COLORS = ['#1a56db','#e74694','#0ea5e9','#f59e0b','#10b981','#8b5cf6','#ef4444','#64748b'];
    const seriesIds = seriesIdx !== -1 ? uniqueValues(rows, seriesIdx).filter(id => {
        const lbl = (seriesLabels[String(id)] || '').trim().toLowerCase();
        return lbl !== 'total' && lbl !== 'toate';
    }) : [null];

    const maxVal = Math.max(...rows.map(r => r[valueIdx] || 0));

    const series = seriesIds.map((sid, i) => {
        const seriesLabel = sid !== null
            ? (seriesLabels[String(sid)] || String(sid))
            : (metadata.matrix_name || 'Value');
        const dataMap = {};
        for (const row of rows) {
            if (sid === null || row[seriesIdx] === sid)
                dataMap[row[timeIdx]] = row[valueIdx];
        }
        return {
            name: seriesLabel, type: 'scatter',
            data: timeIds.map((tid, xi) => {
                const v = dataMap[tid] ?? null;
                return v !== null ? { value: [xi, v], symbolSize: 6 + 30 * Math.sqrt(v / maxVal) } : null;
            }).filter(Boolean),
            itemStyle: { color: COLORS[i % COLORS.length], opacity: 0.8 },
        };
    });

    chart.setOption({
        tooltip: { formatter: p => `<b>${xData[p.value[0]]}</b><br/>${p.seriesName}: <b>${formatNumber(p.value[1])}</b>` },
        legend: { type: 'scroll', bottom: 0, textStyle: { fontSize: 11 } },
        grid: { left: 60, right: 20, top: 20, bottom: 50 },
        xAxis: { type: 'category', data: xData, axisLabel: { fontSize: 11, rotate: xData.length > 20 ? 45 : 0 } },
        yAxis: { type: 'value', axisLabel: { fontSize: 11, formatter: v => formatNumber(v) } },
        series,
        animationDuration: 300,
    });
    return chart;
}


// ---------------------------------------------------------------------------
// Scatter/Correlation chart — pivots one dimension's categories into X/Y axes
// Each bubble = one entity, positioned at (value_for_X_category, value_for_Y_category)
// ---------------------------------------------------------------------------

function createScatterChart(container, config, data, metadata) {
    const chart = echarts.init(container);

    const cols     = data.columns;
    const labels   = data.column_labels;
    const rows     = data.rows;
    const valueIdx = cols.length - 1;

    const pivotDim  = config.pivot_dim;
    const entityDim = config.entity_dim;
    const xCat      = config.x_category;
    const yCat      = config.y_category;

    const pivotIdx  = pivotDim  ? cols.indexOf(pivotDim)  : -1;
    const entityIdx = entityDim ? cols.indexOf(entityDim) : -1;

    if (pivotIdx === -1 || entityIdx === -1 || xCat == null || yCat == null) {
        chart.setOption({
            title: { text: 'Select X and Y axes', left: 'center', top: 'center',
                     textStyle: { color: '#999', fontSize: 14 } },
        });
        return chart;
    }

    const entityLabels = labels[entityDim] || {};
    const pivotLabels  = labels[pivotDim]  || {};

    // Group rows by entity → { pivotValue: obsValue }
    const entityMap = {};
    for (const row of rows) {
        const eid = row[entityIdx];
        const pid = row[pivotIdx];
        if (!entityMap[eid]) entityMap[eid] = {};
        entityMap[eid][pid] = (entityMap[eid][pid] || 0) + (row[valueIdx] || 0);
    }

    // Build scatter points
    const points = [];
    for (const [eid, vals] of Object.entries(entityMap)) {
        const x = vals[xCat];
        const y = vals[yCat];
        if (x != null && y != null) {
            const name = entityLabels[String(eid)] || String(eid);
            // Skip total-like labels
            const lbl = name.trim().toLowerCase();
            if (lbl === 'total' || lbl === 'toate' || lbl === 'ambele sexe') continue;
            points.push({ name, value: [x, y] });
        }
    }

    if (points.length === 0) {
        chart.setOption({
            title: { text: 'No data for selected axes', left: 'center', top: 'center',
                     textStyle: { color: '#999', fontSize: 14 } },
        });
        return chart;
    }

    const xLabel = pivotLabels[String(xCat)] || String(xCat);
    const yLabel = pivotLabels[String(yCat)] || String(yCat);
    const showLabels = points.length <= 25;

    chart.setOption({
        tooltip: {
            formatter: p => {
                return `<b>${p.name}</b><br/>${xLabel}: <b>${formatNumber(p.value[0])}</b><br/>${yLabel}: <b>${formatNumber(p.value[1])}</b>`;
            },
        },
        grid: { left: 70, right: 30, top: 20, bottom: 60 },
        xAxis: {
            type: 'value',
            name: xLabel,
            nameLocation: 'center',
            nameGap: 35,
            nameTextStyle: { fontSize: 12 },
            axisLabel: { fontSize: 11, formatter: v => formatNumber(v) },
        },
        yAxis: {
            type: 'value',
            name: yLabel,
            nameLocation: 'center',
            nameGap: 55,
            nameTextStyle: { fontSize: 12 },
            axisLabel: { fontSize: 11, formatter: v => formatNumber(v) },
        },
        series: [{
            type: 'scatter',
            data: points,
            symbolSize: 14,
            itemStyle: { color: '#3b82f6', opacity: 0.8 },
            emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)', opacity: 1 } },
            label: {
                show: showLabels,
                formatter: '{b}',
                position: 'right',
                fontSize: 10,
                color: '#555',
            },
        }],
        animationDuration: 300,
    });
    return chart;
}


// ---------------------------------------------------------------------------
// Small Multiples — grid of mini line charts, one per facet value
// ---------------------------------------------------------------------------

function createSmallMultiplesChart(container, config, data, metadata) {
    const chart = echarts.init(container);

    const cols     = data.columns;
    const labels   = data.column_labels;
    const rows     = data.rows;
    const valueIdx = cols.length - 1;

    const timeDim  = config.time_dim;
    const facetDim = config.facet_dim;

    const timeIdx  = timeDim  ? cols.indexOf(timeDim)  : -1;
    const facetIdx = facetDim ? cols.indexOf(facetDim) : -1;

    if (timeIdx === -1 || facetIdx === -1) {
        return createTimeSeriesChart(container, config, data, metadata);
    }

    const timeLabels  = labels[timeDim]  || {};
    const facetLabels = labels[facetDim] || {};

    const timeIds = uniqueValues(rows, timeIdx);
    const xData   = timeIds.map(id =>
        (timeLabels[String(id)] || String(id)).replace(/^Anul\s+/, '')
    );

    const allFacetIds = uniqueValues(rows, facetIdx);
    const facetIds = allFacetIds
        .filter(id => {
            const lbl = (facetLabels[String(id)] || '').trim().toLowerCase();
            return lbl !== 'total' && lbl !== 'toate';
        })
        .slice(0, 16);

    const n = facetIds.length;
    const nCols = Math.min(4, n);
    const nRows = Math.ceil(n / nCols);

    const gridArr = [], xAxes = [], yAxes = [], seriesArr = [], titles = [];
    const cellW = 100 / nCols;
    const cellH = 100 / nRows;
    const pad = 2;

    for (let i = 0; i < n; i++) {
        const fid = facetIds[i];
        const c = i % nCols;
        const r = Math.floor(i / nCols);

        gridArr.push({
            left: `${c * cellW + pad}%`, top: `${r * cellH + pad + 6}%`,
            width: `${cellW - pad * 2}%`, height: `${cellH - pad * 2 - 8}%`,
            containLabel: false,
        });
        xAxes.push({
            type: 'category', data: xData, gridIndex: i,
            axisLabel: { show: r === nRows - 1, fontSize: 9, rotate: 45 },
            axisTick: { show: false },
            axisLine: { lineStyle: { color: '#ddd' } },
        });
        yAxes.push({
            type: 'value', gridIndex: i,
            axisLabel: { show: c === 0, fontSize: 9, formatter: v => formatNumber(v, 0) },
            splitLine: { lineStyle: { color: '#f0f0f0' } },
        });

        const dataMap = {};
        for (const row of rows) {
            if (row[facetIdx] === fid) dataMap[row[timeIdx]] = row[valueIdx];
        }
        seriesArr.push({
            type: 'line', smooth: true,
            xAxisIndex: i, yAxisIndex: i,
            data: timeIds.map(tid => dataMap[tid] ?? null),
            connectNulls: true,
            lineStyle: { width: 1.5 }, symbol: 'none',
            itemStyle: { color: '#1a56db' },
            areaStyle: { color: 'rgba(26,86,219,0.08)' },
        });

        const lbl = facetLabels[String(fid)] || String(fid);
        titles.push({
            text: lbl.length > 22 ? lbl.slice(0, 20) + '…' : lbl,
            left: `${c * cellW + cellW / 2}%`,
            top:  `${r * cellH + pad}%`,
            textAlign: 'center',
            textStyle: { fontSize: 10, fontWeight: 'normal', color: '#555' },
        });
    }

    // Create dataZoom for each small multiple
    const dataZoomArr = [];
    for (let i = 0; i < n; i++) {
        dataZoomArr.push({ type: 'inside', xAxisIndex: i });
        dataZoomArr.push({ type: 'slider', xAxisIndex: i, height: 16 });
    }

    chart.setOption({
        title: titles,
        tooltip: {
            trigger: 'axis',
            formatter: params => `<b>${params[0].axisValue}</b><br/>${formatNumber(params[0].value)}`,
        },
        grid: gridArr, xAxis: xAxes, yAxis: yAxes, series: seriesArr,
        dataZoom: dataZoomArr,
        animationDuration: 300,
    });
    return chart;
}

// ---------------------------------------------------------------------------
// Ranking / Bump chart — rank positions over time (rank 1 = highest value)
// ---------------------------------------------------------------------------

function createRankingChart(container, config, data, metadata) {
    const chart = echarts.init(container);
    const cols = data.columns;
    const labels = data.column_labels || {};
    const timeDim = config.time_dim;
    const seriesDim = config.series_dim;
    const valIdx = cols.length - 1;
    const timeIdx = timeDim ? cols.indexOf(timeDim) : -1;
    const seriesIdx = seriesDim ? cols.indexOf(seriesDim) : -1;

    if (timeIdx === -1 || seriesIdx === -1) {
        return createTimeSeriesChart(container, config, data, metadata);
    }

    const timeLabels = labels[timeDim] || {};
    const seriesLabels = labels[seriesDim] || {};

    const timePts = uniqueValues(data.rows, timeIdx);
    const allSeries = uniqueValues(data.rows, seriesIdx);

    // Build value map: series → time → value
    const valueMap = {};
    for (const row of data.rows) {
        const s = row[seriesIdx];
        const t = row[timeIdx];
        const v = row[valIdx];
        if (!valueMap[s]) valueMap[s] = {};
        if (valueMap[s][t] == null && v != null) valueMap[s][t] = v;
    }

    // Compute rank per time point (1 = highest)
    const rankMap = {};
    for (const t of timePts) {
        const valid = allSeries
            .filter(s => valueMap[s]?.[t] != null)
            .sort((a, b) => (valueMap[b][t] || 0) - (valueMap[a][t] || 0));
        valid.forEach((s, i) => {
            if (!rankMap[s]) rankMap[s] = {};
            rankMap[s][t] = i + 1;
        });
    }

    // Cap to top 15 by average rank
    const MAX_SERIES = 15;
    let displaySeries = allSeries;
    if (allSeries.length > MAX_SERIES) {
        displaySeries = allSeries
            .map(s => {
                const ranks = timePts.map(t => rankMap[s]?.[t] ?? 999);
                return { s, avg: ranks.reduce((a, b) => a + b, 0) / ranks.length };
            })
            .sort((a, b) => a.avg - b.avg)
            .slice(0, MAX_SERIES)
            .map(x => x.s);
    }

    const maxRank = Math.max(...displaySeries.flatMap(s => timePts.map(t => rankMap[s]?.[t] || 0)));
    const xData = timePts.map(t => (timeLabels[String(t)] || String(t)).replace(/^Anul\s+/, ''));

    const palette = ['#5470c6','#91cc75','#fac858','#ee6666','#73c0de','#3ba272','#fc8452','#9a60b4','#ea7ccc',
        '#91cc75','#5470c6','#fac858','#ee6666','#73c0de','#3ba272'];

    const series = displaySeries.map((s, i) => ({
        name: seriesLabels[String(s)] || String(s),
        type: 'line',
        data: timePts.map(t => rankMap[s]?.[t] ?? null),
        smooth: 0.2,
        symbol: 'circle',
        symbolSize: 7,
        lineStyle: { width: 2, color: palette[i % palette.length] },
        itemStyle: { color: palette[i % palette.length] },
        label: {
            show: true,
            position: 'right',
            formatter: p => p.dataIndex === timePts.length - 1 ? (seriesLabels[String(s)] || String(s)) : '',
            fontSize: 10,
        },
        emphasis: { lineStyle: { width: 4 } },
        connectNulls: false,
    }));

    chart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis',
            formatter: params => {
                const header = `<b>${params[0]?.axisValue}</b><br/>`;
                return header + params
                    .filter(p => p.value != null)
                    .sort((a, b) => a.value - b.value)
                    .map(p => `${p.marker}${p.seriesName}: <b>#${p.value}</b>`)
                    .join('<br/>');
            },
        },
        legend: { show: false },
        grid: { top: 20, right: 140, bottom: 40, left: 50 },
        xAxis: { type: 'category', data: xData, boundaryGap: false },
        yAxis: {
            type: 'value',
            inverse: true,
            min: 1,
            max: maxRank,
            interval: 1,
            axisLabel: { formatter: '#{value}' },
            name: 'Rank',
            nameLocation: 'middle',
            nameGap: 35,
        },
        series,
        animationDuration: 400,
    });

    window.addEventListener('resize', () => { if (!chart.isDisposed()) chart.resize(); });
    return chart;
}

// ---------------------------------------------------------------------------
// Distribution strip — box plot + scatter dots (compact, for distribution-strip)
// ---------------------------------------------------------------------------

function createDistributionChart(container, values, periodLabel) {
    const chart = echarts.init(container);
    const sorted = [...values].filter(v => v != null && !isNaN(v)).sort((a, b) => a - b);
    const n = sorted.length;
    if (n === 0) return chart;

    const q = p => sorted[Math.max(0, Math.floor(n * p))];
    const min = sorted[0], max = sorted[n - 1];
    const q1 = q(0.25), median = q(0.5), q3 = q(0.75);
    const mean = sorted.reduce((a, b) => a + b, 0) / n;

    // Jitter y for scatter (avoid all dots on same line)
    const scatterData = sorted.map(v => [v, (Math.random() - 0.5) * 0.6]);

    chart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'item',
            formatter: p => {
                if (p.seriesType === 'boxplot') {
                    return `Min: ${formatNumber(min)}<br/>Q1: ${formatNumber(q1)}<br/>Median: ${formatNumber(median)}<br/>Q3: ${formatNumber(q3)}<br/>Max: ${formatNumber(max)}`;
                }
                return formatNumber(p.value[0]);
            },
        },
        grid: { top: 8, bottom: 28, left: 16, right: 16, containLabel: true },
        xAxis: {
            type: 'value',
            name: periodLabel,
            nameLocation: 'middle',
            nameGap: 18,
            nameTextStyle: { fontSize: 10, opacity: 0.6 },
            axisLabel: { fontSize: 10, formatter: v => formatNumber(v) },
            splitLine: { show: false },
        },
        yAxis: {
            type: 'value',
            show: false,
            min: -1,
            max: 1,
        },
        series: [
            {
                type: 'scatter',
                data: scatterData,
                symbolSize: 5,
                itemStyle: { color: 'var(--accent, #5470c6)', opacity: 0.45 },
                z: 1,
            },
            {
                type: 'custom',
                renderItem(params, api) {
                    const x1 = api.coord([min, 0]);
                    const x2 = api.coord([q1, 0]);
                    const x3 = api.coord([median, 0]);
                    const x4 = api.coord([q3, 0]);
                    const x5 = api.coord([max, 0]);
                    const halfH = 12;
                    const y = x1[1];
                    return {
                        type: 'group',
                        children: [
                            // whisker lines
                            { type: 'line', shape: { x1: x1[0], y1: y, x2: x2[0], y2: y }, style: { stroke: 'var(--accent, #5470c6)', lineWidth: 1.5, opacity: 0.7 } },
                            { type: 'line', shape: { x1: x4[0], y1: y, x2: x5[0], y2: y }, style: { stroke: 'var(--accent, #5470c6)', lineWidth: 1.5, opacity: 0.7 } },
                            // min/max caps
                            { type: 'line', shape: { x1: x1[0], y1: y - halfH/2, x2: x1[0], y2: y + halfH/2 }, style: { stroke: 'var(--accent, #5470c6)', lineWidth: 1.5, opacity: 0.7 } },
                            { type: 'line', shape: { x1: x5[0], y1: y - halfH/2, x2: x5[0], y2: y + halfH/2 }, style: { stroke: 'var(--accent, #5470c6)', lineWidth: 1.5, opacity: 0.7 } },
                            // IQR box
                            { type: 'rect', shape: { x: x2[0], y: y - halfH, width: x4[0] - x2[0], height: halfH * 2 }, style: { fill: 'var(--accent, #5470c6)', opacity: 0.2, stroke: 'var(--accent, #5470c6)', lineWidth: 1.5 } },
                            // median line
                            { type: 'line', shape: { x1: x3[0], y1: y - halfH, x2: x3[0], y2: y + halfH }, style: { stroke: 'var(--accent, #5470c6)', lineWidth: 2.5 } },
                        ],
                    };
                },
                data: [0],  // single entry triggers renderItem once
                z: 2,
                tooltip: { show: false },
            },
        ],
    });

    window.addEventListener('resize', () => { if (!chart.isDisposed()) chart.resize(); });
    return chart;
}
