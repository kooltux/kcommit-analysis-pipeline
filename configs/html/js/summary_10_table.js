/* summary_10_table.js — kcommit-analysis-pipeline
 *
 * Middle pane: table head, filter controls, sort, virtual-scroll
 * renderer, live filter, clear-filters and CSV-export wiring.
 *
 * VIRTUAL SCROLL
 * ==============
 * padding-top / padding-bottom on <table> simulate full dataset height;
 * only VIRT_OVERSCAN rows live in <tbody> at any time.
 *
 * PERFORMANCE CONTRACT
 * ====================
 * ① buildDistinct   — never called at parse time; deferred by bootstrap.
 * ② applySort       — Schwartzian transform (key extracted once per row);
 *                    plain < / > compare, no localeCompare, no String().
 * ③ applyFilters    — for-loop (not .filter()) over sortedRows; skips
 *                    columns with no active filter; matchToken compiles
 *                    RegExp once per token outside the row loop.
 * ④ getHaystack     — built lazily; only when global search is active;
 *                    NOT invalidated by sort (order doesn’t matter for
 *                    substring search).
 * ⑤ virtRender      — paints at most VIRT_OVERSCAN rows; skips repaint
 *                    when window hasn’t moved.
 */

const tbody      = document.getElementById('kc-tbody');
const thead      = document.getElementById('kc-thead');
const tableEl    = document.getElementById('kc-table');
const tableWrap  = document.getElementById('kc-table-wrap');
const globalSrch = document.getElementById('kc-global-search');
const liveCount  = document.getElementById('kc-live-count');
const noMatch    = document.getElementById('kc-no-match');
const clearBtn   = document.getElementById('kc-clear-filters');
const exportBtn  = document.getElementById('kc-export-csv');

let sortKey = null, sortDir = 1;
const colFilters = Object.create(null);
COLS.forEach(c => { colFilters[c.key] = ''; });

/* ── Virtual scroll state ───────────────────────────────────────── */
const VIRT_OVERSCAN = 60;
let filteredRows = ROWS.slice();
let virtOffset   = 0;
let rowHeightPx  = 33;

function setTablePadding(topRows, bottomRows) {
  if (!tableEl) return;
  tableEl.style.paddingTop    = topRows    > 0 ? `${topRows    * rowHeightPx}px` : '';
  tableEl.style.paddingBottom = bottomRows > 0 ? `${bottomRows * rowHeightPx}px` : '';
}

function measureRowHeight() {
  const first = tbody?.querySelector('tr');
  if (first) { const h = first.getBoundingClientRect().height; if (h > 0) rowHeightPx = h; }
}

function virtRender(scrollTop) {
  if (!tbody || !tableWrap || !tableEl) return;
  const total    = filteredRows.length;
  const viewH    = tableWrap.clientHeight || 600;
  const top      = (scrollTop != null ? scrollTop : tableWrap.scrollTop) || 0;
  const visStart = Math.floor(top / rowHeightPx);
  const visEnd   = Math.ceil((top + viewH) / rowHeightPx);
  const winStart = Math.max(0,     visStart - Math.floor(VIRT_OVERSCAN / 2));
  const winEnd   = Math.min(total, visEnd   + Math.ceil(VIRT_OVERSCAN  / 2));
  if (winStart === virtOffset && tbody.childElementCount === winEnd - winStart) return;
  virtOffset = winStart;
  const parts = [];
  for (let i = winStart; i < winEnd; i++) parts.push(rowHtml(filteredRows[i]));
  tbody.innerHTML = parts.join('');
  measureRowHeight();
  setTablePadding(winStart, Math.max(0, total - winEnd));
}

let scrollRafPending = false;
function onTableScroll() {
  if (scrollRafPending) return;
  scrollRafPending = true;
  requestAnimationFrame(() => { scrollRafPending = false; virtRender(); });
}

/* ── Filter offset (sticky filter row top) ──────────────────────── */
function updateFilterOffset() {
  if (!thead || !tableWrap) return;
  const sortRow = thead.querySelector('tr.kc-sort-row');
  if (sortRow) tableWrap.style.setProperty('--thead-sort-h', `${sortRow.offsetHeight}px`);
}

/* ── Column filter controls ─────────────────────────────────────── */
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
      + options.map(v => `<option value="${esc(v)}"${colFilters[col.key] === String(v) ? ' selected' : ''}>${esc(v)}</option>`).join('');
    sel.addEventListener('change', scheduleFilter);
    fth.appendChild(sel);
    if (col.type === 'number') {
      const inp = document.createElement('input');
      inp.type = 'text'; inp.placeholder = '> < ='; inp.style.width = '48px'; inp.style.marginTop = '2px';
      inp.dataset.filterKey  = col.key;
      inp.dataset.filterRole = 'text';
      inp.value = colFilters[col.key] || '';
      inp.addEventListener('input', scheduleFilter);
      fth.appendChild(inp);
    }
  } else {
    const inp = document.createElement('input');
    inp.type = 'text'; inp.placeholder = 'Filter…';
    inp.dataset.filterKey  = col.key;
    inp.dataset.filterRole = 'text';
    inp.value = colFilters[col.key] || '';
    inp.addEventListener('input', scheduleFilter);
    fth.appendChild(inp);
  }
}

/* Lightweight rebuild: replace only filter-row <th> contents.
 * Called after deferred buildDistinct() populates COL_DISTINCT. */
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

function buildHead() {
  if (!thead) return;
  virtOffset = 0;
  setTablePadding(0, 0);
  /* Persist current filter values before wiping DOM. */
  document.querySelectorAll('[data-filter-key]').forEach(el => {
    colFilters[el.dataset.filterKey] = el.value || '';
  });
  const sortRow   = document.createElement('tr'); sortRow.className   = 'kc-sort-row';
  const filterRow = document.createElement('tr'); filterRow.className = 'kc-filter-row';
  COLS.forEach(col => {
    const th = document.createElement('th');
    th.innerHTML = `${esc(col.label)} <em class="kc-sort-icon" data-key="${esc(col.key)}"></em>`;
    th.addEventListener('click', () => {
      if (sortKey === col.key) sortDir = -sortDir;
      else { sortKey = col.key; sortDir = 1; }
      updateSortIcons();
      applySort();
      applyFilters();
    });
    sortRow.appendChild(th);
    const fth = document.createElement('th');
    buildFilterCtrl(col, fth);
    filterRow.appendChild(fth);
  });
  thead.innerHTML = ''; thead.appendChild(sortRow); thead.appendChild(filterRow);
  requestAnimationFrame(updateFilterOffset);
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
      out += `<td class="kc-td-num">${num > 0 ? scorePill(num) : '<span class="kc-muted">—</span>'}</td>`;
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

/* ── Sort — Schwartzian transform, no localeCompare ───────────────── */
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
  /* Do NOT invalidate haystackRows here — content hasn’t changed,
   * only order, and substring search doesn’t care about order.
   * The next applyFilters() call will use the existing cache. */
}

function renderRows() { applyFilters(); }

/* renderRowsAsync: synthetic progress bar (~150 ms) then applyFilters.
 * Virtual scroll makes the DOM work trivial regardless of dataset size. */
function renderRowsAsync(onProgress, onDone) {
  const total = sortedRows.length;
  if (total === 0) {
    filteredRows = []; if (tbody) tbody.innerHTML = '';
    setTablePadding(0, 0);
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

/* ── Filter ──────────────────────────────────────────────────────── */
let filterTimer  = 0;
/* haystackRows: index-synced to sortedRows, built lazily.
 * NOT invalidated on sort — content is identical, order irrelevant. */
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
  filterTimer = setTimeout(() => applyFilters(), 120);
}

/* Compile matchers once per active token, outside the row loop.
 * Returns an array of matcher functions, one per (col, token) pair. */
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
  /* Plain substring — no RegExp overhead. */
  return s => s.toLowerCase().includes(t);
}

function applyFilters() {
  const selectVals = Object.create(null);
  const textVals   = Object.create(null);
  document.querySelectorAll('[data-filter-key]').forEach(el => {
    const key = el.dataset.filterKey;
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
    /* Compile matchers once before the row loop. */
    const matchers = buildMatchers(activeCols, selectVals, textVals);
    const hay      = gTokens.length ? getHaystack() : null;
    filteredRows   = [];
    const n        = sortedRows.length;
    outer: for (let idx = 0; idx < n; idx++) {
      const r = sortedRows[idx];
      for (let mi = 0; mi < matchers.length; mi++) {
        const m  = matchers[mi];
        const cv = cellValue(r, m.key);
        if (!m.fn(cv)) continue outer;
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
  virtOffset = 0;
  if (tableWrap) tableWrap.scrollTop = 0;
  virtRender(0);
}

clearBtn?.addEventListener('click', () => {
  document.querySelectorAll('[data-filter-key]').forEach(el => { el.value = ''; colFilters[el.dataset.filterKey] = ''; });
  if (globalSrch) globalSrch.value = '';
  applyFilters();
});
globalSrch?.addEventListener('input', scheduleFilter);

/* CSV export — JS array only, no DOM scan. */
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
