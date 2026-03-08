/**
 * Line / area / bar chart renderer.
 * Reads from slot assignments to determine X axis and series dimension.
 */
function createLineChart(container, slots, data, metadata, chartType = 'line') {
    const chart = echarts.init(container);

    const cols = data.columns;
    const labels = data.column_labels;
    const rows = data.rows;
    const valueIdx = cols.length - 1;

    const xDim = slots.x_axis;
    const seriesDim = slots.series;
    const xIdx = xDim ? cols.indexOf(xDim) : -1;
    const seriesIdx = seriesDim ? cols.indexOf(seriesDim) : -1;

    if (xIdx === -1) {
        // Fallback: generic horizontal bar with first dim
        return createFallbackBar(chart, data);
    }

    // Unique X values, sorted
    const xIds = uniqueValues(rows, xIdx);
    const xLabelsMap = labels[xDim] || {};
    const xData = xIds.map(id => {
        let lbl = xLabelsMap[String(id)] || String(id);
        lbl = lbl.replace(/^Anul\s+/, '');
        return lbl;
    });

    let seriesList = [];
    const isArea = chartType === 'area_stacked';
    const isBar = chartType === 'bar_vertical' || chartType === 'bar';
    const renderType = isBar ? 'bar' : 'line';

    if (seriesIdx !== -1) {
        const groups = groupBy(rows, seriesIdx);
        const seriesLabelsMap = labels[seriesDim] || {};

        for (const [seriesId, groupRows] of Object.entries(groups)) {
            const seriesLabel = seriesLabelsMap[String(seriesId)] || String(seriesId);
            const dataMap = {};
            for (const row of groupRows) {
                dataMap[row[xIdx]] = row[valueIdx];
            }
            seriesList.push({
                name: seriesLabel,
                type: renderType,
                smooth: !isBar,
                data: xIds.map(tid => dataMap[tid] ?? null),
                connectNulls: true,
                ...(isArea ? { areaStyle: {}, stack: 'total' } : {}),
            });
        }
    } else {
        const dataMap = {};
        for (const row of rows) {
            dataMap[row[xIdx]] = row[valueIdx];
        }
        seriesList.push({
            name: metadata.matrix_name || 'Value',
            type: renderType,
            smooth: !isBar,
            data: xIds.map(tid => dataMap[tid] ?? null),
            ...(isArea ? { areaStyle: {}, stack: 'total' } : {}),
        });
    }

    const option = {
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: isBar ? 'shadow' : 'cross' },
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
        legend: {
            show: seriesList.length > 1 && seriesList.length <= 20,
            type: 'scroll',
            bottom: 0,
            textStyle: { fontSize: 11 },
        },
        grid: {
            left: 65,
            right: 20,
            top: 20,
            bottom: seriesList.length > 1 ? 60 : 30,
        },
        xAxis: {
            type: 'category',
            data: xData,
            axisLabel: { fontSize: 11, rotate: xData.length > 20 ? 45 : 0 },
        },
        yAxis: {
            type: 'value',
            axisLabel: { fontSize: 11, formatter: v => formatNumber(v) },
        },
        series: seriesList,
        animationDuration: 300,
    };

    chart.setOption(option);
    return chart;
}


function createFallbackBar(chart, data) {
    const cols = data.columns;
    const rows = data.rows;
    const valueIdx = cols.length - 1;
    const labels = data.column_labels;
    const catIdx = 0;
    const catLabels = labels[cols[catIdx]] || {};

    const items = rows
        .map(r => ({
            name: catLabels[String(r[catIdx])] || String(r[catIdx]),
            value: r[valueIdx],
        }))
        .filter(d => d.value !== null)
        .sort((a, b) => (b.value || 0) - (a.value || 0))
        .slice(0, 30);

    chart.setOption({
        tooltip: { trigger: 'axis' },
        grid: { left: 140, right: 20, top: 10, bottom: 30 },
        xAxis: { type: 'value', axisLabel: { fontSize: 11, formatter: v => formatNumber(v) } },
        yAxis: {
            type: 'category',
            data: items.map(d => d.name).reverse(),
            axisLabel: { fontSize: 11, width: 120, overflow: 'truncate' },
        },
        series: [{
            type: 'bar',
            data: items.map(d => d.value).reverse(),
            itemStyle: { color: '#c85a2a' },
        }],
    });
    return chart;
}
