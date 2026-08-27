/* summary_10_table.js — kcommit-analysis-pipeline
 *
 * Middle pane: table head, filter controls, sort, row HTML, live filter,
 * clear-filters and CSV-export wiring.
 *
 * Virtual scroll is handled entirely by summary_11_vtable.js.
 * This module calls virtRender(0) / resetVirt() / onTableScroll() from
 * that module — it never writes rows to <tbody> directly.
 *
 * V2: tableWrap now points to #kc-scroll-host (was #kc-table-wrap).
 *     Colgroup sync added for header/data table alignment.
 *     Scroll events bound to scroll host.
 *
 * PERFORMANCE CONTRACT (unchanged from v1)
 * ====================
 * ① buildDistinct   — never called at parse time; deferred by bootstrap
 *                    via buildDistinctAsync() (one column per idle tick,
 *                    perf B.1).
 * ② applySort       — Schwartzian transform (key extracted once per row);
 *                    plain < / > compare, no localeCompare, no String().
 *                    Dispatched via requestAnimationFrame so the sort-icon
 *                    update is painted before the blocking work begins
 *                    (perf B.2). haystackRows is invalidated after sort
 *                    because it is index-synced to sortedRows.
 * ③ applyFilters    — for-loop (not .filter()) over sortedRows; skips
 *                    columns with no active filter; matchToken compiles
 *                    RegExp once per token outside the row loop.
 *                    Text inputs debounced at 300 ms; select inputs fire
 *                    immediately (perf B.3).
 * ④ getHaystack     — built lazily; only when global search is active;
 *                    invalidated after sort (index sync required).
 * ⑤ virtRender      — paints at most VIRT_OVERSCAN rows (summary_11_vtable);
 *                    skips repaint when window hasn't moved.
 */

const tbody      = document.getElementById('kc-tbody');
const thead      = document.getElementById('kc-thead');
const tableEl    = document.getElementById('kc-table');
const tableWrap  = document.getElementById('kc-scroll-host');
const theadWrap  = document.getElementById('kc-thead-wrap');
const globalSrch = document.getElementById('kc-global-search');
const liveCount  = document.getElementById('kc-live-count');
const noMatch    = document.getElementById('kc-no-match');
const clearBtn   = document.getElementById('kc-clear-filters');
const exportBtn  = document.getElementById('kc-export-csv');

/* Resize state - stores current column widths in px (null = auto-sized) */
let colWidths = null;
let resizeColIndex = null;
let resizeStartX = null;
let resizeStartWidth = null;

/* Initialize column widths */
function initColWidths() {
  if (!colWidths) {
    colWidths = new Array(COLS.length).fill(null);
  }
}

/* Debounced window resize handler */
let resizeTimer = null;
function scheduleAutoResize() {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => autoSizeColumns(), 150);
}

/* ── Horizontal scroll sync between header and body ──────────────────── */
function syncHorizontalScroll() {
  if (!tableWrap) return;
  /* Get the scroll position from the body scroll host */
  const scrollX = tableWrap.scrollLeft;
  
  /* Apply it as a transform to the header table to keep columns aligned */
  const headerTable = theadWrap?.querySelector('.kc-header-table');
  if (headerTable) {
    headerTable.style.transform = `translateX(${-scrollX}px)`;
  }
}

/* Initial sort seeded from the server-provided DEFAULT_SORT (relevant tab).
 * Only honoured when the referenced column actually exists in COLS. */
let sortKey = null, sortDir = 1;
if (DEFAULT_SORT && DEFAULT_SORT.key &&
    COLS.some(c => c.key === DEFAULT_SORT.key)) {
  sortKey = DEFAULT_SORT.key;
  sortDir = DEFAULT_SORT.dir === -1 ? -1 : 1;
}
const colFilters = Object.create(null);
COLS.forEach(c => { colFilters[c.key] = ''; });

/* filteredRows — result of the last applyFilters() call.
 * Owned here; read by summary_11_vtable.js for rendering. */
let filteredRows = ROWS.slice();

/* ── Column filter controls ──────────────────────────────────────────────── */
function buildFilterCtrl(col, fth) {
  const distinct = COL_DISTINCT[col.key] || [];
  const useList  = (col.type === 'select' && (col.options || []).length)
                || (distinct.length > 0 && distinct.length < 20);
  if (useList) {
    const options = col.options?.length ? col.options : distinct;
    const sel = document.createElement('select');
    sel.dataset.filterKey  = col.key;
    sel.dataset.filterRole = 'select';
    sel.innerHTML = `<option value="">All</option>`
      + options.map(v => `<option value="${esc(v)}"${
          colFilters[col.key] === String(v) ? ' selected' : ''
        }>${esc(v)}</option>`).join('');
    sel.addEventListener('change', scheduleFilter);
    fth.appendChild(sel);
    if (col.type === 'number') {
      const inp = document.createElement('input');
      inp.type = 'text'; inp.placeholder = '> < ='; inp.style.width = '48px'; inp.style.marginTop = '2px';
      inp.dataset.filterKey  = col.key;
      inp.dataset.filterRole = 'text';
      inp.value = colFilters[col.key] || '';
      inp.addEventListener('input', scheduleFilterDebounced);
      fth.appendChild(inp);
    }
  } else {
    const inp = document.createElement('input');
    inp.type = 'text'; inp.placeholder = 'Filter\u2026';
    inp.dataset.filterKey  = col.key;
    inp.dataset.filterRole = 'text';
    inp.value = colFilters[col.key] || '';
    inp.addEventListener('input', scheduleFilterDebounced);
    fth.appendChild(inp);
  }
}

/* Helper: get CSS class for a column key */
function colCssClass(colKey) {
  switch (colKey) {
    case 'rank':     return 'kc-col-rank';
    case 'sha12':    return 'kc-col-sha12';
    case 'subject':  return 'kc-col-subject';
    case 'author_org': return 'kc-col-author';
    case 'date':     return 'kc-col-date';
    case 'profiles': return 'kc-col-profiles';
    default:        return 'kc-col-pill';
  }
}

/* rebuildFilterDropdowns — lightweight rebuild after buildDistinctAsync()
 * populates COL_DISTINCT.  Only replaces filter-row <th> contents. */
function rebuildFilterDropdowns() {
  if (!thead) return;
  const filterRow = thead.querySelector('tr.kc-filter-row');
  if (!filterRow) return;
  const ths = filterRow.querySelectorAll('th');
  COLS.forEach((col, i) => {
    if (!ths[i]) return;
    ths[i].innerHTML = '';
    buildFilterCtrl(col, ths[i]);
  });
}

/* ── Colgroup sync (v2) — keep header and data table columns aligned ──── */
function syncColgroup() {
  const headCg = document.getElementById('kc-thead-colgroup');
  const bodyCg = document.getElementById('kc-tbody-colgroup');
  if (!headCg && !bodyCg) return;
  
  /* Build col elements with width attributes */
  /* If colWidths has a value, use it. Otherwise use CSS min-width fallback. */
  const colHtml = COLS.map((col, i) => {
    const w = colWidths?.[i];
    if (w != null) return `<col style="width:${w}px">`;
    const minW = AUTO_MIN_WIDTHS[col.key];
    if (minW) return `<col style="width:${minW}px">`;
    return '<col>';
  }).join('');
  
  if (headCg) headCg.innerHTML = colHtml;
  if (bodyCg) bodyCg.innerHTML = colHtml;
}

/* ── Horizontal scroll sync between header and body ──────────────────── */
/* Note: syncHorizontalScroll is called directly from scroll event listener */

/* ── Auto-size columns based on content ──────────────────────────────── */
/* Minimum widths per column key (in px) - used as fallback when content is narrow */
const AUTO_MIN_WIDTHS = {
  'rank': 32,
  'sha12': 48,
  'subject': 160,
  'author_org': 80,
  'date': 64,
  'profiles': 64,
  'score': 48,
  'score_norm': 48,
  'pick_priority': 40,
  'backport_cx': 64,
  'cherry_pickable': 48  /* Cherry-pick test: Yes/No select column */
};

function autoSizeColumns() {
  if (!thead || !tbody) return;
  initColWidths();
  
  const visibleRows = tbody.querySelectorAll('tr');
  if (visibleRows.length === 0) return;
  
  /* Measure each column's required width */
  const newWidths = new Array(COLS.length).fill(0);
  
  COLS.forEach((col, colIndex) => {
    /* Skip columns with manual width set (user has resized this column) */
    if (colWidths[colIndex] != null) return;
    
    const cssClass = colCssClass(col.key);
    
    /* Measure header width */
    const headerCells = thead.querySelectorAll(`th.${cssClass}`);
    headerCells.forEach(th => {
      newWidths[colIndex] = Math.max(newWidths[colIndex], th.scrollWidth);
    });
    
    /* Measure body cells width (visible rows only) */
    visibleRows.forEach(row => {
      const cell = row.querySelector(`td.${cssClass}`);
      if (cell) {
        newWidths[colIndex] = Math.max(newWidths[colIndex], cell.scrollWidth);
      }
    });
    
    /* Apply minimum width for the column type */
    const minWidth = AUTO_MIN_WIDTHS[col.key] || 60;
    newWidths[colIndex] = Math.max(newWidths[colIndex], minWidth);
    
    /* Add padding for cell padding (7px left + 10px right from CSS) */
    newWidths[colIndex] += 20;
    
    /* Clamp to a reasonable max */
    newWidths[colIndex] = Math.min(newWidths[colIndex], 800);
  });
  
  /* Apply new widths only if they changed */
  let changed = false;
  newWidths.forEach((w, i) => {
    if (w > 0 && colWidths[i] === null) {
      colWidths[i] = w;
      changed = true;
    }
  });
  
  if (changed) {
    syncColgroup();
    if (typeof virtRender === 'function') {
      virtRender();
    }
  }
}

/* ── Column resize logic ──────────────────────────────────────────── */
function startResize(e) {
  if (e.target.classList.contains('kc-col-resize-handle') ||
      e.target.parentElement.classList.contains('kc-col-resize-handle')) {
    const handle = e.target.classList.contains('kc-col-resize-handle')
      ? e.target : e.target.parentElement;
    resizeColIndex = parseInt(handle.dataset.colIndex, 10);
    if (isNaN(resizeColIndex)) return;
    
    resizeStartX = e.clientX;
    const th = handle.parentElement;
    resizeStartWidth = th.offsetWidth;
    
    handle.classList.add('active');
    th.classList.add('kc-th-resizing');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    
    document.addEventListener('mousemove', doResize, { passive: false });
    document.addEventListener('mouseup', endResize, { passive: true });
    e.preventDefault();
  }
}

function doResize(e) {
  if (resizeColIndex === null) return;
  e.preventDefault();
  
  const dx = e.clientX - resizeStartX;
  const newWidth = Math.max(20, resizeStartWidth + dx); /* min 20px */
  
  /* Store in colWidths array */
  initColWidths();
  colWidths[resizeColIndex] = newWidth;
  
  /* Update the colgroup widths for both header and body tables.
   * With table-layout:fixed, this will propagate to all cells automatically. */
  syncColgroup();
  
  /* Also update header cells inline width for immediate visual feedback */
  const colKey = COLS[resizeColIndex].key;
  const cssClass = colCssClass(colKey);
  const headerCells = thead?.querySelectorAll(`th.${cssClass}`);
  headerCells?.forEach(cell => { cell.style.width = `${newWidth}px`; });
  
  /* Force re-render of visible body rows to pick up the new width */
  if (typeof virtRender === 'function') {
    virtRender();
  }
}

function endResize(e) {
  if (resizeColIndex === null) return;
  
  const handle = document.querySelector(`.kc-col-resize-handle[data-col-index="${resizeColIndex}"]`);
  if (handle) handle.classList.remove('active');
  const th = handle?.parentElement;
  if (th) th.classList.remove('kc-th-resizing');
  
  document.body.style.cursor = '';
  document.body.style.userSelect = '';
  
  resizeColIndex = null;
  resizeStartX = null;
  resizeStartWidth = null;
  
  document.removeEventListener('mousemove', doResize);
  document.removeEventListener('mouseup', endResize);
  e?.preventDefault();
}

/* buildHead — rebuilds thead from scratch using colFilters as the
 * authoritative value source (same contract as v1). */
function buildHead() {
  if (!thead) return;
  initColWidths();
  const sortRow   = document.createElement('tr'); sortRow.className   = 'kc-sort-row';
  const filterRow = document.createElement('tr'); filterRow.className = 'kc-filter-row';
  COLS.forEach((col, colIndex) => {
    /* Sort row header */
    const th = document.createElement('th');
    th.className = colCssClass(col.key);
    th.innerHTML = `${esc(col.label)} <em class="kc-sort-icon" data-key="${esc(col.key)}"></em>`;
    th.addEventListener('click', () => {
      if (sortKey === col.key) sortDir = -sortDir;
      else { sortKey = col.key; sortDir = 1; }
      updateSortIcons();
      requestAnimationFrame(() => { applySort(); applyFilters(); });
    });
    /* Apply custom width if set */
    if (colWidths[colIndex] != null) {
      th.style.width = `${colWidths[colIndex]}px`;
    }
    /* Add resize handle to all but last column */
    if (colIndex < COLS.length - 1) {
      const handle = document.createElement('div');
      handle.className = 'kc-col-resize-handle';
      handle.dataset.colIndex = colIndex;
      handle.addEventListener('mousedown', startResize);
      th.appendChild(handle);
    }
    sortRow.appendChild(th);
    
    /* Filter row header */
    const fth = document.createElement('th');
    fth.className = colCssClass(col.key);
    if (colWidths[colIndex] != null) {
      fth.style.width = `${colWidths[colIndex]}px`;
    }
    buildFilterCtrl(col, fth);
    filterRow.appendChild(fth);
  });
  thead.innerHTML = ''; thead.appendChild(sortRow); thead.appendChild(filterRow);
  syncColgroup();
  tableWrap?.removeEventListener('scroll', onTableScroll);
  tableWrap?.addEventListener('scroll', onTableScroll, { passive: true });
}

function updateSortIcons() {
  document.querySelectorAll('.kc-sort-icon').forEach(el => {
    el.className = 'kc-sort-icon';
    if (el.dataset.key === sortKey) el.classList.add(sortDir === 1 ? 'asc' : 'desc');
  });
}

function cellValue(row, key) {
  const v = row[key];
  if (v == null) return '';
  if (Array.isArray(v)) return v.join('; ');
  return String(v);
}

function rowHtml(r) {
  const isFiltered = activeTab === 'filtered';
  let out = `<tr data-sha12="${esc(r.sha12)}" data-sha="${esc(r.sha || r.sha12)}"`
    + (r._active ? ' class="kc-row-active"' : '') + '>';
  COLS.forEach((col, colIndex) => {
    let v = r[col.key]; if (v == null) v = '';
    const cssClass = colCssClass(col.key);
    const widthStyle = colWidths?.[colIndex] != null ? ` style="width:${colWidths[colIndex]}px"` : '';
    if (col.key === 'sha12') {
      out += `<td class="kc-td-sha ${cssClass}"${widthStyle}><a href="#" class="kc-sha-link" data-sha12="${esc(r.sha12)}" data-sha="${esc(r.sha || r.sha12)}">${esc(r.sha12)}</a></td>`;
    } else if (!isFiltered && col.key === 'score') {
      /* score (raw) is hidden in the table but still present in row data.
       * If somehow visible, render as legacy scorePill. */
      const num = parseFloat(v) || 0;
      out += `<td class="kc-td-num kc-td-score ${cssClass}"${widthStyle}>${num > 0 ? scorePill(num) : '<span class="kc-muted">\u2014</span>'}</td>`;
    } else if (!isFiltered && col.key === 'score_norm') {
      /* Score % pill with higher-better heat (higher score = greener). */
      out += `<td class="kc-td-num ${cssClass}"${widthStyle}>${heatPill(v, {scale: 100, polarity: 'higher-better'})}</td>`;
    } else if (!isFiltered && col.key === 'pick_priority') {
      /* Pick priority pill with higher-better heat (higher = greener). */
      out += `<td class="kc-td-num ${cssClass}"${widthStyle}>${heatPill(v, {scale: 100, polarity: 'higher-better'})}</td>`;
    } else if (!isFiltered && col.key === 'backport_cx') {
      /* Colour the complexity cell by heat level (higher-worse polarity).
       * The numeric value is the authoritative signal; the level is just a
       * 4-step bucket for the pill color. */
      out += `<td class="kc-td-num ${cssClass}"${widthStyle}>${heatPill(v, {scale: 100, polarity: 'higher-worse'})}</td>`;
    } else if (!isFiltered && col.key === 'cherry_pickable') {
      /* Cherry-pick test result: Yes/No select column with appropriate styling */
      out += `<td class="kc-td-text ${cssClass}"${widthStyle}>${esc(v)}</td>`;
    } else if (!isFiltered && col.key === 'profiles') {
      out += `<td class="${cssClass}"${widthStyle}>${profileBullets(Array.isArray(v) ? v : [v])}</td>`;
    } else if (col.key === 'date') {
      out += `<td class="kc-td-num ${cssClass}"${widthStyle}>${esc(fmtDate(v))}</td>`;
    } else if (isFiltered && col.key === 'filter_stage') {
      out += `<td class="${cssClass}"${widthStyle}>${stageBadge(v)}</td>`;
    } else {
      out += `<td class="${cssClass}"${widthStyle}>${esc(Array.isArray(v) ? v.join('; ') : v)}</td>`;
    }
  });
  out += '</tr>';
  return out;
}

/* ── Sort — Schwartzian transform, no localeCompare ────────────────────────── */
function applySort() {
  if (!sortKey) return;
  const col   = COLS.find(c => c.key === sortKey);
  const isNum = col && col.type === 'number';
  const n     = sortedRows.length;
  const keyed = new Array(n);
  for (let i = 0; i < n; i++) {
    const r   = sortedRows[i];
    const raw = r[sortKey];
    const k   = isNum
      ? (raw == null ? 0 : parseFloat(raw) || 0)
      : (raw == null ? '' : Array.isArray(raw) ? raw.join('; ') : String(raw));
    keyed[i] = { r, k };
  }
  if (isNum) {
    keyed.sort((a, b) => (a.k - b.k) * sortDir);
  } else {
    keyed.sort((a, b) => (a.k < b.k ? -sortDir : a.k > b.k ? sortDir : 0));
  }
  for (let i = 0; i < n; i++) sortedRows[i] = keyed[i].r;
  haystackRows = null;
}

/* renderRowsAsync — thin wrapper: synthetic progress ticks then applyFilters. */
function renderRowsAsync(onProgress, onDone) {
  const total = sortedRows.length;
  if (total === 0) {
    filteredRows = [];
    if (tbody) tbody.innerHTML = '';
    resetVirt();
    virtRender(0);
    onDone && onDone(); return;
  }
  let step = 0;
  const STEPS = 5;
  function tick() {
    step++;
    onProgress && onProgress(Math.min(step * Math.ceil(total / STEPS), total), total);
    if (step < STEPS) { setTimeout(tick, 30); return; }
    applyFilters();
    onDone && onDone();
  }
  setTimeout(tick, 30);
}

/* ── Filter ──────────────────────────────────────────────────────────────── */
let filterTimer  = 0;
let haystackRows = null;

function getHaystack() {
  if (haystackRows && haystackRows.length === sortedRows.length) return haystackRows;
  const n = sortedRows.length;
  haystackRows = new Array(n);
  for (let i = 0; i < n; i++) {
    const r = sortedRows[i];
    let s = '';
    for (const k in r) {
      const v = r[k];
      s += (Array.isArray(v) ? v.join(' ') : (v == null ? '' : v)) + ' ';
    }
    haystackRows[i] = s.toLowerCase();
  }
  return haystackRows;
}

function scheduleFilter() {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(() => applyFilters(), 0);
}

function scheduleFilterDebounced() {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(() => applyFilters(), 300);
}

function buildMatchers(activeCols, selectVals, textVals) {
  const matchers = [];
  for (const col of activeCols) {
    const sv = (selectVals[col.key] || '').trim();
    const tv = (textVals[col.key]   || '').trim();
    if (sv) matchers.push({ key: col.key, fn: compileMatcher(sv) });
    if (tv) matchers.push({ key: col.key, fn: compileMatcher(tv) });
  }
  return matchers;
}

function compileMatcher(token) {
  const t = token.trim().toLowerCase();
  if (t[0] === '>') { const n = parseFloat(t.slice(1)); return s => !isNaN(n) && parseFloat(s) > n; }
  if (t[0] === '<') { const n = parseFloat(t.slice(1)); return s => !isNaN(n) && parseFloat(s) < n; }
  if (t[0] === '=') { const v = t.slice(1); return s => s.toLowerCase() === v; }
  if (t.includes('*')) {
    const pat = t.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
    try { const re = new RegExp(pat); return s => re.test(s.toLowerCase()); }
    catch { return s => s.toLowerCase().includes(t); }
  }
  return s => s.toLowerCase().includes(t);
}

function applyFilters() {
  const colKeySet  = new Set(COLS.map(c => c.key));
  const selectVals = Object.create(null);
  const textVals   = Object.create(null);
  document.querySelectorAll('[data-filter-key]').forEach(el => {
    const key = el.dataset.filterKey;
    if (!colKeySet.has(key)) return;
    if (el.dataset.filterRole === 'select') selectVals[key] = el.value || '';
    else                                    textVals[key]   = el.value || '';
    colFilters[key] = el.value || '';
  });
  const global  = (globalSrch?.value || '').trim().toLowerCase();
  const gTokens = global ? global.split(/\s+/).filter(Boolean) : [];

  const activeCols = COLS.filter(col =>
    (selectVals[col.key] || '').trim() || (textVals[col.key] || '').trim()
  );
  const noFilters = !gTokens.length && activeCols.length === 0;

  if (noFilters) {
    filteredRows = sortedRows;
  } else {
    const matchers = buildMatchers(activeCols, selectVals, textVals);
    const hay      = gTokens.length ? getHaystack() : null;
    filteredRows   = [];
    const n        = sortedRows.length;
    outer: for (let idx = 0; idx < n; idx++) {
      const r = sortedRows[idx];
      for (let mi = 0; mi < matchers.length; mi++) {
        if (!matchers[mi].fn(cellValue(r, matchers[mi].key))) continue outer;
      }
      if (hay) {
        const h = hay[idx];
        for (let gi = 0; gi < gTokens.length; gi++) {
          if (!h.includes(gTokens[gi])) continue outer;
        }
      }
      filteredRows.push(r);
    }
  }

  const shown = filteredRows.length;
  if (liveCount) liveCount.textContent = `Showing ${shown.toLocaleString()} of ${ROWS.length.toLocaleString()} commits`;
  if (noMatch)   noMatch.classList.toggle('kc-visible', shown === 0);
  resetVirt();
  virtRender(0);
}

clearBtn?.addEventListener('click', () => {
  document.querySelectorAll('[data-filter-key]').forEach(el => { el.value = ''; colFilters[el.dataset.filterKey] = ''; });
  if (globalSrch) globalSrch.value = '';
  applyFilters();
});
globalSrch?.addEventListener('input', scheduleFilterDebounced);

/* CSV export */
exportBtn?.addEventListener('click', () => {
  const header = COLS.map(c => `"${c.label.replace(/"/g, '""')}"`).join(',');
  const lines  = [header];
  for (const r of filteredRows) {
    lines.push(COLS.map(col => {
      const v = cellValue(r, col.key);
      return `"${v.replace(/"/g, '""')}"`;
    }).join(','));
  }
  const blob = new Blob([lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const a    = document.createElement('a');
  a.href     = URL.createObjectURL(blob);
  a.download = activeTab === 'filtered' ? 'kcommit-filtered.csv' : 'kcommit-report.csv';
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
});

/* Apply the server-provided default sort once on module load.
 * This ensures the initial table render respects DEFAULT_SORT and serves
 * as a safety net for the Python-provided row order. */
if (sortKey) applySort();

/* Auto-size columns on initial load (after render completes) and on window resize */
let autoSizeDone = false;
function maybeAutoSize() {
  if (autoSizeDone) return;
  autoSizeDone = true;
  /* Give time for initial render to complete */
  setTimeout(() => autoSizeColumns(), 500);
}

/* Hook into first filter apply (which happens after initial render) */
const originalApplyFilters = applyFilters;
applyFilters = function() {
  originalApplyFilters();
  maybeAutoSize();
};

window.addEventListener('resize', scheduleAutoResize);

/* Sync horizontal scrolling: body scroll host drives the header transform */
tableWrap?.addEventListener('scroll', syncHorizontalScroll, { passive: true });

/* Fallback: also try after a longer delay */
setTimeout(maybeAutoSize, 1000);
