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
    </style>
</head>
<body>
    <div id="sidebar">
        <h1>Datasets</h1>
        <input type="text" class="search-box" id="searchBox" placeholder="Search datasets..." />
        <ul class="dataset-list" id="datasetList">
            <li class="loading">Loading...</li>
        </ul>
    </div>

    <div id="main">
        <div id="content">
            <h1>Welcome to DuckDB + Parquet Browser</h1>
            <p>Select a dataset from the sidebar to view details.</p>

            <div style="margin-top: 40px;">
                <h2>About This Browser</h2>
                <p style="margin: 10px 0;">This is a simple browser that demonstrates how DuckDB and Parquet work together:</p>
                <ul style="margin-left: 20px; line-height: 1.8;">
                    <li><strong>Metadata</strong> (contexts, matrices, dimensions) is stored in DuckDB</li>
                    <li><strong>Data</strong> (statistical values) is stored in Parquet files</li>
                    <li><strong>Queries</strong> combine both sources for powerful analytics</li>
                </ul>
            </div>
        </div>
    </div>

    <script>
        let currentMatrix = null;
        let allDatasets = [];
        let filteredDatasets = [];

        // Load dataset list
        fetch('/api/datasets')
            .then(r => r.json())
            .then(data => {
                allDatasets = data.datasets;
                filteredDatasets = allDatasets;
                renderDatasets(filteredDatasets);
            });

        // Search functionality
        document.getElementById('searchBox').addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase();
            filteredDatasets = allDatasets.filter(d =>
                d.matrix_code.toLowerCase().includes(query) ||
                d.matrix_name.toLowerCase().includes(query)
            );
            renderDatasets(filteredDatasets);
        });

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
                loadDataset(filteredDatasets[newIdx].matrix_code);
                // Scroll sidebar item into view
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

            list.innerHTML = datasets.map(d => `
                <li class="dataset-item ${d.matrix_code === currentMatrix ? 'active' : ''}"
                    onclick="loadDataset('${d.matrix_code}')">
                    <div class="dataset-code">${d.matrix_code}</div>
                    <div class="dataset-name">${d.matrix_name}</div>
                    <div class="dataset-stats">${(d.row_count || 0).toLocaleString()} rows • ${d.mat_max_dim} dims</div>
                </li>
            `).join('');
        }

        function renderNavButtons() {
            const idx = filteredDatasets.findIndex(d => d.matrix_code === currentMatrix);
            const total = filteredDatasets.length;
            const hasPrev = idx > 0;
            const hasNext = idx < total - 1;
            return `
                <div class="nav-buttons">
                    <button onclick="navigateDataset(-1)" ${!hasPrev ? 'disabled' : ''} title="Previous (← ↑)">&#8592; Prev</button>
                    <span class="nav-position">${idx + 1} / ${total}</span>
                    <button onclick="navigateDataset(1)" ${!hasNext ? 'disabled' : ''} title="Next (→ ↓)">Next &#8594;</button>
                </div>
            `;
        }

        function loadDataset(matrixCode) {
            currentMatrix = matrixCode;
            renderDatasets(allDatasets);

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

        function renderDataset(data) {
            const d = data.metadata;
            const dims = data.dimensions;
            const preview = data.preview;

            let html = `
                ${renderNavButtons()}
                <h1>${d.matrix_code}</h1>
                <p>${d.matrix_name}</p>

                <div style="margin: 20px 0;">
                    <div class="stat-box">
                        <div class="stat-label">Rows</div>
                        <div class="stat-value">${(d.row_count || 0).toLocaleString()}</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">Dimensions</div>
                        <div class="stat-value">${d.mat_max_dim}</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">File Size</div>
                        <div class="stat-value">${formatBytes(d.file_size_bytes)}</div>
                    </div>
                </div>

                <div class="tab-buttons">
                    <button class="tab-button" onclick="switchTab('info')">Info</button>
                    <button class="tab-button" onclick="switchTab('dimensions')">Dimensions</button>
                    <button class="tab-button active" onclick="switchTab('data')">Data Preview</button>
                </div>

                <div class="tab-content " id="tab-info">
                    <h2>Dataset Information</h2>
                    <div class="info-grid">
                        <div class="info-label">Matrix Code:</div>
                        <div>${d.matrix_code}</div>

                        <div class="info-label">Context:</div>
                        <div>${d.context_code || 'N/A'}</div>

                        <div class="info-label">Parquet Path:</div>
                        <div><code>${d.parquet_path || 'N/A'}</code></div>
                    </div>
                </div>

                <div class="tab-content" id="tab-dimensions">
                    <h2>Dimensions (${dims.length})</h2>
                    <ul class="dimension-list">
                        ${dims.map(dim => `
                            <li class="dimension-item">
                                <span class="dimension-label">${dim.dim_label}</span>
                                <span class="dimension-count">(${dim.option_count} options)</span>
                                <br><code style="font-size: 11px; color: #666;">${dim.dim_column_name}</code>
                            </li>
                        `).join('')}
                    </ul>
                </div>

                <div class="tab-content active" id="tab-data">
                    <h2>Data Preview (first 100 rows)</h2>
                    ${renderDataTable(preview)}
                </div>
            `;

            document.getElementById('content').innerHTML = html;
        }

        function renderDataTable(data) {
            if (!data || !data.columns || data.columns.length === 0) {
                return '<p>No data available</p>';
            }

            let html = '<table><thead><tr>';
            data.columns.forEach(col => {
                html += `<th>${col}</th>`;
            });
            html += '</tr></thead><tbody>';

            data.rows.forEach(row => {
                html += '<tr>';
                row.forEach(cell => {
                    const value = cell === null ? '<em>null</em>' :
                                  typeof cell === 'number' ? cell.toLocaleString() : cell;
                    html += `<td>${value}</td>`;
                });
                html += '</tr>';
            });

            html += '</tbody></table>';
            return html;
        }

        function switchTab(tabName) {
            document.querySelectorAll('.tab-button').forEach(btn => {
                btn.classList.remove('active');
            });
            document.querySelectorAll('.tab-content').forEach(content => {
                content.classList.remove('active');
            });

            event.target.classList.add('active');
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


@app.route('/api/datasets')
def api_datasets():
    """Get list of all datasets"""
    try:
        conn = duckdb.connect(str(DB_FILE), read_only=True)
        result = conn.execute("""
            SELECT
                matrix_code,
                matrix_name,
                row_count,
                mat_max_dim,
                file_size_bytes
            FROM matrices
            WHERE row_count > 0
            ORDER BY matrix_name
        """).fetchall()
        conn.close()

        datasets = []
        for row in result:
            datasets.append({
                'matrix_code': row[0],
                'matrix_name': row[1],
                'row_count': row[2],
                'mat_max_dim': row[3],
                'file_size_bytes': row[4]
            })

        return jsonify({'datasets': datasets})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/dataset/<matrix_code>')
def api_dataset(matrix_code):
    """Get details for a specific dataset"""
    try:
        conn_meta = duckdb.connect(str(DB_FILE), read_only=True)

        # Get metadata
        metadata = conn_meta.execute("""
            SELECT
                matrix_code,
                matrix_name,
                context_code,
                row_count,
                mat_max_dim,
                file_size_bytes,
                parquet_path
            FROM matrices
            WHERE matrix_code = ?
        """, [matrix_code]).fetchone()

        if not metadata:
            return jsonify({'error': 'Dataset not found'}), 404

        # Get dimensions
        dimensions = conn_meta.execute("""
            SELECT
                dim_label,
                dim_column_name,
                option_count
            FROM dimensions
            WHERE matrix_code = ?
            ORDER BY dim_code
        """, [matrix_code]).fetchall()

        conn_meta.close()

        # Get data preview from Parquet
        parquet_file = PARQUET_DIR / f"{matrix_code}.parquet"
        preview_data = None

        if parquet_file.exists():
            conn_data = duckdb.connect()
            result = conn_data.execute(f"""
                SELECT * FROM '{parquet_file}' LIMIT 100
            """).fetchdf()

            preview_data = {
                'columns': result.columns.tolist(),
                'rows': result.values.tolist()
            }
            conn_data.close()

        return jsonify({
            'metadata': {
                'matrix_code': metadata[0],
                'matrix_name': metadata[1],
                'context_code': metadata[2],
                'row_count': metadata[3],
                'mat_max_dim': metadata[4],
                'file_size_bytes': metadata[5],
                'parquet_path': metadata[6]
            },
            'dimensions': [
                {
                    'dim_label': d[0],
                    'dim_column_name': d[1],
                    'option_count': d[2]
                }
                for d in dimensions
            ],
            'preview': preview_data
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
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
