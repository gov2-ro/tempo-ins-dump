// Dimension Index Explorer JavaScript - Server-side API Version

class DimensionExplorer {
    constructor() {
        this.apiBase = 'api.php';
        this.cache = new Map();
        this.cacheTTL = 300000; // 5 minutes in milliseconds
        
        this.initializeApp();
    }
    
    async initializeApp() {
        try {
            this.showLoading(true);
            await this.loadInitialData();
            this.setupEventListeners();
            await this.populateFileFilter();
            await this.showStats();
        } catch (error) {
            console.error('Failed to initialize app:', error);
            this.showError('Failed to connect to the dimension API. Please check if the server is running.');
        } finally {
            this.showLoading(false);
        }
    }
    
    async loadInitialData() {
        // Load basic stats to verify API connection
        const stats = await this.apiCall('stats');
        console.log('API connected:', stats);
    }
    
    async apiCall(action, params = {}) {
        const cacheKey = `${action}_${JSON.stringify(params)}`;
        
        // Check cache first
        if (this.cache.has(cacheKey)) {
            const cached = this.cache.get(cacheKey);
            if (Date.now() - cached.timestamp < this.cacheTTL) {
                return cached.data;
            }
        }
        
        // Build URL
        const url = new URL(this.apiBase, window.location.href);
        url.searchParams.set('action', action);
        
        Object.entries(params).forEach(([key, value]) => {
            if (value !== null && value !== undefined && value !== '') {
                url.searchParams.set(key, value);
            }
        });
        
        try {
            const response = await fetch(url.toString());
            const result = await response.json();
            
            if (!result.success) {
                throw new Error(result.error || 'API request failed');
            }
            
            // Cache successful response
            this.cache.set(cacheKey, {
                data: result.data,
                timestamp: Date.now()
            });
            
            return result.data;
            
        } catch (error) {
            console.error('API call failed:', error);
            throw error;
        }
    }
    
    setupEventListeners() {
        const searchInput = document.getElementById('searchInput');
        
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
                const query = e.target.value.trim();
                if (query.length >= 2 || query.length === 0) {
                    this.performSearch();
                }
            }, 400); // Slightly longer delay for server requests
        });
    }
    
    async populateFileFilter() {
        try {
            const files = await this.apiCall('files');
            const fileFilter = document.getElementById('fileFilter');
            
            // Clear existing options except "All Files"
            while (fileFilter.children.length > 1) {
                fileFilter.removeChild(fileFilter.lastChild);
            }
            
            files.forEach(fileId => {
                const option = document.createElement('option');
                option.value = fileId;
                option.textContent = fileId;
                fileFilter.appendChild(option);
            });
        } catch (error) {
            console.error('Failed to load files:', error);
        }
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
        resultsDiv.classList.remove('hidden');
    }
    
    async showStats() {
        try {
            this.hideAllPanels();
            this.showLoading(true);
            
            const stats = await this.apiCall('stats');
            
            const statsPanel = document.getElementById('stats');
            statsPanel.classList.remove('hidden');
            
            // Update stat values
            document.getElementById('totalFiles').textContent = stats.total_files || 0;
            document.getElementById('totalDimensions').textContent = stats.total_dimensions || 0;
            document.getElementById('totalOptions').textContent = stats.total_options || 0;
            
            if (stats.last_updated) {
                const updateDate = new Date(stats.last_updated).toLocaleString();
                document.getElementById('exportTime').textContent = updateDate;
            }
            
            // Update data info in footer
            const dataInfo = document.getElementById('dataInfo');
            if (stats.last_updated) {
                const updateDate = new Date(stats.last_updated).toLocaleString();
                dataInfo.textContent = `Last updated: ${updateDate}`;
            }
            
        } catch (error) {
            console.error('Failed to load stats:', error);
            this.showError('Failed to load statistics');
        } finally {
            this.showLoading(false);
        }
    }
    
    async performSearch() {
        const searchTerm = document.getElementById('searchInput').value.trim();
        const searchType = document.getElementById('searchType').value;
        const fileFilter = document.getElementById('fileFilter').value;
        
        this.hideAllPanels();
        
        if (!searchTerm) {
            this.showWelcomeMessage();
            return;
        }
        
        if (searchTerm.length < 2) {
            this.showError('Search query must be at least 2 characters long.');
            return;
        }
        
        try {
            this.showLoading(true);
            
            const results = await this.apiCall('search', {
                query: searchTerm,
                type: searchType,
                file: fileFilter
            });
            
            this.displaySearchResults(results, searchTerm);
            
        } catch (error) {
            console.error('Search failed:', error);
            this.showError('Search failed. Please try again.');
        } finally {
            this.showLoading(false);
        }
    }
    
    displaySearchResults(results, searchTerm) {
        const resultsDiv = document.getElementById('results');
        
        if (results.total_count === 0) {
            resultsDiv.innerHTML = `
                <div class="no-results">
                    <h3>No results found</h3>
                    <p>No dimensions or options match "${searchTerm}". Try a different search term.</p>
                </div>
            `;
            resultsDiv.classList.remove('hidden');
            return;
        }
        
        let html = `
            <div class="results-header">
                <h3 class="results-title">Search Results for "${searchTerm}"</h3>
                <span class="results-count">${results.total_count} result${results.total_count !== 1 ? 's' : ''}</span>
            </div>
        `;
        
        // Display dimension results
        if (results.dimensions && results.dimensions.length > 0) {
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
                        <td><span class="file-id" onclick="showFileDetails('${dim.file_id}')" style="cursor: pointer; text-decoration: underline;">${dim.file_id}</span></td>
                        <td><span class="matrix-name">${dim.matrix_name}</span></td>
                    </tr>
                `;
            });
            
            html += '</tbody></table></div>';
        }
        
        // Display option results
        if (results.options && results.options.length > 0) {
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
                        <td><span class="dimension-label">${opt.dimension_label || 'Unknown'}</span></td>
                        <td><span class="file-id" onclick="showFileDetails('${opt.file_id}')" style="cursor: pointer; text-decoration: underline;">${opt.file_id}</span></td>
                        <td><span class="matrix-name">${opt.matrix_name || 'Unknown'}</span></td>
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
        
        const regex = new RegExp(`(${searchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
        return text.replace(regex, '<mark>$1</mark>');
    }
    
    async showSummary() {
        try {
            this.hideAllPanels();
            this.showLoading(true);
            
            const summary = await this.apiCall('summary');
            
            const resultsDiv = document.getElementById('results');
            let html = `
                <div class="results-header">
                    <h3 class="results-title">📋 File Summary</h3>
                    <span class="results-count">${summary.length} files</span>
                </div>
            `;
            
            summary.forEach(file => {
                html += `
                    <div class="file-details">
                        <h4>${file.file_id}</h4>
                        <p class="matrix-title">${file.matrix_name}</p>
                        <div style="margin-bottom: 15px;">
                            <strong>Dimensions:</strong> ${file.dimension_count} | 
                            <strong>Total Options:</strong> ${file.option_count}
                        </div>
                        <div style="text-align: center;">
                            <button onclick="showFileDetails('${file.file_id}')" class="action-btn" style="margin: 5px;">
                                📋 View Details
                            </button>
                        </div>
                    </div>
                `;
            });
            
            resultsDiv.innerHTML = html;
            resultsDiv.classList.remove('hidden');
            
        } catch (error) {
            console.error('Failed to load summary:', error);
            this.showError('Failed to load file summary');
        } finally {
            this.showLoading(false);
        }
    }
    
    async showDimensionUsage() {
        try {
            this.hideAllPanels();
            this.showLoading(true);
            
            const usage = await this.apiCall('usage');
            
            const resultsDiv = document.getElementById('results');
            let html = `
                <div class="results-header">
                    <h3 class="results-title">📊 Dimension Usage</h3>
                    <span class="results-count">${usage.length} unique dimensions</span>
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
            
            usage.forEach(dim => {
                const fileList = dim.files.join(', ');
                html += `
                    <tr>
                        <td><span class="dimension-label">${dim.label}</span></td>
                        <td><span class="file-count">${dim.file_count} file${dim.file_count !== 1 ? 's' : ''}</span></td>
                        <td><span class="file-list">${fileList}</span></td>
                    </tr>
                `;
            });
            
            html += '</tbody></table>';
            
            resultsDiv.innerHTML = html;
            resultsDiv.classList.remove('hidden');
            
        } catch (error) {
            console.error('Failed to load dimension usage:', error);
            this.showError('Failed to load dimension usage');
        } finally {
            this.showLoading(false);
        }
    }
    
    async showFileDetails(fileId) {
        try {
            this.hideAllPanels();
            this.showLoading(true);
            
            const fileDetails = await this.apiCall('file_details', { file_id: fileId });
            
            const resultsDiv = document.getElementById('results');
            let html = `
                <div class="results-header">
                    <h3 class="results-title">📋 File Details: ${fileDetails.file_id}</h3>
                    <span class="results-count">${fileDetails.dimension_count} dimensions, ${fileDetails.total_options} options</span>
                </div>
                
                <div class="file-details">
                    <h4>${fileDetails.file_id}</h4>
                    <p class="matrix-title">${fileDetails.matrix_name}</p>
                    <div class="dimensions-list">
            `;
            
            fileDetails.dimensions.forEach(dim => {
                html += `
                    <div class="dimension-item">
                        <div class="dimension-header">
                            ${dim.label} 
                            <span class="dimension-code">(Code: ${dim.dim_code})</span>
                        </div>
                        <div><strong>Options (${dim.options.length}):</strong></div>
                        <div class="options-list">
                `;
                
                const optionsToShow = dim.options.slice(0, 15);
                optionsToShow.forEach(opt => {
                    html += `<span class="option-tag">${opt.label}</span>`;
                });
                
                if (dim.options.length > 15) {
                    html += `<span class="option-tag">... and ${dim.options.length - 15} more</span>`;
                }
                
                html += '</div></div>';
            });
            
            html += '</div></div>';
            
            resultsDiv.innerHTML = html;
            resultsDiv.classList.remove('hidden');
            
        } catch (error) {
            console.error('Failed to load file details:', error);
            this.showError(`Failed to load details for file: ${fileId}`);
        } finally {
            this.showLoading(false);
        }
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

function showFileDetails(fileId) {
    explorer.showFileDetails(fileId);
}

// Initialize the app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    explorer = new DimensionExplorer();
});
