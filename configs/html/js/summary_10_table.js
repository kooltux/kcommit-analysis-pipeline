/* summary_10_table.js — kcommit-analysis-pipeline
 *
 * Middle pane: table head builder, per-column filter controls,
 * sort, row HTML generation, chunked async render, live filter,
 * clear-filters and CSV-export button wiring.
 */

const tbody      = document.getElementById('kc-tbody');
const thead      = document.getElementById('kc-thead');
const globalSrch = document.getElementById('kc-global-search');
const liveCount  = document.getElementById('kc-live-count');
const noMatch    = document.getElementById('kc-no-match');
const clearBtn   = document.getElementById('kc-clear-filters');
const exportBtn  = document.getElementById('kc-export-csv');

let sortKey = null, sortDir = 1, visibleCount = ROWS.length;
const colFilters = Object.create(null);
COLS.forEach(c => { colFilters[c.key] = ''; });

function updateFilterOffset() {
  if (!thead || !tableWrap) return;
  const sortRow = thead.querySelector('tr.kc-sort-row');
  if (!sortRow) return;
  tableWrap.style.setProperty('--thead-sort-h', `${sortRow.offsetHeight}px`);
}

function buildFilterCtrl(col, fth) {
  const distinct = COL_DISTINCT[col.key] || [];
  const useList = (col.type === 'select' && (col.options || []).length)
               || (distinct.length > 0 && distinct.length < 20);
  if (useList) {
    const options = col.options?.length ? col.options : distinct;
    const sel = document.createElement('select');
    sel.dataset.filterKey  = col.key;
    sel.dataset.filterRole = 'select';
    sel.innerHTML = `<option value="">All</option>`
      + options.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
    sel.addEventListener('change', scheduleFilter);
    fth.appendChild(sel);
    if (col.type === 'number') {
      const inp = document.createElement('input');
      inp.type = 'text'; inp.placeholder = '> < ='; inp.style.width = '48px'; inp.style.marginTop = '2px';
      inp.dataset.filterKey  = col.key;
      inp.dataset.filterRole = 'text';
      inp.addEventListener('input', scheduleFilter);
      fth.appendChild(inp);
    }
  } else {
    const inp = document.createElement('input');
    inp.type = 'text'; inp.placeholder = 'Filter\u2026';
    inp.dataset.filterKey  = col.key;
    inp.dataset.filterRole = 'text';
    inp.addEventListener('input', scheduleFilter);
    fth.appendChild(inp);
  }
}

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
      updateSortIcons(); applySort(); renderRows(); applyFilters();
    });
    sortRow.appendChild(th);
    const fth = document.createElement('th');
    buildFilterCtrl(col, fth);
    filterRow.appendChild(fth);
  });
  thead.innerHTML = ''; thead.appendChild(sortRow); thead.appendChild(filterRow);
  requestAnimationFrame(updateFilterOffset);
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
  if (activeTab === 'filtered') {
    const cells = COLS.map(col => {
      let v = r[col.key]; if (v == null) v = '';
      if (col.key === 'sha12')        return `<td class="kc-td-sha"><a href="#" class="kc-sha-link" data-sha12="${esc(r.sha12)}" data-sha="${esc(r.sha || r.sha12)}">${esc(r.sha12)}</a></td>`;
      if (col.key === 'filter_stage') return `<td>${stageBadge(v)}</td>`;
      if (col.key === 'date')         return `<td class="kc-td-num">${esc(fmtDate(v))}</td>`;
      return `<td>${esc(Array.isArray(v) ? v.join('; ') : v)}</td>`;
    }).join('');
    return `<tr data-sha12="${esc(r.sha12)}" data-sha="${esc(r.sha || r.sha12)}">${cells}</tr>`;
  }
  const cells = COLS.map(col => {
    let v = r[col.key]; if (v == null) v = '';
    if (col.key === 'sha12')           return `<td class="kc-td-sha"><a href="#" class="kc-sha-link" data-sha12="${esc(r.sha12)}" data-sha="${esc(r.sha || r.sha12)}">${esc(r.sha12)}</a></td>`;
    if (col.key === 'score' || col._profile) { const num = parseFloat(v) || 0; return `<td class="kc-td-num">${num > 0 ? scorePill(num) : '<span class="kc-muted">\u2014</span>'}</td>`; }
    if (col.key === 'profiles')        return `<td>${chips(Array.isArray(v) ? v : [v])}</td>`;
    if (col.key === 'date')            return `<td class="kc-td-num">${esc(fmtDate(v))}</td>`;
    return `<td>${esc(Array.isArray(v) ? v.join('; ') : v)}</td>`;
  }).join('');
  return `<tr data-sha12="${esc(r.sha12)}" data-sha="${esc(r.sha || r.sha12)}">${cells}</tr>`;
}

function applySort() {
  if (!sortKey) return;
  sortedRows.sort((a, b) => {
    const av = cellValue(a, sortKey), bv = cellValue(b, sortKey);
    const an = parseFloat(av), bn = parseFloat(bv);
    const cmp = (!isNaN(an) && !isNaN(bn)) ? an - bn : av.localeCompare(bv, undefined, { numeric: true });
    return cmp * sortDir;
  });
}

function renderRows() {
  if (!tbody) return;
  tbody.innerHTML = sortedRows.map(rowHtml).join('');
}

/* renderRowsAsync — chunked DOM build with per-chunk progress callbacks.
 * CHUNK_SIZE rows per setTimeout(0) tick so the browser can repaint the
 * progress bar between chunks. */
const CHUNK_SIZE = 500;
function renderRowsAsync(onProgress, onDone) {
  if (!tbody) { onDone && onDone(); return; }
  const rows = sortedRows, total = rows.length;
  if (total === 0) { tbody.innerHTML = ''; onDone && onDone(); return; }
  tbody.innerHTML = '';
  let offset = 0;
  function nextChunk() {
    if (offset >= total) { onDone && onDone(); return; }
    const end  = Math.min(offset + CHUNK_SIZE, total);
    const frag = document.createDocumentFragment();
    for (let i = offset; i < end; i++) {
      const t = document.createElement('template');
      t.innerHTML = rowHtml(rows[i]);
      frag.appendChild(t.content);
    }
    tbody.appendChild(frag);
    offset = end;
    onProgress && onProgress(offset, total);
    setTimeout(nextChunk, 0);
  }
  setTimeout(nextChunk, 0);
}

let filterTimer = 0;
function scheduleFilter() { clearTimeout(filterTimer); filterTimer = setTimeout(applyFilters, 60); }

function matchToken(text, token) {
  if (!token) return true;
  const t = token.trim().toLowerCase(), s = text.toLowerCase();
  if (t.startsWith('>')) { const n = parseFloat(t.slice(1)); return !isNaN(n) && parseFloat(s) > n; }
  if (t.startsWith('<')) { const n = parseFloat(t.slice(1)); return !isNaN(n) && parseFloat(s) < n; }
  if (t.startsWith('=')) return s === t.slice(1);
  const pat = t.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
  try { return new RegExp(pat).test(s); } catch { return s.includes(t); }
}

function applyFilters() {
  const selectVals = Object.create(null), textVals = Object.create(null);
  document.querySelectorAll('[data-filter-key]').forEach(el => {
    const key = el.dataset.filterKey, role = el.dataset.filterRole || 'text';
    if (role === 'select') selectVals[key] = el.value || '';
    else                   textVals[key]   = el.value || '';
    colFilters[key] = el.value || '';
  });
  const global  = (globalSrch?.value || '').trim().toLowerCase();
  const gTokens = global ? global.split(/\s+/).filter(Boolean) : [];

  /* Fast path: no active filters — skip per-row querySelector scan entirely.
   * On initial load (always) this avoids a full layout recalc that would
   * freeze the browser after the last chunk is appended. */
  const noFilters = !gTokens.length && COLS.every(col =>
    !(selectVals[col.key] || '').trim() && !(textVals[col.key] || '').trim()
  );
  if (noFilters) {
    tbody?.querySelectorAll('tr.kc-hidden').forEach(tr => tr.classList.remove('kc-hidden'));
    visibleCount = ROWS.length;
    if (liveCount) liveCount.textContent = `Showing ${ROWS.length.toLocaleString()} of ${ROWS.length.toLocaleString()} commits`;
    if (noMatch)   noMatch.classList.remove('kc-visible');
    return;
  }

  let shown = 0;
  sortedRows.forEach(r => {
    const tr = tbody?.querySelector(`tr[data-sha12="${CSS.escape(r.sha12)}"]`);
    if (!tr) return;
    let ok = COLS.every(col => {
      const sv = (selectVals[col.key] || '').trim();
      const tv = (textVals[col.key]   || '').trim();
      const cv = cellValue(r, col.key);
      if (sv && !matchToken(cv, sv)) return false;
      if (tv && !matchToken(cv, tv)) return false;
      return true;
    });
    if (ok && gTokens.length) {
      const hay = Object.values(r).map(v => Array.isArray(v) ? v.join(' ') : String(v ?? '')).join(' ').toLowerCase();
      ok = gTokens.every(t => hay.includes(t));
    }
    tr.classList.toggle('kc-hidden', !ok);
    if (ok) shown++;
  });
  visibleCount = shown;
  if (liveCount) liveCount.textContent = `Showing ${shown} of ${ROWS.length} commits`;
  if (noMatch)   noMatch.classList.toggle('kc-visible', shown === 0);
}

clearBtn?.addEventListener('click', () => {
  document.querySelectorAll('[data-filter-key]').forEach(el => { el.value = ''; });
  if (globalSrch) globalSrch.value = '';
  applyFilters();
});
globalSrch?.addEventListener('input', scheduleFilter);

exportBtn?.addEventListener('click', () => {
  const header = COLS.map(c => `"${c.label.replace(/"/g, '""')}"`).join(',');
  const lines  = [header];
  (tbody?.querySelectorAll('tr:not(.kc-hidden)') || []).forEach(tr => {
    lines.push(Array.from(tr.querySelectorAll('td'))
      .map(td => `"${td.textContent.trim().replace(/"/g, '""')}"`).join(','));
  });
  const blob = new Blob([lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const a    = document.createElement('a');
  a.href     = URL.createObjectURL(blob);
  a.download = activeTab === 'filtered' ? 'kcommit-filtered.csv' : 'kcommit-report.csv';
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
});
