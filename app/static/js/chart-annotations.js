/**
 * Annotation layer for dashboard v2 tiles.
 *
 * Applies precomputed dataset_trends signals (breakpoint years, peak/trough)
 * onto a rendered ECharts instance via markLine/markPoint merge. Safe no-op
 * for charts without a category x-axis (maps, pyramids).
 */

function applyAnnotations(chart, annotations) {
    if (!chart || !annotations?.length || typeof chart.getOption !== 'function') return;

    let opt;
    try { opt = chart.getOption(); } catch { return; }
    const xAxis = Array.isArray(opt.xAxis) ? opt.xAxis[0] : null;
    if (!xAxis || xAxis.type !== 'category' || !Array.isArray(xAxis.data)) return;

    const xData = xAxis.data.map(String);
    const findIdx = year => {
        const y = String(year);
        return xData.findIndex(x => x === y || x.endsWith(y));
    };
    const singleSeries = (opt.series || []).length === 1;

    const markLineData = [];
    const markPointData = [];

    for (const a of annotations) {
        if (a.type === 'breakpoint') {
            const i = findIdx(a.year);
            if (i >= 0) {
                markLineData.push({
                    xAxis: xData[i],
                    label: { formatter: String(a.year), position: 'end',
                             rotate: 0, fontSize: 10, color: '#9ca3af' },
                });
            }
        } else if ((a.type === 'peak' || a.type === 'trough') && singleSeries) {
            const i = findIdx(a.year);
            const raw = opt.series[0].data?.[i];
            const v = raw != null && typeof raw === 'object' ? raw.value : raw;
            if (i >= 0 && v != null) {
                markPointData.push({
                    coord: [i, v],
                    value: a.type === 'peak' ? 'max' : 'min',
                    symbol: 'pin',
                    symbolSize: 34,
                    itemStyle: { color: a.type === 'peak' ? '#34d399' : '#f87171', opacity: 0.85 },
                    label: { fontSize: 8.5, color: '#fff' },
                });
            }
        }
    }

    if (!markLineData.length && !markPointData.length) return;

    const patch = {};
    if (markLineData.length) {
        patch.markLine = {
            silent: true,
            symbol: 'none',
            lineStyle: { type: 'dashed', color: '#9ca3af', opacity: 0.7, width: 1 },
            data: markLineData,
        };
    }
    if (markPointData.length) {
        patch.markPoint = { silent: true, data: markPointData };
    }
    // Series-index merge: attaches to the first series, leaves the rest as-is
    chart.setOption({ series: [patch] });
}
