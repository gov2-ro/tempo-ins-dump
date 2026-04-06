/**
 * Chart factory — dispatches to chart builders based on chart type + slot assignments.
 * Returns a chart instance (or Promise<instance> for async charts like choropleth).
 */
function renderChart(container, chartType, slots, data, metadata) {
    // Dispose previous ECharts instance on this element (if any)
    const existing = echarts.getInstanceByDom(container);
    if (existing) existing.dispose();

    switch (chartType) {
        case 'line':
        case 'area_stacked':
        case 'bar_vertical':
            return createLineChart(container, slots, data, metadata, chartType);

        case 'grouped_bar':
        case 'stacked_bar':
        case 'horizontal_bar':
            return createBarChart(container, slots, data, metadata, chartType);

        case 'choropleth':
            // Async — returns Promise<chart>
            return createGeoChart(container, slots, data, metadata);

        case 'population_pyramid':
            return createPyramidChart(container, slots, data, metadata);

        case 'heatmap':
            return createHeatmapChart(container, slots, data, metadata);

        case 'bubble':
            return createBubbleChart(container, slots, data, metadata);

        case 'small_multiples':
            return createSmallMultiplesChart(container, slots, data, metadata);

        case 'table':
            return createTableChart(container, slots, data, metadata);

        default:
            return createLineChart(container, slots, data, metadata, 'line');
    }
}
