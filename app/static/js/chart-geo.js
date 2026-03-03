/**
 * Choropleth map chart for geo_time datasets
 * Uses ECharts map series with registered Romania GeoJSON
 */

let _geoJsonData = null;
let _geoRegistered = false;

/**
 * Load and register Romania GeoJSON with ECharts.
 * Returns true if successful.
 */
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
        window._geoDataLoaded = true;
        return true;
    } catch (err) {
        console.error('Failed to load Romania GeoJSON:', err);
        return false;
    }
}


/**
 * Create a choropleth map chart.
 * Data shape: rows = [[geo_id, time_id, value], ...] or [[geo_id, ..., time_id, value]]
 * config.geo_dim, config.time_dim specify which columns hold geo and time IDs.
 */
function createChoroplethChart(container, config, data, metadata) {
    const chart = echarts.init(container);

    const cols = data.columns;
    const labels = data.column_labels;
    const rows = data.rows;
    const valueIdx = cols.length - 1;

    const geoDim = config.geo_dim;
    const timeDim = config.time_dim;
    const geoIdx = geoDim ? cols.indexOf(geoDim) : -1;
    const timeIdx = timeDim ? cols.indexOf(timeDim) : -1;

    if (geoIdx === -1) {
        // No geo dim — fall back to line chart
        return createTimeSeriesChart(container, config, data, metadata);
    }

    const geoLabels = labels[geoDim] || {};
    const timeLabels = labels[timeDim] || {};

    // Build geo_name_clean → nom_item_id mapping from metadata dimensions
    const geoNameMap = {}; // geo_name_clean → { nom_item_id, label, geo_level }
    const geoDimMeta = metadata.dimensions.find(d => d.dim_column_name === geoDim);
    if (geoDimMeta) {
        for (const opt of geoDimMeta.options) {
            if (opt.parsed && opt.parsed.geo_name_clean) {
                geoNameMap[opt.nom_item_id] = {
                    label: opt.label,
                    geo_level: opt.parsed.geo_level || 'unknown',
                    geo_name_clean: opt.parsed.geo_name_clean,
                };
            }
        }
    }

    // Filter to county-level geo IDs only (for map)
    const countyIds = new Set();
    for (const [id, info] of Object.entries(geoNameMap)) {
        if (info.geo_level === 'county') {
            countyIds.add(Number(id));
        }
    }

    // Get unique time points
    const timeIds = timeIdx !== -1 ? uniqueValues(rows, timeIdx) : [null];
    const timeLabelsClean = timeIds.map(id => {
        if (id === null) return '';
        let lbl = (timeLabels[String(id)] || String(id));
        return lbl.replace(/^Anul\s+/, '');
    });

    // Build data frames: { timeId: {countyName: value} }
    // Uses last-write-wins per county to deduplicate multiple dimension combos
    const framesMaps = {};
    for (const row of rows) {
        const geoId = row[geoIdx];
        if (!countyIds.has(geoId)) continue;

        const timeId = timeIdx !== -1 ? row[timeIdx] : null;
        const value = row[valueIdx];
        if (value === null || value === undefined) continue;

        if (!framesMaps[timeId]) framesMaps[timeId] = {};
        const info = geoNameMap[geoId];
        const name = info ? info.geo_name_clean : String(geoId);
        framesMaps[timeId][name] = value;
    }
    // Convert to array format
    const frames = {};
    for (const [timeId, map] of Object.entries(framesMaps)) {
        frames[timeId] = Object.entries(map).map(([name, value]) => ({ name, value }));
    }

    // If no county data, fall back to line
    if (Object.keys(frames).length === 0) {
        return createTimeSeriesChart(container, config, data, metadata);
    }

    // Compute global min/max for consistent color scale
    let globalMin = Infinity, globalMax = -Infinity;
    for (const frame of Object.values(frames)) {
        for (const d of frame) {
            if (d.value < globalMin) globalMin = d.value;
            if (d.value > globalMax) globalMax = d.value;
        }
    }

    // Use the latest time point as default
    const defaultTimeIdx = timeIds.length - 1;
    const defaultData = frames[timeIds[defaultTimeIdx]] || [];

    const option = {
        tooltip: {
            trigger: 'item',
            formatter: function (params) {
                if (params.value !== undefined && !isNaN(params.value)) {
                    return `<b>${params.name}</b><br/>Value: <b>${formatNumber(params.value)}</b>`;
                }
                return `<b>${params.name}</b><br/>No data`;
            },
        },
        visualMap: {
            min: globalMin,
            max: globalMax,
            left: 'left',
            top: 'center',
            orient: 'vertical',
            text: ['High', 'Low'],
            realtime: false,
            calculable: true,
            inRange: {
                color: ['#e0f2fe', '#38bdf8', '#0369a1', '#1e3a5f'],
            },
            textStyle: { fontSize: 11 },
            itemWidth: 12,
            itemHeight: 100,
        },
        series: [{
            name: metadata.matrix_name || 'Value',
            type: 'map',
            map: 'Romania',
            roam: true,
            emphasis: {
                label: { show: true, fontSize: 12 },
                itemStyle: { areaColor: '#f59e0b' },
            },
            label: {
                show: false,
            },
            data: defaultData,
        }],
        animationDurationUpdate: 300,
    };

    // Add timeline if multiple time points
    if (timeIds.length > 1) {
        option.title = {
            text: timeLabelsClean[defaultTimeIdx] || '',
            right: 20,
            top: 10,
            textStyle: { fontSize: 22, fontWeight: 300, color: '#9ca3af' },
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

        // Build options for each time point
        option.baseOption = {
            timeline: option.timeline,
            title: option.title,
            tooltip: option.tooltip,
            visualMap: option.visualMap,
            series: option.series,
        };
        option.options = timeIds.map((tid, i) => ({
            title: { text: timeLabelsClean[i] || '' },
            series: [{
                data: frames[tid] || [],
            }],
        }));

        // Remove top-level duplicates since we're using baseOption
        delete option.title;
        delete option.tooltip;
        delete option.visualMap;
        delete option.series;
        delete option.timeline;
    }

    chart.setOption(option);
    return chart;
}
