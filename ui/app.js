 let allDimensions = [];
        let allDatasets = [];
        let selectedDimensions = new Set();
        let datasetMetadataLookup = {};

        // Load and parse CSV files
        async function loadData() {
            try {
                // Load dataset metadata index
                try {
                    const metadataResponse = await fetch('data/dataset-metadata.json');
                    if (metadataResponse.ok) {
                        const metadataIndex = await metadataResponse.json();
                        // Create lookup by matrixCode
                        metadataIndex.metadata.forEach(item => {
                            datasetMetadataLookup[item.matrixCode] = item;
                        });
                        console.log('Loaded metadata for', Object.keys(datasetMetadataLookup).length, 'datasets');
                    }
                } catch (error) {
                    console.warn('Could not load dataset metadata:', error);
                }

                // Load datasets
                const datasetsResponse = await fetch('../data/3-db/ro/csv/datasets.csv');
                const datasetsText = await datasetsResponse.text();
                allDatasets = parseCSV(datasetsText, ['filename', 'matrixName', 'dim_labels']);

                // Parse dim_labels JSON strings and attach metadata
                allDatasets.forEach(ds => {
                    try {
                        const parsed = JSON.parse(ds.dim_labels || '[]');
                        ds.dim_labels_array = Array.isArray(parsed) ? parsed : [];
                    } catch (e) {
                        console.warn('Failed to parse dim_labels for', ds.filename, ':', ds.dim_labels, e);
                        ds.dim_labels_array = [];
                    }

                    // Attach file metadata
                    ds.fileMetadata = datasetMetadataLookup[ds.filename];
                });

                // Build dimension list from actual dataset dimensions with usage counts
                const dimCounts = new Map();
                allDatasets.forEach(ds => {
                    if (Array.isArray(ds.dim_labels_array)) {
                        ds.dim_labels_array.forEach(dim => {
                            dimCounts.set(dim, (dimCounts.get(dim) || 0) + 1);
                        });
                    }
                });
                // Sort by usage count (descending), then alphabetically
                allDimensions = Array.from(dimCounts.entries())
                    .sort((a, b) => {
                        if (b[1] !== a[1]) return b[1] - a[1]; // Count descending
                        return a[0].localeCompare(b[0]); // Name ascending
                    })
                    .map(entry => ({name: entry[0], count: entry[1]}));

                console.log('Loaded', allDatasets.length, 'datasets');
                console.log('Sample dataset:', allDatasets[0]);
                console.log('Sample dataset dim_labels field:', allDatasets[0].dim_labels);
                console.log('Sample dataset dim_labels_array:', allDatasets[0].dim_labels_array);
                console.log('Loaded', allDimensions.length, 'dimensions');
                console.log('Top 5 dimensions by usage:', allDimensions.slice(0, 5));

                renderDimensions();

                // Load dimensions from URL
                loadDimensionsFromURL();
            } catch (error) {
                console.error('Error loading data:', error);
                document.getElementById('dimensions-tags').innerHTML = '<div class="no-results">Error loading data</div>';
            }
        }

        // CSV parser that handles multi-line quoted fields
        function parseCSV(text, columns) {
            const rows = parseCSVRows(text);
            if (rows.length === 0) return [];

            const headers = rows[0].map(h => h.trim());
            const result = [];

            for (let i = 1; i < rows.length; i++) {
                const values = rows[i];
                const row = {};

                columns.forEach(col => {
                    const index = headers.indexOf(col);
                    if (index >= 0) {
                        row[col] = values[index] || '';
                    }
                });

                result.push(row);
            }

            return result;
        }

        // Parse CSV text into rows, handling quoted fields with newlines
        function parseCSVRows(text) {
            const rows = [];
            let currentRow = [];
            let currentField = '';
            let inQuotes = false;

            for (let i = 0; i < text.length; i++) {
                const char = text[i];
                const nextChar = text[i + 1];

                if (char === '"' && nextChar === '"' && inQuotes) {
                    // Escaped quote inside quoted field
                    currentField += '"';
                    i++; // Skip next quote
                } else if (char === '"') {
                    // Toggle quote mode
                    inQuotes = !inQuotes;
                } else if (char === ',' && !inQuotes) {
                    // Field separator
                    currentRow.push(currentField);
                    currentField = '';
                } else if ((char === '\n' || char === '\r') && !inQuotes) {
                    // Row separator (handle both \n and \r\n)
                    if (char === '\r' && nextChar === '\n') {
                        i++; // Skip \n in \r\n
                    }
                    if (currentField || currentRow.length > 0) {
                        currentRow.push(currentField);
                        if (currentRow.some(f => f.trim())) {
                            rows.push(currentRow);
                        }
                        currentRow = [];
                        currentField = '';
                    }
                } else {
                    // Regular character (including newlines inside quotes)
                    currentField += char;
                }
            }

            // Push last field and row if any
            if (currentField || currentRow.length > 0) {
                currentRow.push(currentField);
                if (currentRow.some(f => f.trim())) {
                    rows.push(currentRow);
                }
            }

            return rows;
        }

        // Check if dimension is a unit of measure
        function isUnitOfMeasure(dim) {
            const lower = dim.toLowerCase();
            return lower.startsWith('um:') ||
                   lower.startsWith('unitati de masura') ||
                   lower.includes('unități de măsură');
        }

        // Render dimension tags
        function renderDimensions() {
            const container = document.getElementById('dimensions-tags');
            const otherDimsContainer = document.getElementById('other-dims-drawer');
            const umContainer = document.getElementById('um-drawer');

            const POPULAR_THRESHOLD = 15;

            // Separate regular dimensions from UM dimensions
            const regularDims = allDimensions.filter(dim => !isUnitOfMeasure(dim.name));
            const umDims = allDimensions.filter(dim => isUnitOfMeasure(dim.name));

            // Split regular dimensions into popular and other
            const popularDims = regularDims.filter(dim => dim.count >= POPULAR_THRESHOLD);
            const otherDims = regularDims.filter(dim => dim.count < POPULAR_THRESHOLD);

            document.getElementById('dim-count').textContent = popularDims.length;
            document.getElementById('other-dim-count').textContent = otherDims.length;
            document.getElementById('um-count').textContent = umDims.length;

            container.innerHTML = popularDims.map(dim =>
                `<span class="tag" onclick="filterByDimension('${escapeHtml(dim.name)}')">${escapeHtml(dim.name)} <sup>${dim.count}</sup></span>`
            ).join('');

            otherDimsContainer.innerHTML = otherDims.map(dim =>
                `<span class="tag" onclick="filterByDimension('${escapeHtml(dim.name)}')">${escapeHtml(dim.name)} <sup>${dim.count}</sup></span>`
            ).join('');

            umContainer.innerHTML = umDims.map(dim =>
                `<span class="tag" onclick="filterByDimension('${escapeHtml(dim.name)}')">${escapeHtml(dim.name)} <sup>${dim.count}</sup></span>`
            ).join('');
        }

        // Toggle drawer
        function toggleDrawer(drawerId) {
            const content = document.getElementById(drawerId + '-drawer');
            const toggles = document.querySelectorAll('.drawer-toggle');

            // Find the correct toggle button by checking which one was clicked
            toggles.forEach(toggle => {
                if (toggle.onclick.toString().includes(drawerId)) {
                    toggle.classList.toggle('open');
                }
            });

            content.classList.toggle('open');
        }

        // Toggle dimension selection
        function filterByDimension(dimension) {
            // Toggle selection
            if (selectedDimensions.has(dimension)) {
                selectedDimensions.delete(dimension);
            } else {
                selectedDimensions.add(dimension);
            }

            console.log('Selected dimensions:', Array.from(selectedDimensions));

            // Update URL
            updateURL();

            // Update active tags
            updateActiveTags();

            // Filter and render datasets
            filterAndRenderDatasets();
        }

        // Update active tag styling
        function updateActiveTags() {
            document.querySelectorAll('.tag').forEach(tag => {
                const tagText = tag.textContent.replace(/\s*\d+$/, '').trim(); // Remove count suffix
                if (selectedDimensions.has(tagText)) {
                    tag.classList.add('active');
                } else {
                    tag.classList.remove('active');
                }
            });
        }

        // Filter datasets based on selected dimensions
        function filterAndRenderDatasets() {
            if (selectedDimensions.size === 0) {
                document.getElementById('datasets-list').innerHTML = '<div class="no-results">Click a dimension tag above to see datasets</div>';
                document.getElementById('dataset-count').textContent = '0';
                return;
            }

            const dimensionsArray = Array.from(selectedDimensions);

            // Split into two groups
            const withAll = []; // Datasets with ALL selected dimensions
            const withSome = []; // Datasets with at least ONE selected dimension

            allDatasets.forEach(ds => {
                if (!Array.isArray(ds.dim_labels_array)) return;

                const matchCount = dimensionsArray.filter(dim =>
                    ds.dim_labels_array.includes(dim)
                ).length;

                if (matchCount === dimensionsArray.length) {
                    withAll.push(ds);
                } else if (matchCount > 0) {
                    withSome.push(ds);
                }
            });

            console.log(`Found ${withAll.length} datasets with all dimensions, ${withSome.length} with some`);

            renderDatasets(withAll, withSome);
        }

        // Load dimensions from URL parameters
        function loadDimensionsFromURL() {
            const params = new URLSearchParams(window.location.search);
            const dims = params.get('dims');

            if (dims) {
                const dimensionList = dims.split(',').map(d => decodeURIComponent(d));
                dimensionList.forEach(dim => selectedDimensions.add(dim));
                updateActiveTags();
                filterAndRenderDatasets();
            }
        }

        // Update URL with selected dimensions
        function updateURL() {
            const params = new URLSearchParams();

            if (selectedDimensions.size > 0) {
                const dims = Array.from(selectedDimensions)
                    .map(d => encodeURIComponent(d))
                    .join(',');
                params.set('dims', dims);
            }

            const newURL = params.toString()
                ? `${window.location.pathname}?${params.toString()}`
                : window.location.pathname;

            window.history.replaceState({}, '', newURL);

            // Show/hide clear button
            const clearBtn = document.getElementById('clear-selection');
            if (clearBtn) {
                clearBtn.style.display = selectedDimensions.size > 0 ? 'inline-block' : 'none';
            }
        }

        // Clear all selections
        function clearSelection() {
            selectedDimensions.clear();
            updateURL();
            updateActiveTags();
            filterAndRenderDatasets();
        }

        // Render dataset cards
        function renderDatasets(withAll = [], withSome = []) {
            const container = document.getElementById('datasets-list');
            const totalCount = withAll.length + withSome.length;
            document.getElementById('dataset-count').textContent = totalCount;

            if (totalCount === 0) {
                container.innerHTML = '<div class="no-results">No datasets found for selected dimension(s)</div>';
                return;
            }

            let html = '';

            // Render datasets with all dimensions
            if (withAll.length > 0) {
                if (selectedDimensions.size > 1) {
                    html += `<h3 style="font-size: 14px; color: #2196f3; margin: 10px 0; padding: 5px 10px; background: #e3f2fd; border-radius: 4px;">
                        All ${selectedDimensions.size} dimensions (${withAll.length})
                    </h3>`;
                }

                html += withAll.map(ds => {
                    const path = ds.fileMetadata?.ancestorPath ? `
                        <div class="dataset-path" title="${escapeHtml(ds.fileMetadata.ancestorPath)}">
                            ${escapeHtml(ds.fileMetadata.ancestorPath)}
                        </div>
                    ` : '';

                    const fileInfo = ds.fileMetadata ? `
                        <div class="dataset-file-info">
                            <span class="size ${ds.fileMetadata.fileSizeMB > 5 ? 'large' : ''}">${ds.fileMetadata.fileSizeMB.toFixed(2)} MB</span> &middot; 
                            <span>${ds.fileMetadata.rowCount.toLocaleString()} rows</span>
                        </div>
                    ` : '';

                     return `
                        <div class="dataset-card" onclick="openDataset('${escapeHtml(ds.filename)}')">
                        ${path}    
                        <div>
                            <div class="dataset-filename">${escapeHtml(ds.filename)}</div>
                            &emsp; &middot; &emsp;
                            ${fileInfo}
                        </div>
                            <h4 class="dataset-name">${escapeHtml(ds.matrixName)}</h4> 
                            <div class="dataset-dims">
                                ${(Array.isArray(ds.dim_labels_array) ? ds.dim_labels_array : []).map(dim =>
                                    `<span class="tag small ${selectedDimensions.has(dim) ? 'active' : ''}" onclick="event.stopPropagation(); filterByDimension('${escapeHtml(dim)}')">${escapeHtml(dim)}</span>`
                                ).join('')}
                            </div>
                        </div>
                    `;
                }).join('');
            }

            // Render datasets with some dimensions
            if (withSome.length > 0 && selectedDimensions.size > 1) {
                html += `<h3 style="font-size: 14px; color: #666; margin: 20px 0 10px 0; padding: 5px 10px; background: #f5f5f5; border-radius: 4px;">
                    At least one dimension (${withSome.length})
                </h3>`;

                html += withSome.map(ds => {
                    const path = ds.fileMetadata?.ancestorPath ? `
                        <div class="dataset-path" title="${escapeHtml(ds.fileMetadata.ancestorPath)}">
                            ${escapeHtml(ds.fileMetadata.ancestorPath)}
                        </div>
                    ` : '';

                    const fileInfo = ds.fileMetadata ? `
                        <div class="dataset-file-info">
                            <span class="size ${ds.fileMetadata.fileSizeMB > 5 ? 'large' : ''}">${ds.fileMetadata.fileSizeMB.toFixed(2)} MB</span> &middot; 
                            <span>${ds.fileMetadata.rowCount.toLocaleString()} rows</span>
                        </div>
                    ` : '';

                    return `
                        <div class="dataset-card" onclick="openDataset('${escapeHtml(ds.filename)}')">
                        ${path}    
                        <div>
                            <div class="dataset-filename">${escapeHtml(ds.filename)}</div>
                            &emsp; &middot; &emsp;
                            ${fileInfo}
                        </div>
                            <h4 class="dataset-name">${escapeHtml(ds.matrixName)}</h4> 
                            <div class="dataset-dims">
                                ${(Array.isArray(ds.dim_labels_array) ? ds.dim_labels_array : []).map(dim =>
                                    `<span class="tag small ${selectedDimensions.has(dim) ? 'active' : ''}" onclick="event.stopPropagation(); filterByDimension('${escapeHtml(dim)}')">${escapeHtml(dim)}</span>`
                                ).join('')}
                            </div>
                        </div>
                    `;
                }).join('');
            }

            container.innerHTML = html;
        }

        // Escape HTML
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // Open dataset profile
        function openDataset(filename) {
            const params = new URLSearchParams();
            params.set('id', filename);

            // Pass selected dimensions to dataset profile
            if (selectedDimensions.size > 0) {
                const dims = Array.from(selectedDimensions)
                    .map(d => encodeURIComponent(d))
                    .join(',');
                params.set('dims', dims);
            }

            window.location.href = `dataset-profile.html?${params.toString()}`;
        }

        // Initialize
        loadData();