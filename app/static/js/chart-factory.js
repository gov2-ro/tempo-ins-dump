/**
 * Chart factory — dispatches to correct chart builder based on chart type.
 * Resolves dimension roles from ranked_charts[].roles if available.
 */

function resolveRoles(chartConfig) {
    const type = chartConfig.primary_chart;
    const ranked = chartConfig.ranked_charts || [];
    const entry = ranked.find(r => r.chart_type === type);
    // Merge scored roles with legacy compat fields
    const roles = entry ? entry.roles : {};
    return {
        time_dim:   roles.timeline || chartConfig.time_dim || roles.x_axis || null,
        geo_dim:    chartConfig.geo_dim || null,
        series_dim: roles.series || chartConfig.series_dim || null,
        facet_dim:  roles.facet || null,
        x_axis_dim: roles.x_axis || chartConfig.x_axis_dim || null,
        // legacy compat
        age_dim:    chartConfig.age_dim || null,
        gender_dim: chartConfig.gender_dim || null,
        // scatter/correlation
        pivot_dim:  roles.pivot || chartConfig.pivot_dim || null,
        entity_dim: roles.entity || chartConfig.entity_dim || null,
    };
}

async function createChart(container, chartConfig, data, metadata) {
    const chartType = chartConfig.primary_chart;
    const roles = resolveRoles(chartConfig);
    const cfg = { ...chartConfig, ...roles };

    switch (chartType) {
        case 'line':
            // If x_axis is a category (not time), render as demographic line
            if (cfg.x_axis_dim && cfg.x_axis_dim !== cfg.time_dim) {
                cfg._lineMode = true;
                return createDemographicChart(container, cfg, data, metadata);
            }
            return createTimeSeriesChart(container, cfg, data, metadata);
        case 'area':
        case 'area_stacked':
            return createTimeSeriesChart(container, cfg, data, metadata);
        case 'bar':
        case 'bar_vertical':
            return createTimeSeriesChart(container, cfg, data, metadata, 'bar');
        case 'horizontal_bar':
            return createHorizontalBarChart(container, cfg, data, metadata);
        case 'stacked_bar':
            // If x_axis is a category (not time), use demographic chart with stacking
            if (cfg.x_axis_dim && cfg.x_axis_dim !== cfg.time_dim) {
                cfg._stacked = true;
                return createDemographicChart(container, cfg, data, metadata);
            }
            return createStackedBarChart(container, cfg, data, metadata);
        case 'choropleth': {
            // Detect geo level to ensure correct GeoJSON is loaded
            const geoDimMeta = metadata.dimensions?.find(d => d.dim_column_name === cfg.geo_dim);
            let geoLevel = 'county';
            if (geoDimMeta) {
                const lvlCounts = {};
                for (const opt of (geoDimMeta.options || [])) {
                    const lvl = opt.parsed?.geo_level;
                    if (lvl) lvlCounts[lvl] = (lvlCounts[lvl] || 0) + 1;
                }
                if (lvlCounts['macroregion'] > 0 && !lvlCounts['county']) geoLevel = 'macroregion';
                else if (lvlCounts['region'] > 0 && !lvlCounts['county']) geoLevel = 'region';
            }
            if (typeof loadRomaniaGeoJSON === 'function') {
                const loaded = await loadRomaniaGeoJSON(geoLevel);
                if (loaded) return createChoroplethChart(container, cfg, data, metadata);
            }
            return createTimeSeriesChart(container, cfg, data, metadata);
        }
        case 'grouped_bar':
            return createDemographicChart(container, cfg, data, metadata);
        case 'population_pyramid':
            return createPopulationPyramidChart(container, cfg, data, metadata);
        case 'heatmap':
            return createHeatmapChart(container, cfg, data, metadata);
        case 'bubble':
            return createBubbleChart(container, cfg, data, metadata);
        case 'scatter':
            return createScatterChart(container, cfg, data, metadata);
        case 'small_multiples':
            return createSmallMultiplesChart(container, cfg, data, metadata);
        case 'ranking':
            return createRankingChart(container, cfg, data, metadata);
        default:
            return createTimeSeriesChart(container, cfg, data, metadata);
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

    let timeIdx = timeDim ? cols.indexOf(timeDim) : -1;
    const seriesIdx = seriesDim ? cols.indexOf(seriesDim) : -1;

    // Fallback: try x_axis_dim if time_dim not found in columns
    if (timeIdx === -1 && config.x_axis_dim) {
        timeIdx = cols.indexOf(config.x_axis_dim);
    }
    // Last resort: use first dimension column as x-axis
    if (timeIdx === -1 && cols.length > 1) {
        timeIdx = 0;
        console.warn('Time dim not found in data, using first column as x-axis:', cols[0]);
    }

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

    // Default zoom to last ~5 years for dense raw monthly data (not yearly-aggregated)
    const _isDenseRaw = !config._yearlyAgg && config._timeGranularity === 'monthly' && xData.length > 60;
    const _zoomStart = _isDenseRaw ? Math.max(0, Math.round((1 - 60 / xData.length) * 100)) : 0;

    let series = [];
    const chartType = config.primary_chart;
    const isArea = chartType === 'area' || chartType === 'area_stacked';
    const isStacked = chartType === 'area_stacked';

    if (seriesIdx !== -1) {
        // Multiple series
        const groups = groupBy(rows, seriesIdx);
        const seriesLabelsMap = labels[seriesDim] || {};

        // Cap high-cardinality series — keep top N by sum
        let entries = Object.entries(groups);
        const MAX_SERIES = config.max_series || 12;
        if (entries.length > MAX_SERIES) {
            entries.sort((a, b) => {
                const sumA = a[1].reduce((s, r) => s + (r[valueIdx] || 0), 0);
                const sumB = b[1].reduce((s, r) => s + (r[valueIdx] || 0), 0);
                return sumB - sumA;
            });
            entries = entries.slice(0, MAX_SERIES);
        }

        for (const [seriesId, groupRows] of entries) {
            const seriesLabel = seriesLabelsMap[String(seriesId)] || String(seriesId);
            const dataMap = {};
            for (const row of groupRows) {
                const tid = row[timeIdx];
                const val = row[valueIdx];
                if (val === null || val === undefined) continue;
                dataMap[tid] = (dataMap[tid] || 0) + val;
            }

            series.push({
                name: seriesLabel,
                type: forceType || 'line',
                smooth: true,
                data: timeIds.map(tid => dataMap[tid] ?? null),
                connectNulls: true,
                ...(isArea && { areaStyle: { opacity: 0.35 } }),
                ...(isStacked && { stack: 'total' }),
            });
        }
    } else {
        // Single series
        const dataMap = {};
        for (const row of rows) {
            const tid = row[timeIdx];
            const val = row[valueIdx];
            if (val === null || val === undefined) continue;
            dataMap[tid] = (dataMap[tid] || 0) + val;
        }
        series.push({
            name: metadata.matrix_name || 'Value',
            type: forceType || 'line',
            smooth: true,
            data: timeIds.map(tid => dataMap[tid] ?? null),
            ...(isArea && { areaStyle: { opacity: 0.35 } }),
        });
    }

    const showTotal = series.length > 1;

    const vfmt = config._valueFormat;
    const fmtVal = v => {
        if (v == null) return '—';
        if (vfmt === 'index') return v.toFixed(1);
        if (vfmt === 'pct_change') return (v > 0 ? '+' : '') + v.toFixed(2) + '%';
        return formatNumber(v);
    };
    const yAxisLabel = vfmt === 'index' ? v => v.toFixed(0)
                     : vfmt === 'pct_change' ? v => v.toFixed(1) + '%'
                     : v => formatNumber(v);

    const option = {
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross' },
            formatter: function (params) {
                let rows = '';
                let total = 0;
                let hasValues = false;
                for (const p of params) {
                    if (p.value !== null && p.value !== undefined) {
                        rows += `${p.marker} ${p.seriesName}: <b>${fmtVal(p.value)}</b><br/>`;
                        total += p.value;
                        hasValues = true;
                    }
                }
                let html = `<b>${params[0].axisValue}</b>`;
                if (!vfmt && showTotal && hasValues) {
                    html += `<br/>∑ <b>${formatNumber(total)}</b>`;
                    html += `<hr style="margin:4px 0;border-color:currentColor;opacity:0.15"/>`;
                } else {
                    html += '<br/>';
                }
                return html + rows;
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
                formatter: yAxisLabel,
            },
        },
        dataZoom: [
            { type: 'inside', xAxisIndex: 0 },
            { type: 'slider', xAxisIndex: 0 },
        ],
        series,
        animationDuration: 300,
    };

    chart.setOption(option);
    // ECharts ignores start/end in the initial setOption — must dispatchAction after render
    if (_isDenseRaw) {
        chart.dispatchAction({ type: 'dataZoom', start: _zoomStart, end: 100 });
    }
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
