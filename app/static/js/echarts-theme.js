/**
 * Shared ECharts lens themes (dark/light) + init patch.
 *
 * Loaded by index.html AND dataset-v2.html before any chart module, so both
 * surfaces render identically themed charts. The monkey-patched echarts.init
 * picks the theme from body.dataset.theme at chart-creation time — pages
 * must mirror their theme onto <body> and recreate charts on toggle.
 */
(function registerThemes() {
    const COLORS = ['#818cf8','#f472b6','#34d399','#fbbf24','#60a5fa','#a78bfa','#fb923c','#94a3b8',
                    '#e879f9','#22d3ee','#f87171','#84cc16'];

    const sharedStyle = {
        color: COLORS,
        line: { smooth: true, symbolSize: 4, lineStyle: { width: 2.5 } },
        bar: { barMaxWidth: 40, itemStyle: { borderRadius: [3, 3, 0, 0] } },
        scatter: { symbolSize: 10 },
    };

    echarts.registerTheme('lens-dark', {
        ...sharedStyle,
        backgroundColor: 'transparent',
        textStyle: { color: '#a1a1aa', fontFamily: "'Inter', system-ui, sans-serif" },
        title: { textStyle: { color: '#fafafa', fontWeight: 600 }, subtextStyle: { color: '#71717a' } },
        legend: { textStyle: { color: '#a1a1aa' }, pageTextStyle: { color: '#a1a1aa' } },
        tooltip: {
            backgroundColor: 'rgba(24,24,28,0.95)',
            borderColor: 'rgba(255,255,255,0.08)',
            textStyle: { color: '#fafafa', fontSize: 12 },
            extraCssText: 'border-radius:8px; backdrop-filter:blur(8px); box-shadow:0 4px 20px rgba(0,0,0,0.5);',
        },
        categoryAxis: {
            axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
            axisTick: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
            axisLabel: { color: '#71717a', fontSize: 11 },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
        },
        valueAxis: {
            axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
            axisTick: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
            axisLabel: { color: '#71717a', fontSize: 11 },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
        },
        visualMap: { textStyle: { color: '#71717a' } },
        timeline: {
            lineStyle: { color: 'rgba(255,255,255,0.15)' },
            itemStyle: { color: '#818cf8' },
            label: { color: '#71717a' },
            controlStyle: { color: '#a1a1aa', borderColor: '#a1a1aa' },
        },
    });

    echarts.registerTheme('lens-light', {
        ...sharedStyle,
        backgroundColor: 'transparent',
        textStyle: { color: '#4a4a55', fontFamily: "'Inter', system-ui, sans-serif" },
        title: { textStyle: { color: '#111118', fontWeight: 600 }, subtextStyle: { color: '#8a8a99' } },
        legend: { textStyle: { color: '#4a4a55' }, pageTextStyle: { color: '#4a4a55' } },
        tooltip: {
            backgroundColor: 'rgba(255,255,255,0.96)',
            borderColor: 'rgba(0,0,0,0.08)',
            textStyle: { color: '#111118', fontSize: 12 },
            extraCssText: 'border-radius:8px; backdrop-filter:blur(8px); box-shadow:0 4px 20px rgba(0,0,0,0.12);',
        },
        categoryAxis: {
            axisLine: { lineStyle: { color: 'rgba(0,0,0,0.1)' } },
            axisTick: { lineStyle: { color: 'rgba(0,0,0,0.06)' } },
            axisLabel: { color: '#8a8a99', fontSize: 11 },
            splitLine: { lineStyle: { color: 'rgba(0,0,0,0.05)' } },
        },
        valueAxis: {
            axisLine: { lineStyle: { color: 'rgba(0,0,0,0.1)' } },
            axisTick: { lineStyle: { color: 'rgba(0,0,0,0.06)' } },
            axisLabel: { color: '#8a8a99', fontSize: 11 },
            splitLine: { lineStyle: { color: 'rgba(0,0,0,0.05)' } },
        },
        visualMap: { textStyle: { color: '#8a8a99' } },
        timeline: {
            lineStyle: { color: 'rgba(0,0,0,0.15)' },
            itemStyle: { color: '#6366f1' },
            label: { color: '#8a8a99' },
            controlStyle: { color: '#4a4a55', borderColor: '#4a4a55' },
        },
    });

    // Monkey-patch echarts.init to use the current theme
    const _origInit = echarts.init.bind(echarts);
    echarts.init = (dom, _theme, opts) => {
        const themeName = document.body.dataset.theme === 'light' ? 'lens-light' : 'lens-dark';
        return _origInit(dom, themeName, opts);
    };
})();
