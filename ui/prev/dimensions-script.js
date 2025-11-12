// Dimension Index Explorer JavaScript

class DimensionExplorer {
    constructor() {
        this.data = null;
        this.dimensions = [];
        this.options = [];
        this.filteredResults = [];
        
        this.initializeApp();
    }
    
    async initializeApp() {
        try {
            this.showLoading(true);
            await this.loadData();
            this.setupEventListeners();
            this.populateFileFilter();
            this.showStats();
            this.updateDataInfo();
        } catch (error) {
            console.error('Failed to initialize app:', error);
            this.showError('Failed to load dimension data. Please check if the data file exists.');
        } finally {
            this.showLoading(false);
        }
    }
    
    async loadData() {
        const response = await fetch('data/dimension_index.json');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        this.data = await response.json();
        this.dimensions = this.data.dimensions || [];
        this.options = this.data.options || [];
        
        console.log('Data loaded:', {
            dimensions: this.dimensions.length,
            options: this.options.length,
            files: this.data.stats?.total_files
        });
    }
    
    setupEventListeners() {
        const searchInput = document.getElementById('searchInput');
        const searchBtn = document.getElementById('searchBtn');
        
        // Search on Enter key
        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.performSearch();
            }
        });
        
        // Real-time search (debounced)
        let searchTimeout;
        searchInput.addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                if (e.target.value.length >= 2 || e.target.value.length === 0) {
                    this.performSearch();
                }
            }, 300);
        });
    }
    
    populateFileFilter() {
        const fileFilter = document.getElementById('fileFilter');
        const uniqueFiles = [...new Set(this.dimensions.map(d => d.file_id))].sort();
        
        uniqueFiles.forEach(fileId => {
            const option = document.createElement('option');
            option.value = fileId;
            option.textContent = fileId;
            fileFilter.appendChild(option);
        });
    }
    
    showLoading(show) {
        const loading = document.getElementById('loading');
        loading.classList.toggle('hidden', !show);
    }
    
    showError(message) {
        const resultsDiv = document.getElementById('results');
        resultsDiv.innerHTML = `
            <div class="error-message">
                <strong>Error:</strong>
                <p>${message}</p>
            </div>
        `;
    }
    
    updateDataInfo() {
        const dataInfo = document.getElementById('dataInfo');
        if (this.data?.export_timestamp) {
            const exportDate = new Date(this.data.export_timestamp).toLocaleString();
            dataInfo.textContent = `Last updated: ${exportDate}`;
        }
    }
    
    showStats() {
        const statsPanel = document.getElementById('stats');
        const resultsDiv = document.getElementById('results');
        
        // Hide results, show stats
        resultsDiv.classList.add('hidden');
        statsPanel.classList.remove('hidden');
        
        // Update stat values
        document.getElementById('totalFiles').textContent = this.data.stats?.total_files || 0;
        document.getElementById('totalDimensions').textContent = this.data.stats?.total_dimensions || 0;
        document.getElementById('totalOptions').textContent = this.data.stats?.total_options || 0;
        
        if (this.data?.export_timestamp) {
            const exportDate = new Date(this.data.export_timestamp).toLocaleString();
            document.getElementById('exportTime').textContent = exportDate;
        }
    }
    
    performSearch() {
        const searchTerm = document.getElementById('searchInput').value.trim();
        const searchType = document.getElementById('searchType').value;
        const fileFilter = document.getElementById('fileFilter').value;
        
        this.hideAllPanels();
        
        if (!searchTerm) {
            this.showWelcomeMessage();
            return;
        }
        
        const results = this.searchData(searchTerm, searchType, fileFilter);
        this.displaySearchResults(results, searchTerm);
    }
    
    searchData(searchTerm, searchType, fileFilter) {
        const term = searchTerm.toLowerCase();
        const results = {
            dimensions: [],
            options: []
        };
        
        // Search dimensions
        if (searchType === 'all' || searchType === 'dimensions') {
            results.dimensions = this.dimensions.filter(dim => {
                const matchesSearch = dim.label.toLowerCase().includes(term);
                const matchesFile = !fileFilter || dim.file_id === fileFilter;
                return matchesSearch && matchesFile;
            });
        }
        
        // Search options
        if (searchType === 'all' || searchType === 'options') {
            results.options = this.options.filter(opt => {
                const matchesSearch = opt.label.toLowerCase().includes(term);
                const matchesFile = !fileFilter || opt.file_id === fileFilter;
                return matchesSearch && matchesFile;
            }).map(opt => {
                // Add dimension info to each option
                const dimension = this.dimensions.find(d => d.id === opt.dimension_id);
                return { ...opt, dimension };
            });
        }
        
        return results;
    }
    
    displaySearchResults(results, searchTerm) {
        const resultsDiv = document.getElementById('results');
        const totalResults = results.dimensions.length + results.options.length;
        
        if (totalResults === 0) {
            resultsDiv.innerHTML = `
                <div class="no-results">
                    <h3>No results found</h3>
                    <p>No dimensions or options match "${searchTerm}". Try a different search term.</p>
                </div>
            `;
            return;
        }
        
        let html = `
            <div class="results-header">
                <h3 class="results-title">Search Results for "${searchTerm}"</h3>
                <span class="results-count">${totalResults} result${totalResults !== 1 ? 's' : ''}</span>
            </div>
        `;
        
        // Display dimension results
        if (results.dimensions.length > 0) {
            html += `
                <div class="results-section">
                    <h4>📊 Dimensions (${results.dimensions.length})</h4>
                    <table class="results-table">
                        <thead>
                            <tr>
                                <th>Dimension</th>
                                <th>Code</th>
                                <th>File ID</th>
                                <th>Matrix</th>
                            </tr>
                        </thead>
                        <tbody>
            `;
            
            results.dimensions.forEach(dim => {
                html += `
                    <tr>
                        <td><span class="dimension-label">${this.highlightText(dim.label, searchTerm)}</span></td>
                        <td>${dim.dim_code}</td>
                        <td><span class="file-id">${dim.file_id}</span></td>
                        <td><span class="matrix-name">${dim.matrix_name}</span></td>
                    </tr>
                `;
            });
            
            html += '</tbody></table></div>';
        }
        
        // Display option results
        if (results.options.length > 0) {
            html += `
                <div class="results-section mt-20">
                    <h4>🔸 Options (${results.options.length})</h4>
                    <table class="results-table">
                        <thead>
                            <tr>
                                <th>Option</th>
                                <th>Dimension</th>
                                <th>File ID</th>
                                <th>Matrix</th>
                            </tr>
                        </thead>
                        <tbody>
            `;
            
            results.options.forEach(opt => {
                html += `
                    <tr>
                        <td><span class="option-label">${this.highlightText(opt.label, searchTerm)}</span></td>
                        <td><span class="dimension-label">${opt.dimension?.label || 'Unknown'}</span></td>
                        <td><span class="file-id">${opt.file_id}</span></td>
                        <td><span class="matrix-name">${opt.dimension?.matrix_name || 'Unknown'}</span></td>
                    </tr>
                `;
            });
            
            html += '</tbody></table></div>';
        }
        
        resultsDiv.innerHTML = html;
        resultsDiv.classList.remove('hidden');
    }
    
    highlightText(text, searchTerm) {
        if (!searchTerm) return text;
        
        const regex = new RegExp(`(${searchTerm})`, 'gi');
        return text.replace(regex, '<mark>$1</mark>');
    }
    
    showSummary() {
        this.hideAllPanels();
        
        // Group dimensions by file
        const fileGroups = {};
        this.dimensions.forEach(dim => {
            if (!fileGroups[dim.file_id]) {
                fileGroups[dim.file_id] = {
                    file_id: dim.file_id,
                    matrix_name: dim.matrix_name,
                    dimensions: []
                };
            }
            
            // Get options for this dimension
            const dimensionOptions = this.options.filter(opt => opt.dimension_id === dim.id);
            
            fileGroups[dim.file_id].dimensions.push({
                ...dim,
                options: dimensionOptions
            });
        });
        
        const resultsDiv = document.getElementById('results');
        let html = `
            <div class="results-header">
                <h3 class="results-title">📋 File Summary</h3>
                <span class="results-count">${Object.keys(fileGroups).length} files</span>
            </div>
        `;
        
        Object.values(fileGroups).sort((a, b) => a.file_id.localeCompare(b.file_id)).forEach(fileGroup => {
            const totalOptions = fileGroup.dimensions.reduce((sum, dim) => sum + dim.options.length, 0);
            
            html += `
                <div class="file-details">
                    <h4>${fileGroup.file_id}</h4>
                    <p class="matrix-title">${fileGroup.matrix_name}</p>
                    <div style="margin-bottom: 15px;">
                        <strong>Dimensions:</strong> ${fileGroup.dimensions.length} | 
                        <strong>Total Options:</strong> ${totalOptions}
                    </div>
                    <div class="dimensions-list">
            `;
            
            fileGroup.dimensions.forEach(dim => {
                html += `
                    <div class="dimension-item">
                        <div class="dimension-header">
                            ${dim.label} 
                            <span class="dimension-code">(Code: ${dim.dim_code})</span>
                        </div>
                        <div><strong>Options (${dim.options.length}):</strong></div>
                        <div class="options-list">
                `;
                
                dim.options.slice(0, 10).forEach(opt => {
                    html += `<span class="option-tag">${opt.label}</span>`;
                });
                
                if (dim.options.length > 10) {
                    html += `<span class="option-tag">... and ${dim.options.length - 10} more</span>`;
                }
                
                html += '</div></div>';
            });
            
            html += '</div></div>';
        });
        
        resultsDiv.innerHTML = html;
        resultsDiv.classList.remove('hidden');
    }
    
    showDimensionUsage() {
        this.hideAllPanels();
        
        // Group dimensions by label
        const dimensionGroups = {};
        this.dimensions.forEach(dim => {
            if (!dimensionGroups[dim.label]) {
                dimensionGroups[dim.label] = {
                    label: dim.label,
                    files: new Set(),
                    fileDetails: []
                };
            }
            dimensionGroups[dim.label].files.add(dim.file_id);
            dimensionGroups[dim.label].fileDetails.push({
                file_id: dim.file_id,
                matrix_name: dim.matrix_name
            });
        });
        
        // Convert to array and sort by usage count
        const sortedDimensions = Object.values(dimensionGroups)
            .map(group => ({
                ...group,
                fileCount: group.files.size,
                fileList: Array.from(group.files).sort().join(', ')
            }))
            .sort((a, b) => b.fileCount - a.fileCount);
        
        const resultsDiv = document.getElementById('results');
        let html = `
            <div class="results-header">
                <h3 class="results-title">📊 Dimension Usage</h3>
                <span class="results-count">${sortedDimensions.length} unique dimensions</span>
            </div>
            <table class="usage-table">
                <thead>
                    <tr>
                        <th>Dimension Label</th>
                        <th>Usage</th>
                        <th>Found in Files</th>
                    </tr>
                </thead>
                <tbody>
        `;
        
        sortedDimensions.forEach(dim => {
            html += `
                <tr>
                    <td><span class="dimension-label">${dim.label}</span></td>
                    <td><span class="file-count">${dim.fileCount} file${dim.fileCount !== 1 ? 's' : ''}</span></td>
                    <td><span class="file-list">${dim.fileList}</span></td>
                </tr>
            `;
        });
        
        html += '</tbody></table>';
        
        resultsDiv.innerHTML = html;
        resultsDiv.classList.remove('hidden');
    }
    
    clearSearch() {
        document.getElementById('searchInput').value = '';
        document.getElementById('searchType').value = 'all';
        document.getElementById('fileFilter').value = '';
        this.showWelcomeMessage();
    }
    
    showWelcomeMessage() {
        this.hideAllPanels();
        const resultsDiv = document.getElementById('results');
        resultsDiv.innerHTML = `
            <div class="welcome-message">
                <h3>🎯 Welcome to Dimension Index Explorer</h3>
                <p>This tool helps you search through statistical dimension metadata from Tempo INS data files.</p>
                <ul>
                    <li><strong>Search</strong> for specific dimensions or options</li>
                    <li><strong>Filter</strong> by file or search type</li>
                    <li><strong>Explore</strong> file summaries and dimension usage patterns</li>
                </ul>
                <p class="tip">💡 <strong>Tip:</strong> Try searching for terms like "Perioade", "Bucuresti", or "Grade Celsius"</p>
            </div>
        `;
        resultsDiv.classList.remove('hidden');
    }
    
    hideAllPanels() {
        document.getElementById('stats').classList.add('hidden');
        document.getElementById('results').classList.add('hidden');
    }
}

// Global functions for button onclick handlers
let explorer;

function performSearch() {
    explorer.performSearch();
}

function clearSearch() {
    explorer.clearSearch();
}

function showSummary() {
    explorer.showSummary();
}

function showDimensionUsage() {
    explorer.showDimensionUsage();
}

function showStats() {
    explorer.showStats();
}

// Initialize the app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    explorer = new DimensionExplorer();
});
