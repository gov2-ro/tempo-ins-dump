"""
Simple Flask browser for DuckDB + Parquet data

This demonstrates:
- Listing datasets from metadata
- Viewing dataset details
- Previewing Parquet data
- Filtering data by dimensions
"""
from flask import Flask, render_template_string, request, jsonify
import duckdb
import math
from pathlib import Path
from duckdb_config import DB_FILE, PARQUET_DIR

app = Flask(__name__)


# HTML Template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>DuckDB + Parquet Browser</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            display: flex;
            height: 100vh;
            overflow: hidden;
        }
        #sidebar {
            width: 300px;
            background: #f5f5f5;
            border-right: 1px solid #ddd;
            overflow-y: auto;
            padding: 20px;
        }
        #main {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
        }
        h1 { font-size: 24px; margin-bottom: 20px; }
        h2 { font-size: 18px; margin: 20px 0 10px; }
        h3 { font-size: 14px; margin: 15px 0 5px; }

        .search-box {
            width: 100%;
            padding: 8px;
            margin-bottom: 15px;
            border: 1px solid #ddd;
            border-radius: 4px;
        }

        .dataset-list {
            list-style: none;
        }
        .dataset-item {
            padding: 8px;
            margin-bottom: 4px;
            background: white;
            border: 1px solid #ddd;
            border-radius: 4px;
            cursor: pointer;
            font-size: 13px;
        }
        .dataset-item:hover {
            background: #e8f4f8;
        }
        .dataset-item.active {
            background: #007bff;
            color: white;
            border-color: #0056b3;
        }

        .dataset-code {
            font-weight: bold;
            margin-bottom: 2px;
        }
        .dataset-name {
            font-size: 11px;
            color: #666;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .dataset-item.active .dataset-name {
            color: rgba(255,255,255,0.9);
        }
        .dataset-stats {
            font-size: 10px;
            color: #999;
            margin-top: 3px;
        }
        .dataset-item.active .dataset-stats {
            color: rgba(255,255,255,0.7);
        }
        .dataset-item.is-split {
            border-left: 3px solid #b8daff;
            padding-left: 5px;
        }
        .dataset-item.is-split .dataset-code::before {
            content: '↳ ';
            color: #6cb2f7;
            font-size: 11px;
        }
        .dataset-item.is-split.active {
            border-left-color: rgba(255,255,255,0.5);
        }
        .split-badge {
            display: inline-block;
            font-size: 9px;
            padding: 1px 5px;
            border-radius: 3px;
            background: #e8f0fe;
            color: #1967d2;
            margin-left: 4px;
            vertical-align: middle;
        }
        .dataset-item.active .split-badge {
            background: rgba(255,255,255,0.25);
            color: white;
        }

        .info-grid {
            display: grid;
            grid-template-columns: 150px 1fr;
            gap: 10px;
            margin: 10px 0;
            font-size: 14px;
        }
        .info-label {
            font-weight: bold;
            color: #666;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            margin: 10px 0;
            font-size: 13px;
        }
        th, td {
            padding: 8px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }
        th {
            background: #f5f5f5;
            font-weight: 600;
        }
        tr:hover {
            background: #f9f9f9;
        }
        .filter-row td { background: #f0f4f8; padding: 3px 6px; }
        .filter-row:hover td { background: #f0f4f8; }
        .col-filter {
            width: 100%;
            padding: 2px 4px;
            font-size: 11px;
            border: 1px solid #ccc;
            border-radius: 3px;
            box-sizing: border-box;
            background: white;
        }
        .col-filter:focus { outline: none; border-color: #007bff; }
        .col-filter.active { border-color: #007bff; background: #e8f0fe; font-weight: 600; }
        .row-count { font-size: 12px; color: #666; margin-top: 4px; }

        .dimension-list {
            list-style: none;
            margin: 10px 0;
        }
        .dimension-item {
            padding: 6px;
            background: white;
            border: 1px solid #ddd;
            margin-bottom: 4px;
            border-radius: 4px;
            font-size: 13px;
        }
        .dimension-label {
            font-weight: 600;
        }
        .dimension-count {
            color: #666;
            font-size: 11px;
        }

        .tab-buttons {
            margin: 20px 0 10px;
            border-bottom: 1px solid #ddd;
        }
        .tab-button {
            padding: 8px 16px;
            background: none;
            border: none;
            border-bottom: 2px solid transparent;
            cursor: pointer;
            font-size: 14px;
            color: #666;
        }
        .tab-button:hover {
            color: #007bff;
            background: #f9f9f9;
        }
        .tab-button.active {
            border-bottom-color: #007bff;
            color: #007bff;
            font-weight: 600;
        }
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }

        .filter-section {
            background: #f9f9f9;
            padding: 15px;
            border-radius: 4px;
            margin: 10px 0;
        }
        select {
            width: 100%;
            padding: 6px;
            border: 1px solid #ddd;
            border-radius: 4px;
            margin: 5px 0;
        }
        button {
            padding: 8px 16px;
            background: #007bff;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
        }
        button:hover {
            background: #0056b3;
        }

        .loading {
            text-align: center;
            padding: 40px;
            color: #666;
        }

        .error {
            background: #fee;
            border: 1px solid #fcc;
            padding: 10px;
            border-radius: 4px;
            color: #c00;
            margin: 10px 0;
        }

        .stat-box {
            display: inline-block;
            background: #f0f8ff;
            padding: 10px 15px;
            border-radius: 4px;
            margin-right: 10px;
            margin-bottom: 10px;
        }
        .stat-label {
            font-size: 11px;
            color: #666;
            text-transform: uppercase;
        }
        .stat-value {
            font-size: 20px;
            font-weight: bold;
            color: #007bff;
        }

        .nav-buttons {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 16px;
        }
        .nav-buttons button {
            padding: 6px 14px;
            font-size: 13px;
        }
        .nav-buttons button:disabled {
            background: #ccc;
            cursor: not-allowed;
        }
        .nav-position {
            font-size: 13px;
            color: #666;
        }

        /* Sort bar */
        .sort-bar {
            display: flex;
            gap: 4px;
            margin-bottom: 10px;
            flex-wrap: wrap;
        }
        .sort-bar span { font-size: 11px; color: #999; align-self: center; margin-right: 2px; }
        .sort-btn {
            padding: 3px 8px;
            font-size: 11px;
            background: #e9ecef;
            color: #555;
            border: 1px solid #ccc;
            border-radius: 3px;
            cursor: pointer;
        }
        .sort-btn:hover { background: #dee2e6; }
        .sort-btn.active { background: #007bff; color: white; border-color: #0056b3; }

        /* Info sections */
        .info-section { margin: 18px 0; }
        .info-section h3 {
            font-size: 12px;
            text-transform: uppercase;
            color: #999;
            letter-spacing: 0.05em;
            border-bottom: 1px solid #eee;
            padding-bottom: 4px;
            margin-bottom: 8px;
        }
        .info-grid2 {
            display: grid;
            grid-template-columns: 160px 1fr;
            gap: 5px 12px;
            font-size: 13px;
        }
        .info-grid2 .lbl { color: #888; }
        .info-grid2 .val { color: #333; }
        .info-text {
            font-size: 13px;
            line-height: 1.6;
            color: #444;
            white-space: pre-wrap;
        }

        /* Table pagination */
        .table-pagination {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-top: 8px;
            font-size: 13px;
        }
        .table-pagination button {
            padding: 4px 12px;
            font-size: 12px;
        }
        .table-pagination button:disabled { background: #ccc; cursor: not-allowed; }

        /* Breadcrumbs */
        .breadcrumbs {
            font-size: 13px;
            color: #888;
            margin-bottom: 10px;
        }
        .breadcrumbs a {
            color: #007bff;
            text-decoration: none;
            cursor: pointer;
        }
        .breadcrumbs a:hover { text-decoration: underline; }
        .breadcrumbs span.sep { margin: 0 5px; color: #ccc; }

        /* Landing page */
        .hero {
            text-align: center;
            padding: 40px 20px 30px;
            background: linear-gradient(135deg, #f0f4f8, #e8f0fe);
            border-radius: 8px;
            margin-bottom: 28px;
        }
        .hero h1 { font-size: 28px; color: #1a1a2e; margin-bottom: 8px; }
        .hero p { color: #666; font-size: 15px; margin-bottom: 18px; }
        .hero-stats { display: flex; justify-content: center; gap: 24px; flex-wrap: wrap; }
        .hero-stat { text-align: center; }
        .hero-stat .num { font-size: 24px; font-weight: bold; color: #007bff; }
        .hero-stat .lbl { font-size: 11px; color: #999; text-transform: uppercase; }

        /* Split family panel */
        .split-family {
            background: #f0f7ff;
            border: 1px solid #cce0ff;
            border-radius: 6px;
            padding: 14px 16px;
            margin: 14px 0;
        }
        .split-family h3 {
            font-size: 13px;
            color: #1967d2;
            margin-bottom: 8px;
        }
        .split-family .parent-link {
            font-size: 13px;
            margin-bottom: 8px;
        }
        .split-family .parent-link a {
            color: #1967d2;
            text-decoration: none;
            cursor: pointer;
        }
        .split-family .parent-link a:hover { text-decoration: underline; }
        .sibling-list {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .sibling-item {
            display: flex;
            gap: 8px;
            align-items: baseline;
            padding: 5px 8px;
            border-radius: 4px;
            font-size: 13px;
            cursor: pointer;
            background: white;
            border: 1px solid #dde5f0;
        }
        .sibling-item:hover { border-color: #1967d2; background: #e8f0fe; }
        .sibling-item.current { background: #d2e3fc; border-color: #1967d2; font-weight: 600; }
        .sibling-item .s-code { color: #1967d2; min-width: 60px; font-size: 12px; }
        .sibling-item .s-label { flex: 1; color: #333; }
        .sibling-item .s-rows { color: #888; font-size: 11px; white-space: nowrap; }
        .sibling-item .s-pattern {
            font-size: 10px;
            padding: 1px 5px;
            border-radius: 3px;
            background: #e8eaed;
            color: #666;
        }

        .theme-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 14px;
            margin-bottom: 24px;
        }
        .theme-card {
            padding: 16px;
            border: 1px solid #ddd;
            border-radius: 8px;
            cursor: pointer;
            background: white;
            transition: border-color 0.15s, box-shadow 0.15s;
        }
        .theme-card:hover {
            border-color: #007bff;
            box-shadow: 0 2px 8px rgba(0,123,255,0.1);
        }
        .theme-card h3 { font-size: 14px; color: #222; margin-bottom: 6px; line-height: 1.4; }
        .theme-card .count { font-size: 12px; color: #888; }
        .theme-card .sub-count { font-size: 11px; color: #aaa; margin-top: 2px; }

        .context-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 18px;
        }
        .context-header h2 { font-size: 20px; }

        .dataset-grid-item {
            padding: 8px 10px;
            border: 1px solid #eee;
            border-radius: 4px;
            cursor: pointer;
            background: white;
            font-size: 13px;
            display: flex;
            gap: 8px;
            align-items: baseline;
        }
        .dataset-grid-item:hover { border-color: #007bff; background: #f0f7ff; }
        .dataset-grid-item .dcode { font-weight: bold; color: #007bff; min-width: 72px; }
        .dataset-grid-item .dname { color: #444; flex: 1; }
        .dataset-grid-item .drows { color: #aaa; font-size: 11px; white-space: nowrap; }
        .datasets-in-context { display: flex; flex-direction: column; gap: 4px; }
    </style>
</head>
<body>
    <div id="sidebar">
        <h1>Datasets</h1>
        <input type="text" class="search-box" id="searchBox" placeholder="Search datasets..." />
        <div class="sort-bar">
            <span>Sort:</span>
            <button class="sort-btn active" data-sort="name" onclick="setSort('name')">Name</button>
            <button class="sort-btn" data-sort="updated" onclick="setSort('updated')">Updated</button>
            <button class="sort-btn" data-sort="records" onclick="setSort('records')">Records</button>
            <button class="sort-btn" data-sort="dimensions" onclick="setSort('dimensions')">Dims</button>
            <button class="sort-btn" data-sort="cells" onclick="setSort('cells')">Cells</button>
            <button class="sort-btn" data-sort="options" onclick="setSort('options')">Options</button>
        </div>
        <ul class="dataset-list" id="datasetList">
            <li class="loading">Loading...</li>
        </ul>
    </div>

    <div id="main">
        <div id="content">
            <div class="loading">Loading...</div>
        </div>
    </div>

    <script>
        let currentMatrix = null;
        let allDatasets = [];
        let filteredDatasets = [];
        let currentSort = 'name';
        let contextTree = null;   // loaded once at startup
        let contextMap = {};      // code → node, built from tree

        // ─── Bootstrap ─────────────────────────────────────────────────────────
        Promise.all([
            fetch('/api/datasets?sort=name').then(r => r.json()),
            fetch('/api/contexts').then(r => r.json()),
        ]).then(([dsData, ctxData]) => {
            allDatasets = dsData.datasets;
            filteredDatasets = allDatasets;
            renderDatasets(filteredDatasets);

            contextTree = ctxData.themes;
            // Build flat map: code → node
            function walkTree(nodes) {
                nodes.forEach(n => {
                    contextMap[n.code] = n;
                    if (n.children) walkTree(n.children);
                });
            }
            walkTree(contextTree);

            // Hash routing — handle initial load
            handleHash();
        });

        // ─── Hash routing ───────────────────────────────────────────────────────
        window.addEventListener('hashchange', handleHash);

        function handleHash() {
            const hash = location.hash.slice(1); // '#AMG159E' → 'AMG159E'
            if (!hash) {
                showLanding();
            } else if (hash.startsWith('ctx/')) {
                showContext(hash.slice(4));
            } else {
                // treat as matrix code
                _loadDatasetContent(hash);
            }
        }

        function setHash(h) {
            // Set without triggering hashchange twice; use replaceState for internal nav
            if (location.hash.slice(1) !== h) {
                history.pushState(null, '', h ? '#' + h : location.pathname);
                // pushState doesn't fire hashchange, so call handler manually
                handleHash();
            }
        }

        // ─── Sort / search ──────────────────────────────────────────────────────
        function loadDatasetList(sort) {
            if (sort === currentSort && allDatasets.length) {
                // already loaded; just re-filter
                applySearch();
                return;
            }
            currentSort = sort;
            fetch(`/api/datasets?sort=${currentSort}`)
                .then(r => r.json())
                .then(data => {
                    allDatasets = data.datasets;
                    applySearch();
                });
        }

        function setSort(key) {
            currentSort = key;
            document.querySelectorAll('.sort-btn').forEach(b => {
                b.classList.toggle('active', b.dataset.sort === key);
            });
            fetch(`/api/datasets?sort=${key}`)
                .then(r => r.json())
                .then(data => {
                    allDatasets = data.datasets;
                    applySearch();
                });
        }

        function applySearch() {
            const q = document.getElementById('searchBox').value.toLowerCase();
            filteredDatasets = q
                ? allDatasets.filter(d =>
                    d.matrix_code.toLowerCase().includes(q) ||
                    d.matrix_name.toLowerCase().includes(q))
                : allDatasets;
            renderDatasets(filteredDatasets);
        }

        document.getElementById('searchBox').addEventListener('input', applySearch);

        // Keyboard navigation
        document.addEventListener('keydown', (e) => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
            if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') navigateDataset(-1);
            if (e.key === 'ArrowRight' || e.key === 'ArrowDown') navigateDataset(1);
        });

        function navigateDataset(delta) {
            if (filteredDatasets.length === 0) return;
            const idx = filteredDatasets.findIndex(d => d.matrix_code === currentMatrix);
            let newIdx;
            if (idx === -1) {
                newIdx = delta > 0 ? 0 : filteredDatasets.length - 1;
            } else {
                newIdx = Math.max(0, Math.min(filteredDatasets.length - 1, idx + delta));
            }
            if (newIdx !== idx) {
                setHash(filteredDatasets[newIdx].matrix_code);
                setTimeout(() => {
                    const items = document.querySelectorAll('.dataset-item');
                    if (items[newIdx]) items[newIdx].scrollIntoView({ block: 'nearest' });
                }, 50);
            }
        }

        function renderDatasets(datasets) {
            const list = document.getElementById('datasetList');
            if (datasets.length === 0) {
                list.innerHTML = '<li class="loading">No datasets found</li>';
                return;
            }
            list.innerHTML = datasets.map(d => {
                const extra = currentSort === 'updated' && d.ultima_actualizare
                    ? ` • ${d.ultima_actualizare}`
                    : currentSort === 'cells'
                    ? ` • ${((d.row_count||0)*(d.mat_max_dim||0)).toLocaleString()} cells`
                    : currentSort === 'options' && d.total_options != null
                    ? ` • ${d.total_options.toLocaleString()} opts`
                    : '';
                const splitClass = d.is_split ? ' is-split' : '';
                const splitBadge = d.is_split ? `<span class="split-badge">${d.matrix_code.replace(d.parent_matrix_code + '_', '')}</span>` : '';
                return `
                <li class="dataset-item${splitClass} ${d.matrix_code === currentMatrix ? 'active' : ''}"
                    onclick="setHash('${d.matrix_code}')">
                    <div class="dataset-code">${d.matrix_code}${splitBadge}</div>
                    <div class="dataset-name">${d.matrix_name}</div>
                    <div class="dataset-stats">${(d.row_count || 0).toLocaleString()} rows • ${d.mat_max_dim} dims${extra}</div>
                </li>`;
            }).join('');
        }

        // ─── Landing page ───────────────────────────────────────────────────────
        function showLanding() {
            currentMatrix = null;
            renderDatasets(filteredDatasets);  // clear active highlight

            if (!contextTree) {
                // Still loading — show placeholder
                document.getElementById('content').innerHTML = '<div class="loading">Loading...</div>';
                return;
            }

            const totalDatasets = allDatasets.length;
            const totalRows = allDatasets.reduce((s, d) => s + (d.row_count || 0), 0);

            const cardsHtml = contextTree.map(theme => `
                <div class="theme-card" onclick="setHash('ctx/${theme.code}')">
                    <h3>${theme.name}</h3>
                    <div class="count">${theme.count.toLocaleString()} datasets</div>
                    <div class="sub-count">${(theme.children || []).length} sub-themes</div>
                </div>
            `).join('');

            document.getElementById('content').innerHTML = `
                <div class="hero">
                    <h1>INS TEMPO — Date Statistice</h1>
                    <p>Browse Romanian National Statistics datasets</p>
                    <div class="hero-stats">
                        <div class="hero-stat"><div class="num">${totalDatasets.toLocaleString()}</div><div class="lbl">Datasets</div></div>
                        <div class="hero-stat"><div class="num">${(totalRows/1e6).toFixed(1)}M</div><div class="lbl">Total Rows</div></div>
                        <div class="hero-stat"><div class="num">${contextTree.length}</div><div class="lbl">Themes</div></div>
                    </div>
                </div>
                <h2 style="margin-bottom:14px">Browse by Theme</h2>
                <div class="theme-grid">${cardsHtml}</div>
            `;
        }

        // ─── Context / theme view ───────────────────────────────────────────────
        function showContext(code) {
            currentMatrix = null;
            const node = contextMap[code];
            if (!node) { showLanding(); return; }

            const crumbs = buildBreadcrumbsForContext(code);

            if (node.level === 0) {
                // Show sub-themes as cards
                const childCards = (node.children || []).map(child => `
                    <div class="theme-card" onclick="setHash('ctx/${child.code}')">
                        <h3>${child.name}</h3>
                        <div class="count">${child.count.toLocaleString()} datasets</div>
                        <div class="sub-count">${(child.children || []).length} categories</div>
                    </div>
                `).join('');

                document.getElementById('content').innerHTML = `
                    <div class="breadcrumbs">${crumbs}</div>
                    <div class="context-header"><h2>${node.name}</h2></div>
                    <div class="theme-grid">${childCards || '<p style="color:#999">No sub-themes</p>'}</div>
                `;
            } else if (node.level === 1) {
                // Show leaf categories as cards
                const childCards = (node.children || []).map(child => `
                    <div class="theme-card" onclick="setHash('ctx/${child.code}')">
                        <h3>${child.name}</h3>
                        <div class="count">${child.count.toLocaleString()} datasets</div>
                    </div>
                `).join('');

                document.getElementById('content').innerHTML = `
                    <div class="breadcrumbs">${crumbs}</div>
                    <div class="context-header"><h2>${node.name}</h2></div>
                    <div class="theme-grid">${childCards || '<p style="color:#999">No categories</p>'}</div>
                `;
            } else {
                // Level 2 — show dataset list
                const datasets = allDatasets.filter(d =>
                    d.ancestor_codes && d.ancestor_codes.includes(code)
                );
                // Fallback: also filter by context_code
                const dsForCtx = datasets.length > 0 ? datasets :
                    allDatasets.filter(d => d.context_code === code);

                const dsHtml = dsForCtx.length
                    ? dsForCtx.map(d => `
                        <div class="dataset-grid-item" onclick="setHash('${d.matrix_code}')">
                            <span class="dcode">${d.matrix_code}</span>
                            <span class="dname">${d.matrix_name}</span>
                            <span class="drows">${(d.row_count||0).toLocaleString()} rows</span>
                        </div>
                    `).join('')
                    : '<p style="color:#999">No datasets in this category</p>';

                document.getElementById('content').innerHTML = `
                    <div class="breadcrumbs">${crumbs}</div>
                    <div class="context-header"><h2>${node.name}</h2>
                        <span style="color:#999;font-size:13px">${dsForCtx.length} datasets</span>
                    </div>
                    <div class="datasets-in-context">${dsHtml}</div>
                `;
            }
        }

        function buildBreadcrumbsForContext(code) {
            // Walk up tree to build path
            const path = [];
            let cur = contextMap[code];
            while (cur) {
                path.unshift(cur);
                cur = cur.parent_code ? contextMap[cur.parent_code] : null;
            }
            const parts = [`<a onclick="setHash('')">Home</a>`];
            path.forEach((node, i) => {
                parts.push('<span class="sep">›</span>');
                if (i < path.length - 1) {
                    parts.push(`<a onclick="setHash('ctx/${node.code}')">${node.name}</a>`);
                } else {
                    parts.push(`<span>${node.name}</span>`);
                }
            });
            return parts.join('');
        }

        // ─── Dataset view ────────────────────────────────────────────────────────
        function loadDataset(matrixCode) {
            setHash(matrixCode);
        }

        function _loadDatasetContent(matrixCode) {
            currentMatrix = matrixCode;
            renderDatasets(filteredDatasets);
            document.getElementById('content').innerHTML = '<div class="loading">Loading...</div>';

            fetch(`/api/dataset/${matrixCode}`)
                .then(r => r.json())
                .then(data => {
                    if (data.error) {
                        document.getElementById('content').innerHTML =
                            `<div class="error">${data.error}</div>`;
                        return;
                    }
                    renderDataset(data);
                });
        }

        function buildBreadcrumbs(ancestorCodes) {
            if (!ancestorCodes || !ancestorCodes.length || !Object.keys(contextMap).length) return '';
            const parts = [`<a onclick="setHash('')">Home</a>`];
            ancestorCodes.forEach(code => {
                const node = contextMap[code];
                if (!node) return;
                parts.push('<span class="sep">›</span>');
                parts.push(`<a onclick="setHash('ctx/${code}')">${node.name}</a>`);
            });
            return `<div class="breadcrumbs">${parts.join('')}</div>`;
        }

        function renderDataset(data) {
            const d = data.metadata;
            const dims = data.dimensions;
            const cov = data.coverage || {};
            const vp = data.value_profile || {};
            const preview = data.preview;

            const breadcrumbs = buildBreadcrumbs(d.ancestor_codes);

            // --- Info tab ---
            function row2(lbl, val) {
                if (!val && val !== 0) return '';
                return `<div class="lbl">${lbl}</div><div class="val">${val}</div>`;
            }
            function section(title, content) {
                return `<div class="info-section"><h3>${title}</h3>${content}</div>`;
            }

            const timeRange = (cov.time_min_year && cov.time_max_year)
                ? `${cov.time_min_year} – ${cov.time_max_year}` + (cov.time_year_count ? ` (${cov.time_year_count} years)` : '')
                : 'N/A';
            const geoInfo = cov.geo_county_count
                ? `${cov.geo_county_count} counties` + (cov.geo_has_national ? ' + national' : '')
                : 'N/A';

            const infoHtml = `
                ${section('General', `<div class="info-grid2">
                    ${row2('Code', d.matrix_code)}
                    ${row2('Category', d.context_code)}
                    ${row2('Path', d.ancestor_path ? `<small>${d.ancestor_path}</small>` : null)}
                    ${row2('Periodicity', Array.isArray(d.periodicitati) ? d.periodicitati.join(', ') : d.periodicitati)}
                    ${row2('Last Updated', d.ultima_actualizare)}
                    ${row2('Active', d.mat_active ? 'Yes' : 'No')}
                    ${row2('Views / Downloads', d.mat_views != null ? `${d.mat_views} / ${d.mat_downloads}` : null)}
                    ${row2('Has Counties', d.nom_jud ? 'Yes' : null)}
                    ${row2('Has Localities', d.nom_loc ? 'Yes' : null)}
                    ${row2('Has SIRUTA', d.mat_siruta ? 'Yes' : null)}
                    ${row2('File Size', formatBytes(d.file_size_bytes))}
                </div>`)}
                ${section('Coverage', `<div class="info-grid2">
                    ${row2('Time Range', timeRange)}
                    ${row2('Granularity', cov.time_granularity)}
                    ${row2('Geo Coverage', geoInfo)}
                    ${row2('Fill Rate', cov.fill_rate)}
                    ${row2('Freshness', cov.freshness_years != null ? `${cov.freshness_years} years old` : null)}
                </div>`)}
                ${vp.val_min != null ? section('Value Profile', `<div class="info-grid2">
                    ${row2('Range', `${vp.val_min} – ${vp.val_max}`)}
                    ${row2('Mean / Median', `${vp.val_mean} / ${vp.val_median}`)}
                    ${row2('Std Dev', vp.val_stddev)}
                    ${row2('Coeff. Variation', vp.coeff_variation)}
                    ${row2('Magnitude', vp.magnitude)}
                    ${row2('Distribution', vp.distribution_shape)}
                    ${row2('Null %', vp.null_pct)}
                    ${row2('Zero %', vp.zero_pct)}
                    ${row2('Negative %', vp.negative_pct)}
                </div>`) : ''}
                ${d.definitie ? section('Definition', `<p class="info-text">${d.definitie}</p>`) : ''}
                ${d.metodologie ? section('Methodology', `<p class="info-text">${d.metodologie}</p>`) : ''}
                ${d.observatii ? section('Notes', `<p class="info-text">${d.observatii}</p>`) : ''}
                ${d.persoane_responsabile ? section('Responsible', `<p class="info-text">${d.persoane_responsabile}</p>`) : ''}
            `;

            // --- Dimensions tab ---
            const dimsHtml = `
                <h2>Dimensions (${dims.length})</h2>
                <table>
                    <thead><tr><th>Label</th><th>Column</th><th style="text-align:right">Options</th></tr></thead>
                    <tbody>
                        ${dims.map(dim => `
                            <tr>
                                <td>
                                    ${dim.options && dim.options.length ? `
                                    <details>
                                        <summary style="cursor:pointer">${dim.dim_label}</summary>
                                        <div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:4px;padding-bottom:4px">
                                            ${dim.options.map(o => `<span style="background:#e8f0fe;border-radius:3px;padding:1px 6px;font-size:11px;color:#333">${o}</span>`).join('')}
                                        </div>
                                    </details>` : dim.dim_label}
                                </td>
                                <td><code style="font-size:11px">${dim.dim_column_name}</code></td>
                                <td style="text-align:right">${dim.option_count}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;

            // --- Split family panel ---
            const sf = data.split_family;
            let splitFamilyHtml = '';
            if (sf && sf.siblings && sf.siblings.length) {
                const isChild = sf.is_split && sf.parent_matrix_code;
                const title = isChild ? 'Sibling Splits' : 'Sub-datasets';
                const parentLink = isChild
                    ? `<div class="parent-link">Parent: <a onclick="setHash('${sf.parent_matrix_code}')">${sf.parent_matrix_code}</a></div>`
                    : '';
                const items = sf.siblings.map(s => `
                    <div class="sibling-item ${s.is_current ? 'current' : ''}"
                         onclick="setHash('${s.matrix_code}')">
                        <span class="s-label">${s.suffix_label || s.matrix_code}</span>
                        <span class="s-pattern">${s.split_pattern.replace(/_/g, ' ')}</span>
                        <span class="s-rows">${(s.row_count||0).toLocaleString()} rows</span>
                    </div>
                `).join('');
                splitFamilyHtml = `
                    <div class="split-family">
                        <h3>${title} (${sf.siblings.length})</h3>
                        ${parentLink}
                        <div class="sibling-list">${items}</div>
                    </div>`;
            }

            const navBtns = renderNavButtons();
            document.getElementById('content').innerHTML = `
                ${breadcrumbs}
                ${navBtns}
                <h1>${d.matrix_code}</h1>
                <p style="color:#555; margin-bottom:12px">${d.matrix_name}</p>
                ${splitFamilyHtml}

                <div style="margin: 12px 0;">
                    <div class="stat-box">
                        <div class="stat-label">Rows</div>
                        <div class="stat-value">${(d.row_count || 0).toLocaleString()}</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">Dimensions</div>
                        <div class="stat-value">${d.mat_max_dim}</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">Cells</div>
                        <div class="stat-value">${((d.row_count||0)*(d.mat_max_dim||0)).toLocaleString()}</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">File Size</div>
                        <div class="stat-value">${formatBytes(d.file_size_bytes)}</div>
                    </div>
                </div>

                <div class="tab-buttons">
                    <button class="tab-button" onclick="switchTab('info', event)">Info</button>
                    <button class="tab-button" onclick="switchTab('dimensions', event)">Dimensions</button>
                    <button class="tab-button active" onclick="switchTab('data', event)">Data</button>
                </div>

                <div class="tab-content" id="tab-info">${infoHtml}</div>
                <div class="tab-content" id="tab-dimensions">${dimsHtml}</div>
                <div class="tab-content active" id="tab-data">
                    <div id="data-table-area">${renderDataTable(preview, d.matrix_code)}</div>
                </div>
            `;
        }

        function renderNavButtons() {
            const idx = filteredDatasets.findIndex(d => d.matrix_code === currentMatrix);
            const total = filteredDatasets.length;
            const hasPrev = idx > 0;
            const hasNext = idx < total - 1;
            return `
                <div class="nav-buttons">
                    <button onclick="setHash('')" style="background:#6c757d">⌂ Home</button>
                    <button onclick="navigateDataset(-1)" ${!hasPrev ? 'disabled' : ''} title="Previous (← ↑)">&#8592; Prev</button>
                    <span class="nav-position">${idx + 1} / ${total}</span>
                    <button onclick="navigateDataset(1)" ${!hasNext ? 'disabled' : ''} title="Next (→ ↓)">Next &#8594;</button>
                </div>
            `;
        }

        function renderDataTable(data, matrixCode) {
            if (!data || !data.columns || data.columns.length === 0) {
                return '<p>No data available</p>';
            }

            const columns = data.columns;
            const serverUniques = data.unique_vals || {};
            const colFilters = {};
            let currentPage = data.page || 0;
            const totalPages = data.total_pages || 1;
            const totalRows = data.total_rows || data.rows.length;

            function buildBody(rows) {
                if (!rows.length) return '<tr><td colspan="100" style="text-align:center;color:#999">No matching rows</td></tr>';
                return rows.map(row => '<tr>' + row.map((cell, i) => {
                    if (columns[i] === 'value') {
                        const v = cell === null ? '<em>null</em>' :
                                  typeof cell === 'number' ? cell.toLocaleString() : cell;
                        return `<td style="text-align:right">${v}</td>`;
                    }
                    return `<td>${cell === null ? '<em>null</em>' : cell}</td>`;
                }).join('') + '</tr>').join('');
            }

            function buildPagination(page, pages) {
                if (pages <= 1) return '';
                const activeFilters = Object.values(colFilters).some(v => v);
                if (activeFilters) return `<div class="table-pagination"><em style="color:#999">Pagination disabled while filtering</em></div>`;
                return `<div class="table-pagination">
                    <button onclick="tablePage(${page - 1})" ${page === 0 ? 'disabled' : ''}>← Prev</button>
                    <span>Page ${page + 1} / ${pages}</span>
                    <button onclick="tablePage(${page + 1})" ${page >= pages - 1 ? 'disabled' : ''}>Next →</button>
                    <span style="color:#999">(${totalRows.toLocaleString()} total rows)</span>
                </div>`;
            }

            const uid = 'tbl_' + Date.now();
            let html = `<div id="${uid}">`;
            html += '<table><thead><tr>';
            columns.forEach(col => { html += `<th>${col}</th>`; });
            html += '</tr><tr class="filter-row">';
            columns.forEach((col, i) => {
                if (col === 'value') { html += '<td></td>'; return; }
                const vals = serverUniques[col] || [];
                const opts = vals.map(v =>
                    `<option value="${String(v).replace(/"/g,'&quot;')}">${v}</option>`
                ).join('');
                html += `<td><select class="col-filter" data-col="${i}"><option value="">— all —</option>${opts}</select></td>`;
            });
            html += '</tr></thead>';
            html += `<tbody>${buildBody(data.rows)}</tbody>`;
            html += '</table>';
            html += `<div id="${uid}_pag">${buildPagination(currentPage, totalPages)}</div>`;
            html += `<div class="row-count" id="${uid}_count">${totalRows.toLocaleString()} rows total</div>`;
            html += '</div>';

            setTimeout(() => {
                const wrapper = document.getElementById(uid);
                if (!wrapper) return;
                wrapper.querySelectorAll('.col-filter').forEach(sel => {
                    sel.addEventListener('click', e => e.stopPropagation());
                    sel.addEventListener('change', e => {
                        const idx = e.target.dataset.col;
                        colFilters[idx] = e.target.value;
                        e.target.classList.toggle('active', !!e.target.value);
                        const hasFilters = Object.values(colFilters).some(v => v);
                        if (hasFilters) {
                            fetchFilteredPage(wrapper, uid, matrixCode, columns, colFilters, buildBody, buildPagination);
                        } else {
                            fetchPage(wrapper, uid, matrixCode, currentPage, buildBody, buildPagination, (p) => { currentPage = p; });
                        }
                    });
                });
                window.tablePage = (page) => {
                    currentPage = page;
                    fetchPage(wrapper, uid, matrixCode, page, buildBody, buildPagination, (p) => { currentPage = p; });
                };
            }, 0);

            return html;
        }

        function fetchPage(wrapper, uid, matrixCode, page, buildBody, buildPagination, setPage) {
            fetch(`/api/dataset/${matrixCode}/data?page=${page}&page_size=50`)
                .then(r => r.json())
                .then(d => {
                    setPage(d.page);
                    wrapper.querySelector('tbody').innerHTML = buildBody(d.rows);
                    document.getElementById(uid + '_pag').innerHTML = buildPagination(d.page, d.total_pages);
                    document.getElementById(uid + '_count').textContent = `${d.total_rows.toLocaleString()} rows total`;
                });
        }

        function fetchFilteredPage(wrapper, uid, matrixCode, columns, colFilters, buildBody, buildPagination) {
            fetch(`/api/dataset/${matrixCode}/data?page=0&page_size=100000`)
                .then(r => r.json())
                .then(d => {
                    const filtered = d.rows.filter(row =>
                        Object.entries(colFilters).every(([idx, val]) => {
                            if (!val) return true;
                            return String(row[idx] ?? '') === val;
                        })
                    );
                    wrapper.querySelector('tbody').innerHTML = buildBody(filtered);
                    document.getElementById(uid + '_pag').innerHTML = buildPagination(0, 0);
                    document.getElementById(uid + '_count').textContent =
                        `${filtered.length} / ${d.total_rows.toLocaleString()} rows`;
                });
        }

        function switchTab(tabName, evt) {
            document.querySelectorAll('.tab-button').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            if (evt) evt.target.classList.add('active');
            document.getElementById(`tab-${tabName}`).classList.add('active');
        }

        function formatBytes(bytes) {
            if (!bytes) return 'N/A';
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
            return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
        }
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    """Main page"""
    return render_template_string(HTML_TEMPLATE)


SORT_OPTIONS = {
    'name':       'matrix_name ASC',
    'updated':    'ultima_actualizare DESC NULLS LAST',
    'records':    'row_count DESC NULLS LAST',
    'dimensions': 'mat_max_dim DESC NULLS LAST',
    'cells':      '(row_count * mat_max_dim) DESC NULLS LAST',
}

@app.route('/api/datasets')
def api_datasets():
    """Get list of all datasets"""
    try:
        sort_key = request.args.get('sort', 'name')

        conn = duckdb.connect(str(DB_FILE), read_only=True)

        if sort_key == 'options':
            result = conn.execute("""
                WITH opt_counts AS (
                    SELECT d.matrix_code,
                           SUM(d.option_count) AS total_options
                    FROM dimensions d
                    WHERE LOWER(d.dim_label) NOT LIKE '%perioade%'
                      AND LOWER(d.dim_label) NOT LIKE '%trimestre%'
                      AND LOWER(d.dim_label) NOT LIKE '%luni%'
                    GROUP BY d.matrix_code
                )
                SELECT m.matrix_code, m.matrix_name, m.row_count, m.mat_max_dim,
                       m.file_size_bytes, m.ultima_actualizare, m.ancestor_codes,
                       m.context_code, COALESCE(o.total_options, 0) AS total_options,
                       m.is_split, m.parent_matrix_code
                FROM matrices m
                LEFT JOIN opt_counts o ON o.matrix_code = m.matrix_code
                WHERE m.row_count > 0
                ORDER BY total_options DESC NULLS LAST
            """).fetchall()
            datasets = []
            for row in result:
                datasets.append({
                    'matrix_code': row[0],
                    'matrix_name': row[1],
                    'row_count': row[2],
                    'mat_max_dim': row[3],
                    'file_size_bytes': row[4],
                    'ultima_actualizare': str(row[5]) if row[5] else None,
                    'ancestor_codes': row[6] or [],
                    'context_code': row[7],
                    'total_options': row[8],
                    'is_split': bool(row[9]),
                    'parent_matrix_code': row[10],
                })
        else:
            order_by = SORT_OPTIONS.get(sort_key, SORT_OPTIONS['name'])
            result = conn.execute(f"""
                SELECT matrix_code, matrix_name, row_count, mat_max_dim,
                       file_size_bytes, ultima_actualizare, ancestor_codes, context_code,
                       is_split, parent_matrix_code
                FROM matrices
                WHERE row_count > 0
                ORDER BY {order_by}
            """).fetchall()
            datasets = []
            for row in result:
                datasets.append({
                    'matrix_code': row[0],
                    'matrix_name': row[1],
                    'row_count': row[2],
                    'mat_max_dim': row[3],
                    'file_size_bytes': row[4],
                    'ultima_actualizare': str(row[5]) if row[5] else None,
                    'ancestor_codes': row[6] or [],
                    'context_code': row[7],
                    'is_split': bool(row[8]),
                    'parent_matrix_code': row[9],
                })

        conn.close()
        return jsonify({'datasets': datasets, 'sort': sort_key})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/contexts')
def api_contexts():
    """Return full context tree (3 levels) with dataset counts."""
    try:
        conn = duckdb.connect(str(DB_FILE), read_only=True)
        rows = conn.execute("""
            SELECT c.context_code, c.context_name, c.level, c.parent_code,
                   COUNT(DISTINCT m.matrix_code) AS cnt
            FROM contexts c
            LEFT JOIN matrices m
                ON list_contains(m.ancestor_codes, c.context_code) AND m.row_count > 0
            GROUP BY c.context_code, c.context_name, c.level, c.parent_code
            ORDER BY c.level, c.context_code
        """).fetchall()
        conn.close()

        # Build node map
        nodes = {}
        for code, name, level, parent_code, cnt in rows:
            nodes[code] = {
                'code': code,
                'name': name,
                'level': level,
                'parent_code': parent_code,
                'count': cnt,
                'children': [],
            }

        # Wire children, collect roots
        roots = []
        for code, node in nodes.items():
            parent = node['parent_code']
            if parent and parent in nodes:
                nodes[parent]['children'].append(node)
            elif node['level'] == 0:
                roots.append(node)

        # Sort children by code
        def sort_children(n):
            n['children'].sort(key=lambda x: x['code'])
            for c in n['children']:
                sort_children(c)
        for r in roots:
            sort_children(r)
        roots.sort(key=lambda x: x['code'])

        return jsonify({'themes': roots})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def _resolve_parquet(matrix_code, parquet_path_hint):
    """Return existing parquet Path, preferring text-label version (parquet/ro/)."""
    for variant in ['parquet', 'parquet-v2']:
        p = Path('data') / variant / 'ro' / f'{matrix_code}.parquet'
        if p.exists():
            return p
    if parquet_path_hint:
        p = Path(parquet_path_hint)
        if p.exists():
            return p
    return PARQUET_DIR / f'{matrix_code}.parquet'


def _parquet_data(parquet_file, page=0, page_size=50):
    """Fetch one page + full unique values from parquet."""
    conn = duckdb.connect()
    offset = page * page_size
    df = conn.execute(
        f"SELECT * FROM '{parquet_file}' ORDER BY 1 LIMIT {page_size} OFFSET {offset}"
    ).fetchdf()
    total_rows = conn.execute(f"SELECT COUNT(*) FROM '{parquet_file}'").fetchone()[0]

    unique_vals = {}
    for col in df.columns:
        if col != 'value':
            vals = conn.execute(
                f'SELECT DISTINCT "{col}" FROM \'{parquet_file}\' ORDER BY 1'
            ).fetchall()
            unique_vals[col] = [str(r[0]) for r in vals if r[0] is not None]

    conn.close()
    return {
        'columns': df.columns.tolist(),
        'rows': [[None if (hasattr(v, '__class__') and v.__class__.__name__ == 'float' and str(v) == 'nan') else v for v in row] for row in df.values.tolist()],
        'total_rows': total_rows,
        'page': page,
        'page_size': page_size,
        'total_pages': math.ceil(total_rows / page_size) if total_rows else 1,
        'unique_vals': unique_vals,
    }


@app.route('/api/dataset/<matrix_code>/data')
def api_dataset_data(matrix_code):
    """Paginated data-only endpoint."""
    try:
        page = int(request.args.get('page', 0))
        page_size = int(request.args.get('page_size', 50))

        conn_meta = duckdb.connect(str(DB_FILE), read_only=True)
        row = conn_meta.execute(
            "SELECT parquet_path FROM matrices WHERE matrix_code = ?", [matrix_code]
        ).fetchone()
        conn_meta.close()

        parquet_file = _resolve_parquet(matrix_code, row[0] if row else None)
        if not parquet_file.exists():
            return jsonify({'error': 'Parquet file not found'}), 404

        return jsonify(_parquet_data(parquet_file, page, page_size))
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/dataset/<matrix_code>')
def api_dataset(matrix_code):
    """Get full details for a specific dataset."""
    try:
        conn_meta = duckdb.connect(str(DB_FILE), read_only=True)

        # Full metadata
        meta_row = conn_meta.execute("""
            SELECT matrix_code, matrix_name, context_code, ancestor_path,
                   periodicitati, definitie, metodologie, ultima_actualizare,
                   observatii, persoane_responsabile,
                   row_count, mat_max_dim, file_size_bytes, parquet_path,
                   mat_active, mat_views, mat_downloads, mat_charge,
                   nom_jud, nom_loc, mat_siruta, ancestor_codes
            FROM matrices WHERE matrix_code = ?
        """, [matrix_code]).fetchone()

        if not meta_row:
            return jsonify({'error': 'Dataset not found'}), 404

        # Coverage
        cov = conn_meta.execute("""
            SELECT time_min_year, time_max_year, time_year_count, time_granularity,
                   geo_county_count, geo_has_national, fill_rate, freshness_years, dim_count
            FROM dataset_coverage WHERE matrix_code = ?
        """, [matrix_code]).fetchone()

        # Value profile
        vp = conn_meta.execute("""
            SELECT val_min, val_max, val_mean, val_median, val_stddev,
                   null_pct, zero_pct, negative_pct, magnitude, distribution_shape, coeff_variation
            FROM dataset_value_profiles WHERE matrix_code = ?
        """, [matrix_code]).fetchone()

        # Split family: siblings (if this is a split) or children (if this is a parent)
        is_split = meta_row[14] if len(meta_row) > 14 else False  # reuse existing field
        parent_code = None
        siblings = []
        # Re-fetch split info specifically
        split_info = conn_meta.execute("""
            SELECT is_split, parent_matrix_code FROM matrices WHERE matrix_code = ?
        """, [matrix_code]).fetchone()
        if split_info:
            is_split_flag, parent_code = split_info
            if is_split_flag and parent_code:
                # This is a split child — get siblings (other children of same parent)
                sib_rows = conn_meta.execute("""
                    SELECT ds.sub_matrix_code, ds.suffix_label, ds.split_pattern, ds.row_count,
                           m.matrix_name
                    FROM dataset_splits ds
                    JOIN matrices m ON m.matrix_code = ds.sub_matrix_code
                    WHERE ds.parent_matrix_code = ?
                    ORDER BY ds.sub_matrix_code
                """, [parent_code]).fetchall()
                siblings = [{
                    'matrix_code': r[0], 'suffix_label': r[1], 'split_pattern': r[2],
                    'row_count': r[3], 'matrix_name': r[4], 'is_current': r[0] == matrix_code,
                } for r in sib_rows]
            else:
                # This is a parent — get children
                child_rows = conn_meta.execute("""
                    SELECT ds.sub_matrix_code, ds.suffix_label, ds.split_pattern, ds.row_count,
                           m.matrix_name
                    FROM dataset_splits ds
                    JOIN matrices m ON m.matrix_code = ds.sub_matrix_code
                    WHERE ds.parent_matrix_code = ?
                    ORDER BY ds.sub_matrix_code
                """, [matrix_code]).fetchall()
                siblings = [{
                    'matrix_code': r[0], 'suffix_label': r[1], 'split_pattern': r[2],
                    'row_count': r[3], 'matrix_name': r[4], 'is_current': False,
                } for r in child_rows]

        # Dimensions with options
        dimensions = conn_meta.execute("""
            SELECT d.dim_label, d.dim_column_name, d.option_count,
                   list(dopt.option_label ORDER BY dopt.option_label) AS options
            FROM dimensions d
            LEFT JOIN dimension_options dopt ON dopt.dimension_id = d.dimension_id
            WHERE d.matrix_code = ?
            GROUP BY d.dim_label, d.dim_column_name, d.option_count, d.dim_code
            ORDER BY d.dim_code
        """, [matrix_code]).fetchall()

        conn_meta.close()

        # First page of data
        parquet_file = _resolve_parquet(matrix_code, meta_row[13])
        page = int(request.args.get('page', 0))
        page_size = int(request.args.get('page_size', 50))
        preview_data = _parquet_data(parquet_file, page, page_size) if parquet_file.exists() else None

        def fmt_date(d): return str(d) if d else None
        def fmt_pct(v): return f'{v:.1%}' if v is not None else None
        def fmt_num(v): return round(v, 4) if v is not None else None

        return jsonify({
            'metadata': {
                'matrix_code': meta_row[0],
                'matrix_name': meta_row[1],
                'context_code': meta_row[2],
                'ancestor_path': meta_row[3],
                'periodicitati': meta_row[4],
                'definitie': meta_row[5],
                'metodologie': meta_row[6],
                'ultima_actualizare': fmt_date(meta_row[7]),
                'observatii': meta_row[8],
                'persoane_responsabile': meta_row[9],
                'row_count': meta_row[10],
                'mat_max_dim': meta_row[11],
                'file_size_bytes': meta_row[12],
                'mat_active': meta_row[14],
                'mat_views': meta_row[15],
                'mat_downloads': meta_row[16],
                'mat_charge': meta_row[17],
                'nom_jud': meta_row[18],
                'nom_loc': meta_row[19],
                'mat_siruta': meta_row[20],
                'ancestor_codes': meta_row[21] or [],
            },
            'coverage': {
                'time_min_year': cov[0], 'time_max_year': cov[1],
                'time_year_count': cov[2], 'time_granularity': cov[3],
                'geo_county_count': cov[4], 'geo_has_national': cov[5],
                'fill_rate': fmt_pct(cov[6]), 'freshness_years': cov[7],
            } if cov else {},
            'value_profile': {
                'val_min': fmt_num(vp[0]), 'val_max': fmt_num(vp[1]),
                'val_mean': fmt_num(vp[2]), 'val_median': fmt_num(vp[3]),
                'val_stddev': fmt_num(vp[4]),
                'null_pct': fmt_pct(vp[5]), 'zero_pct': fmt_pct(vp[6]),
                'negative_pct': fmt_pct(vp[7]),
                'magnitude': vp[8], 'distribution_shape': vp[9],
                'coeff_variation': fmt_num(vp[10]),
            } if vp else {},
            'dimensions': [
                {'dim_label': d[0], 'dim_column_name': d[1], 'option_count': d[2], 'options': d[3] or []}
                for d in dimensions
            ],
            'preview': preview_data,
            'split_family': {
                'is_split': bool(split_info[0]) if split_info else False,
                'parent_matrix_code': parent_code,
                'siblings': siblings,
            } if siblings else None,
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def main():
    """Run the browser"""
    print("=" * 70)
    print("DuckDB + Parquet Browser")
    print("=" * 70)
    print()
    print("Starting server at http://localhost:5050")
    print()
    print("This browser demonstrates:")
    print("  - Listing datasets from DuckDB metadata")
    print("  - Viewing dataset details (dimensions, stats)")
    print("  - Previewing Parquet data")
    print()
    print("Press Ctrl+C to stop")
    print()

    app.run(host='0.0.0.0', port=5050, debug=True, use_reloader=False)


if __name__ == '__main__':
    main()
