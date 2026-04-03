/**
 * Demographic chart — grouped bar by age/category, grouped by gender or other series.
 * Used for 'demographic' archetype datasets.
 */

function createDemographicChart(container, config, data, metadata) {
    const chart = echarts.init(container);

    const cols = data.columns;
    const labels = data.column_labels;
    const rows = data.rows;
    const valueIdx = cols.length - 1;

    const timeDim = config.time_dim;
    // Use explicit x_axis_dim/series_dim from roles (variant charts) over profile defaults
    const ageDim = config.x_axis_dim || config.age_dim;
    const genderDim = config.gender_dim;

    const timeIdx = timeDim ? cols.indexOf(timeDim) : -1;
    const ageIdx = ageDim ? cols.indexOf(ageDim) : -1;
    // Prefer explicit series_dim (from variant chart roles) over gender_dim
    const seriesDim = config.series_dim || genderDim;
    const seriesIdx = seriesDim ? cols.indexOf(seriesDim) : -1;

    // Fall back to time series if no age/category dimension
    if (ageIdx === -1) {
        return createTimeSeriesChart(container, config, data, metadata);
    }

    const timeLabels = labels[timeDim] || {};
    const ageLabels = labels[ageDim] || {};
    const seriesLabels = labels[seriesDim] || {};

    // Get sorted unique time IDs
    const timeIds = timeIdx !== -1 ? uniqueValues(rows, timeIdx) : [null];
    const timeLabelsClean = timeIds.map(id => {
        if (id === null) return '';
        let lbl = timeLabels[String(id)] || String(id);
        return lbl.replace(/^Anul\s+/, '').replace(/^Trim\w*\s+([IVX]+)\s+/, 'Q$1 ');
    });

    // Get age groups — detect v3 (string labels) vs v2 (integer nomItemIds)
    const ageDimMeta = metadata.dimensions.find(d => d.dim_column_name === ageDim);
    const sampleVal = rows.find(r => r[ageIdx] !== null)?.[ageIdx];
    const isStringData = typeof sampleVal === 'string' && isNaN(Number(sampleVal));

    let ageOrder;
    if (ageDimMeta && isStringData) {
        // v3: metadata has nomItemIds but data has string labels
        // Use metadata ordering, match by label
        const dataVals = new Set(rows.map(r => r[ageIdx]).filter(v => v !== null));
        ageOrder = ageDimMeta.options
            .map(o => o.label || o.option_label)
            .filter(lbl => lbl && dataVals.has(lbl));
        // Add any data values not in metadata
        for (const v of dataVals) {
            if (!ageOrder.includes(v)) ageOrder.push(v);
        }
    } else if (ageDimMeta) {
        // v2: nomItemIds match data values
        ageOrder = ageDimMeta.options.map(o => o.nom_item_id);
    } else {
        ageOrder = uniqueValues(rows, ageIdx);
    }
    const ageCats = ageOrder.map(id => ageLabels[String(id)] || String(id));

    // Get series IDs (genders, etc.)
    const seriesIds = seriesIdx !== -1 ? uniqueValues(rows, seriesIdx) : [null];

    // Build frames: { timeId → { seriesId → { ageId → value } } }
    const frames = {};
    for (const row of rows) {
        const timeId = timeIdx !== -1 ? row[timeIdx] : null;
        const ageId = row[ageIdx];
        const seriesId = seriesIdx !== -1 ? row[seriesIdx] : null;
        const value = row[valueIdx];
        if (value === null || value === undefined) continue;

        if (!frames[timeId]) frames[timeId] = {};
        if (!frames[timeId][seriesId]) frames[timeId][seriesId] = {};
        frames[timeId][seriesId][ageId] = value;
    }

    if (Object.keys(frames).length === 0) {
        return createTimeSeriesChart(container, config, data, metadata);
    }

    const defaultTimeIdx = timeIds.length - 1;
    const defaultTimeId = timeIds[defaultTimeIdx];

    // Color palette for series
    const colors = ['#1a56db', '#e74c3c', '#27ae60', '#f39c12', '#8e44ad', '#16a085'];

    function buildSeriesForTime(timeId) {
        const frame = frames[timeId] || {};
        return seriesIds.map((sid, i) => {
            const seriesLabel = sid !== null ? (seriesLabels[String(sid)] || String(sid)) : (metadata.matrix_name || 'Value');
            const sData = frame[sid] || {};
            const isLine = config._lineMode;
            return {
                name: seriesLabel,
                type: isLine ? 'line' : 'bar',
                data: ageOrder.map(aid => sData[aid] ?? null),
                itemStyle: { color: colors[i % colors.length] },
                ...(isLine && { smooth: true, symbol: 'circle', symbolSize: 4 }),
                ...(config._stacked && { stack: 'total' }),
            };
        });
    }

    const option = {
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'shadow' },
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
            show: seriesIds.length > 1 && seriesIds.length <= 10,
            top: 0,
            textStyle: { fontSize: 11 },
        },
        grid: {
            left: 60,
            right: 20,
            top: seriesIds.length > 1 ? 36 : 16,
            bottom: timeIds.length > 1 ? 80 : (ageCats.length > 8 ? 80 : 36),
        },
        xAxis: {
            type: 'category',
            data: ageCats,
            axisLabel: {
                fontSize: 11,
                rotate: ageCats.length > 8 ? 35 : 0,
                interval: 0,
                width: 100,
                overflow: 'truncate',
            },
        },
        yAxis: {
            type: 'value',
            axisLabel: { fontSize: 11, formatter: v => formatNumber(v) },
        },
        series: buildSeriesForTime(defaultTimeId),
        animationDurationUpdate: 300,
    };

    // Add timeline if multiple time points
    if (timeIds.length > 1) {
        option.title = {
            text: timeLabelsClean[defaultTimeIdx] || '',
            right: 20,
            top: seriesIds.length > 1 ? 8 : 0,
            textStyle: { fontSize: 20, fontWeight: 300, color: '#9ca3af' },
        };
        option.timeline = {
            axisType: 'category',
            data: timeLabelsClean,
            autoPlay: false,
            playInterval: 1000,
            currentIndex: defaultTimeIdx,
            bottom: 10,
            left: 80,
            right: 80,
            height: 36,
            label: { fontSize: 11 },
            controlStyle: { itemSize: 18 },
        };

        option.baseOption = {
            timeline: option.timeline,
            title: option.title,
            tooltip: option.tooltip,
            legend: option.legend,
            grid: option.grid,
            xAxis: option.xAxis,
            yAxis: option.yAxis,
            series: option.series,
        };
        option.options = timeIds.map((tid, i) => ({
            title: { text: timeLabelsClean[i] || '' },
            series: buildSeriesForTime(tid),
        }));

        delete option.title;
        delete option.tooltip;
        delete option.legend;
        delete option.grid;
        delete option.xAxis;
        delete option.yAxis;
        delete option.series;
        delete option.timeline;
    }

    chart.setOption(option);
    return chart;
}
