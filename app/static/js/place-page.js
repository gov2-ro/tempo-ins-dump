function _esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function alignToYears(seriesData, years) {
    const map = {};
    for (const r of seriesData) map[r.year] = r.value;
    return years.map(y => map[y] ?? null);
}

class PlaceProfileApp {
    constructor() {
        this.data = null;
        this.activeKpiIndex = 0;
        this.activePeers = new Set();
        this.activeCategory = 'all';
        this.comparisonChart = null;
        this.comparisonData = {};  // kpi_label → {series_name: [{year, value}]}
        this.sparklines = [];
        this.itemsPerPage = 25;
        this.currentPage = 1;
    }

    async init() {
        const parts = window.location.pathname.split('/').filter(Boolean);
        // /place/{type}/{slug}
        if (parts.length < 3) return;
        this.placeType = parts[1];
        this.placeSlug = parts[2];

        try {
            const resp = await fetch(`/api/places/${this.placeType}/${this.placeSlug}`);
            if (!resp.ok) {
                document.getElementById('place-loading').textContent = 'Locul nu a fost găsit.';
                return;
            }
            this.data = await resp.json();
        } catch (e) {
            document.getElementById('place-loading').textContent = 'Eroare la încărcare.';
            return;
        }

        this._renderHeader();
        this._renderKPIs();
        this._renderIndicatorGrid();
        this._renderComparison();

        document.getElementById('place-loading').style.display = 'none';
        document.getElementById('place-content').style.display = 'block';

        document.title = `${this.data.place.name} — INS+`;
    }

    _renderHeader() {
        const { place, dataset_count } = this.data;
        const crumbs = ['<a href="/places">Locuri</a>'];
        if (place.parent) {
            crumbs.push(`<a href="/place/${place.parent.type}/${place.parent.slug}">${place.parent.name}</a>`);
        }
        crumbs.push(place.name);
        document.getElementById('breadcrumb').innerHTML = crumbs.join(' › ');
        document.getElementById('place-name').textContent = place.name;
        const typeLabels = { county: 'Județ', region: 'Regiune', macroregion: 'Macroregiune', locality: 'Localitate' };
        document.getElementById('geo-badge').textContent = typeLabels[place.type] || place.type;
        document.getElementById('dataset-count').textContent = `${dataset_count} seturi de date disponibile`;
    }

    _renderKPIs() {
        const grid = document.getElementById('kpi-grid');
        for (const c of this.sparklines) c.dispose();
        this.sparklines = [];
        grid.innerHTML = this.data.kpis.map((kpi, i) => {
            const deltaHtml = kpi.change_yoy != null
                ? `<div class="kpi-delta ${kpi.change_yoy >= 0 ? 'up' : 'down'}">
                     ${kpi.change_yoy >= 0 ? '▲' : '▼'} ${Math.abs(kpi.change_yoy)} ${_esc(kpi.unit)}
                   </div>`
                : '';
            return `
                <div class="kpi-card ${i === 0 ? 'active' : ''}"
                     data-kpi-index="${i}"
                     onclick="app._selectKpi(${i})">
                    <div class="kpi-label">${_esc(kpi.label)}</div>
                    <div>
                        <span class="kpi-value">${kpi.value != null ? kpi.value.toLocaleString('ro-RO') : '—'}</span>
                        <span class="kpi-unit">${_esc(kpi.unit)}</span>
                    </div>
                    ${deltaHtml}
                    <div class="kpi-sparkline" id="kpi-spark-${i}"></div>
                </div>`;
        }).join('');

        requestAnimationFrame(() => {
            this.data.kpis.forEach((kpi, i) => {
                this._renderSparkline(`kpi-spark-${i}`, kpi.sparkline);
            });
        });
    }

    _renderSparkline(containerId, series) {
        const el = document.getElementById(containerId);
        if (!el || !series || series.length < 2) return;
        const chart = echarts.init(el, null, { renderer: 'svg' });
        this.sparklines.push(chart);
        chart.setOption({
            animation: false,
            grid: { top: 2, right: 2, bottom: 2, left: 2 },
            xAxis: { type: 'category', show: false, data: series.map(r => r.year) },
            yAxis: { type: 'value', show: false },
            series: [{
                type: 'line',
                data: series.map(r => r.value),
                smooth: true,
                showSymbol: false,
                lineStyle: { color: '#3b82f6', width: 1.5 },
                areaStyle: { color: 'rgba(59,130,246,0.1)' },
            }],
        });
        setTimeout(() => chart.resize(), 0);
    }

    _selectKpi(index) {
        document.querySelectorAll('.kpi-card').forEach((el, i) => {
            el.classList.toggle('active', i === index);
        });
        this.activeKpiIndex = index;
        document.getElementById('comparison-kpi-label').textContent =
            this.data.kpis[index]?.label || '';
        this._refreshComparisonChart();
    }

    _renderIndicatorGrid() {
        const { datasets } = this.data;
        const categories = ['all', ...new Set(datasets.map(d => d.category))].sort((a, b) =>
            a === 'all' ? -1 : b === 'all' ? 1 : a.localeCompare(b, 'ro')
        );

        const chips = document.getElementById('category-chips');
        chips.innerHTML = categories.map(cat => {
            const label = cat === 'all' ? 'Toate' : cat;
            return `<div class="cat-chip ${cat === 'all' ? 'active' : ''}"
                        data-cat="${_esc(cat)}"
                        onclick="app._filterCategory('${_esc(cat)}')">${_esc(label)}</div>`;
        }).join('');

        this._renderDatasetCards(datasets);
    }

    _filterCategory(cat) {
        this.activeCategory = cat;
        this.currentPage = 1;
        document.querySelectorAll('.cat-chip').forEach(el => {
            el.classList.toggle('active', el.dataset.cat === cat);
        });
        const filtered = cat === 'all'
            ? this.data.datasets
            : this.data.datasets.filter(d => d.category === cat);
        this._renderDatasetCards(filtered);
        setTimeout(() => {
            document.getElementById('indicator-grid')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 100);
    }

    _renderDatasetCards(datasets) {
        const grid = document.getElementById('indicator-grid');
        const totalPages = Math.ceil(datasets.length / this.itemsPerPage);
        const start = (this.currentPage - 1) * this.itemsPerPage;
        const end = start + this.itemsPerPage;
        const pageDatasets = datasets.slice(start, end);

        let html = pageDatasets.map(d => {
            if (!d.has_data) {
                return `<div class="ind-card no-data">
                    <div class="ind-title">${_esc(d.title)}</div>
                    <div class="no-data-label">fără date</div>
                </div>`;
            }
            return `<a class="ind-card"
                       href="/dataset/${d.code}?place=${encodeURIComponent(this.placeSlug)}"
                       title="${_esc(d.title)}">
                <div class="ind-title">${_esc(d.title)}</div>
            </a>`;
        }).join('');

        if (datasets.length > this.itemsPerPage) {
            const pageButtons = [];
            for (let i = 1; i <= totalPages; i++) {
                pageButtons.push(`<button class="pagination-btn ${i === this.currentPage ? 'active' : ''}"
                    onclick="window.app._goToPage(${i}, ${datasets.length})">${i}</button>`);
            }
            html += `<div class="pagination">${pageButtons.join('')}</div>`;
        }

        grid.innerHTML = html;
    }

    _goToPage(page, totalDatasets) {
        const totalPages = Math.ceil(totalDatasets / this.itemsPerPage);
        if (page >= 1 && page <= totalPages) {
            this.currentPage = page;
            const filtered = this.activeCategory === 'all'
                ? this.data.datasets
                : this.data.datasets.filter(d => d.category === this.activeCategory);
            this._renderDatasetCards(filtered);
            setTimeout(() => {
                document.getElementById('indicator-grid')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 100);
        }
    }

    _renderComparison() {
        const { place, peers, kpis } = this.data;

        const alwaysChips = document.getElementById('always-chips');
        const baselines = [];
        if (place.parent) {
            baselines.push(`<span class="baseline-chip">🇷🇴 Medie națională</span>`);
            baselines.push(`<span class="baseline-chip">${_esc(place.parent.name)} (regiune)</span>`);
        } else {
            baselines.push(`<span class="baseline-chip">🇷🇴 Medie națională</span>`);
        }
        alwaysChips.innerHTML = baselines.join('');

        const peerGroupsEl = document.getElementById('peer-groups');
        const groups = [];
        if (peers.same_region?.length) {
            const chips = peers.same_region.map(p =>
                `<div class="peer-chip" data-slug="${p.slug}" data-type="${p.type}" data-name="${_esc(p.name)}"
                      onclick="app._togglePeer(this)">${_esc(p.name)}</div>`
            ).join('');
            groups.push(`<div class="peer-group">
                <span class="peer-group-label">Aceeași regiune:</span>${chips}
            </div>`);
        }
        if (peers.similar_size?.length) {
            const chips = peers.similar_size.map(p =>
                `<div class="peer-chip" data-slug="${p.slug}" data-type="${p.type}" data-name="${_esc(p.name)}"
                      onclick="app._togglePeer(this)">${_esc(p.name)}</div>`
            ).join('');
            groups.push(`<div class="peer-group">
                <span class="peer-group-label">Mărime similară:</span>${chips}
            </div>`);
        }
        peerGroupsEl.innerHTML = groups.join('');

        document.getElementById('comparison-kpi-label').textContent = kpis[0]?.label || '';

        const chartEl = document.getElementById('comparison-chart');
        this.comparisonChart = echarts.init(chartEl, null, { renderer: 'svg' });

        this._loadBaselines().then(() => this._refreshComparisonChart());
    }

    async _loadBaselines() {
        const kpi = this.data.kpis[this.activeKpiIndex];
        if (!kpi) return;
        const label = encodeURIComponent(kpi.label);
        try {
            const resp = await fetch(
                `/api/places/${this.placeType}/${this.placeSlug}/baselines/${label}`
            );
            if (!resp.ok) return;
            const { national, region } = await resp.json();
            this.comparisonData['__national__'] = national;
            this.comparisonData['__region__'] = region;
        } catch (_) {}
    }

    async _togglePeer(el) {
        const slug = el.dataset.slug;
        const type = el.dataset.type;
        const name = el.dataset.name;

        if (this.activePeers.has(slug)) {
            this.activePeers.delete(slug);
            el.classList.remove('active');
            delete this.comparisonData[slug];
        } else {
            if (this.activePeers.size >= 3) return;
            this.activePeers.add(slug);
            el.classList.add('active');
            try {
                const resp = await fetch(`/api/places/${type}/${slug}`);
                if (resp.ok) {
                    const peer = await resp.json();
                    const kpiLabel = this.data.kpis[this.activeKpiIndex]?.label;
                    const kpi = peer.kpis.find(k => k.label === kpiLabel);
                    this.comparisonData[slug] = kpi ? kpi.sparkline : [];
                }
            } catch (_) {}
        }
        this._refreshComparisonChart();
    }

    _refreshComparisonChart() {
        if (!this.comparisonChart) return;
        const kpi = this.data.kpis[this.activeKpiIndex];
        if (!kpi) return;

        const xYears = kpi.sparkline.map(r => r.year);
        const series = [];
        const colors = ['#3b82f6', '#94a3b8', '#64748b', '#f59e0b', '#a78bfa', '#4ade80'];
        let colorIdx = 0;

        series.push({
            name: this.data.place.name,
            type: 'line',
            data: alignToYears(kpi.sparkline, xYears),
            lineStyle: { width: 2.5, color: colors[colorIdx++] },
            showSymbol: false, smooth: true,
        });

        if (this.comparisonData['__national__']?.length) {
            series.push({
                name: 'Medie națională',
                type: 'line',
                data: alignToYears(this.comparisonData['__national__'], xYears),
                lineStyle: { width: 1.5, color: colors[colorIdx++], type: 'dashed' },
                showSymbol: false, smooth: true,
            });
        }

        if (this.comparisonData['__region__']?.length) {
            series.push({
                name: this.data.place.parent?.name || 'Regiune',
                type: 'line',
                data: alignToYears(this.comparisonData['__region__'], xYears),
                lineStyle: { width: 1.5, color: colors[colorIdx++], type: 'dashed' },
                showSymbol: false, smooth: true,
            });
        }

        for (const slug of this.activePeers) {
            if (this.comparisonData[slug]?.length) {
                const peerName = [...document.querySelectorAll('.peer-chip')]
                    .find(el => el.dataset.slug === slug)?.dataset.name || slug;
                series.push({
                    name: peerName,
                    type: 'line',
                    data: alignToYears(this.comparisonData[slug], xYears),
                    lineStyle: { width: 1.5, color: colors[colorIdx++ % colors.length] },
                    showSymbol: false, smooth: true,
                });
            }
        }

        this.comparisonChart.setOption({
            animation: false,
            tooltip: { trigger: 'axis', confine: true },
            legend: { bottom: 0, textStyle: { color: '#94a3b8', fontSize: 11 }, orient: 'horizontal' },
            grid: { top: 12, right: 16, bottom: 48, left: 32 },
            xAxis: { type: 'category', data: xYears, axisLabel: { color: '#64748b', fontSize: 11, rotate: 45 } },
            yAxis: {
                type: 'value',
                axisLabel: { color: '#64748b', fontSize: 10,
                    formatter: v => {
                        if (v >= 1e6) return (v/1e6).toFixed(0) + 'M';
                        if (v >= 1e3) return (v/1e3).toFixed(0) + 'K';
                        return v;
                    }
                },
                splitLine: { lineStyle: { color: '#1e293b' } },
            },
            series,
        }, true);
    }
}

window.app = new PlaceProfileApp();
document.addEventListener('DOMContentLoaded', () => window.app.init());
