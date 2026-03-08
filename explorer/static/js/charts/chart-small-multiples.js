/**
 * Small multiples — grid of mini line charts, one per facet value.
 * slots.x_axis = time dim, slots.facet = facet dim.
 */
function createSmallMultiplesChart(container, slots, data, metadata) {
    const chart = echarts.init(container);

    const cols     = data.columns;
    const labels   = data.column_labels;
    const rows     = data.rows;
    const valueIdx = cols.length - 1;

    const timeDim  = slots.x_axis;
    const facetDim = slots.facet || slots.series;
    const timeIdx  = timeDim  ? cols.indexOf(timeDim)  : -1;
    const facetIdx = facetDim ? cols.indexOf(facetDim) : -1;

    if (timeIdx === -1 || facetIdx === -1) {
        chart.dispose();
        return createBarChart(container, slots, data, metadata, 'grouped_bar');
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

    const n    = facetIds.length;
    const nCols = Math.min(4, n);
    const nRows = Math.ceil(n / nCols);

    const gridArr = [], xAxes = [], yAxes = [], seriesArr = [], titles = [];
    const cellW = 100 / nCols;
    const cellH = 100 / nRows;
    const pad   = 2;

    for (let i = 0; i < n; i++) {
        const fid = facetIds[i];
        const c   = i % nCols;
        const r   = Math.floor(i / nCols);

        gridArr.push({
            left:   `${c * cellW + pad}%`,
            top:    `${r * cellH + pad + 6}%`,
            width:  `${cellW - pad * 2}%`,
            height: `${cellH - pad * 2 - 8}%`,
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
            itemStyle: { color: '#c85a2a' },
            areaStyle: { color: 'rgba(200,90,42,0.08)' },
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
