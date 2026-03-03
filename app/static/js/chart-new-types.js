/**
 * New chart renderers: population_pyramid, horizontal_bar, stacked_bar, heatmap,
 *                      bubble, small_multiples
 */

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

    // Age groups in order (exclude "Total" age)
    const ageIds = uniqueValues(activeRows, ageIdx).filter(id => {
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

    // Use x_axis_dim (highest-cardinality categorical) or geo, fallback to first col
    const catDim = config.x_axis_dim || config.geo_dim || cols[0];
    const catIdx = cols.indexOf(catDim);
    const catLabels = labels[catDim] || {};

    // Aggregate: sum values per category
    const totals = {};
    for (const row of rows) {
        const key = row[catIdx];
        totals[key] = (totals[key] || 0) + (row[valueIdx] || 0);
    }

    // Sort by value desc, take top 40
    const items = Object.entries(totals)
        .map(([id, val]) => ({ name: catLabels[String(id)] || String(id), value: val }))
        .filter(d => {
            const lbl = d.name.trim().toLowerCase();
            return lbl !== 'total' && lbl !== 'toate';
        })
        .sort((a, b) => b.value - a.value)
        .slice(0, 40);

    // Reverse so largest is at top
    items.reverse();

    const option = {
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'shadow' },
            formatter: params => `${params[0].name}<br/>${params[0].marker} <b>${formatNumber(params[0].value)}</b>`,
        },
        grid: { left: 160, right: 20, top: 10, bottom: 30 },
        xAxis: {
            type: 'value',
            axisLabel: { fontSize: 11, formatter: v => formatNumber(v) },
        },
        yAxis: {
            type: 'category',
            data: items.map(d => d.name),
            axisLabel: { fontSize: 11, width: 145, overflow: 'truncate' },
        },
        series: [{
            type: 'bar',
            data: items.map(d => d.value),
            itemStyle: { color: '#1a56db' },
            label: {
                show: items.length <= 20,
                position: 'right',
                fontSize: 10,
                formatter: p => formatNumber(p.value),
            },
        }],
        animationDuration: 300,
    };

    chart.setOption(option);
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
                let html = `<b>${params[0].axisValue}</b><br/>`;
                for (const p of params) {
                    if (p.value !== null && p.value !== undefined) {
                        html += `${p.marker} ${p.seriesName}: <b>${formatNumber(p.value)}</b><br/>`;
                    }
                }
                return html;
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

    // Pick the two categorical dims with the most options (excluding time/unit)
    const dims = metadata.dimensions.filter(d =>
        !['time', 'unit'].includes(d.dim_type) && cols.includes(d.dim_column_name)
    );
    dims.sort((a, b) => b.option_count - a.option_count);

    const xDim = (dims[0] || {}).dim_column_name || cols[0];
    const yDim = (dims[1] || {}).dim_column_name || cols[1 < cols.length - 1 ? 1 : 0];

    const xIdx = cols.indexOf(xDim);
    const yIdx = cols.indexOf(yDim);

    const xLabels = labels[xDim] || {};
    const yLabels = labels[yDim] || {};

    // Aggregate by (x, y) — take latest time if present
    const timeDim = config.time_dim;
    const timeIdx = timeDim ? cols.indexOf(timeDim) : -1;
    const timeIds = timeIdx !== -1 ? uniqueValues(rows, timeIdx) : [null];
    const latestTime = timeIds[timeIds.length - 1];

    const activeRows = latestTime !== null
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

    chart.setOption({
        title: titles,
        tooltip: {
            trigger: 'axis',
            formatter: params => `<b>${params[0].axisValue}</b><br/>${formatNumber(params[0].value)}`,
        },
        grid: gridArr, xAxis: xAxes, yAxis: yAxes, series: seriesArr,
        animationDuration: 300,
    });
    return chart;
}
