/**
 * API client for INS TEMPO Explorer.
 *
 * Two modes (js/config.js): "server" calls the FastAPI /api; "static" answers
 * the same paths from the static build through js/engine/static-api.js (loaded
 * on first use), so pages never know the difference. Errors carry `.status`.
 */
const API = {
    base: '/api',
    isStatic: (window.TEMPO_CONFIG || {}).mode === 'static',
    _static: null,

    /** The static site's API (engine/static-api.js), created once. */
    staticApi() {
        if (!this._static) {
            this._static = import('/js/engine/static-api.js').then(m => ({
                m, api: m.makeStaticApi(m.browserIO('/')),
            }));
        }
        return this._static;
    },

    async fetch(path, params = {}) {
        if (this.isStatic) {
            const p = {};
            for (const [k, v] of Object.entries(params || {})) {
                if (v !== null && v !== undefined && v !== '') p[k] = String(v);
            }
            const { api } = await this.staticApi();
            try {
                return await api.handle(path, p);
            } catch (e) {
                throw Object.assign(new Error(e.message), { status: e.status || 500, detail: e.detail });
            }
        }
        const url = new URL(this.base + path, window.location.origin);
        Object.entries(params).forEach(([k, v]) => {
            if (v !== null && v !== undefined && v !== '') {
                url.searchParams.set(k, v);
            }
        });
        const resp = await fetch(url);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            const d = err.detail;
            throw Object.assign(
                new Error((d && typeof d === 'object') ? (d.message || JSON.stringify(d)) : (d || `HTTP ${resp.status}`)),
                { status: resp.status, detail: d });
        }
        return resp.json();
    },

    getCategories(params = {}) {
        return this.fetch('/categories', params);
    },

    getCategoryTrends() {
        return this.fetch('/categories/trends');
    },

    getDatasets(params = {}) {
        return this.fetch('/datasets', params);
    },

    /** Concept-first search: reviewed concepts + parsed place/period + families. */
    search(q, params = {}) {
        return this.fetch('/search', { q, ...params });
    },

    /** Actual values of one dimension, searchable and paginated. */
    getOptions(code, column, params = {}) {
        return this.fetch(`/datasets/${code}/options`, { column, ...params });
    },

    getDataset(code, params = {}) {
        return this.fetch(`/datasets/${code}`, params);
    },

    getDatasetData(code, filters = {}, limit = 5000, { groupBy = null } = {}) {
        const params = {
            filters: JSON.stringify(filters),
            limit,
        };
        if (groupBy) params.group_by = JSON.stringify(groupBy);
        return this.fetch(`/datasets/${code}/data`, params);
    },

    getDimensions(params = {}) {
        return this.fetch('/dimensions', params);
    },

    getCorpusSummary(params = {}) {
        return this.fetch('/corpus/summary', params);
    },

    getCategorySummary(code, params = {}) {
        return this.fetch(`/categories/${code}/summary`, params);
    },

    async getViewProfile(code) {
        const resp = await fetch(`/view-profiles/${code}.json`);
        if (!resp.ok) return null;
        return resp.json();
    },

    /**
     * Download CSV/XLSX of the current selection (raw observations, not the
     * chart sample). A preflight call first reports the matching row count or
     * the rejection (e.g. XLSX over the sheet limit) so the browser never
     * saves an error page as a file.
     */
    async download(code, fmt, lang, filters, btn) {
        if (this.isStatic) return this.staticDownload(code, fmt, lang, filters, btn);
        const qs = `format=${fmt}&lang=${lang}&filters=${encodeURIComponent(JSON.stringify(filters || {}))}`;
        const label = btn ? btn.textContent : '';
        try {
            const resp = await fetch(`${this.base}/datasets/${code}/download?${qs}&preflight=1`);
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({ detail: resp.statusText }));
                alert(typeof err.detail === 'string' ? err.detail : `HTTP ${resp.status}`);
                return;
            }
            const info = await resp.json();
            if (btn) {
                btn.textContent = `${info.matching_rows.toLocaleString()} ${lang === 'en' ? 'rows' : 'rânduri'}`;
                setTimeout(() => { btn.textContent = label; }, 4000);
            }
            window.location.href = `${this.base}/datasets/${code}/download?${qs}`;
        } catch (e) {
            alert(lang === 'en' ? `Download failed: ${e.message}` : `Descărcarea a eșuat: ${e.message}`);
        }
    },

    /** Save bytes or text as a file. */
    saveFile(data, name, type) {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([data], { type }));
        a.download = name;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    },

    /** Static site: the same raw observations, written in the browser
     *  (CSV exactly as the server writes it; XLSX via SheetJS, loaded on demand). */
    async staticDownload(code, fmt, lang, filters, btn) {
        const label = btn ? btn.textContent : '';
        try {
            const { api, m } = await this.staticApi();
            const out = await api.exportRows(code, { format: fmt, lang, filters: JSON.stringify(filters || {}) });
            if (btn) {
                btn.textContent = `${out.total.toLocaleString()} ${lang === 'en' ? 'rows' : 'rânduri'}`;
                setTimeout(() => { btn.textContent = label; }, 4000);
            }
            if (fmt === 'csv') {
                this.saveFile(m.toCsv(out.columns, out.rows), `${code}.csv`, 'text/csv;charset=utf-8');
                return;
            }
            const XLSX = await this.loadSheetJS();
            const num = v => (v === null ? null : Number(v));
            const aoa = [out.columns, ...out.rows.map(r => [...r.slice(0, -1), num(r[r.length - 1])])];
            const ws = XLSX.utils.aoa_to_sheet(aoa);
            const wb = XLSX.utils.book_new();
            XLSX.utils.book_append_sheet(wb, ws, code.slice(0, 31));
            this.saveFile(XLSX.write(wb, { type: 'array', bookType: 'xlsx', compression: true }), `${code}.xlsx`,
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
        } catch (e) {
            alert(lang === 'en' ? `Download failed: ${e.message}` : `Descărcarea a eșuat: ${e.message}`);
        }
    },

    loadSheetJS() {
        if (window.XLSX) return Promise.resolve(window.XLSX);
        return new Promise((resolve, reject) => {
            const s = document.createElement('script');
            s.src = 'https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js';
            s.onload = () => resolve(window.XLSX);
            s.onerror = () => reject(new Error('XLSX library could not be loaded'));
            document.head.appendChild(s);
        });
    },

    /** Dataset evidence ZIP (PA-03a): server endpoint, or built in the browser. */
    async datasetEvidence(code, { filters, groupBy, lang }) {
        if (!this.isStatic) {
            const url = new URL(`${this.base}/datasets/${encodeURIComponent(code)}/evidence`, window.location.origin);
            url.searchParams.set('filters', JSON.stringify(filters || {}));
            if (groupBy) url.searchParams.set('group_by', JSON.stringify(groupBy));
            url.searchParams.set('lang', lang);
            const resp = await fetch(url);
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw Object.assign(new Error(err.detail || `HTTP ${resp.status}`), { status: resp.status });
            }
            return resp.blob();
        }
        const [{ api, m }, ev] = await Promise.all([this.staticApi(), import('/js/engine/evidence.js')]);
        const q = new URLSearchParams({ code });
        if (filters && Object.keys(filters).length) q.set('f', JSON.stringify(filters));
        if (lang !== 'ro') q.set('lang', lang);
        try {
            const out = await ev.datasetEvidence(api, m.ApiError, code, {
                filters, groupBy, lang, link: `${window.location.origin}/dataset-v2.html?${q}`,
                build: await api.loader.build() });
            return new Blob([out.zip], { type: 'application/zip' });
        } catch (e) {
            throw Object.assign(new Error(e.message), { status: e.status || 500 });
        }
    },

    /** Recipe evidence link: the server bundle, or the one recorded at build time
     *  (static: the full-year bundle; an area subset is not applied). */
    recipeEvidenceHref(id, { year, areas, lang }) {
        if (this.isStatic) return `/rec/recipe/${encodeURIComponent(id)}/${year}.${lang === 'en' ? 'en' : 'ro'}.zip`;
        const q = new URLSearchParams(Object.entries({ year, areas, lang }).filter(([, v]) => v));
        return `${this.base}/recipes/${encodeURIComponent(id)}/evidence?${q}`;
    },
};
