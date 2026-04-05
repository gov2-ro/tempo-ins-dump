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
};
