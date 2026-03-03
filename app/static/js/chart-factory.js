/**
 * Chart factory — dispatches to correct chart builder based on archetype
 */

function createChart(container, chartConfig, data, metadata) {
    const chartType = chartConfig.primary_chart;

    switch (chartType) {
        case 'line':
        case 'area':
            return createTimeSeriesChart(container, chartConfig, data, metadata);
        case 'bar':
            return createTimeSeriesChart(container, chartConfig, data, metadata, 'bar');
        case 'choropleth':
            // Fallback to line if no geo data loaded
            if (window._geoDataLoaded) {
                return createChoroplethChart(container, chartConfig, data, metadata);
            }
            return createTimeSeriesChart(container, chartConfig, data, metadata);
        case 'grouped_bar':
            return createDemographicChart(container, chartConfig, data, metadata);
        default:
            return createTimeSeriesChart(container, chartConfig, data, metadata);
    }
}

/**
 * Time series line/area/bar chart (covers time_series + time_residence archetypes)
 */
function createTimeSeriesChart(container, config, data, metadata, forceType = null) {
    const chart = echarts.init(container);

    const cols = data.columns;
    const labels = data.column_labels;
    const rows = data.rows;
    const valueIdx = cols.length - 1;

    // Determine X axis (time) and series dimension
    const timeDim = config.time_dim;
    const seriesDim = config.series_dim;

    const timeIdx = timeDim ? cols.indexOf(timeDim) : -1;
    const seriesIdx = seriesDim ? cols.indexOf(seriesDim) : -1;

    if (timeIdx === -1) {
        // No time dimension — generic bar chart
        return createGenericChart(chart, data, metadata);
    }

    // Get unique time points, sorted by year
    const timeIds = uniqueValues(rows, timeIdx);
    const timeLabelsMap = labels[timeDim] || {};
    const xData = timeIds.map(id => {
        let lbl = timeLabelsMap[String(id)] || String(id);
        // Clean up "Anul 2020" → "2020", "Trimestrul III 2020" stays
        lbl = lbl.replace(/^Anul\s+/, '');
        return lbl;
    });

    let series = [];

    if (seriesIdx !== -1) {
        // Multiple series
        const groups = groupBy(rows, seriesIdx);
        const seriesLabelsMap = labels[seriesDim] || {};

        for (const [seriesId, groupRows] of Object.entries(groups)) {
            const seriesLabel = seriesLabelsMap[String(seriesId)] || String(seriesId);
            const dataMap = {};
            for (const row of groupRows) {
                dataMap[row[timeIdx]] = row[valueIdx];
            }

            series.push({
                name: seriesLabel,
                type: forceType || 'line',
                smooth: true,
                data: timeIds.map(tid => dataMap[tid] ?? null),
                connectNulls: true,
            });
        }
    } else {
        // Single series
        const dataMap = {};
        for (const row of rows) {
            dataMap[row[timeIdx]] = row[valueIdx];
        }
        series.push({
            name: metadata.matrix_name || 'Value',
            type: forceType || 'line',
            smooth: true,
            data: timeIds.map(tid => dataMap[tid] ?? null),
        });
    }

    const option = {
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross' },
            formatter: function (params) {
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
            show: series.length > 1 && series.length <= 20,
            type: 'scroll',
            bottom: 0,
            textStyle: { fontSize: 11 },
        },
        grid: {
            left: 60,
            right: 20,
            top: 20,
            bottom: series.length > 1 ? 60 : 30,
        },
        xAxis: {
            type: 'category',
            data: xData,
            axisLabel: { fontSize: 11, rotate: xData.length > 20 ? 45 : 0 },
        },
        yAxis: {
            type: 'value',
            axisLabel: {
                fontSize: 11,
                formatter: (v) => formatNumber(v),
            },
        },
        series,
        animationDuration: 300,
    };

    chart.setOption(option);
    return chart;
}

/**
 * Generic chart for datasets without clear time/series structure
 */
function createGenericChart(chart, data, metadata) {
    const cols = data.columns;
    const rows = data.rows;
    const valueIdx = cols.length - 1;
    const labels = data.column_labels;

    // Use first dimension as categories
    const catIdx = 0;
    const catLabels = labels[cols[catIdx]] || {};

    const items = rows.map(r => ({
        name: catLabels[String(r[catIdx])] || String(r[catIdx]),
        value: r[valueIdx],
    })).filter(d => d.value !== null);

    items.sort((a, b) => (b.value || 0) - (a.value || 0));
    const top = items.slice(0, 30);

    chart.setOption({
        tooltip: { trigger: 'axis' },
        grid: { left: 140, right: 20, top: 10, bottom: 30 },
        xAxis: { type: 'value', axisLabel: { fontSize: 11, formatter: v => formatNumber(v) } },
        yAxis: {
            type: 'category',
            data: top.map(d => d.name).reverse(),
            axisLabel: { fontSize: 11, width: 120, overflow: 'truncate' },
        },
        series: [{
            type: 'bar',
            data: top.map(d => d.value).reverse(),
            itemStyle: { color: '#1a56db' },
        }],
    });
    return chart;
}
