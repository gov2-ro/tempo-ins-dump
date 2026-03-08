/**
 * Heatmap chart.
 * slots.x_axis = first categorical dim, slots.series = second categorical dim.
 * Uses latest time point if present.
 */
function createHeatmapChart(container, slots, data, metadata) {
    const chart = echarts.init(container);

    const cols     = data.columns;
    const labels   = data.column_labels;
    const rows     = data.rows;
    const valueIdx = cols.length - 1;

    // Pick x and y dims from slots, fall back to metadata dims by option_count
    let xDim = slots.x_axis;
    let yDim = slots.series;

    if (!xDim || !yDim) {
        const dims = (metadata.dimensions || [])
            .filter(d => !['time', 'unit'].includes(d.dim_type) && cols.includes(d.dim_column_name))
            .sort((a, b) => b.option_count - a.option_count);
        xDim = xDim || (dims[0]?.dim_column_name);
        yDim = yDim || (dims[1]?.dim_column_name || dims[0]?.dim_column_name);
    }

    const xIdx = xDim ? cols.indexOf(xDim) : -1;
    const yIdx = yDim ? cols.indexOf(yDim) : -1;

    if (xIdx === -1 || yIdx === -1 || xIdx === yIdx) {
        chart.dispose();
        return createBarChart(container, slots, data, metadata, 'horizontal_bar');
    }

    const xLabels = labels[xDim] || {};
    const yLabels = labels[yDim] || {};

    // Latest time point
    const timeDimMeta = metadata.dimensions.find(d => d.dim_type === 'time');
    const timeDim     = timeDimMeta?.dim_column_name;
    const timeIdx     = timeDim ? cols.indexOf(timeDim) : -1;
    const timeIds     = timeIdx !== -1 ? uniqueValues(rows, timeIdx) : [null];
    const latestTime  = timeIds[timeIds.length - 1];
    const activeRows  = latestTime !== null ? rows.filter(r => r[timeIdx] === latestTime) : rows;

    const xIds = uniqueValues(activeRows, xIdx).filter(id => {
        const lbl = (xLabels[String(id)] || '').trim().toLowerCase();
        return lbl !== 'total' && lbl !== 'toate';
    }).slice(0, 30);

    const yIds = uniqueValues(activeRows, yIdx).filter(id => {
        const lbl = (yLabels[String(id)] || '').trim().toLowerCase();
        return lbl !== 'total' && lbl !== 'toate';
    }).slice(0, 30);

    const xSet = new Set(xIds), ySet = new Set(yIds);
    const cellMap = {};
    for (const row of activeRows) {
        const x = row[xIdx], y = row[yIdx];
        if (xSet.has(x) && ySet.has(y)) cellMap[`${x}__${y}`] = row[valueIdx];
    }

    const heatData = [];
    let minVal = Infinity, maxVal = -Infinity;
    for (let xi = 0; xi < xIds.length; xi++) {
        for (let yi = 0; yi < yIds.length; yi++) {
            const v = cellMap[`${xIds[xi]}__${yIds[yi]}`] ?? null;
            if (v !== null) {
                heatData.push([xi, yi, v]);
                if (v < minVal) minVal = v;
                if (v > maxVal) maxVal = v;
            }
        }
    }

    const truncate = s => s.length > 20 ? s.slice(0, 18) + '…' : s;
    const xData = xIds.map(id => truncate(xLabels[String(id)] || String(id)));
    const yData = yIds.map(id => truncate(yLabels[String(id)] || String(id)));

    chart.setOption({
        tooltip: {
            position: 'top',
            formatter(p) {
                return `${xData[p.data[0]]}<br/>${yData[p.data[1]]}<br/><b>${formatNumber(p.data[2])}</b>`;
            },
        },
        grid: { left: 120, right: 80, top: 20, bottom: 80 },
        xAxis: {
            type: 'category', data: xData,
            axisLabel: { fontSize: 10, rotate: 45, interval: 0 },
            splitArea: { show: true },
        },
        yAxis: {
            type: 'category', data: yData,
            axisLabel: { fontSize: 10, width: 110, overflow: 'truncate' },
            splitArea: { show: true },
        },
        visualMap: {
            min: minVal, max: maxVal,
            calculable: true, orient: 'vertical', right: 0, top: 'center',
            textStyle: { fontSize: 10 },
            formatter: v => formatNumber(v),
            inRange: { color: ['#fef3ee', '#c85a2a'] },
        },
        series: [{
            type: 'heatmap',
            data: heatData,
            label: { show: xIds.length <= 15 && yIds.length <= 15, fontSize: 9 },
            emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' } },
        }],
        animationDuration: 300,
    });
    return chart;
}
