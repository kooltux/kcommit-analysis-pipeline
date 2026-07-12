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
const globalSrch = document.getElementById('kc-global-search');
const liveCount  = document.getElementById('kc-live-count');
const noMatch    = document.getElementById('kc-no-match');
const clearBtn   = document.getElementById('kc-clear-filters');
const exportBtn  = document.getElementById('kc-export-csv');

let sortKey = null, sortDir = 1;
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
  const cols = COLS.map(() => '<col>').join('');
  const headCg = document.getElementById('kc-thead-colgroup');
  const bodyCg = document.getElementById('kc-tbody-colgroup');
  if (headCg) headCg.innerHTML = cols;
  if (bodyCg) bodyCg.innerHTML = cols;
}

/* buildHead — rebuilds thead from scratch using colFilters as the
 * authoritative value source (same contract as v1). */
function buildHead() {
  if (!thead) return;
  const sortRow   = document.createElement('tr'); sortRow.className   = 'kc-sort-row';
  const filterRow = document.createElement('tr'); filterRow.className = 'kc-filter-row';
  COLS.forEach(col => {
    const th = document.createElement('th');
    th.innerHTML = `${esc(col.label)} <em class="kc-sort-icon" data-key="${esc(col.key)}"></em>`;
    th.addEventListener('click', () => {
      if (sortKey === col.key) sortDir = -sortDir;
      else { sortKey = col.key; sortDir = 1; }
      updateSortIcons();
      requestAnimationFrame(() => { applySort(); applyFilters(); });
    });
    sortRow.appendChild(th);
    const fth = document.createElement('th');
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
  for (const col of COLS) {
    let v = r[col.key]; if (v == null) v = '';
    if (col.key === 'sha12') {
      out += `<td class="kc-td-sha"><a href="#" class="kc-sha-link" data-sha12="${esc(r.sha12)}" data-sha="${esc(r.sha || r.sha12)}">${esc(r.sha12)}</a></td>`;
    } else if (!isFiltered && (col.key === 'score' || col._profile)) {
      const num = parseFloat(v) || 0;
      out += `<td class="kc-td-num">${num > 0 ? scorePill(num) : '<span class="kc-muted">\u2014</span>'}</td>`;
    } else if (!isFiltered && col.key === 'profiles') {
      out += `<td>${chips(Array.isArray(v) ? v : [v])}</td>`;
    } else if (col.key === 'date') {
      out += `<td class="kc-td-num">${esc(fmtDate(v))}</td>`;
    } else if (isFiltered && col.key === 'filter_stage') {
      out += `<td>${stageBadge(v)}</td>`;
    } else {
      out += `<td>${esc(Array.isArray(v) ? v.join('; ') : v)}</td>`;
    }
  }
  out += '</tr>';
  return out;
}

/* ── Sort — Schwartzian transform, no localeCompare ────────────────────────── */
function applySort() {
  if (!sortKey) return;
  const col   = COLS.find(c => c.key === sortKey);
  const isNum = col && (col.type === 'number' || col._profile);
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
