/**
 * Bubble / scatter chart.
 * slots.x_axis = categorical or geo dim, slots.series = series grouping.
 */
function createBubbleChart(container, slots, data, metadata) {
    const chart = echarts.init(container);

    const cols     = data.columns;
    const labels   = data.column_labels;
    const rows     = data.rows;
    const valueIdx = cols.length - 1;

    const xDim      = slots.x_axis;
    const seriesDim = slots.series;
    const xIdx      = xDim      ? cols.indexOf(xDim)      : -1;
    const seriesIdx = seriesDim ? cols.indexOf(seriesDim) : -1;

    const xLabels      = labels[xDim]      || {};
    const seriesLabels = labels[seriesDim] || {};

    // Time dim for latest-point filtering
    const timeDimMeta = metadata.dimensions.find(d => d.dim_type === 'time');
    const timeDim     = timeDimMeta?.dim_column_name;
    const timeIdx     = timeDim ? cols.indexOf(timeDim) : -1;
    const timeLabels  = labels[timeDim] || {};
    const timeIds     = timeIdx !== -1 ? uniqueValues(rows, timeIdx) : [null];
    const latestTime  = timeIds[timeIds.length - 1];

    // ---- Time-based scatter: x=time, y=value, size=value, color=series ----
    if (xIdx === -1 || (timeDim && xDim === timeDim)) {
        const activeTimeIds = timeIdx !== -1 ? uniqueValues(rows, timeIdx) : [];
        const xData = activeTimeIds.map(id =>
            (timeLabels[String(id)] || String(id)).replace(/^Anul\s+/, '')
        );
        const COLORS = ['#c85a2a','#3b82f6','#8b5cf6','#10b981','#f59e0b','#ef4444','#64748b','#e74694'];

        const seriesIds = seriesIdx !== -1 ? uniqueValues(rows, seriesIdx).filter(id => {
            const lbl = (seriesLabels[String(id)] || '').trim().toLowerCase();
            return lbl !== 'total' && lbl !== 'toate';
        }) : [null];

        const maxVal = Math.max(...rows.map(r => r[valueIdx] || 0));

        const series = seriesIds.map((sid, i) => {
            const sLabel = sid !== null
                ? (seriesLabels[String(sid)] || String(sid))
                : (metadata.matrix_name || 'Value');
            const dataMap = {};
            for (const row of rows) {
                if (sid === null || row[seriesIdx] === sid)
                    dataMap[row[timeIdx]] = row[valueIdx];
            }
            return {
                name: sLabel, type: 'scatter',
                data: activeTimeIds.map((tid, xi) => {
                    const v = dataMap[tid] ?? null;
                    return v !== null ? { value: [xi, v], symbolSize: 6 + 30 * Math.sqrt(v / (maxVal || 1)) } : null;
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

    // ---- Category bubble: x=category, bubble size = value (latest time) ----
    const activeRows = latestTime !== null ? rows.filter(r => r[timeIdx] === latestTime) : rows;

    const catTotals = {};
    for (const row of activeRows) {
        const key = row[xIdx];
        catTotals[key] = (catTotals[key] || 0) + (row[valueIdx] || 0);
    }

    const items = Object.entries(catTotals)
        .map(([id, val]) => ({ name: xLabels[String(id)] || String(id), value: val }))
        .filter(d => {
            const lbl = d.name.trim().toLowerCase();
            return lbl !== 'total' && lbl !== 'toate';
        })
        .sort((a, b) => b.value - a.value);

    const maxVal = Math.max(...items.map(d => d.value));
    const minVal = Math.min(...items.map(d => d.value));

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
            textStyle: { fontSize: 10 }, formatter: v => formatNumber(v),
            inRange: { color: ['#fef3ee', '#c85a2a'] },
        },
        series: [{
            type: 'scatter',
            data: items.map((d, i) => ({
                name: d.name,
                value: [i, d.value],
                symbolSize: 10 + 40 * Math.sqrt((d.value - minVal) / ((maxVal - minVal) || 1)),
            })).reverse(),
            encode: { x: 0, y: 1 },
        }],
        animationDuration: 300,
    });
    return chart;
}
