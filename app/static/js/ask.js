/**
 * ask.js — Chat UI for POST /api/ask (NL→Data agent)
 *
 * Manages multi-turn conversation history, renders assistant responses
 * (text + citations + data table + chart + warnings + tool trace).
 */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const history = [];   // [{role:'user'|'assistant', content: str}]
let isLoading = false;

// ---------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------

function initTheme() {
    const saved = localStorage.getItem('lens_theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = saved || (prefersDark ? 'dark' : 'light');
    applyTheme(theme);
}

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('lens_theme', theme);
    const sun = document.getElementById('theme-icon-sun');
    const moon = document.getElementById('theme-icon-moon');
    if (sun) sun.classList.toggle('hidden', theme === 'dark');
    if (moon) moon.classList.toggle('hidden', theme === 'light');
}

// ---------------------------------------------------------------------------
// Markdown-lite renderer
// ---------------------------------------------------------------------------

function escapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderMarkdown(text) {
    // Escape first, then apply formatting
    let s = escapeHtml(text);
    // Bold
    s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Code spans
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Bullet lists (lines starting with - or *)
    s = s.replace(/^[ \t]*[-*] (.+)$/gm, '<li>$1</li>');
    s = s.replace(/(<li>.*<\/li>)/s, (m) => `<ul>${m}</ul>`);
    // Numbered lists
    s = s.replace(/^[ \t]*\d+\. (.+)$/gm, '<li>$1</li>');
    // Headings
    s = s.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    s = s.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    // Double newline → paragraph break
    s = s.replace(/\n\n/g, '</p><p>');
    // Single newline → <br>
    s = s.replace(/\n/g, '<br>');
    return `<p>${s}</p>`;
}

// ---------------------------------------------------------------------------
// Data table
// ---------------------------------------------------------------------------

function renderDataTable(data) {
    if (!data || !data.columns || !data.rows || data.rows.length === 0) return null;

    const wrap = document.createElement('div');
    wrap.className = 'chat-data-table-wrap';

    const meta = document.createElement('div');
    meta.className = 'chat-data-meta';
    meta.textContent = `${data.row_count ?? data.rows.length} rows`;
    if (data.matrix_code) {
        const link = document.createElement('a');
        link.href = `/dataset.html?code=${data.matrix_code}`;
        link.target = '_blank';
        link.textContent = data.matrix_code;
        link.className = 'chat-data-code';
        meta.appendChild(document.createTextNode(' · '));
        meta.appendChild(link);
    }
    wrap.appendChild(meta);

    const tableWrap = document.createElement('div');
    tableWrap.className = 'chat-table-scroll';

    const table = document.createElement('table');
    table.className = 'chat-table';

    const thead = table.createTHead();
    const hrow = thead.insertRow();
    data.columns.forEach(col => {
        const th = document.createElement('th');
        th.textContent = col;
        hrow.appendChild(th);
    });

    const tbody = table.createTBody();
    const displayRows = data.rows.slice(0, 200);
    displayRows.forEach(row => {
        const tr = tbody.insertRow();
        row.forEach(cell => {
            const td = tr.insertCell();
            td.textContent = cell ?? '';
        });
    });

    if (data.rows.length > 200) {
        const tr = tbody.insertRow();
        const td = tr.insertCell();
        td.colSpan = data.columns.length;
        td.className = 'chat-table-truncated';
        td.textContent = `… ${data.rows.length - 200} more rows not shown`;
    }

    tableWrap.appendChild(table);
    wrap.appendChild(tableWrap);
    return wrap;
}

// ---------------------------------------------------------------------------
// Chart rendering (simple eCharts for line / bar)
// ---------------------------------------------------------------------------

function renderChart(data, chartSpec) {
    if (!data || !data.columns || !data.rows || data.rows.length === 0) return null;
    if (!chartSpec || !chartSpec.primary_chart) return null;

    const primary = chartSpec.primary_chart;
    if (!['line', 'bar', 'grouped_bar', 'stacked_bar', 'area'].includes(primary)) return null;

    // Detect column roles
    const cols = data.columns;
    const timeIdx = cols.findIndex(c => c === 'TIME_PERIOD' || c.toLowerCase().includes('time') || c.toLowerCase().includes('year'));
    const valueIdx = cols.findIndex(c => c === 'OBS_VALUE' || c.toLowerCase().includes('value') || c.toLowerCase().includes('obs'));
    const groupIdx = cols.findIndex((c, i) => i !== timeIdx && i !== valueIdx && !['REF_AREA', 'UNIT_MEASURE', 'UNIT_MULT'].includes(c));

    if (timeIdx === -1 || valueIdx === -1) return null;

    const container = document.createElement('div');
    container.className = 'chat-chart';

    // Build series — group by groupIdx if available
    const seriesMap = {};
    const allX = new Set();

    data.rows.forEach(row => {
        const x = row[timeIdx];
        const y = parseFloat(row[valueIdx]);
        const g = groupIdx >= 0 ? (row[groupIdx] ?? 'Value') : 'Value';
        if (!seriesMap[g]) seriesMap[g] = {};
        seriesMap[g][x] = isNaN(y) ? null : y;
        allX.add(x);
    });

    const xData = Array.from(allX).sort();
    const chartType = ['area', 'line'].includes(primary) ? 'line' : 'bar';
    const series = Object.entries(seriesMap).map(([name, pts]) => ({
        name,
        type: chartType,
        areaStyle: primary === 'area' ? {} : undefined,
        data: xData.map(x => pts[x] ?? null),
        smooth: primary === 'line' || primary === 'area',
    }));

    // Limit to 8 series to avoid clutter
    const visibleSeries = series.slice(0, 8);
    const hiddenCount = series.length - visibleSeries.length;

    const isDark = document.documentElement.getAttribute('data-theme') !== 'light';

    const option = {
        backgroundColor: 'transparent',
        textStyle: { color: isDark ? '#c8ccd4' : '#374151' },
        tooltip: { trigger: 'axis' },
        legend: series.length > 1 ? { top: 4, textStyle: { color: isDark ? '#c8ccd4' : '#374151' } } : undefined,
        grid: { left: 48, right: 16, top: series.length > 1 ? 36 : 12, bottom: 40, containLabel: false },
        xAxis: {
            type: 'category',
            data: xData,
            axisLabel: {
                color: isDark ? '#9ca3af' : '#6b7280',
                rotate: xData.length > 12 ? 45 : 0,
                fontSize: 11,
            },
            axisLine: { lineStyle: { color: isDark ? '#374151' : '#e5e7eb' } },
        },
        yAxis: {
            type: 'value',
            axisLabel: { color: isDark ? '#9ca3af' : '#6b7280', fontSize: 11 },
            splitLine: { lineStyle: { color: isDark ? '#1f2937' : '#f3f4f6' } },
        },
        series: visibleSeries,
        color: ['#818cf8', '#34d399', '#fb923c', '#f472b6', '#60a5fa', '#a78bfa', '#fbbf24', '#4ade80'],
    };

    // Defer init so container is in DOM
    requestAnimationFrame(() => {
        try {
            const chart = echarts.init(container);
            chart.setOption(option);
            if (hiddenCount > 0) {
                const note = document.createElement('div');
                note.className = 'chat-chart-note';
                note.textContent = `+${hiddenCount} series hidden`;
                container.after(note);
            }
        } catch (e) {
            console.warn('Chart render failed:', e);
        }
    });

    return container;
}

// ---------------------------------------------------------------------------
// Message rendering
// ---------------------------------------------------------------------------

function appendMessage(role, text) {
    const list = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = `chat-msg chat-msg--${role}`;
    div.innerHTML = role === 'user'
        ? `<div class="chat-bubble">${escapeHtml(text)}</div>`
        : `<div class="chat-bubble">${renderMarkdown(text)}</div>`;
    list.appendChild(div);
    scrollToBottom();
    return div;
}

function appendAssistantResponse(result) {
    const list = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'chat-msg chat-msg--assistant';

    // Answer text
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    bubble.innerHTML = renderMarkdown(result.answer || '(no answer)');
    div.appendChild(bubble);

    // Citations
    if (result.citations && result.citations.length > 0) {
        const cites = document.createElement('div');
        cites.className = 'chat-citations';
        result.citations.forEach(c => {
            const a = document.createElement('a');
            a.href = `/dataset.html?code=${c.matrix_code}`;
            a.target = '_blank';
            a.className = 'chat-citation';
            a.textContent = `↗ ${c.matrix_code}${c.matrix_name ? ' — ' + c.matrix_name : ''}`;
            cites.appendChild(a);
        });
        div.appendChild(cites);
    }

    // Warnings
    if (result.warnings && result.warnings.length > 0) {
        const warn = document.createElement('div');
        warn.className = 'chat-warnings';
        result.warnings.forEach(w => {
            const item = document.createElement('div');
            item.className = 'chat-warning-item';
            item.textContent = w;
            warn.appendChild(item);
        });
        div.appendChild(warn);
    }

    // Data table
    const tableEl = renderDataTable(result.data);
    if (tableEl) div.appendChild(tableEl);

    // Chart
    const chartEl = renderChart(result.data, result.chart_spec);
    if (chartEl) div.appendChild(chartEl);

    // Tool trace (collapsible)
    if (result.tool_trace && result.tool_trace.length > 0) {
        const details = document.createElement('details');
        details.className = 'chat-trace';
        const summary = document.createElement('summary');
        summary.textContent = `${result.tool_trace.length} tool call${result.tool_trace.length > 1 ? 's' : ''}`;
        details.appendChild(summary);
        result.tool_trace.forEach(t => {
            const row = document.createElement('div');
            row.className = 'chat-trace-item';
            row.innerHTML = `<span class="chat-trace-tool">${escapeHtml(t.tool)}</span>`
                + `<code class="chat-trace-input">${escapeHtml(JSON.stringify(t.input))}</code>`;
            details.appendChild(row);
        });
        div.appendChild(details);
    }

    list.appendChild(div);
    scrollToBottom();
}

function appendLoadingIndicator() {
    const list = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'chat-msg chat-msg--assistant chat-msg--loading';
    div.id = 'chat-loading';
    div.innerHTML = '<div class="chat-bubble"><span class="chat-dots"><span></span><span></span><span></span></span></div>';
    list.appendChild(div);
    scrollToBottom();
    return div;
}

function scrollToBottom() {
    const list = document.getElementById('chat-messages');
    list.scrollTop = list.scrollHeight;
}

// ---------------------------------------------------------------------------
// Send message
// ---------------------------------------------------------------------------

async function sendMessage() {
    const input = document.getElementById('chat-input');
    const question = input.value.trim();
    if (!question || isLoading) return;

    isLoading = true;
    input.value = '';
    autoResize(input);
    setInputDisabled(true);

    appendMessage('user', question);
    const loadingEl = appendLoadingIndicator();

    try {
        const resp = await fetch('/api/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question, history }),
        });

        loadingEl.remove();

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            appendMessage('assistant', `Error: ${err.detail || resp.statusText}`);
            return;
        }

        const result = await resp.json();
        appendAssistantResponse(result);

        // Update history for next turn
        history.push({ role: 'user', content: question });
        history.push({ role: 'assistant', content: result.answer || '' });

    } catch (e) {
        loadingEl.remove();
        appendMessage('assistant', `Network error: ${e.message}`);
    } finally {
        isLoading = false;
        setInputDisabled(false);
        input.focus();
    }
}

function setInputDisabled(disabled) {
    document.getElementById('chat-input').disabled = disabled;
    document.getElementById('chat-send').disabled = disabled;
    document.getElementById('chat-send').classList.toggle('loading', disabled);
}

// ---------------------------------------------------------------------------
// Auto-resize textarea
// ---------------------------------------------------------------------------

function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
    initTheme();

    // Theme toggle
    document.getElementById('theme-toggle').addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme');
        applyTheme(current === 'dark' ? 'light' : 'dark');
    });

    // Send button
    document.getElementById('chat-send').addEventListener('click', sendMessage);

    // Enter to send (Shift+Enter = newline)
    const input = document.getElementById('chat-input');
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    input.addEventListener('input', () => autoResize(input));

    // Example questions
    document.querySelectorAll('.chat-example').forEach(btn => {
        btn.addEventListener('click', () => {
            input.value = btn.dataset.q;
            autoResize(input);
            input.focus();
        });
    });

    input.focus();
});
