/**
 * Bar chart renderers: grouped_bar, stacked_bar, horizontal_bar.
 * All read slots.x_axis and slots.series from the slot assignments.
 */
function createBarChart(container, slots, data, metadata, chartType) {
    const chart = echarts.init(container);

    const cols     = data.columns;
    const labels   = data.column_labels;
    const rows     = data.rows;
    const valueIdx = cols.length - 1;

    const xDim      = slots.x_axis;
    const seriesDim = slots.series;
    const xIdx      = xDim      ? cols.indexOf(xDim)      : -1;
    const seriesIdx = seriesDim ? cols.indexOf(seriesDim) : -1;

    // ---- Horizontal bar (ranking) ----
    if (chartType === 'horizontal_bar') {
        const catDim    = xDim || cols[0];
        const catIdx    = cols.indexOf(catDim);
        const catLabels = labels[catDim] || {};

        const totals = {};
        for (const row of rows) {
            const key = row[catIdx];
            totals[key] = (totals[key] || 0) + (row[valueIdx] || 0);
        }

        const items = Object.entries(totals)
            .map(([id, val]) => ({ name: catLabels[String(id)] || String(id), value: val }))
            .filter(d => {
                const lbl = d.name.trim().toLowerCase();
                return lbl !== 'total' && lbl !== 'toate';
            })
            .sort((a, b) => b.value - a.value)
            .slice(0, 40)
            .reverse();  // largest at top

        chart.setOption({
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
                itemStyle: { color: '#c85a2a' },
                label: {
                    show: items.length <= 20,
                    position: 'right',
                    fontSize: 10,
                    formatter: p => formatNumber(p.value),
                },
            }],
            animationDuration: 300,
        });
        return chart;
    }

    // ---- Grouped / Stacked bar ----
    const isStacked = chartType === 'stacked_bar';

    if (xIdx === -1) {
        // Fallback: horizontal bar on first dim
        chart.dispose();
        return createBarChart(container, { ...slots, x_axis: cols[0] }, data, metadata, 'horizontal_bar');
    }

    const xLabels      = labels[xDim] || {};
    const seriesLabels = labels[seriesDim] || {};

    const xIds = uniqueValues(rows, xIdx);
    const xData = xIds.map(id => {
        let lbl = xLabels[String(id)] || String(id);
        return lbl.replace(/^Anul\s+/, '');
    });

    const COLORS = ['#c85a2a','#3b82f6','#8b5cf6','#10b981','#f59e0b','#ef4444','#64748b','#e74694'];

    let seriesList;
    if (seriesIdx !== -1) {
        const allSeriesIds = uniqueValues(rows, seriesIdx);
        const seriesIds = allSeriesIds.filter(id => {
            const lbl = (seriesLabels[String(id)] || '').trim().toLowerCase();
            return lbl !== 'total' && lbl !== 'toate' && lbl !== 'ambele sexe';
        });

        seriesList = seriesIds.map((sid, i) => {
            const sLabel = seriesLabels[String(sid)] || String(sid);
            const dataMap = {};
            for (const row of rows) {
                if (row[seriesIdx] === sid) dataMap[row[xIdx]] = row[valueIdx];
            }
            return {
                name: sLabel,
                type: 'bar',
                ...(isStacked ? { stack: 'total' } : {}),
                data: xIds.map(xid => dataMap[xid] ?? null),
                itemStyle: { color: COLORS[i % COLORS.length] },
            };
        });
    } else {
        const dataMap = {};
        for (const row of rows) dataMap[row[xIdx]] = row[valueIdx];
        seriesList = [{
            name: metadata.matrix_name || 'Value',
            type: 'bar',
            data: xIds.map(xid => dataMap[xid] ?? null),
            itemStyle: { color: COLORS[0] },
        }];
    }

    chart.setOption({
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
        legend: {
            show: seriesList.length > 1 && seriesList.length <= 20,
            type: 'scroll', bottom: 0, textStyle: { fontSize: 11 },
        },
        grid: { left: 65, right: 20, top: 20, bottom: seriesList.length > 1 ? 50 : 30 },
        xAxis: {
            type: 'category',
            data: xData,
            axisLabel: { fontSize: 11, rotate: xData.length > 15 ? 45 : 0 },
        },
        yAxis: {
            type: 'value',
            axisLabel: { fontSize: 11, formatter: v => formatNumber(v) },
        },
        series: seriesList,
        animationDuration: 300,
    });
    return chart;
}
