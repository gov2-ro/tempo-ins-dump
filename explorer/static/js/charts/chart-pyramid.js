/**
 * Population pyramid chart.
 * slots.x_axis = age dim, slots.series = gender dim.
 * Uses latest time point if time dim exists.
 */
function createPyramidChart(container, slots, data, metadata) {
    const chart = echarts.init(container);

    const cols     = data.columns;
    const labels   = data.column_labels;
    const rows     = data.rows;
    const valueIdx = cols.length - 1;

    const ageDim    = slots.x_axis;
    const genderDim = slots.series;
    const ageIdx    = ageDim    ? cols.indexOf(ageDim)    : -1;
    const genderIdx = genderDim ? cols.indexOf(genderDim) : -1;

    if (ageIdx === -1 || genderIdx === -1) {
        // Fall back to bar
        return createBarChart(container, slots, data, metadata, 'grouped_bar');
    }

    const ageLabels    = labels[ageDim]    || {};
    const genderLabels = labels[genderDim] || {};

    // Use latest time point
    const timeDimMeta = metadata.dimensions.find(d => d.dim_type === 'time');
    const timeDim     = timeDimMeta?.dim_column_name;
    const timeIdx     = timeDim ? cols.indexOf(timeDim) : -1;
    const timeLabels  = labels[timeDim] || {};

    const timeIds    = timeIdx !== -1 ? uniqueValues(rows, timeIdx) : [null];
    const latestTime = timeIds[timeIds.length - 1];
    const activeRows = latestTime !== null
        ? rows.filter(r => r[timeIdx] === latestTime)
        : rows;

    // Gender IDs — exclude totals
    const genderIds = uniqueValues(activeRows, genderIdx);
    const nonTotal  = genderIds.filter(id => {
        const lbl = (genderLabels[String(id)] || '').trim().toLowerCase();
        return lbl !== 'total' && lbl !== 'toate' && lbl !== 'ambele sexe';
    });
    const [g1, g2] = nonTotal.length >= 2 ? nonTotal.slice(0, 2) : genderIds.slice(0, 2);

    // Age IDs — exclude totals
    const ageIds = uniqueValues(activeRows, ageIdx).filter(id => {
        const lbl = (ageLabels[String(id)] || '').trim().toLowerCase();
        return lbl !== 'total' && lbl !== 'toate';
    });

    const mapG1 = {}, mapG2 = {};
    for (const row of activeRows) {
        if (row[genderIdx] === g1) mapG1[row[ageIdx]] = row[valueIdx] ?? 0;
        if (row[genderIdx] === g2) mapG2[row[ageIdx]] = row[valueIdx] ?? 0;
    }

    const g1Label = genderLabels[String(g1)] || String(g1);
    const g2Label = genderLabels[String(g2)] || String(g2);
    const ageData = ageIds.map(id => ageLabels[String(id)] || String(id));
    const g1Data  = ageIds.map(id => -(mapG1[id] ?? 0));
    const g2Data  = ageIds.map(id =>  (mapG2[id] ?? 0));

    const maxVal = Math.max(...ageIds.map(id =>
        Math.max(Math.abs(mapG1[id] ?? 0), Math.abs(mapG2[id] ?? 0))
    ));

    let subtitle = '';
    if (latestTime !== null) {
        subtitle = (timeLabels[String(latestTime)] || String(latestTime)).replace(/^Anul\s+/, '');
    }

    chart.setOption({
        title: subtitle ? {
            text: subtitle,
            textStyle: { fontSize: 13, fontWeight: 'normal', color: '#666' },
            left: 'center', top: 4,
        } : undefined,
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
            axisLabel: { fontSize: 11, formatter: v => formatNumber(Math.abs(v)) },
        },
        yAxis: {
            type: 'category',
            data: ageData,
            axisLabel: { fontSize: 11 },
        },
        series: [
            {
                name: g1Label, type: 'bar', stack: 'pyramid',
                data: g1Data,
                itemStyle: { color: '#3b82f6' },
                label: { show: false },
            },
            {
                name: g2Label, type: 'bar', stack: 'pyramid',
                data: g2Data,
                itemStyle: { color: '#e74694' },
                label: { show: false },
            },
        ],
        animationDuration: 300,
    });
    return chart;
}
