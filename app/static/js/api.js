/**
 * API client for INS TEMPO Explorer
 */
const API = {
    base: '/api',

    async fetch(path, params = {}) {
        const url = new URL(this.base + path, window.location.origin);
        Object.entries(params).forEach(([k, v]) => {
            if (v !== null && v !== undefined && v !== '') {
                url.searchParams.set(k, v);
            }
        });
        const resp = await fetch(url);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(err.detail || `HTTP ${resp.status}`);
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
};
