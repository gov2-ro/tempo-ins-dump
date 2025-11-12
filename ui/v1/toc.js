// CSV Parser function
function parseCsv(csv) {
    const lines = csv.split('\n');
    const headers = lines[0].split(',').map(header => header.trim());
    
    return lines.slice(1)
        .filter(line => line.trim()) // Skip empty lines
        .map(line => {
            // Handle quoted fields properly
            const values = [];
            let inQuotes = false;
            let currentValue = '';
            
            for (let char of line) {
                if (char === '"') {
                    inQuotes = !inQuotes;
                } else if (char === ',' && !inQuotes) {
                    values.push(currentValue);
                    currentValue = '';
                } else {
                    currentValue += char;
                }
            }
            values.push(currentValue); // Don't forget the last value
            
            // Create object from headers and values
            return headers.reduce((obj, header, index) => {
                const value = values[index] ? values[index].replace(/^["']|["']$/g, '').trim() : '';
                obj[header] = value;
                return obj;
            }, {});
        });
}

// Function to transform flat data into hierarchical structure
function buildHierarchy(categories) {
    const hierarchy = [];
    const lookup = {};
    
    // First pass: create lookup table and identify root nodes
    categories.forEach(category => {
        if (category.level === '0') return;
        
        lookup[category.code] = {
            ...category,
            children: [],
            datasets: []
        };
        
        if (!category.parentCode) {
            hierarchy.push(lookup[category.code]);
        }
    });
    
    // Second pass: build hierarchy
    categories.forEach(category => {
        if (category.level === '0' || !category.parentCode) return;
        
        const parent = lookup[category.parentCode];
        if (parent) {
            parent.children.push(lookup[category.code]);
        }
    });
    
    return { hierarchy, lookup };
}

// Function to add datasets to their respective categories
function addDatasetsToCategories(datasets, lookup) {
    datasets.forEach(dataset => {
        const parentCategory = lookup[dataset.directAncestor];
        if (parentCategory) {
            parentCategory.datasets.push(dataset);
        }
    });
}

// Function to generate HTML for the table of contents
function generateTocHtml(node) {
    let html = '';
    
    // Generate heading based on level
    if (node.level) {
        const levelClass = `level-${node.level}`;
        html += `<div class="${levelClass}">
            <h${node.level} id="x-${node.code}">
                <span class="code">${node.code}</span>
                ${node.name}
            </h${node.level}>
        </div>\n`;
    }
    
    // Add datasets if any
    if (node.datasets && node.datasets.length > 0) {
        // console.log(node.datasets)   
        html += '<ul class="datasets">\n';
        node.datasets.sort((a, b) => a.fileName.localeCompare(b.fileName));
        node.datasets.forEach(dataset => {
            
            html += `  <li>
                <span class="code"><a class="ccode" href="dataset.html#${dataset.fileName}">${dataset.fileName}</a></span>
                <a class="cname" href="dataset.html#${dataset.fileName}">${dataset.matrixName}</a> <code>(${convertSize(dataset.filesize)})</code>
                
            </li>\n`;
        });
        html += '</ul>\n';
    }
    
    // Recursively process children
    if (node.children && node.children.length > 0) {
        // Sort children by code
        node.children.sort((a, b) => a.code.localeCompare(b.code));
        
        html += '<ul class="categories">\n';
        node.children.forEach(child => {
            html += '<li class="lx-' + node.level +'">\n';
            html += generateTocHtml(child);
            html += '</li>\n';
        });
        html += '</ul>\n';
    }
    
    return html;
}
 
function convertSize(human) {
    // const units = ['B', 'K', 'M', 'G', 'T'];
    // let size = parseFloat(human.replace(/[^0-9.]/g, ''));
    let size = parseFloat(human.replace(/[^0-9.]/g, ''));
 
    // Convert human-readable string to bytes
    // um = human.toLowerCase().slice(-1)
    um = human.slice(-1)
    switch (um) {
        case 'B':
            zz = size / 1000;
        case 'K':
            zz = size;
        case 'M':
            zz = size * 1000;
        case 'G':
            zz = size * 1000 * 1000;
        case 'T':
            zz = size * 1000 * 1000 * 1000;
        default:
            // throw new Error('Invalid unit');
            zz = size
    }
    ismuch = '  '
    if(um=='M' || um=='K' || (um=='B' && size >= 500)) {
        ismuch = ' not-much '
    }
    if(um=='M' && size >= 4.2) {
        ismuch = ' is-much '
    }

    return '<span class="size-'+um+ ismuch +'">' + zz + um +'</span>'
}

// Main function to initialize the table of contents
async function initializeTableOfContents() {
    try {
        // Load CSV files
        const [categoriesResponse, datasetsResponse] = await Promise.all([
            fetch('data/x-categories0.csv'),
            fetch('data/x-datasets-size.csv')
        ]);

        if (!categoriesResponse.ok || !datasetsResponse.ok) {
            throw new Error('Failed to load CSV files');
        }

        const [categoriesCsv, datasetsCsv] = await Promise.all([
            categoriesResponse.text(),
            datasetsResponse.text()
        ]);

        // Parse CSV data
        const categories = parseCsv(categoriesCsv);
        const datasets = parseCsv(datasetsCsv);

        // Build hierarchy and get lookup
        const { hierarchy, lookup } = buildHierarchy(categories);

        // Sort root level items by code
        hierarchy.sort((a, b) => a.code.localeCompare(b.code));

        // Add datasets to categories
        addDatasetsToCategories(datasets, lookup);

        // Generate HTML
        let tocHtml = '<div class="table-of-contents">\n';
        hierarchy.forEach(node => {
            tocHtml += generateTocHtml(node);
        });
        tocHtml += '</div>';

        // Insert into document
        document.getElementById('toc-container').innerHTML = tocHtml;
        addSearch();

    } catch (error) {
        console.error('Error loading table of contents:', error);
        document.getElementById('toc-container').innerHTML = `
            <div class="error">
                Error loading table of contents: ${error.message}
                <br>Please check that the CSV files are available and properly formatted.
            </div>
        `;
    }
}

// Add required CSS for autocomplete
// const style = document.createElement('style');
// style.textContent = ``;
// document.head.appendChild(style);

// Function to build search index
function buildSearchIndex() {
    const searchItems = [];
    
    // Index headers
    document.querySelectorAll('[id^="x-"]').forEach(header => {
        const code = header.querySelector('.code')?.textContent || '';
        const name = header.textContent.replace(code, '').trim();
        searchItems.push({
            type: 'header',
            code,
            name,
            element: header,
            text: `${code} ${name}`,
            id: header.id
        });
    });
    
    // Index dataset links
    document.querySelectorAll('.datasets li').forEach(item => {
        const code = item.querySelector('.ccode')?.textContent || '';
        const name = item.querySelector('.cname')?.textContent || '';
        const link = item.querySelector('a')?.href;
        searchItems.push({
            type: 'dataset',
            code,
            name,
            link,
            text: `${code} ${name}`
        });
    });
    
    return searchItems;
}

// Function to add search functionality
function addSearch() {
    const searchContainer = document.createElement('div');
    searchContainer.className = 'search-container';
    searchContainer.innerHTML = `
        <input type="text" class="search-input" placeholder="Caută în capitole și seturi de date">
        <div class="autocomplete-items" style="display: none;"></div>
    `;
    
    // Insert before the table of contents
    const tocContainer = document.getElementById('toc-container');
    tocContainer.parentNode.insertBefore(searchContainer, tocContainer);
    
    const searchInput = searchContainer.querySelector('.search-input');
    const autocompleteList = searchContainer.querySelector('.autocomplete-items');
    const searchIndex = buildSearchIndex();
    
    // Function to highlight match in text
    function highlightMatch(text, query) {
        if (!query) return text;
        const regex = new RegExp(`(${query})`, 'gi');
        return text.replace(regex, '<strong>$1</strong>');
    }
    
    // Function to handle search and show results
    function handleSearch() {
        const query = searchInput.value.toLowerCase();
        if (!query) {
            autocompleteList.style.display = 'none';
            return;
        }
        
        const matches = searchIndex.filter(item => 
            item.text.toLowerCase().includes(query)
        ).slice(0, 30); // Limit to 10 results
        
        if (matches.length === 0) {
            autocompleteList.style.display = 'none';
            return;
        }
        
        autocompleteList.innerHTML = matches.map(item => `
            <div class="autocomplete-item" data-type="${item.type}" ${
                item.type === 'header' ? `data-id="${item.id}"` :
                item.type === 'dataset' ? `data-link="${item.link}"` : ''
            }>
                <span class="type-indicator type-${item.type}">${item.type}</span>
                ${highlightMatch(item.code, query)} - ${highlightMatch(item.name, query)}
            </div>
        `).join('');
        
        autocompleteList.style.display = 'block';
    }
    
    // Handle click on autocomplete item
    autocompleteList.addEventListener('click', (e) => {
        const item = e.target.closest('.autocomplete-item');
        if (!item) return;
        
        if (item.dataset.type === 'header') {
            const element = document.getElementById(item.dataset.id);
            element.scrollIntoView({ behavior: 'smooth', block: 'start' });
            // Add a brief highlight effect
            element.style.backgroundColor = '#fff3cd';
            setTimeout(() => element.style.backgroundColor = '', 2000);
        } else if (item.dataset.type === 'dataset') {
            window.location.href = item.dataset.link;
        }
        
        searchInput.value = '';
        autocompleteList.style.display = 'none';
    });
    
    // Handle input events
    searchInput.addEventListener('input', handleSearch);
    
    // Close autocomplete when clicking outside
    document.addEventListener('click', (e) => {
        if (!searchContainer.contains(e.target)) {
            autocompleteList.style.display = 'none';
        }
    });
    
    // Handle keyboard navigation
    searchInput.addEventListener('keydown', (e) => {
        const items = autocompleteList.getElementsByClassName('autocomplete-item');
        const activeItem = document.querySelector('.autocomplete-item.active');
        let index = Array.from(items).indexOf(activeItem);
        
        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                if (index < items.length - 1) index++;
                break;
            case 'ArrowUp':
                e.preventDefault();
                if (index > 0) index--;
                break;
            case 'Enter':
                e.preventDefault();
                if (activeItem) activeItem.click();
                return;
            default:
                return;
        }
        
        Array.from(items).forEach(item => item.classList.remove('active'));
        if (items[index]) {
            items[index].classList.add('active');
            items[index].scrollIntoView({ block: 'nearest' });
        }
    });
}

// Initialize when the document is ready
document.addEventListener('DOMContentLoaded', initializeTableOfContents);