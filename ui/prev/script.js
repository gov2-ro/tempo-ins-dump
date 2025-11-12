/**
 * Enhanced Statistical Navigator
 * Advanced dataset exploration with smart filtering and navigation
 */

class EnhancedNavigator {
    constructor() {
        this.apiBase = './navigator-api.php';
        this.state = {
            navigationTree: [],
            staticData: null,
            currentFilters: {},
            searchQuery: '',
            currentPage: 1,
            pageSize: 24,
            sortField: 'title',
            sortOrder: 'ASC',
            viewMode: 'grid',
            datasets: [],
            totalResults: 0,
            selectedCategory: null
        };
        
        this.debounceTimer = null;
        this.suggestionTimer = null;
        
        this.init();
    }
    
    async init() {
        try {
            await this.loadStaticData();
            this.setupEventListeners();
            this.renderNavigation();
            this.updateStats();
            await this.loadDatasets();
        } catch (error) {
            console.error('Navigator initialization failed:', error);
            this.showError('Failed to initialize navigator. Please refresh the page.');
        }
    }
    
    async loadStaticData() {
        try {
            const response = await fetch(`${this.apiBase}?action=navigation`);
            const data = await response.json();
            
            if (data.success) {
                this.state.staticData = data.data;
                this.state.navigationTree = this.buildTreeStructure(data.data);
            } else {
                throw new Error(data.error?.message || 'Failed to load navigation data');
            }
        } catch (error) {
            console.error('Error loading static data:', error);
            throw error;
        }
    }
    
    buildTreeStructure(flatTree) {
        const tree = {};
        const rootNodes = [];
        
        // First pass: create all nodes
        flatTree.forEach(node => {
            tree[node.code] = {
                ...node,
                children: []
            };
        });
        
        // Second pass: build parent-child relationships
        flatTree.forEach(node => {
            if (node.parent_code && tree[node.parent_code]) {
                tree[node.parent_code].children.push(tree[node.code]);
            } else if (node.level === 0) {
                rootNodes.push(tree[node.code]);
            }
        });
        
        return rootNodes;
    }
    
    setupEventListeners() {
        // Search functionality
        const searchInput = document.getElementById('search-input');
        searchInput.addEventListener('input', (e) => {
            this.handleSearchInput(e.target.value);
        });
        
        searchInput.addEventListener('focus', () => {
            this.showSearchSuggestions();
        });
        
        searchInput.addEventListener('blur', () => {
            setTimeout(() => this.hideSearchSuggestions(), 150);
        });
        
        document.getElementById('search-btn').addEventListener('click', () => {
            this.performSearch();
        });
        
        // Filter controls
        document.getElementById('apply-filters').addEventListener('click', () => {
            this.applyFilters();
        });
        
        document.getElementById('clear-filters').addEventListener('click', () => {
            this.clearFilters();
        });
        
        document.getElementById('clear-all-filters').addEventListener('click', () => {
            this.clearAllFilters();
        });
        
        // Quality slider
        const qualitySlider = document.getElementById('quality-slider');
        qualitySlider.addEventListener('input', (e) => {
            this.updateQualityDisplay(e.target.value);
        });
        
        // Sort controls
        document.getElementById('sort-select').addEventListener('change', (e) => {
            this.state.sortField = e.target.value;
            this.loadDatasets();
        });
        
        document.getElementById('sort-order').addEventListener('click', (e) => {
            const button = e.target;
            const currentOrder = button.dataset.order;
            const newOrder = currentOrder === 'ASC' ? 'DESC' : 'ASC';
            
            button.dataset.order = newOrder;
            button.textContent = newOrder === 'ASC' ? '↑' : '↓';
            button.title = `Sort ${newOrder === 'ASC' ? 'Ascending' : 'Descending'}`;
            
            this.state.sortOrder = newOrder;
            this.loadDatasets();
        });
        
        // View mode controls
        document.getElementById('view-grid').addEventListener('click', () => {
            this.setViewMode('grid');
        });
        
        document.getElementById('view-list').addEventListener('click', () => {
            this.setViewMode('list');
        });
        
        // Pagination
        document.getElementById('prev-page').addEventListener('click', () => {
            if (this.state.currentPage > 1) {
                this.state.currentPage--;
                this.loadDatasets();
            }
        });
        
        document.getElementById('next-page').addEventListener('click', () => {
            const maxPage = Math.ceil(this.state.totalResults / this.state.pageSize);
            if (this.state.currentPage < maxPage) {
                this.state.currentPage++;
                this.loadDatasets();
            }
        });
        
        // Modal controls
        document.getElementById('modal-close').addEventListener('click', () => {
            this.closeModal();
        });
        
        document.getElementById('dataset-modal').addEventListener('click', (e) => {
            if (e.target.id === 'dataset-modal') {
                this.closeModal();
            }
        });
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeModal();
                this.hideSearchSuggestions();
            }
            if (e.key === 'Enter' && e.target.id === 'search-input') {
                this.performSearch();
            }
        });
    }
    
    renderNavigation() {
        const container = document.getElementById('navigation-tree');
        container.innerHTML = '';
        
        if (this.state.navigationTree.length === 0) {
            container.innerHTML = '<div class="no-data">No navigation data available</div>';
            return;
        }
        
        const tree = this.createTreeElement(this.state.navigationTree);
        container.appendChild(tree);
    }
    
    createTreeElement(nodes, level = 0) {
        const ul = document.createElement('ul');
        ul.className = 'tree-level';
        
        nodes.forEach(node => {
            const li = document.createElement('li');
            li.className = 'tree-node';
            
            const nodeElement = document.createElement('div');
            nodeElement.className = 'tree-node-content';
            
            // Add expand/collapse button if has children
            if (node.children && node.children.length > 0) {
                const toggleBtn = document.createElement('button');
                toggleBtn.className = 'tree-toggle';
                toggleBtn.textContent = '▶';
                toggleBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.toggleTreeNode(li, toggleBtn);
                });
                nodeElement.appendChild(toggleBtn);
            } else {
                const spacer = document.createElement('span');
                spacer.className = 'tree-spacer';
                nodeElement.appendChild(spacer);
            }
            
            // Node label and count
            const label = document.createElement('span');
            label.className = 'tree-label';
            label.textContent = node.name;
            
            const count = document.createElement('span');
            count.className = 'tree-count';
            count.textContent = `(${node.dataset_count})`;
            
            nodeElement.appendChild(label);
            nodeElement.appendChild(count);
            
            // Click handler for navigation
            nodeElement.addEventListener('click', () => {
                this.selectCategory(node);
            });
            
            li.appendChild(nodeElement);
            
            // Add children if they exist
            if (node.children && node.children.length > 0) {
                const childTree = this.createTreeElement(node.children, level + 1);
                childTree.className += ' tree-children collapsed';
                li.appendChild(childTree);
            }
            
            ul.appendChild(li);
        });
        
        return ul;
    }
    
    toggleTreeNode(nodeElement, toggleBtn) {
        const children = nodeElement.querySelector('.tree-children');
        if (children) {
            const isCollapsed = children.classList.contains('collapsed');
            if (isCollapsed) {
                children.classList.remove('collapsed');
                toggleBtn.textContent = '▼';
            } else {
                children.classList.add('collapsed');
                toggleBtn.textContent = '▶';
            }
        }
    }
    
    selectCategory(node) {
        // Update visual selection
        document.querySelectorAll('.tree-node-content').forEach(el => {
            el.classList.remove('selected');
        });
        
        event.target.closest('.tree-node-content').classList.add('selected');
        
        // Update state and reload
        this.state.selectedCategory = node.code;
        this.state.currentFilters.category = node.code;
        this.state.currentPage = 1;
        
        this.updateActiveFilters();
        this.loadDatasets();
    }
    
    handleSearchInput(query) {
        this.state.searchQuery = query;
        
        // Debounce search
        clearTimeout(this.debounceTimer);
        this.debounceTimer = setTimeout(() => {
            if (query.length > 2) {
                this.loadSearchSuggestions(query);
            } else {
                this.hideSearchSuggestions();
            }
        }, 300);
    }
    
    async loadSearchSuggestions(query) {
        try {
            const response = await fetch(`${this.apiBase}?action=suggestions&q=${encodeURIComponent(query)}`);
            const data = await response.json();
            
            if (data.success) {
                this.renderSearchSuggestions(data.data);
            }
        } catch (error) {
            console.error('Error loading suggestions:', error);
        }
    }
    
    renderSearchSuggestions(suggestions) {
        const container = document.getElementById('search-suggestions');
        container.innerHTML = '';
        
        if (suggestions.length === 0) {
            container.style.display = 'none';
            return;
        }
        
        suggestions.forEach(suggestion => {
            const item = document.createElement('div');
            item.className = 'suggestion-item';
            item.textContent = suggestion;
            item.addEventListener('click', () => {
                document.getElementById('search-input').value = suggestion;
                this.state.searchQuery = suggestion;
                this.hideSearchSuggestions();
                this.performSearch();
            });
            container.appendChild(item);
        });
        
        container.style.display = 'block';
    }
    
    showSearchSuggestions() {
        const container = document.getElementById('search-suggestions');
        if (container.children.length > 0) {
            container.style.display = 'block';
        }
    }
    
    hideSearchSuggestions() {
        const container = document.getElementById('search-suggestions');
        container.style.display = 'none';
    }
    
    performSearch() {
        this.state.currentPage = 1;
        this.loadDatasets();
        this.hideSearchSuggestions();
    }
    
    applyFilters() {
        const filters = this.collectFilterValues();
        this.state.currentFilters = { ...this.state.currentFilters, ...filters };
        this.state.currentPage = 1;
        
        this.updateActiveFilters();
        this.loadDatasets();
    }
    
    collectFilterValues() {
        return {
            min_quality: document.getElementById('quality-slider').value || null,
            year_from: document.getElementById('year-from').value || null,
            year_to: document.getElementById('year-to').value || null,
            geo_level: document.getElementById('geo-level-filter').value || null,
            periodicity: document.getElementById('periodicity-filter').value || null,
            recent: document.getElementById('recent-data').checked ? true : null,
            methodology: document.getElementById('has-methodology').checked ? true : null
        };
    }
    
    clearFilters() {
        // Reset form elements
        document.getElementById('quality-slider').value = 0;
        document.getElementById('quality-stars').textContent = '☆☆☆☆☆';
        document.getElementById('quality-value').textContent = 'Any';
        document.getElementById('year-from').value = '';
        document.getElementById('year-to').value = '';
        document.getElementById('geo-level-filter').value = '';
        document.getElementById('periodicity-filter').value = '';
        document.getElementById('recent-data').checked = false;
        document.getElementById('has-methodology').checked = false;
        
        // Clear filter state (but keep category)
        const category = this.state.currentFilters.category;
        this.state.currentFilters = category ? { category } : {};
        
        this.updateActiveFilters();
        this.loadDatasets();
    }
    
    clearAllFilters() {
        this.clearFilters();
        
        // Also clear category selection
        this.state.currentFilters = {};
        this.state.selectedCategory = null;
        this.state.searchQuery = '';
        document.getElementById('search-input').value = '';
        
        // Clear visual selection
        document.querySelectorAll('.tree-node-content').forEach(el => {
            el.classList.remove('selected');
        });
        
        this.updateActiveFilters();
        this.loadDatasets();
    }
    
    updateQualityDisplay(value) {
        const stars = document.getElementById('quality-stars');
        const valueDisplay = document.getElementById('quality-value');
        
        const starCount = Math.round(value * 5);
        const starString = '★'.repeat(starCount) + '☆'.repeat(5 - starCount);
        
        stars.textContent = starString;
        valueDisplay.textContent = value == 0 ? 'Any' : `${Math.round(value * 100)}%`;
    }
    
    updateActiveFilters() {
        const activeFiltersContainer = document.getElementById('active-filters');
        const filterChipsContainer = document.getElementById('filter-chips');
        
        filterChipsContainer.innerHTML = '';
        
        const hasFilters = Object.keys(this.state.currentFilters).length > 0 || this.state.searchQuery;
        
        if (!hasFilters) {
            activeFiltersContainer.style.display = 'none';
            return;
        }
        
        // Add search query chip
        if (this.state.searchQuery) {
            this.addFilterChip(filterChipsContainer, 'Search', this.state.searchQuery, () => {
                this.state.searchQuery = '';
                document.getElementById('search-input').value = '';
                this.loadDatasets();
            });
        }
        
        // Add filter chips
        Object.entries(this.state.currentFilters).forEach(([key, value]) => {
            if (value !== null && value !== '') {
                const label = this.getFilterLabel(key);
                const displayValue = this.getFilterDisplayValue(key, value);
                
                this.addFilterChip(filterChipsContainer, label, displayValue, () => {
                    delete this.state.currentFilters[key];
                    if (key === 'category') {
                        this.state.selectedCategory = null;
                        document.querySelectorAll('.tree-node-content').forEach(el => {
                            el.classList.remove('selected');
                        });
                    }
                    this.updateActiveFilters();
                    this.loadDatasets();
                });
            }
        });
        
        activeFiltersContainer.style.display = 'block';
    }
    
    addFilterChip(container, label, value, removeCallback) {
        const chip = document.createElement('div');
        chip.className = 'filter-chip';
        
        const text = document.createElement('span');
        text.textContent = `${label}: ${value}`;
        
        const removeBtn = document.createElement('button');
        removeBtn.className = 'filter-chip-remove';
        removeBtn.textContent = '×';
        removeBtn.addEventListener('click', removeCallback);
        
        chip.appendChild(text);
        chip.appendChild(removeBtn);
        container.appendChild(chip);
    }
    
    getFilterLabel(key) {
        const labels = {
            category: 'Category',
            min_quality: 'Min Quality',
            year_from: 'From Year',
            year_to: 'To Year',
            geo_level: 'Geographic Level',
            periodicity: 'Frequency',
            recent: 'Recent Data',
            methodology: 'Has Methodology'
        };
        return labels[key] || key;
    }
    
    getFilterDisplayValue(key, value) {
        if (key === 'min_quality') {
            return `${Math.round(value * 100)}%`;
        }
        if (key === 'recent' || key === 'methodology') {
            return value ? 'Yes' : 'No';
        }
        if (key === 'category' && this.state.staticData) {
            const node = this.state.staticData.find(n => n.code === value);
            return node ? node.name : value;
        }
        return value;
    }
    
    async loadDatasets() {
        this.showLoading();
        
        try {
            const params = new URLSearchParams({
                q: this.state.searchQuery,
                limit: this.state.pageSize,
                offset: (this.state.currentPage - 1) * this.state.pageSize,
                sort: this.state.sortField,
                order: this.state.sortOrder,
                ...this.state.currentFilters
            });
            
            const response = await fetch(`${this.apiBase}?action=datasets&${params}`);
            const data = await response.json();
            
            if (data.success) {
                this.state.datasets = data.data.datasets;
                this.state.totalResults = data.data.pagination.total;
                
                this.renderDatasets();
                this.updatePagination(data.data.pagination);
                this.updateResultsSummary();
            } else {
                throw new Error(data.error?.message || 'Failed to load datasets');
            }
        } catch (error) {
            console.error('Error loading datasets:', error);
            this.showError('Failed to load datasets. Please try again.');
        }
    }
    
    renderDatasets() {
        const container = document.getElementById('datasets-grid');
        container.innerHTML = '';
        
        if (this.state.datasets.length === 0) {
            container.innerHTML = '<div class="no-results">No datasets found matching your criteria.</div>';
            return;
        }
        
        this.state.datasets.forEach(dataset => {
            const card = this.createDatasetCard(dataset);
            container.appendChild(card);
        });
    }
    
    createDatasetCard(dataset) {
        const card = document.createElement('div');
        card.className = `dataset-card ${this.state.viewMode}`;
        
        const qualityStars = '★'.repeat(Math.round(dataset.quality_score * 5)) + 
                           '☆'.repeat(5 - Math.round(dataset.quality_score * 5));
        
        card.innerHTML = `
            <div class="card-header">
                <div class="dataset-id">${dataset.id}</div>
                <div class="quality-badge" title="Data Quality Score">
                    ${qualityStars} ${Math.round(dataset.quality_score * 100)}%
                </div>
            </div>
            <div class="card-body">
                <h3 class="dataset-title">${dataset.title}</h3>
                <p class="dataset-description">${dataset.description}</p>
                <div class="dataset-meta">
                    <div class="meta-item">
                        <strong>Category:</strong> ${dataset.category_path || 'Uncategorized'}
                    </div>
                    <div class="meta-item">
                        <strong>Periodicity:</strong> ${dataset.periodicity || 'N/A'}
                    </div>
                    <div class="meta-item">
                        <strong>Dimensions:</strong> ${dataset.dimensions_count}
                    </div>
                    ${dataset.um_label ? `<div class="meta-item"><strong>Unit:</strong> ${dataset.um_label}</div>` : ''}
                    <div class="meta-item">
                        <strong>Last Updated:</strong> ${dataset.last_update || 'Unknown'}
                    </div>
                </div>
                <div class="dataset-badges">
                    ${dataset.has_recent_data ? '<span class="badge recent">Recent Data</span>' : ''}
                    ${dataset.geographic_level !== 'unknown' ? `<span class="badge geo">${dataset.geographic_level}</span>` : ''}
                </div>
                <div class="dataset-keywords">
                    ${dataset.keywords.slice(0, 3).map(keyword => `<span class="keyword">${keyword}</span>`).join('')}
                </div>
            </div>
            <div class="card-actions">
                <button class="btn btn-primary" onclick="navigator.openDatasetDetail('${dataset.id}')">
                    View Details
                </button>
            </div>
        `;
        
        return card;
    }
    
    async openDatasetDetail(datasetId) {
        try {
            const response = await fetch(`${this.apiBase}?action=dataset&id=${encodeURIComponent(datasetId)}`);
            const data = await response.json();
            
            if (data.success) {
                this.renderDatasetModal(data.data);
                document.getElementById('dataset-modal').style.display = 'block';
            } else {
                throw new Error(data.error?.message || 'Failed to load dataset details');
            }
        } catch (error) {
            console.error('Error loading dataset details:', error);
            this.showError('Failed to load dataset details.');
        }
    }
    
    renderDatasetModal(dataset) {
        document.getElementById('modal-title').textContent = `${dataset.id} - ${dataset.title}`;
        
        const modalBody = document.getElementById('modal-body');
        modalBody.innerHTML = `
            <div class="dataset-detail">
                <div class="detail-section">
                    <h4>Description</h4>
                    <p>${dataset.description || 'No description available.'}</p>
                </div>
                
                <div class="detail-section">
                    <h4>Dataset Information</h4>
                    <div class="detail-grid">
                        <div class="detail-item">
                            <strong>Category Path:</strong>
                            <span>${dataset.category_path || 'Uncategorized'}</span>
                        </div>
                        <div class="detail-item">
                            <strong>Periodicity:</strong>
                            <span>${dataset.periodicity || 'N/A'}</span>
                        </div>
                        <div class="detail-item">
                            <strong>Geographic Level:</strong>
                            <span>${dataset.geographic_level}</span>
                        </div>
                        <div class="detail-item">
                            <strong>Last Update:</strong>
                            <span>${dataset.last_update || 'Unknown'}</span>
                        </div>
                        <div class="detail-item">
                            <strong>Data Sources:</strong>
                            <span>${dataset.data_sources || 'Not specified'}</span>
                        </div>
                        <div class="detail-item">
                            <strong>Quality Score:</strong>
                            <span>${Math.round(dataset.quality_score * 100)}%</span>
                        </div>
                        ${dataset.time_span_start ? `
                        <div class="detail-item">
                            <strong>Time Coverage:</strong>
                            <span>${dataset.time_span_start} - ${dataset.time_span_end || 'ongoing'}</span>
                        </div>
                        ` : ''}
                    </div>
                </div>
                
                ${dataset.dimensions_list && dataset.dimensions_list.length > 0 ? `
                <div class="detail-section">
                    <h4>Dimensions (${dataset.dimensions_count})</h4>
                    <div class="dimensions-list">
                        ${dataset.dimensions_list.map(dim => `<span class="dimension-chip">${dim}</span>`).join('')}
                    </div>
                </div>
                ` : ''}
                
                ${dataset.keywords && dataset.keywords.length > 0 ? `
                <div class="detail-section">
                    <h4>Keywords</h4>
                    <div class="keywords-list">
                        ${dataset.keywords.map(keyword => `<span class="keyword-chip">${keyword}</span>`).join('')}
                    </div>
                </div>
                ` : ''}
                
                <div class="detail-actions">
                    <button class="btn btn-primary" onclick="window.open('data/4-datasets/ro/${dataset.id}.csv', '_blank')">
                        Download CSV
                    </button>
                    <button class="btn btn-secondary" onclick="window.open('data/2-metas/ro/${dataset.id}.json', '_blank')">
                        View Metadata
                    </button>
                </div>
            </div>
        `;
    }
    
    closeModal() {
        document.getElementById('dataset-modal').style.display = 'none';
    }
    
    setViewMode(mode) {
        this.state.viewMode = mode;
        
        // Update button states
        document.querySelectorAll('.view-btn').forEach(btn => btn.classList.remove('active'));
        document.getElementById(`view-${mode}`).classList.add('active');
        
        // Re-render with new view mode
        this.renderDatasets();
    }
    
    updatePagination(pagination) {
        const paginationContainer = document.getElementById('pagination');
        const prevBtn = document.getElementById('prev-page');
        const nextBtn = document.getElementById('next-page');
        const pageInfo = document.getElementById('page-info-text');
        
        prevBtn.disabled = pagination.page <= 1;
        nextBtn.disabled = pagination.page >= pagination.total_pages;
        
        pageInfo.textContent = `Page ${pagination.page} of ${pagination.total_pages}`;
        
        paginationContainer.style.display = pagination.total_pages > 1 ? 'flex' : 'none';
    }
    
    updateResultsSummary() {
        const summary = document.getElementById('results-summary');
        const start = (this.state.currentPage - 1) * this.state.pageSize + 1;
        const end = Math.min(start + this.state.datasets.length - 1, this.state.totalResults);
        
        summary.textContent = `Showing ${start}-${end} of ${this.state.totalResults} datasets`;
    }
    
    async updateStats() {
        try {
            const response = await fetch(`${this.apiBase}?action=stats`);
            const data = await response.json();
            
            if (data.success) {
                const stats = data.data.real_time;
                document.getElementById('total-count').textContent = stats.total_datasets;
                document.getElementById('filtered-count').textContent = this.state.totalResults || stats.total_datasets;
                document.getElementById('quality-avg').textContent = `${Math.round(stats.avg_quality * 100)}%`;
                document.getElementById('recent-count').textContent = stats.recent_datasets;
            }
        } catch (error) {
            console.error('Error updating stats:', error);
        }
    }
    
    showLoading() {
        const container = document.getElementById('datasets-grid');
        container.innerHTML = `
            <div class="loading-container">
                <div class="loading-spinner"></div>
                <div>Loading datasets...</div>
            </div>
        `;
    }
    
    showError(message) {
        const container = document.getElementById('datasets-grid');
        container.innerHTML = `<div class="error-message">${message}</div>`;
    }
}

// Global instance
let navigator;

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    navigator = new EnhancedNavigator();
    
    // Make openDatasetDetail globally available for onclick handlers
    window.navigator = navigator;
});