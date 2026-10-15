/** Shared reading preferences. Four fixed sizes, persisted across every page. */
(() => {
    const sizes = [16, 17, 18, 20];
    const saved = Number(localStorage.getItem('ins-text-size'));
    document.documentElement.style.fontSize = `${sizes.includes(saved) ? saved : 17}px`;
    const ro = () => (new URLSearchParams(location.search).get('lang') || localStorage.getItem('lens_lang') || 'ro') !== 'en';
    document.addEventListener('DOMContentLoaded', () => {
        const bar = document.querySelector('.topbar');
        if (bar && window.ResizeObserver) new ResizeObserver(() => {
            document.documentElement.style.setProperty('--topbar-h', `${bar.offsetHeight}px`);
        }).observe(bar);
        const nav = document.querySelector('.topbar-right');
        if (!nav) return;
        const host = document.createElement('div');
        host.className = 'reading-control';
        host.innerHTML = `<button type="button" class="toggle-btn reading-toggle" aria-expanded="false" aria-controls="reading-options" aria-label="${ro() ? 'Mărimea textului' : 'Text size'}">Aa</button>
            <div id="reading-options" class="reading-options hidden" role="group" aria-label="${ro() ? 'Mărimea textului' : 'Text size'}">
            ${sizes.map((n, i) => `<button type="button" data-size="${n}" aria-pressed="${n === (sizes.includes(saved) ? saved : 17)}">${['S', 'M', 'L', 'XL'][i]}</button>`).join('')}</div>`;
        let ask = nav.querySelector('a[href="/ask.html"]');
        if (!ask && !location.pathname.endsWith('/ask.html')) {
            ask = document.createElement('a');
            ask.href = '/ask.html';
            ask.className = 'toggle-btn ask-nav-link';
            nav.prepend(ask);
        }
        if (ask) { ask.textContent = '🤖 Ask'; ask.classList.add('ask-nav-link'); ask.setAttribute('aria-label','Ask'); }
        nav.prepend(host);
        new MutationObserver(() => {
            const label = ro() ? 'Mărimea textului' : 'Text size';
            host.querySelector('.reading-toggle').setAttribute('aria-label', label);
            host.querySelector('.reading-options').setAttribute('aria-label', label);
        }).observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
        const toggle = host.querySelector('.reading-toggle');
        const menu = host.querySelector('.reading-options');
        const close = () => { menu.classList.add('hidden'); toggle.setAttribute('aria-expanded', 'false'); };
        toggle.addEventListener('click', () => {
            const open = menu.classList.contains('hidden');
            menu.classList.toggle('hidden', !open);
            toggle.setAttribute('aria-expanded', String(open));
        });
        host.querySelectorAll('[data-size]').forEach(btn => btn.addEventListener('click', () => {
            document.documentElement.style.fontSize = `${btn.dataset.size}px`;
            localStorage.setItem('ins-text-size', btn.dataset.size);
            host.querySelectorAll('[data-size]').forEach(b => b.setAttribute('aria-pressed', String(b === btn)));
            window.dispatchEvent(new Event('resize'));
            window.dispatchEvent(new Event('textsizechange'));
        }));
        document.addEventListener('click', e => { if (!host.contains(e.target)) close(); });
        host.addEventListener('keydown', e => { if (e.key === 'Escape') { close(); toggle.focus(); } });
    });
})();

// ECharts uses pixel fonts; keep its labels in step with the reading preset.
// Skip observation arrays, and retain the current zoom/legend state on resize.
if (window.echarts) {
    const init = echarts.init.bind(echarts);
    const scaleFonts = (obj, factor) => {
        if (Array.isArray(obj)) return obj.map(x => scaleFonts(x, factor));
        if (!obj || typeof obj !== 'object') return obj;
        return Object.fromEntries(Object.entries(obj).map(([key, value]) => [key,
            key === 'fontSize' && typeof value === 'number' ? value * factor
                : ['data', 'source', 'geoJSON'].includes(key) ? value : scaleFonts(value, factor)]));
    };
    echarts.init = (...args) => {
        const chart = init(...args);
        const setOption = chart.setOption.bind(chart);
        const scale = () => parseFloat(getComputedStyle(document.documentElement).fontSize) / 16;
        let applied = scale();
        chart.setOption = (option, ...rest) => {
            applied = scale();
            return setOption(scaleFonts(option, applied), ...rest);
        };
        const resizeText = () => {
            if (chart.isDisposed()) return;
            const next = scale();
            setOption(scaleFonts(chart.getOption(), next / applied));
            applied = next;
            chart.resize();
        };
        window.addEventListener('textsizechange', resizeText);
        const dispose = chart.dispose.bind(chart);
        chart.dispose = () => { window.removeEventListener('textsizechange', resizeText); dispose(); };
        return chart;
    };
}
