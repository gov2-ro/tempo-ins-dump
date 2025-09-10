async function fetchJSON(url) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return await res.json()
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag)
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v
    else if (k === 'text') node.textContent = v
    else node.setAttribute(k, v)
  }
  for (const child of children) node.appendChild(child)
  return node
}

function chip(text, active) {
  return el('span', { class: `flag-chip${active ? ' active' : ''}`, 'data-flag': text, text })
}

const state = {
  q: '',
  flags: new Set(),
  items: [],
  flagsIndex: {},
  currentDatasetIndex: -1, // Track current position in the list
}

function renderFlags() {
  const wrap = document.getElementById('flag-list')
  wrap.innerHTML = ''
  const keys = Object.keys(state.flagsIndex)
  for (const f of keys) wrap.appendChild(chip(`${f} (${state.flagsIndex[f]})`, state.flags.has(f)))
}

function renderList() {
  const list = document.getElementById('list')
  const detail = document.getElementById('detail')
  list.innerHTML = ''
  detail.classList.add('hidden')

  document.getElementById('count').textContent = state.items.length

  for (const it of state.items) {
    const card = el('div', { class: 'card', 'data-id': it.id })
    
    // Create title with ID and descriptive name
    const titleText = it.matrix_name ? `${it.id} - ${it.matrix_name}` : `${it.id} - ${it.name}`
    card.appendChild(el('div', { class: 'title', text: titleText }))
    
    const meta = [
      it.um_label ? `UM: ${it.um_label}` : null,
      it.columns_count ? `${it.columns_count} cols` : null,
    ].filter(Boolean).join(' • ')
    card.appendChild(el('div', { class: 'meta', text: meta }))
    const flags = el('div', { class: 'flags' })
    for (const f of it.flags || []) flags.appendChild(chip(f))
    card.appendChild(flags)

    card.addEventListener('click', () => openDetail(it.id))
    list.appendChild(card)
  }
}

async function refresh() {
  const params = new URLSearchParams()
  if (state.q) params.set('q', state.q)
  if (state.flags.size) params.set('flags', Array.from(state.flags).join(','))
  const data = await fetchJSON(`/api/datasets?${params}`)
  state.items = data.items
  renderList()
}

async function openDetail(id) {
  // Update URL hash
  window.location.hash = id
  
  // Find and store the current dataset index
  state.currentDatasetIndex = state.items.findIndex(item => item.id === id)
  
  const data = await fetchJSON(`/api/datasets/${id}`)
  const prev = await fetchJSON(`/api/datasets/${id}/preview`).catch(() => ({ 
    rows: [], 
    columns: [], 
    total_rows: 0, 
    file_size_mb: 0, 
    is_truncated: false 
  }))

  document.getElementById('list').innerHTML = ''
  const detail = document.getElementById('detail')
  detail.classList.remove('hidden')
  
  // Update navigation buttons
  updateNavigationButtons()
  
  // Show ID and descriptive name in detail title
  const filename = data.source_csv ? data.source_csv.split('/').pop() : `${id}.csv`
  const titleText = data.matrix_name ? `${id} - ${data.matrix_name}` : `${id} - ${filename}`
  document.getElementById('title').textContent = titleText
  
  // Update preview title with row count and file size info
  const previewTitle = document.getElementById('preview-title')
  let titleSuffix = `(${prev.total_rows} rows, ${prev.file_size_mb}MB)`
  if (prev.is_truncated) {
    titleSuffix = `(showing top 400 of many rows, ${prev.file_size_mb}MB)`
  }
  previewTitle.textContent = `Preview ${titleSuffix}`
  
  // Render JSON with pretty formatting
  $('#json-viewer').html(`<pre>${JSON.stringify(data, null, 2)}</pre>`)

  // Destroy existing DataTable if it exists
  if ($.fn.DataTable.isDataTable('#preview')) {
    $('#preview').DataTable().destroy()
  }

  // Clear and prepare table
  const tbl = document.getElementById('preview')
  tbl.innerHTML = ''

  if (prev.rows.length > 0) {
    // Create table structure
    const thead = el('thead')
    const trh = el('tr')
    for (const c of prev.columns) {
      trh.appendChild(el('th', { text: c }))
    }
    thead.appendChild(trh)
    tbl.appendChild(thead)

    const tbody = el('tbody')
    for (const row of prev.rows) {
      const tr = el('tr')
      for (const c of prev.columns) {
        tr.appendChild(el('td', { text: row[c] == null ? '' : String(row[c]) }))
      }
      tbody.appendChild(tr)
    }
    tbl.appendChild(tbody)

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
    })
  } else {
    // No data available
    tbl.innerHTML = '<tr><td colspan="100%">No data available</td></tr>'
  }

  document.getElementById('back').onclick = () => {
    // Clear URL hash
    window.location.hash = ''
    
    detail.classList.add('hidden')
    // Destroy DataTable when going back
    if ($.fn.DataTable.isDataTable('#preview')) {
      $('#preview').DataTable().destroy()
    }
    renderList()
  }
  
  // Add navigation button event listeners
  document.getElementById('prev-dataset').onclick = () => navigateToDataset(-1)
  document.getElementById('next-dataset').onclick = () => navigateToDataset(1)
}

function updateNavigationButtons() {
  const prevBtn = document.getElementById('prev-dataset')
  const nextBtn = document.getElementById('next-dataset')
  const positionSpan = document.getElementById('dataset-position')
  
  // Update position display
  if (state.currentDatasetIndex >= 0 && state.items.length > 0) {
    positionSpan.textContent = `${state.currentDatasetIndex + 1} of ${state.items.length}`
  } else {
    positionSpan.textContent = ''
  }
  
  // Enable/disable buttons based on position
  prevBtn.disabled = state.currentDatasetIndex <= 0
  nextBtn.disabled = state.currentDatasetIndex >= state.items.length - 1
}

function navigateToDataset(direction) {
  let newIndex = state.currentDatasetIndex + direction
  
  // Bounds checking
  if (newIndex < 0 || newIndex >= state.items.length) {
    return
  }
  
  const nextDataset = state.items[newIndex]
  if (nextDataset) {
    openDetail(nextDataset.id)
  }
}

async function init() {
  const health = await fetchJSON('/api/health')
  console.log('Health:', health)

  const flags = await fetchJSON('/api/flags')
  state.flagsIndex = flags.counts
  renderFlags()

  document.getElementById('flag-list').addEventListener('click', (e) => {
    const f = e.target.getAttribute('data-flag')
    if (!f) return
    const flag = f.split(' (')[0]
    if (state.flags.has(flag)) state.flags.delete(flag)
    else state.flags.add(flag)
    renderFlags()
    refresh()
  })

  const search = document.getElementById('search')
  search.addEventListener('input', (e) => {
    state.q = e.target.value
    refresh()
  })

  // Handle browser back/forward navigation
  window.addEventListener('hashchange', handleHashChange)
  
  await refresh()
  
  // Check if there's a hash in the URL on page load
  handleHashChange()
}

function handleHashChange() {
  const hash = window.location.hash.slice(1) // Remove the # character
  if (hash) {
    // Open the dataset if hash is present
    openDetail(hash).catch(err => {
      console.error('Failed to load dataset from hash:', err)
      // If dataset doesn't exist, clear the hash and show the list
      window.location.hash = ''
      const detail = document.getElementById('detail')
      detail.classList.add('hidden')
      renderList()
    })
  } else {
    // No hash, show the list
    const detail = document.getElementById('detail')
    detail.classList.add('hidden')
    if ($.fn.DataTable.isDataTable('#preview')) {
      $('#preview').DataTable().destroy()
    }
    renderList()
  }
}

init().catch(err => {
  console.error(err)
  alert('Failed to initialize explorer: ' + err.message)
})
