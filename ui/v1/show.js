// Parse CSV content handling quoted values and escapes
function parseCSV(csv) {
    const lines = csv.split(/\r\n|\n/);
    const result = [];
    let inQuotes = false;
    let currentField = '';
    let currentLine = [];

    function pushField() {
        currentLine.push(currentField.trim());
        currentField = '';
    }

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        
        if (!line.trim() && i > 0) continue; // Skip empty lines except header

        for (let char of line) {
            if (char === '"') {
                if (inQuotes && line[i + 1] === '"') {
                    // Handle escaped quotes
                    currentField += '"';
                    i++;
                } else {
                    // Toggle quotes mode
                    inQuotes = !inQuotes;
                }
            } else if (char === ',' && !inQuotes) {
                pushField();
            } else {
                currentField += char;
            }
        }
        
        pushField();
        result.push(currentLine);
        currentLine = [];
    }

    return result;
}

// Initialize DataTable with dynamic columns
function initializeDataTable(data) {
    // Filter out regional rows
    const filteredData = filterOutRegionalRows(data);
    const headers = filteredData[0];
    const rows = filteredData.slice(1);

    // Configure columns
    const columns = headers.map(header => ({
        title: header,
        data: header
    }));

    // Transform data into objects
    const tableData = rows.map(row => {
        const obj = {};
        headers.forEach((header, index) => {
            obj[header] = row[index];
        });
        return obj;
    });

    // Destroy existing DataTable if it exists
    if ($.fn.DataTable.isDataTable('#dataset-table')) {
        $('#dataset-table').DataTable().destroy();
    }

    // Create table element if it doesn't exist
    if (!$('#dataset-table').length) {
        $('#table-container').html('<table id="dataset-table" class="display" width="100%"></table>');
    }

    // Initialize DataTable
    $('#dataset-table').DataTable({
        data: tableData,
        columns: columns,
        pageLength: 25,
        lengthMenu: [[10, 25, 50, 100, -1], [10, 25, 50, 100, "All"]],
        order: [], // Disable initial sorting
        responsive: true,
        dom: '<"top"lf>rt<"bottom"ip>',
        language: {
            search: "Filter:",
            lengthMenu: "Show _MENU_ entries",
            info: "Showing _START_ to _END_ of _TOTAL_ entries",
            infoEmpty: "Showing 0 to 0 of 0 entries",
            infoFiltered: "(filtered from _MAX_ total entries)"
        },
        initComplete: function() {
            $('.dataTables_wrapper').addClass('full-width-table');
        }
    });
}

// Load and process CSV file
 async function loadDataset() {
    try {
        // Get dataset ID from URL hash
        const datasetId = window.location.hash.slice(1);
        if (!datasetId) {
            throw new Error('No dataset ID specified in URL');
        }

        // Update page title
        document.getElementById('dataset-title').textContent = `${datasetId}`;
        document.title = `Dataset: ${datasetId}`;

        // Fetch CSV file
        const response = await fetch(`data/csv/${datasetId}.csv`);
        if (!response.ok) {
            throw new Error(`Failed to load dataset (${response.status} ${response.statusText})`);
        }

        // Load CSV data
        const csvContent = await response.text();
        const data = parseCSV(csvContent);

        if (data.length === 0) {
            throw new Error('Dataset is empty');
        }

        // Initialize DataTable with filtered data
        initializeDataTable(data);

        // Convert filtered data to array of objects for chart
        const filteredData = filterOutRegionalRows(data);
        const headers = filteredData[0];
        const rows = filteredData.slice(1);
        const objectData = rows.map(row => {
            const obj = {};
            headers.forEach((header, index) => {
                obj[header] = row[index];
            });
            return obj;
        });
        await displayMetadata(datasetId);
        // Initialize chart with filtered data
        await initializeChart(objectData);

        // Load JSON metadata
        const response2 = await fetch(`data/matrices/${datasetId}.json`);
        if (!response2.ok) {
            throw new Error(`Failed to load dataset metadata (${response2.status} ${response2.statusText})`);
        }

        // Process JSON metadata
        const jsonContent = await response2.json();
        
        // Update page elements with metadata
        document.getElementById('ziname').innerHTML = jsonContent['matrixName'];
        document.getElementById('ziobs').innerHTML = '<small class="lh1">obs: ' + jsonContent['observatii'] + '</small>';
        document.getElementById('zidef').innerHTML = '<small class="lh1">' + jsonContent['definitie'] + '</small>' + '| <small class="lh1"><b>Sursă</b> date: ' + jsonContent['surseDeDate'][0]['nume'] + '</small>';
        document.getElementById('ziultimaActualizare').innerHTML = 'ultima actualizare: ' + jsonContent['ultimaActualizare'];
        document.getElementById('download').innerHTML = '<a class="dl" href="data/csv/' + datasetId + '.csv" download="' + datasetId + '.csv">download csv</a>  &darr;';
        document.getElementById('link2tempoins').innerHTML = '<a class="tempoins" href="http://statistici.insse.ro/tempoins/index.jsp?page=tempo3&lang=ro&ind=' + datasetId + '">tempoins</a>';
        document.getElementById('ancestors1').innerHTML = '<small>' + jsonContent['ancestors'][1]['code'] + '</small> ' + jsonContent['ancestors'][1]['name'];
        
        const rr = jsonContent['ancestors'][2]['name'];
        document.getElementById('ancestors2').innerHTML = '<small>' + jsonContent['ancestors'][2]['code'] + '</small> ' + rr;
        document.getElementById('ancestors3').innerHTML = '<small>' + jsonContent['ancestors'][3]['code'] + '</small> ' + jsonContent['ancestors'][3]['name'];
        
        // Update page title
        document.title = datasetId + ' - ' + jsonContent['matrixName'] + ' &middot; ' + document.title;

    } catch (error) {
        console.error('Error loading dataset:', error);
        document.getElementById('table-container').innerHTML = `
            <div class="error">
                Error loading dataset: ${error.message}
                <br>Please check that the CSV file exists and is properly formatted.
            </div>
        `;
    }
}

// Handle hash changes to load different datasets
window.addEventListener('hashchange', loadDataset);

// Initial load
document.addEventListener('DOMContentLoaded', loadDataset);

// Export functionality
function exportToCSV() {
    const table = $('#dataset-table').DataTable();
    const csvContent = table
        .data()
        .toArray()
        .map(row => Object.values(row).join(','))
        .join('\n');
    
    const headers = table.columns().header().toArray()
        .map(header => header.textContent)
        .join(',');

    const blob = new Blob([headers + '\n' + csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `dataset_${window.location.hash.slice(1)}_export.csv`;
    link.click();
}

// Add Chart.js to the page
function loadChartJS() {
    return new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = 'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js';
        script.onload = resolve;
        script.onerror = reject;
        document.head.appendChild(script);
    });
}

// Create and update the chart
function createYearlySumChart(data) {
    // Check if Sexe column exists
    const hasGenderData = data.some(row => 'Sexe' in row);
    
    if (!hasGenderData) {
        // Use original single bar implementation
        const yearlyTotals = data.reduce((acc, row) => {
            let year = row.Perioade.startsWith('Anul ') ? 
                row.Perioade.split(' ')[1] : 
                row.Perioade.includes('Trimestrul') ? 
                    row.Perioade.split(' ').pop() : null;
            
            if (year) {
                acc[year] = (acc[year] || 0) + parseInt(row.Valoare, 10);
            }
            return acc;
        }, {});

        // Rest of original single bar implementation...
        return createSingleBarChart(yearlyTotals);
    }
    function createSingleBarChart(yearlyTotals) {
        const yearlyData = Object.entries(yearlyTotals)
            .map(([year, value]) => ({ year, value }))
            .sort((a, b) => a.year - b.year);
    
        const chartContainer = document.getElementById('zichart');
        chartContainer.innerHTML = '<canvas id="yearlyBarChart"></canvas>';
    
        const ctx = document.getElementById('yearlyBarChart').getContext('2d');
        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: yearlyData.map(d => d.year),
                datasets: [{
                    label: 'Total',
                    data: yearlyData.map(d => d.value),
                    backgroundColor: '#4299E1',
                    borderColor: '#3182CE',
                    borderWidth: 1,
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return context.parsed.y.toLocaleString();
                            }
                        }
                    },
                    legend: {
                        display: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: function(value) {
                                return value.toLocaleString();
                            }
                        }
                    }
                }
            }
        });
    }
    // Group data by year and gender
    const yearlyGenderTotals = data.reduce((acc, row) => {
        let year;
        if (row.Perioade.startsWith('Anul ')) {
            year = row.Perioade.split(' ')[1];
        } else if (row.Perioade.includes('Trimestrul')) {
            year = row.Perioade.split(' ').pop();
        }
        
        if (year) {
            if (!acc[year]) {
                acc[year] = { Masculin: 0, Feminin: 0 };
            }
            acc[year][row.Sexe] += parseInt(row.Valoare, 10);
        }
        return acc;
    }, {});

    // Convert to arrays and sort by year
    const years = Object.keys(yearlyGenderTotals).sort();
    const masculinData = years.map(year => yearlyGenderTotals[year].Masculin);
    const femininData = years.map(year => yearlyGenderTotals[year].Feminin);

    // Clear existing chart
    const chartContainer = document.getElementById('zichart');
    chartContainer.innerHTML = '<canvas id="yearlyBarChart"></canvas>';

    // Create stacked bar chart
    const ctx = document.getElementById('yearlyBarChart').getContext('2d');
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: years,
            datasets: [
                {
                    label: 'Masculin',
                    data: masculinData,
                    backgroundColor: '#4299E1',
                    borderColor: '#3182CE',
                    borderWidth: 1,
                    borderRadius: 4
                },
                {
                    label: 'Feminin',
                    data: femininData,
                    backgroundColor: '#F56565',
                    borderColor: '#E53E3E',
                    borderWidth: 1,
                    borderRadius: 4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return `${context.dataset.label}: ${context.parsed.y.toLocaleString()}`;
                        }
                    }
                },
                legend: {
                    display: true,
                    position: 'top'
                }
            },
            scales: {
                x: {
                    stacked: true
                },
                y: {
                    stacked: true,
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return value.toLocaleString();
                        }
                    }
                }
            }
        }
    });
}

// Create and update the chart
function createYearlyChart(data) {
    // Filter for annual data and transform
    const yearlyData = data
        .filter(row => row.Perioade?.match(/^Anul \d{4}$/))
        .map(row => ({
            year: row.Perioade.split(' ')[1],
            value: parseInt(row.Valoare, 10)
        }))
        .sort((a, b) => a.year - b.year);

    // Clear existing chart if any
    const chartContainer = document.getElementById('zichart');
    chartContainer.innerHTML = '<canvas id="yearlyBarChart"></canvas>';

    // Create the chart
    const ctx = document.getElementById('yearlyBarChart').getContext('2d');
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: yearlyData.map(d => d.year),
            datasets: [{
                label: 'Annual Values',
                data: yearlyData.map(d => d.value),
                backgroundColor: '#4299E1',
                borderColor: '#3182CE',
                borderWidth: 1,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return context.parsed.y.toLocaleString();
                        }
                    }
                },
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return value.toLocaleString();
                        }
                    }
                }
            }
        }
    });
}

// Initialize chart when data is loaded
async function initializeChart(data) {
    try {
        await loadChartJS();
        createYearlySumChart(data);
        initializeCountyVisualization(data);
    } catch (error) {
        console.error('Error initializing chart:', error);
        document.getElementById('zichart').innerHTML = 
            '<div class="error">Error loading chart: ' + error.message + '</div>';
    }
}

function filterOutRegionalRows(data) {
    // First find column that contains both region and judet
    const headers = data[0];
    const regionColumn = headers.findIndex(header => 
        header.toLowerCase().includes('regiun') || 
        header.toLowerCase().includes('judet') ||
        header.toLowerCase().includes('oras') ||
        header.toLowerCase().includes('municipi') 
    );

    if (regionColumn === -1) {
        // No mixed region/judet column found, return original data
        return data;
    }

    // Keep header row and filter other rows
    return [
        data[0],
        ...data.slice(1).filter(row => 
            !row[regionColumn].toLowerCase().includes('regiun')
        )
    ];
}

function getYearRange(data) {
    const years = data.map(row => {
        if (row.Perioade.startsWith('Anul ')) {
            return parseInt(row.Perioade.split(' ')[1]);
        } else if (row.Perioade.includes('Trimestrul')) {
            return parseInt(row.Perioade.split(' ').pop());
        }
        return null;
    }).filter(year => year !== null);
    
    return {
        min: Math.min(...years),
        max: Math.max(...years)
    };
}

function findCountyColumn(headers) {
    return headers.find(header => 
        header.toLowerCase().includes('regiun') || 
        header.toLowerCase().includes('municip') || 
        header.toLowerCase().includes('oras') || 
        header.toLowerCase().includes('judete')
    );
}

function findPeriodColumn(headers) {
    return headers.find(header => 
        header.toLowerCase().includes('perioad') ||
        header === 'Perioade'  // Add exact match
    );
}

function calculateCountyTotals(data, year, countyColumn, periodColumn) {
    return data.reduce((acc, row) => {
        const rowYear = row[periodColumn].startsWith('Anul ') ? 
            row[periodColumn].split(' ')[1] : 
            row[periodColumn].includes('Trimestrul') ?
                row[periodColumn].split(' ').pop() : null;
                
        if (rowYear === year.toString()) {
            const county = row[countyColumn];
            if (!county.toLowerCase().includes('macroregiunea') && 
                !county.toLowerCase().includes('regiunea')) {
                acc[county] = (acc[county] || 0) + parseFloat(row.Valoare);
            }
        }
        return acc;
    }, {});
}

// Modified county chart creation
function createCountyChart(data, year, countyColumn, periodColumn) {    
    const countyTotals = calculateCountyTotals(data, year, countyColumn, periodColumn);
    const sortedData = Object.entries(countyTotals)
        .sort((a, b) => b[1] - a[1]);
    
    const ctx = document.getElementById('countyBarChart').getContext('2d');
    
    if (window.countyChart) {
        window.countyChart.destroy();
    }
    
    window.countyChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: sortedData.map(([county]) => county),
            datasets: [{
                label: `Values by County (${year})`,
                data: sortedData.map(([, value]) => value),
                backgroundColor: '#4299E1',
                borderColor: '#3182CE',
                borderWidth: 1,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            indexAxis: 'y',
            animation: {
                duration: 0 // Remove animations
            },
            hover: {
                animationDuration: 0 // Remove hover animations
            },
            responsiveAnimationDuration: 0, // Remove resize animations
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return context.parsed.x.toLocaleString();
                        }
                    }
                },
                legend: {
                    display: false
                }
            },
            scales: {
                x: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return value.toLocaleString();
                        }
                    } 
                },
                y: {
                    ticks: {
                        autoSkip: false
                    }
                }
            }
        }
    });
}

function initializeCountyVisualization(data) {
    const headers = Object.keys(data[0]);
    const countyColumn = findCountyColumn(headers);
    const periodColumn = findPeriodColumn(headers);
    
    if (!countyColumn || !periodColumn) {
        console.log('Missing required columns:', { countyColumn, periodColumn });
        return;createCountyChartContainer
    }
    
    // Create container and get elements
    createCountyChartContainer();
    const slider = document.getElementById('year-slider');
    const yearLabel = document.getElementById('year-label');
    
    // Setup year slider
    const yearRange = getYearRange(data);
    slider.min = yearRange.min;
    slider.max = yearRange.max;
    slider.value = yearRange.max; // Default to most recent year
    slider.step = 1;
    
    // Update label
    yearLabel.textContent = `Select Year: ${slider.value}`;
    
    // Create initial chart
    createCountyChart(data, slider.value, countyColumn, periodColumn);
    
    // Handle slider changes
    slider.addEventListener('input', (e) => {
        yearLabel.textContent = `Select Year: ${e.target.value}`;
        createCountyChart(data, e.target.value, countyColumn, periodColumn);
    });
}
function createCountyChartContainer() {
    const container = document.createElement('div');
    container.id = 'county-chart-container';
    container.style.marginTop = '2rem';
    container.innerHTML = `
        <div id="year-slider-container" style="margin: 1rem 0;">
            <label for="year-slider" id="year-label" style="display: block; margin-bottom: 0.5rem;"></label>
            <input type="range" id="year-slider" style="width: 100%;">
        </div>
        <div style="height: 45em;"> <!-- Fixed height container -->
            <canvas id="countyBarChart"></canvas>
        </div>
    `;
    
    // Insert after the yearly chart
    const yearlyChart = document.getElementById('zichart');
    yearlyChart.parentNode.insertBefore(container, yearlyChart.nextSibling);
    
    return container;
}

/* - - - - - - - - - - - - - - - - - - - - -  
display metadata
- - - - - - - - - - - - - - - - - - - - -  */

async function displayMetadata(datasetId) {
    try {
        const response = await fetch(`data/metas/ro/${datasetId}.json`);
        const metadata = await response.json();
        
        const display = document.getElementById('metadata-display');
        display.innerHTML = '';
        
        // File stats
        const statsDiv = document.createElement('div');
        statsDiv.className = 'file-stats';
        statsDiv.innerHTML = `
            <h3>Dataset Profile</h3>
            <p>
                Rows: ${metadata.file_stats.row_count.toLocaleString()} | 
                Columns: ${metadata.file_stats.column_count} | 
                Size: ${metadata.file_stats.file_size_mb.toFixed(2)} MB
            </p>
            ${metadata.value_column ? `<p>Value column: ${metadata.value_column}</p>` : ''}
        `;
        display.appendChild(statsDiv);
        
        // Columns
        const columnsDiv = document.createElement('div');
        columnsDiv.className = 'columns';
        
        for (const [colName, colData] of Object.entries(metadata.columns)) {
            const colDiv = document.createElement('div');
            colDiv.className = 'column-card';
            
            // Column header with type tags
            let typeInfo = `
                <span class="type-tag">${colData.type}</span>
                ${colData.type2 ? colData.type2.split(',').map(t => `<span class="type-tag">${t.trim()}</span>`).join('') : ''}
            `;
            
            colDiv.innerHTML = `
                <h4>${colName}</h4>
                <div>${typeInfo}</div>
                <p>
                    Unique: ${colData.unique_count.toLocaleString()} | 
                    Null: ${colData.null_count.toLocaleString()}
                </p>
                ${colData.warnings ? `<p class="warning">⚠️ ${colData.warnings}</p>` : ''}
            `;
            
            // Add numeric stats if available
            if (colData.type === 'numeric' || colData.type === 'numeric+') {
                colDiv.innerHTML += `
                    <p>
                        Min: ${colData.min.toLocaleString()} | 
                        Max: ${colData.max.toLocaleString()}<br>
                        Mean: ${colData.mean.toLocaleString()} | 
                        Median: ${colData.median.toLocaleString()}
                    </p>
                `;
            }
            
            // Add bar chart for categorical data
            if (colData.type === 'categorical' && colData.value_counts) {
                const chart = createBarChart(colData.value_counts, colData.total_count);
                colDiv.appendChild(chart);
            }
            
            columnsDiv.appendChild(colDiv);
        }
        
        display.appendChild(columnsDiv);
        
    } catch (error) {
        console.error('Error loading metadata:', error);
        document.getElementById('metadata-display').innerHTML = `
            <div class="warning">Error loading metadata for ${datasetId}</div>
        `;
    }
}

// Helper function to create bar charts for categorical data
function createBarChart(valueCounts, total) {
    const container = document.createElement('div');
    container.className = 'chart-container';
    
    // Get top 7 values
    let entries = Object.entries(valueCounts);
    let others = 0;
    if (entries.length > 7) {
        others = entries.slice(7).reduce((sum, [_, count]) => sum + count, 0);
        entries = entries.slice(0, 7);
    }
    
    // Add others if exists
    if (others > 0) {
        entries.push(['-others-', others]);
    }
    
    // Find max value for scaling
    const maxCount = Math.max(...entries.map(([_, count]) => count));
    
    // Create bars
    entries.forEach(([label, count]) => {
        const barWrapper = document.createElement('div');
        barWrapper.className = 'bar-wrapper';
        
        const bar = document.createElement('div');
        bar.className = 'bar';
        bar.style.width = `${(count/maxCount)*100}%`;
        
        const labelSpan = document.createElement('span');
        labelSpan.className = 'bar-label';
        labelSpan.textContent = label;
        
        const valueSpan = document.createElement('span');
        valueSpan.className = 'bar-value';
        valueSpan.textContent = `${count} (${((count/total)*100).toFixed(1)}%)`;
        
        barWrapper.appendChild(bar);
        barWrapper.appendChild(labelSpan);
        barWrapper.appendChild(valueSpan);
        container.appendChild(barWrapper);
    });
    
    return container;
}