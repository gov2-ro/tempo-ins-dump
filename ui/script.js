document.addEventListener('DOMContentLoaded', () => {
    // --- CONFIG & STATE ---
    const DATA_PATH = './data';
    let allDatasets = [];
    let contextTree = {};
    let contextMap = {};
    let currentFilteredDatasets = [];
    let selectedCategoryCode = null;
    let selectedThemeCode = null; // root context code filter
    const selectedKeywords = new Set();

    // --- DOM ELEMENTS ---
    const totalCountEl = document.getElementById('total-count');
    const filteredCountEl = document.getElementById('filtered-count');
    const categoryCountEl = document.getElementById('category-count');
    const treeRootEl = document.getElementById('tree-root');
    const searchInputEl = document.getElementById('search');
    const breadcrumbEl = document.getElementById('breadcrumb');
    const datasetsContentEl = document.getElementById('datasets-content');
    const themesBarEl = document.getElementById('themes-bar');
    const keywordsBarEl = document.getElementById('keywords-bar');
    const modalEl = document.getElementById('modal');
    const modalCloseEl = document.getElementById('modal-close');
    const modalTitleEl = document.getElementById('modal-title');
    const modalBodyEl = document.getElementById('modal-body');

    // --- INITIALIZATION ---
    async function init() {
        try {
            await loadAllData();
            buildTreeNavigation();
            buildThemesBar();
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
                const [metaRes, csvHead, detectedRes] = await Promise.all([
                    fetch(`${DATA_PATH}/metas/${filename}.json`),
                    fetch(`${DATA_PATH}/datasets/${filename}.csv`, { method: 'HEAD' }),
                    fetch(`${DATA_PATH}/meta-detected/${filename}.json`).catch(() => ({ ok: false }))
                ]);

                if (!metaRes.ok || !csvHead.ok) {
                    return null;
                }

                const meta = await metaRes.json();
                let detected = null;
                if (detectedRes && detectedRes.ok) {
                    try { detected = await detectedRes.json(); } catch {}
                }

                const dataset = {
                    id: filename,
                    code: filename,
                    contextCode: row['context-code'],
                    title: row.matrixName,
                    lastUpdate: row.ultimaActualizare,
                    meta,
                    detected,
                    description: meta.definitie,
                    dimensions: (meta.dimensionsMap || []).map(d => d.label).filter(Boolean),
                    periodicity: meta.periodicitati?.[0] || 'N/A',
                    keywords: [],
                    themeCode: null,
                    um: detected?.file_checks?.um_label || detected?.file_checks?.um_value || null,
                    umClass: detected?.file_checks?.um_classification || null,
                };

                // derive keywords from metadata
                dataset.keywords = deriveKeywords(dataset);
                return dataset;
            } catch (e) {
                return null;
            }
        });

        allDatasets = (await Promise.all(datasetPromises)).filter(Boolean);
        associateDatasetsWithContext();
        // After context is built, compute theme root per dataset
        allDatasets.forEach(ds => {
            ds.themeCode = getRootCode(ds.contextCode) || null;
        });
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
    function buildThemesBar(themeCounts) {
        if (!Array.isArray(contextTree) || contextTree.length === 0) {
            themesBarEl.innerHTML = '';
            return;
        }

        // compute counts per root if not provided
        const counts = themeCounts || computeThemeCounts(allDatasets);

        const chips = [];
        // All chip
        const allActive = selectedThemeCode === null;
        const allCount = Object.values(counts).reduce((a, b) => a + b, 0);
        chips.push(`<span class="theme-chip ${allActive ? 'active' : ''}" data-theme="__ALL__">All (${allCount})</span>`);

        // One chip per root with non-zero count
        contextTree
            .slice()
            .sort((a, b) => a.name.localeCompare(b.name))
            .forEach(root => {
                const cnt = counts[root.code] || 0;
                if (cnt > 0) {
                    const active = selectedThemeCode === root.code;
                    chips.push(`<span class="theme-chip ${active ? 'active' : ''}" data-theme="${root.code}">${escapeHTML(root.name)} (${cnt})</span>`);
                }
            });

        themesBarEl.innerHTML = chips.join('');
        themesBarEl.querySelectorAll('.theme-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                const val = chip.getAttribute('data-theme');
                selectedThemeCode = (val === '__ALL__') ? null : val;
                applyFilters();
            });
        });
    }

    function renderKeywordsBar(datasets) {
        const freq = new Map();
        datasets.forEach(ds => {
            (ds.keywords || []).forEach(k => {
                // don't count selected keywords here to keep them visible but deprioritized
                freq.set(k, (freq.get(k) || 0) + 1);
            });
        });

        // Remove common stopwords and very short tokens
        const STOP = getStopwords();
        const entries = [...freq.entries()]
            .filter(([k, v]) => !STOP.has(k) && k.length > 2)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 30);

        if (entries.length === 0) {
            keywordsBarEl.style.display = 'none';
            keywordsBarEl.innerHTML = '';
            return;
        }

        keywordsBarEl.style.display = 'flex';
        const html = entries.map(([k]) => {
            const active = selectedKeywords.has(k) ? 'active' : '';
            return `<span class="keyword-chip ${active}" data-key="${k}">${escapeHTML(k)}</span>`;
        }).join('');
        keywordsBarEl.innerHTML = html;
        keywordsBarEl.querySelectorAll('.keyword-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                const k = chip.getAttribute('data-key');
                if (selectedKeywords.has(k)) selectedKeywords.delete(k); else selectedKeywords.add(k);
                applyFilters();
            });
        });
    }

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
            ${dataset.um ? `<span class="meta-tag">🧪 UM: ${escapeHTML(dataset.um)}</span>` : ''}
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
        // 1) Start from category selection if any
        let baseDatasets;
        if (selectedCategoryCode && contextMap[selectedCategoryCode]) {
            baseDatasets = contextMap[selectedCategoryCode].datasets;
        } else {
            baseDatasets = allDatasets;
        }
        // 2) Text search
        const textFiltered = baseDatasets.filter(dataset => {
            const title = dataset.title || '';
            const desc = dataset.description || '';
            const code = dataset.code || '';
            return code.toLowerCase().includes(query) ||
                   title.toLowerCase().includes(query) ||
                   desc.toLowerCase().includes(query);
        });
        // Update themes bar counts according to textFiltered + category filter
        const themeCounts = computeThemeCounts(textFiltered);
        // If current selectedThemeCode is no longer present, reset to All
        if (selectedThemeCode && !themeCounts[selectedThemeCode]) {
            selectedThemeCode = null;
        }
        buildThemesBar(themeCounts);

        // 3) Theme filter
        const themeFiltered = selectedThemeCode
            ? textFiltered.filter(d => d.themeCode === selectedThemeCode)
            : textFiltered;

        // 4) Keyword filter (AND across selected keywords)
        let keywordFiltered = themeFiltered;
        if (selectedKeywords.size > 0) {
            keywordFiltered = themeFiltered.filter(d => {
                const set = new Set(d.keywords || []);
                for (const k of selectedKeywords) {
                    if (!set.has(k)) return false;
                }
                return true;
            });
        }

        // Update keyword chips based on themeFiltered (not post-keyword filtering)
        renderKeywordsBar(themeFiltered);

        currentFilteredDatasets = keywordFiltered;
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
            ${dataset.detected ? `
            <div class="metadata-section">
                <h4>Detected Schema</h4>
                <div class="metadata-content">
                    ${dataset.um ? `<div><strong>Unit of Measure:</strong> ${escapeHTML(dataset.um)}${dataset.umClass ? ` <em>(${escapeHTML(dataset.umClass)})</em>` : ''}</div>` : ''}
                </div>
                <div class="column-info">
                    ${(dataset.detected.columns || []).map(col => `
                        <div class="column-item">
                            <span class="column-name">${escapeHTML(col.column_name)}</span>
                            <span>
                                ${col.guessed_type ? `<em>${escapeHTML(col.guessed_type)}</em>` : ''}
                                ${col.semantic_categories ? ` · ${escapeHTML(col.semantic_categories)}` : ''}
                                ${col.functional_types ? ` · ${escapeHTML(col.functional_types)}` : ''}
                            </span>
                        </div>
                    `).join('')}
                </div>
            </div>` : ''}
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

    // --- Helpers ---
    function getRootCode(code) {
        let current = contextMap[code];
        let last = current;
        while (current && current.parentCode && current.parentCode !== '0') {
            last = contextMap[current.parentCode] || last;
            current = contextMap[current.parentCode];
        }
        return (last && last.code) || code || null;
    }

    function escapeHTML(str) {
        return String(str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function deriveKeywords(dataset) {
        const meta = dataset.meta || {};
        const detected = dataset.detected || {};
        const words = [];
        // Title and matrix name
        if (dataset.title) words.push(...splitWords(dataset.title));
        if (meta.matrixName) words.push(...splitWords(meta.matrixName));
        // Definition (first 200 chars)
        if (meta.definitie) words.push(...splitWords(meta.definitie.slice(0, 200)));
        // Periodicities
        if (Array.isArray(meta.periodicitati)) words.push(...meta.periodicitati);
        // Dimensions labels
        if (Array.isArray(meta.dimensionsMap)) {
            meta.dimensionsMap.forEach(d => { if (d.label) words.push(...splitWords(d.label)); });
        }
        // Data sources names
        if (Array.isArray(meta.surseDeDate)) {
            meta.surseDeDate.forEach(s => { if (s?.nume) words.push(...splitWords(s.nume)); });
        }
        // Detected schema: UM label/value/classification
        const um = detected?.file_checks?.um_label || detected?.file_checks?.um_value || '';
        if (um) words.push(...splitWords(um));
        if (detected?.file_checks?.um_classification) words.push(...splitWords(detected.file_checks.um_classification));
        // Detected columns: names, types, semantic categories, functional types
        if (Array.isArray(detected?.columns)) {
            detected.columns.forEach(c => {
                if (c.column_name) words.push(...splitWords(c.column_name));
                if (c.guessed_type) words.push(...splitWords(c.guessed_type));
                if (c.semantic_categories) words.push(...splitWords(c.semantic_categories));
                if (c.functional_types) words.push(...splitWords(c.functional_types));
            });
        }
        // Unique, lowercase
        const STOP = getStopwords();
        const uniq = new Set();
        words.forEach(w => {
            const k = w.toLowerCase();
            if (k.length > 2 && !STOP.has(k)) uniq.add(k);
        });
        return [...uniq];
    }

    function splitWords(text) {
        return String(text || '')
            .replace(/[()\[\],.;:!?/\\\-]+/g, ' ')
            .split(/\s+/)
            .filter(Boolean);
    }

    function computeThemeCounts(datasets) {
        const counts = {};
        datasets.forEach(d => {
            const root = d.themeCode || getRootCode(d.contextCode);
            if (!root) return;
            counts[root] = (counts[root] || 0) + 1;
        });
        return counts;
    }

    function getStopwords() {
        // Light set combining English and Romanian common stopwords
        const arr = [
            'the','and','or','for','of','in','to','a','an','on','by','with','from','as','at','is','are','be','per','la','si','sau','din','ale','al','un','o','cu','de','pe','in','a','anul','ani','rata','numar','numărul','nr','total','medie'
        ];
        return new Set(arr);
    }

    // --- START ---
    init();
});
