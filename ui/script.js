document.addEventListener('DOMContentLoaded', () => {
    // --- CONFIG & STATE ---
    const DATA_PATH = './data';
    let allDatasets = [];
    let contextTree = {};
    let contextMap = {};
    let currentFilteredDatasets = [];
    let selectedCategoryCode = null;

    // --- DOM ELEMENTS ---
    const totalCountEl = document.getElementById('total-count');
    const filteredCountEl = document.getElementById('filtered-count');
    const categoryCountEl = document.getElementById('category-count');
    const treeRootEl = document.getElementById('tree-root');
    const searchInputEl = document.getElementById('search');
    const breadcrumbEl = document.getElementById('breadcrumb');
    const datasetsContentEl = document.getElementById('datasets-content');
    const modalEl = document.getElementById('modal');
    const modalCloseEl = document.getElementById('modal-close');
    const modalTitleEl = document.getElementById('modal-title');
    const modalBodyEl = document.getElementById('modal-body');

    // --- INITIALIZATION ---
    async function init() {
        try {
            await loadAllData();
            buildTreeNavigation();
            applyFilters();
            setupEventListeners();
            updateStats();
        } catch (error) {
            console.error("Initialization failed:", error);
            datasetsContentEl.innerHTML = `<div class="no-results">Failed to load application data. Please check the console.</div>`;
        }
    }

    // --- DATA LOADING & PARSING ---
    async function loadAllData() {
        const matricesPromise = fetch(`${DATA_PATH}/indexes/matrices.csv`).then(res => res.text());
        const contextPromise = fetch(`${DATA_PATH}/indexes/context.json`).then(res => res.json());

        const [matricesCSV, contextData] = await Promise.all([matricesPromise, contextPromise]);

        // Process context data first to build the map
        buildContextMap(contextData);

        // Process matrices and fetch metadata for each
        const matrixLines = parseCSV(matricesCSV);
        const datasetPromises = matrixLines.map(async (row) => {
            const filename = row.filename?.trim();
            if (!filename) return null;

            try {
                // Check both meta and CSV exist locally (avoid 404s and missing dims)
                const [metaRes, csvHead] = await Promise.all([
                    fetch(`${DATA_PATH}/metas/${filename}.json`),
                    fetch(`${DATA_PATH}/datasets/${filename}.csv`, { method: 'HEAD' })
                ]);

                if (!metaRes.ok || !csvHead.ok) {
                    return null;
                }

                const meta = await metaRes.json();

                return {
                    id: filename,
                    code: filename,
                    contextCode: row['context-code'],
                    title: row.matrixName,
                    lastUpdate: row.ultimaActualizare,
                    meta,
                    description: meta.definitie,
                    dimensions: (meta.dimensionsMap || []).map(d => d.label).filter(Boolean),
                    periodicity: meta.periodicitati?.[0] || 'N/A',
                };
            } catch (e) {
                return null;
            }
        });

        allDatasets = (await Promise.all(datasetPromises)).filter(Boolean);
        associateDatasetsWithContext();
    }

    function parseCSV(csvText) {
        const lines = csvText.trim().split('\n');
        // Remove potential BOM from first header cell
        const headers = lines[0].replace(/^\uFEFF/, '').split(',').map(h => h.trim());
        return lines.slice(1).map(line => {
            const values = line.split(/,(?=(?:(?:[^"]*"){2})*[^"]*$)/); // Handle commas inside quotes
            const obj = {};
            headers.forEach((header, i) => {
                obj[header] = values[i]?.replace(/"/g, '').trim();
            });
            return obj;
        });
    }

    function buildContextMap(contextData) {
        // First, create a map of all nodes by their code for easy lookup.
        // And extract the relevant properties.
        contextData.forEach(item => {
            if (item.context) { // Defensive check
                contextMap[item.context.code] = {
                    code: item.context.code,
                    name: item.context.name,
                    parentCode: item.parentCode,
                    children: [],
                    datasets: []
                };
            }
        });

        // Now, build the tree structure.
        const roots = [];
        Object.values(contextMap).forEach(node => {
            if (node.parentCode === '0') {
                roots.push(node);
            } else {
                const parent = contextMap[node.parentCode];
                if (parent) {
                    parent.children.push(node);
                }
            }
        });

        contextTree = roots; // contextTree is now an array of root nodes.
        categoryCountEl.textContent = Object.keys(contextMap).length;
    }

    function associateDatasetsWithContext() {
        allDatasets.forEach(dataset => {
            const contextCode = dataset.contextCode;
            if (contextMap[contextCode]) {
                let current = contextMap[contextCode];
                while (current) {
                    if (!current.datasets.some(d => d.id === dataset.id)) {
                         current.datasets.push(dataset);
                    }
                    current = contextMap[current.parentCode];
                }
            }
        });
    }


    // --- UI RENDERING ---
    function buildTreeNavigation() {
        treeRootEl.innerHTML = ''; // Clear loading
        
        const allNode = createAllCategoriesNode();
        treeRootEl.appendChild(allNode);

        const createNodeRecursive = (nodeData) => {
            const nodeEl = createTreeNode(nodeData);
            const childrenContainer = nodeEl.querySelector('.tree-children');
            if (nodeData.children && nodeData.children.length > 0) {
                nodeData.children
                    .sort((a, b) => a.name.localeCompare(b.name))
                    .forEach(child => childrenContainer.appendChild(createNodeRecursive(child)));
            }
            return nodeEl;
        };

        contextTree
            .sort((a, b) => a.name.localeCompare(b.name))
            .forEach(node => treeRootEl.appendChild(createNodeRecursive(node)));
    }

    function createAllCategoriesNode() {
        const nodeEl = document.createElement('div');
        nodeEl.className = 'tree-node';
        const content = document.createElement('div');
        content.className = 'tree-node-content selected';
        content.innerHTML = `
            <span class="tree-expand no-children"></span>
            <span class="tree-icon">🗂️</span>
            <span class="tree-label">All Categories</span>
            <span class="tree-count">${allDatasets.length}</span>
        `;
        content.addEventListener('click', () => {
            document.querySelectorAll('.tree-node-content').forEach(el => el.classList.remove('selected'));
            content.classList.add('selected');
            selectedCategoryCode = null;
            applyFilters();
            updateBreadcrumb(null);
        });
        nodeEl.appendChild(content);
        return nodeEl;
    }

    function createTreeNode(node) {
        const nodeEl = document.createElement('div');
        nodeEl.className = 'tree-node';
        
        const content = document.createElement('div');
        content.className = 'tree-node-content';
        const totalDatasetsInNode = node.datasets.length;
        if (totalDatasetsInNode > 0) content.classList.add('has-datasets');
        
        const hasChildren = node.children && node.children.length > 0;
        
        content.innerHTML = `
            <span class="tree-expand ${hasChildren ? '' : 'no-children'}">${hasChildren ? '▶' : ''}</span>
            <span class="tree-icon">${hasChildren ? '📂' : '📄'}</span>
            <span class="tree-label">${node.name.replace(/<[^>]*>/g, '').trim()}</span>
            ${totalDatasetsInNode > 0 ? `<span class="tree-count">${totalDatasetsInNode}</span>` : ''}
        `;
        
        const childrenContainer = document.createElement('div');
        childrenContainer.className = 'tree-children';
        
        content.addEventListener('click', (e) => {
            e.stopPropagation();
            document.querySelectorAll('.tree-node-content').forEach(el => el.classList.remove('selected'));
            content.classList.add('selected');
            selectedCategoryCode = node.code;
            applyFilters();
            updateBreadcrumb(node);
        });
        
        if (hasChildren) {
            const expander = content.querySelector('.tree-expand');
            expander.addEventListener('click', (e) => {
                e.stopPropagation();
                childrenContainer.classList.toggle('expanded');
                expander.classList.toggle('expanded');
            });
        }

        nodeEl.appendChild(content);
        nodeEl.appendChild(childrenContainer);
        return nodeEl;
    }

    function renderDatasets(datasets) {
        if (datasets.length === 0) {
            datasetsContentEl.innerHTML = `<div class="no-results">No datasets match your criteria.</div>`;
            return;
        }
        
        const gridHTML = datasets.map(dataset => `
            <div class="dataset-card" data-id="${dataset.id}">
                <div class="dataset-header">
                    <div class="dataset-code">${dataset.code}</div>
                    <div class="dataset-title">${dataset.title || 'Untitled'}</div>
                </div>
                <div class="dataset-body">
                     <div class="dataset-meta">
                        <span class="meta-tag">📅 ${dataset.lastUpdate || 'N/A'}</span>
                        <span class="meta-tag">🔄 ${dataset.periodicity || 'N/A'}</span>
                        <span class="meta-tag">📏 ${dataset.dimensions.length} Dimensions</span>
                    </div>
                    <div class="dataset-description">${(dataset.description || 'No description available.').substring(0, 120)}...</div>
                </div>
            </div>
        `).join('');
        datasetsContentEl.innerHTML = `<div class="datasets-grid">${gridHTML}</div>`;

        document.querySelectorAll('.dataset-card').forEach(card => {
            card.addEventListener('click', () => openModal(card.dataset.id));
        });
    }

    function updateBreadcrumb(category) {
        if (!category) {
            breadcrumbEl.style.display = 'none';
            return;
        }
        breadcrumbEl.style.display = 'block';
        
        let path = [];
        let current = category;
        while (current) {
            path.unshift(current);
            current = contextMap[current.parentCode];
        }
        
        breadcrumbEl.innerHTML = path.map(node => 
            `<span class="breadcrumb-item">${node.name.replace(/<[^>]*>/g, '').trim()}</span>`
        ).join('<span class="breadcrumb-separator">›</span>');
    }

    function updateStats() {
        totalCountEl.textContent = allDatasets.length;
        filteredCountEl.textContent = currentFilteredDatasets.length;
    }

    // --- EVENT HANDLING & LOGIC ---
    function setupEventListeners() {
        searchInputEl.addEventListener('input', applyFilters);
        modalCloseEl.addEventListener('click', closeModal);
        modalEl.addEventListener('click', (e) => {
            if (e.target === modalEl) closeModal();
        });
    }
    
    function applyFilters() {
        const query = searchInputEl.value.toLowerCase();
        
        let baseDatasets;
        if (selectedCategoryCode && contextMap[selectedCategoryCode]) {
            baseDatasets = contextMap[selectedCategoryCode].datasets;
        } else {
            baseDatasets = allDatasets;
        }
        
        currentFilteredDatasets = baseDatasets.filter(dataset => {
            const title = dataset.title || '';
            const desc = dataset.description || '';
            const code = dataset.code || '';
            return code.toLowerCase().includes(query) ||
                   title.toLowerCase().includes(query) ||
                   desc.toLowerCase().includes(query);
        });
        
        renderDatasets(currentFilteredDatasets);
        updateStats();
    }

    function openModal(datasetId) {
        const dataset = allDatasets.find(d => d.id === datasetId);
        if (!dataset) return;
        
        modalTitleEl.textContent = `${dataset.code} - ${dataset.title}`;
        
        const meta = dataset.meta;
        let path = 'N/A';
        if (meta?.ancestors) {
            path = meta.ancestors.map(a => a.name.replace(/<[^>]*>/g, '').trim()).join(' > ');
        }

        modalBodyEl.innerHTML = `
            <div class="metadata-section">
                <h4>Full Description</h4>
                <div class="metadata-content">${meta?.definitie || 'Not available.'}</div>
            </div>
            <div class="metadata-section">
                <h4>Category Path</h4>
                <div class="metadata-content">${path}</div>
            </div>
            <div class="metadata-section">
                <h4>Details</h4>
                <div class="metadata-content">
                    <strong>Periodicity:</strong> ${meta?.periodicitati?.join(', ') || 'N/A'}<br>
                    <strong>Last Updated:</strong> ${dataset.lastUpdate || 'N/A'}<br>
                    <strong>Data Sources:</strong> ${meta?.surseDeDate?.map(s => s.nume).join(', ') || 'N/A'}
                </div>
            </div>
            <div class="metadata-section">
                <h4>Dimensions</h4>
                <div class="column-info">
                    ${(meta?.dimensionsMap || []).map(dim => `
                        <div class="column-item">
                            <span class="column-name">${dim.label}</span>
                        </div>
                    `).join('') || 'No dimensions specified.'}
                </div>
            </div>
            ${meta?.observatii ? `
            <div class="metadata-section">
                <h4>Observations</h4>
                <div class="metadata-content">${meta.observatii}</div>
            </div>` : ''}
            <div class="metadata-section">
                <h4>Data Preview (First 20 Rows)</h4>
                <div id="data-preview-container">
                    <div class="loading">
                        <div class="loading-spinner"></div>
                        <div>Loading preview...</div>
                    </div>
                </div>
            </div>
            <div class="metadata-section">
                <h4>Download</h4>
                <div class="metadata-content">
                    <a href="${DATA_PATH}/datasets/${dataset.id}.csv" download>Download ${dataset.id}.csv</a>
                </div>
            </div>
        `;
        modalEl.style.display = 'flex';
        loadDataPreview(datasetId);
    }
    
    function closeModal() {
        modalEl.style.display = 'none';
    }

    async function loadDataPreview(datasetId) {
        const previewContainer = document.getElementById('data-preview-container');
        try {
            const res = await fetch(`${DATA_PATH}/datasets/${datasetId}.csv`);
            if (!res.ok) {
                throw new Error(`CSV file not found for ${datasetId}`);
            }
            const csvText = await res.text();
            const lines = parseCSV(csvText);
            
            const previewData = lines.slice(0, 20);
            
            if (previewData.length === 0) {
                previewContainer.innerHTML = '<div class="no-results">No data to preview.</div>';
                return;
            }
    
            const headers = Object.keys(previewData[0]);
            
            let tableHTML = '<div class="data-preview-table-wrapper"><table>';
            tableHTML += '<thead><tr>';
            headers.forEach(h => { tableHTML += `<th>${h}</th>`; });
            tableHTML += '</tr></thead>';
            
            tableHTML += '<tbody>';
            previewData.forEach(row => {
                tableHTML += '<tr>';
                headers.forEach(h => {
                    tableHTML += `<td>${row[h] || ''}</td>`;
                });
                tableHTML += '</tr>';
            });
            tableHTML += '</tbody></table></div>';
            
            previewContainer.innerHTML = tableHTML;
    
        } catch (error) {
            console.error("Failed to load data preview:", error);
            previewContainer.innerHTML = `<div class="no-results">Could not load data preview.</div>`;
        }
    }

    // --- START ---
    init();
});
