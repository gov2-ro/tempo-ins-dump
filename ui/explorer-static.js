/**
 * Static Explorer - Client-side version
 * No server dependency, all data loaded from static files
 */

// Configuration
const CONFIG = {
  dataPath: './data/',
  maxPreviewRows: 400,
  maxFileSize: 4 * 1024 * 1024 // 4MB
};

// Initialize CSV parser
const csvParser = new CSVParser();

async function fetchJSON(url) {
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    return await res.json();
  } catch (error) {
    console.error(`Failed to fetch ${url}:`, error);
    throw error;
  }
}

async function fetchText(url) {
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    return await res.text();
  } catch (error) {
    console.error(`Failed to fetch ${url}:`, error);
    throw error;
  }
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const child of children) node.appendChild(child);
  return node;
}

function chip(text, active) {
  return el('span', { class: `flag-chip${active ? ' active' : ''}`, 'data-flag': text, text });
}

const state = {
  q: '',
  flags: new Set(),
  allItems: [], // Full dataset index
  filteredItems: [], // Current filtered results
  flagsIndex: {},
  currentDatasetIndex: -1,
  datasetsCache: new Map(), // Cache for dataset details
  previewCache: new Map()   // Cache for CSV previews
};

function renderFlags() {
  const wrap = document.getElementById('flag-list');
  wrap.innerHTML = '';
  const keys = Object.keys(state.flagsIndex);
  for (const f of keys) {
    wrap.appendChild(chip(`${f} (${state.flagsIndex[f]})`, state.flags.has(f)));
  }
}

function renderList() {
  const list = document.getElementById('list');
  const detail = document.getElementById('detail');
  list.innerHTML = '';
  detail.classList.add('hidden');

  document.getElementById('count').textContent = state.filteredItems.length;

  for (const it of state.filteredItems) {
    const card = el('div', { class: 'card', 'data-id': it.id });
    
    // Create title with ID and descriptive name
    const titleText = it.matrix_name ? `${it.id} - ${it.matrix_name}` : `${it.id} - ${it.name}`;
    card.appendChild(el('div', { class: 'title', text: titleText }));
    
    const meta = [
      it.um_label ? `UM: ${it.um_label}` : null,
      it.columns_count ? `${it.columns_count} cols` : null,
    ].filter(Boolean).join(' • ');
    card.appendChild(el('div', { class: 'meta', text: meta }));
    
    const flags = el('div', { class: 'flags' });
    for (const f of it.flags || []) flags.appendChild(chip(f));
    card.appendChild(flags);

    card.addEventListener('click', () => openDetail(it.id));
    list.appendChild(card);
  }
}

function filterItems() {
  const query = state.q.toLowerCase();
  
  state.filteredItems = state.allItems.filter(item => {
    // Text search
    if (query) {
      const searchText = [
        item.id,
        item.name,
        item.matrix_name || '',
        item.um_label || ''
      ].join(' ').toLowerCase();
      
      if (!searchText.includes(query)) {
        return false;
      }
    }
    
    // Flag filters
    if (state.flags.size > 0) {
      const itemFlags = new Set(item.flags || []);
      for (const requiredFlag of state.flags) {
        if (!itemFlags.has(requiredFlag)) {
          return false;
        }
      }
    }
    
    return true;
  });
}

function refresh() {
  filterItems();
  renderList();
}

async function loadDatasetDetail(id) {
  // Check cache first
  if (state.datasetsCache.has(id)) {
    return state.datasetsCache.get(id);
  }
  
  try {
    const data = await fetchJSON(`${CONFIG.dataPath}datasets/${id}.json`);
    state.datasetsCache.set(id, data);
    return data;
  } catch (error) {
    console.error(`Failed to load dataset ${id}:`, error);
    throw new Error(`Dataset ${id} not found`);
  }
}

async function loadCSVPreview(csvPath, maxRows = null) {
  // Create cache key
  const cacheKey = `${csvPath}_${maxRows || 'all'}`;
  
  // Check cache first
  if (state.previewCache.has(cacheKey)) {
    return state.previewCache.get(cacheKey);
  }
  
  try {
    // Try to get file size first using HEAD request
    let fileSize = 0;
    try {
      const headResponse = await fetch(csvPath, { method: 'HEAD' });
      const contentLength = headResponse.headers.get('content-length');
      if (contentLength) {
        fileSize = parseInt(contentLength);
      }
    } catch (e) {
      console.warn('Could not get file size via HEAD request');
    }
    
    // Determine if we should truncate based on file size
    const shouldTruncate = csvParser.shouldTruncate(fileSize);
    const effectiveMaxRows = maxRows || (shouldTruncate ? CONFIG.maxPreviewRows : null);
    
    // Load CSV content
    const csvText = await fetchText(csvPath);
    const parseResult = csvParser.parse(csvText, effectiveMaxRows);
    
    const result = {
      rows: parseResult.rows,
      columns: parseResult.columns,
      total_rows: parseResult.totalRows,
      actual_total_rows: parseResult.actualTotalRows,
      file_size_mb: csvParser.getFileSizeMB(csvText.length), // Approximate from content
      is_truncated: parseResult.isTruncated
    };
    
    // Cache the result
    state.previewCache.set(cacheKey, result);
    return result;
    
  } catch (error) {
    console.error(`Failed to load CSV preview from ${csvPath}:`, error);
    return {
      rows: [],
      columns: [],
      total_rows: 0,
      actual_total_rows: 0,
      file_size_mb: 0,
      is_truncated: false
    };
  }
}

async function openDetail(id) {
  try {
    // Update URL hash
    window.location.hash = id;
    
    // Find and store the current dataset index
    state.currentDatasetIndex = state.filteredItems.findIndex(item => item.id === id);
    
    // Load dataset details
    const data = await loadDatasetDetail(id);
    
    // Load CSV preview
    let preview = { rows: [], columns: [], total_rows: 0, file_size_mb: 0, is_truncated: false };
    if (data.source_csv) {
      // Convert absolute path to relative CSV path
      const csvFilename = data.source_csv.split('/').pop();
      const csvPath = `${CONFIG.dataPath}csv/${csvFilename}`;
      preview = await loadCSVPreview(csvPath);
    }

    // Update UI
    document.getElementById('list').innerHTML = '';
    const detail = document.getElementById('detail');
    detail.classList.remove('hidden');
    
    // Update navigation buttons
    updateNavigationButtons();
    
    // Show ID and descriptive name in detail title
    const filename = data.source_csv ? data.source_csv.split('/').pop() : `${id}.csv`;
    const titleText = data.matrix_name ? `${id} - ${data.matrix_name}` : `${id} - ${filename}`;
    document.getElementById('title').textContent = titleText;
    
    // Update preview title with row count and file size info
    const previewTitle = document.getElementById('preview-title');
    let titleSuffix = `(${preview.total_rows} rows, ${preview.file_size_mb}MB)`;
    if (preview.is_truncated) {
      titleSuffix = `(showing top ${CONFIG.maxPreviewRows} of ${preview.actual_total_rows} rows, ${preview.file_size_mb}MB)`;
    }
    previewTitle.textContent = `Preview ${titleSuffix}`;
    
    // Render JSON with pretty formatting
    $('#json-viewer').html(`<pre>${JSON.stringify(data, null, 2)}</pre>`);

    // Generate and render column analysis
    renderColumnAnalysis(data);

    // Add toggle functionality for JSON viewer
    document.getElementById('toggle-json').onclick = () => {
      const jsonViewer = document.getElementById('json-viewer');
      const toggleBtn = document.getElementById('toggle-json');
      
      if (jsonViewer.style.display === 'none') {
        jsonViewer.style.display = 'block';
        toggleBtn.textContent = 'Hide';
      } else {
        jsonViewer.style.display = 'none';
        toggleBtn.textContent = 'Show';
      }
    };

    // Setup preview table
    await setupPreviewTable(preview);

    // Setup navigation
    document.getElementById('back').onclick = () => {
      window.location.hash = '';
      detail.classList.add('hidden');
      if ($.fn.DataTable.isDataTable('#preview')) {
        $('#preview').DataTable().destroy();
      }
      renderList();
    };
    
    document.getElementById('prev-dataset').onclick = () => navigateToDataset(-1);
    document.getElementById('next-dataset').onclick = () => navigateToDataset(1);
    
  } catch (error) {
    console.error('Failed to open dataset detail:', error);
    alert(`Failed to load dataset: ${error.message}`);
  }
}

async function setupPreviewTable(preview) {
  // Destroy existing DataTable if it exists
  if ($.fn.DataTable.isDataTable('#preview')) {
    $('#preview').DataTable().destroy();
  }

  // Clear and prepare table
  const tbl = document.getElementById('preview');
  tbl.innerHTML = '';

  if (preview.rows.length > 0) {
    // Create table structure
    const thead = el('thead');
    const trh = el('tr');
    for (const col of preview.columns) {
      trh.appendChild(el('th', { text: col }));
    }
    thead.appendChild(trh);
    tbl.appendChild(thead);

    const tbody = el('tbody');
    for (const row of preview.rows) {
      const tr = el('tr');
      for (const col of preview.columns) {
        tr.appendChild(el('td', { text: row[col] == null ? '' : String(row[col]) }));
      }
      tbody.appendChild(tr);
    }
    tbl.appendChild(tbody);

    // Initialize DataTable
    $('#preview').DataTable({
      pageLength: 25,
      lengthMenu: [[10, 25, 50, 100, -1], [10, 25, 50, 100, "All"]],
      scrollX: true,
      columnDefs: [
        {
          targets: '_all',
          className: 'dt-body-nowrap'
        }
      ]
    });
  } else {
    // No data available
    tbl.innerHTML = '<tr><td colspan="100%">No data available</td></tr>';
  }
}

function updateNavigationButtons() {
  const prevBtn = document.getElementById('prev-dataset');
  const nextBtn = document.getElementById('next-dataset');
  const positionSpan = document.getElementById('dataset-position');
  
  // Update position display
  if (state.currentDatasetIndex >= 0 && state.filteredItems.length > 0) {
    positionSpan.textContent = `${state.currentDatasetIndex + 1} of ${state.filteredItems.length}`;
  } else {
    positionSpan.textContent = '';
  }
  
  // Enable/disable buttons based on position
  prevBtn.disabled = state.currentDatasetIndex <= 0;
  nextBtn.disabled = state.currentDatasetIndex >= state.filteredItems.length - 1;
}

function navigateToDataset(direction) {
  const newIndex = state.currentDatasetIndex + direction;
  
  // Bounds checking
  if (newIndex < 0 || newIndex >= state.filteredItems.length) {
    return;
  }
  
  const nextDataset = state.filteredItems[newIndex];
  if (nextDataset) {
    openDetail(nextDataset.id);
  }
}

async function init() {
  try {
    console.log('Initializing static explorer...');

    // Load datasets index
    console.log('Loading datasets index...');
    state.allItems = await fetchJSON(`${CONFIG.dataPath}datasets-index.json`);
    console.log(`Loaded ${state.allItems.length} datasets`);

    // Load flags index
    console.log('Loading flags index...');
    const flagsData = await fetchJSON(`${CONFIG.dataPath}flags-index.json`);
    state.flagsIndex = flagsData.counts;
    console.log(`Loaded ${Object.keys(state.flagsIndex).length} flags`);

    // Render initial UI
    renderFlags();

    // Setup event listeners
    document.getElementById('flag-list').addEventListener('click', (e) => {
      const f = e.target.getAttribute('data-flag');
      if (!f) return;
      const flag = f.split(' (')[0];
      if (state.flags.has(flag)) {
        state.flags.delete(flag);
      } else {
        state.flags.add(flag);
      }
      renderFlags();
      refresh();
    });

    const search = document.getElementById('search');
    search.addEventListener('input', (e) => {
      state.q = e.target.value;
      refresh();
    });

    // Handle browser back/forward navigation
    window.addEventListener('hashchange', handleHashChange);
    
    // Initial refresh
    refresh();
    
    // Check if there's a hash in the URL on page load
    handleHashChange();

    console.log('Static explorer initialized successfully!');
    
  } catch (error) {
    console.error('Failed to initialize explorer:', error);
    alert('Failed to initialize explorer: ' + error.message);
  }
}

function handleHashChange() {
  const hash = window.location.hash.slice(1); // Remove the # character
  if (hash) {
    // Open the dataset if hash is present
    openDetail(hash).catch(err => {
      console.error('Failed to load dataset from hash:', err);
      // If dataset doesn't exist, clear the hash and show the list
      window.location.hash = '';
      const detail = document.getElementById('detail');
      detail.classList.add('hidden');
      renderList();
    });
  } else {
    // No hash, show the list
    const detail = document.getElementById('detail');
    detail.classList.add('hidden');
    if ($.fn.DataTable.isDataTable('#preview')) {
      $('#preview').DataTable().destroy();
    }
    renderList();
  }
}

function getFlagType(flag) {
  if (flag.includes('time')) return 'flag-time';
  if (flag.includes('geo')) return 'flag-geo';
  return 'flag-general';
}

function renderColumnAnalysis(data) {
  const summaryContainer = document.getElementById('data-summary');
  if (!summaryContainer || !data) return;

  const columns = data.columns || [];
  const fileChecks = data.file_checks || {};
  const validationResults = fileChecks.validation_results || [];
  
  let html = `
    <div class="analysis-grid">
      <div class="overview-card">
        <div class="card-header">
          <h4>📊 Dataset Overview</h4>
        </div>
        <div class="card-content">
          <div class="overview-stats">
            <div class="stat-item"><span>Columns:</span> <strong>${columns.length}</strong></div>
            <div class="stat-item"><span>Unit Consistency:</span> <span class="status-${fileChecks.um_col_uniformity === 'Uniform' ? 'good' : 'warning'}">${fileChecks.um_col_uniformity || 'Unknown'}</span></div>
            <div class="stat-item"><span>Unit:</span> <strong>${fileChecks.um_label || 'N/A'}</strong></div>
            <div class="stat-item"><span>Validation:</span> <span class="status-good">${fileChecks.validation_summary?.info || 0} checks passed</span></div>
          </div>
        </div>
      </div>
  `;
  
  columns.forEach(col => {
    const flags = col.validation_flags || [];
    const sample = col.unique_values_sample && col.unique_values_sample !== 'High cardinality (30)' 
      ? col.unique_values_sample.split(' | ').slice(0, 3).join(', ') + (col.unique_values_sample.split(' | ').length > 3 ? '...' : '')
      : null;
      
    // Find validation messages for this column
    const columnMessages = validationResults.filter(result => result.column_name === col.column_name);
    
    html += `
      <div class="column-card">
        <div class="card-header">
          <h4>${col.column_name}</h4>
          <span class="column-type">${col.guessed_type || 'unknown'}</span>
        </div>
        <div class="card-content">
          <div class="column-stat">
            <span>Unique Values:</span> <strong>${(col.unique_values_count || 0).toLocaleString()}</strong>
          </div>
          ${sample ? `<div class="column-stat sample-data"><span>Sample:</span> <code>${sample}</code></div>` : ''}
          ${flags.length > 0 ? `
            <div class="column-flags">
              ${flags.map(flag => `<span class="flag-badge ${getFlagType(flag)}">${flag}</span>`).join(' ')}
            </div>
          ` : ''}
          ${columnMessages.length > 0 ? `
            <div class="column-messages">
              ${columnMessages.map(msg => `<div class="validation-msg ${msg.severity}">${msg.message}</div>`).join('')}
            </div>
          ` : ''}
        </div>
      </div>
    `;
  });
  
  html += `
    </div>
  `;
  
  summaryContainer.innerHTML = html;
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
