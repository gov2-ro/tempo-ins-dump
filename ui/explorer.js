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
  const data = await fetchJSON(`/api/datasets/${id}`)
  const prev = await fetchJSON(`/api/datasets/${id}/preview`).catch(() => ({ rows: [], columns: [] }))

  document.getElementById('list').innerHTML = ''
  const detail = document.getElementById('detail')
  detail.classList.remove('hidden')
  
  // Show ID and descriptive name in detail title
  const filename = data.source_csv ? data.source_csv.split('/').pop() : `${id}.csv`
  const titleText = data.matrix_name ? `${id} - ${data.matrix_name}` : `${id} - ${filename}`
  document.getElementById('title').textContent = titleText
  
  // Render JSON with pretty formatting
  $('#json-viewer').html(`<pre>${JSON.stringify(data, null, 2)}</pre>`)

  // Render table
  const tbl = document.getElementById('preview')
  tbl.innerHTML = ''
  const thead = el('thead')
  const trh = el('tr')
  for (const c of prev.columns) trh.appendChild(el('th', { text: c }))
  thead.appendChild(trh)
  tbl.appendChild(thead)

  const tbody = el('tbody')
  for (const row of prev.rows) {
    const tr = el('tr')
    for (const c of prev.columns) tr.appendChild(el('td', { text: row[c] == null ? '' : String(row[c]) }))
    tbody.appendChild(tr)
  }
  tbl.appendChild(tbody)

  document.getElementById('back').onclick = () => {
    detail.classList.add('hidden')
    renderList()
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

  await refresh()
}

init().catch(err => {
  console.error(err)
  alert('Failed to initialize explorer: ' + err.message)
})
