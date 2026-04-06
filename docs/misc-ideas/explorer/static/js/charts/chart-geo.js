/**
 * Choropleth map chart — Romania counties.
 * Ported from app/static/js/chart-geo.js, adapted to slot API.
 */

let _geoJsonData = null;
let _geoRegistered = false;

async function loadRomaniaGeoJSON() {
    if (_geoRegistered) return true;
    try {
        if (!_geoJsonData) {
            const resp = await fetch('/geo/romania-counties.geojson');
            if (!resp.ok) throw new Error(`GeoJSON fetch failed: ${resp.status}`);
            _geoJsonData = await resp.json();
        }
        echarts.registerMap('Romania', _geoJsonData);
        _geoRegistered = true;
        return true;
    } catch (err) {
        console.error('Failed to load Romania GeoJSON:', err);
        return false;
    }
}

/**
 * Create choropleth. slots.x_axis = geo dim, time dim auto-detected from metadata.
 * Returns a Promise that resolves to the chart instance.
 */
async function createGeoChart(container, slots, data, metadata) {
    const ok = await loadRomaniaGeoJSON();
    if (!ok) {
        // Fall back to horizontal bar if no GeoJSON
        return createBarChart(container, slots, data, metadata, 'horizontal_bar');
    }

    const chart = echarts.init(container);

    const cols     = data.columns;
    const labels   = data.column_labels;
    const rows     = data.rows;
    const valueIdx = cols.length - 1;

    // geo dim: prefer slots.x_axis, else find from metadata
    const geoDimMeta = metadata.dimensions.find(d =>
        d.dim_type === 'geo' || d.dim_column_name === slots.x_axis
    );
    const geoDim = geoDimMeta?.dim_column_name || slots.x_axis;
    const geoIdx = geoDim ? cols.indexOf(geoDim) : -1;

    // time dim: find from metadata
    const timeDimMeta = metadata.dimensions.find(d => d.dim_type === 'time');
    const timeDim = timeDimMeta?.dim_column_name;
    const timeIdx = timeDim ? cols.indexOf(timeDim) : -1;

    if (geoIdx === -1) {
        // No geo column in data — fall back
        chart.dispose();
        return createBarChart(container, slots, data, metadata, 'horizontal_bar');
    }

    const geoLabels  = labels[geoDim] || {};
    const timeLabels = labels[timeDim] || {};

    // Build nom_item_id → { geo_name_clean, geo_level } from metadata options
    const geoNameMap = {};
    if (geoDimMeta) {
        for (const opt of (geoDimMeta.options || [])) {
            if (opt.parsed?.geo_name_clean) {
                geoNameMap[opt.nom_item_id] = {
                    geo_level: opt.parsed.geo_level || 'unknown',
                    geo_name_clean: opt.parsed.geo_name_clean,
                };
            }
        }
    }

    // County-level IDs only
    const countyIds = new Set(
        Object.entries(geoNameMap)
            .filter(([, info]) => info.geo_level === 'county')
            .map(([id]) => Number(id))
    );

    const timeIds = timeIdx !== -1 ? uniqueValues(rows, timeIdx) : [null];
    const timeLabelsClean = timeIds.map(id =>
        id === null ? '' : (timeLabels[String(id)] || String(id)).replace(/^Anul\s+/, '')
    );

    // Build frames: { timeId: [{name, value}] }
    const framesMaps = {};
    for (const row of rows) {
        const geoId = row[geoIdx];
        if (countyIds.size > 0 && !countyIds.has(geoId)) continue;
        const timeId = timeIdx !== -1 ? row[timeIdx] : null;
        const value  = row[valueIdx];
        if (value === null || value === undefined) continue;

        if (!framesMaps[timeId]) framesMaps[timeId] = {};
        const info = geoNameMap[geoId];
        const name = info ? info.geo_name_clean : (geoLabels[String(geoId)] || String(geoId));
        framesMaps[timeId][name] = value;
    }

    const frames = {};
    for (const [timeId, map] of Object.entries(framesMaps)) {
        frames[timeId] = Object.entries(map).map(([name, value]) => ({ name, value }));
    }

    if (Object.keys(frames).length === 0) {
        chart.dispose();
        return createBarChart(container, slots, data, metadata, 'horizontal_bar');
    }

    let globalMin = Infinity, globalMax = -Infinity;
    for (const frame of Object.values(frames)) {
        for (const d of frame) {
            if (d.value < globalMin) globalMin = d.value;
            if (d.value > globalMax) globalMax = d.value;
        }
    }

    const defaultTimeIdx = timeIds.length - 1;
    const defaultData    = frames[timeIds[defaultTimeIdx]] || [];

    const baseMap = {
        tooltip: {
            trigger: 'item',
            formatter(params) {
                if (params.value !== undefined && !isNaN(params.value)) {
                    return `<b>${params.name}</b><br/>Valoare: <b>${formatNumber(params.value)}</b>`;
                }
                return `<b>${params.name}</b><br/>Fără date`;
            },
        },
        visualMap: {
            min: globalMin, max: globalMax,
            left: 'left', top: 'center', orient: 'vertical',
            text: ['Ridicat', 'Scăzut'],
            realtime: false, calculable: true,
            inRange: { color: ['#e0f2fe', '#38bdf8', '#0369a1', '#1e3a5f'] },
            textStyle: { fontSize: 11 },
            itemWidth: 12, itemHeight: 100,
        },
        series: [{
            name: metadata.matrix_name || 'Value',
            type: 'map', map: 'Romania', roam: true,
            emphasis: {
                label: { show: true, fontSize: 12 },
                itemStyle: { areaColor: '#f59e0b' },
            },
            label: { show: false },
            data: defaultData,
        }],
        animationDurationUpdate: 300,
    };

    if (timeIds.length > 1) {
        chart.setOption({
            baseOption: {
                ...baseMap,
                timeline: {
                    axisType: 'category',
                    data: timeLabelsClean,
                    autoPlay: false,
                    playInterval: 1000,
                    currentIndex: defaultTimeIdx,
                    bottom: 10, left: 80, right: 80, height: 36,
                    label: { fontSize: 11 },
                    controlStyle: { itemSize: 18 },
                },
                title: {
                    text: timeLabelsClean[defaultTimeIdx] || '',
                    right: 20, top: 10,
                    textStyle: { fontSize: 22, fontWeight: 300, color: '#9ca3af' },
                },
            },
            options: timeIds.map((tid, i) => ({
                title: { text: timeLabelsClean[i] || '' },
                series: [{ data: frames[tid] || [] }],
            })),
        });
    } else {
        chart.setOption(baseMap);
    }

    return chart;
}
