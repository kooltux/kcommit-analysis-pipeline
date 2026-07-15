/* summary_01_globals.js — kcommit-analysis-pipeline
 *
 * Top-level constants, dataset preparation and mutable active-state.
 * Consumed by every other part; must be the first file concatenated.
 *
 * NOTE: COL_DISTINCT is intentionally left empty here.
 * bootstrap (summary_12) defers buildDistinct() to after first paint
 * so it never blocks the initial render.
 */

/* ========= Data globals ========= */
const UI    = window.__KC_UI__              || {};
const STORE = window.__KC_COMMITS__         || {};
const FSTORE= window.__KC_FILTERED_COMMITS__|| {};
const META  = UI.meta    || {};
const CTX   = UI.context || {};
const SB    = UI.sidebar || {};
const DROOT = (UI.detail_root || './commits').replace(/\/+$/, '');

/* ---- Two-tab mode detection ---------------------------------------- */
const TABS_CFG = UI.tabs || null;

/* ---- Relevant tab dataset ------------------------------------------ */
const BASE_COLS   = UI.columns || [];
const PROFILE_NAMES = (() => {
  const profilesCol = (UI.columns || []).find(c => c.key === 'profiles');
  return (profilesCol?.options || []).slice();
})();

const REL_COLS = (() => {
  const out = [];
  for (const col of BASE_COLS) {
    out.push(col);
    if (col.key === 'score' && PROFILE_NAMES.length) {
      for (const p of PROFILE_NAMES)
        out.push({ key: `score_${p}`, label: p, type: 'number', _profile: p });
    }
  }
  return out.filter(c => c.key !== 'profile_scores');
})();

const REL_ROWS = UI.rows || [];

/* ---- Filtered tab dataset ------------------------------------------ */
const FILT_COLS = UI.filtered_columns || [];
const FILT_ROWS = UI.filtered_rows    || [];

/* ---- Active dataset state (mutable) --------------------------------- */
let activeTab  = 'relevant';
let COLS       = REL_COLS;
let ROWS       = REL_ROWS;
let sortedRows = (UI.rows || []).slice();

/* ---- SHA → row lookup (both datasets) ------------------------------ */
const rowBySha = Object.create(null);
(UI.rows || []).forEach(r => { rowBySha[r.sha12] = r; if (r.sha) rowBySha[r.sha] = r; });

const filtRowBySha = Object.create(null);
FILT_ROWS.forEach(r => { filtRowBySha[r.sha12] = r; if (r.sha) filtRowBySha[r.sha] = r; });

/* ---- Per-column distinct value cache --------------------------------
 * buildDistinct() is O(rows × cols) and must NOT run at parse time.
 * COL_DISTINCT starts empty; bootstrap fills it after first paint.
 *
 * buildDistinctAsync() processes one column per idle/timeout tick so
 * it never blocks the main thread for large datasets (perf B.1).
 * ------------------------------------------------------------------- */
function buildDistinct(cols, rows) {
  /* Synchronous version — kept for callers that need an immediate return value. */
  const dist = Object.create(null);
  for (const col of cols) {
    const vals = new Set();
    for (const r of rows) {
      const v = r[col.key];
      if (Array.isArray(v)) { for (const x of v) vals.add(String(x)); }
      else if (v != null && v !== '') vals.add(String(v));
    }
    dist[col.key] = [...vals].sort((a, b) => {
      const na = parseFloat(a), nb = parseFloat(b);
      return (!isNaN(na) && !isNaN(nb)) ? na - nb : a.localeCompare(b);
    });
  }
  return dist;
}

/* Async variant: processes one column per idle/timeout tick.
 * Calls onDone(dist) when all columns are finished — no main-thread
 * jank on large datasets (perf B.1).
 * Uses requestIdleCallback when available (Chrome/Firefox),
 * falls back to setTimeout(0) for Safari. */
function buildDistinctAsync(cols, rows, onDone) {
  const dist = Object.create(null);
  let i = 0;
  const schedule = (typeof requestIdleCallback === 'function')
    ? cb => requestIdleCallback(cb, { timeout: 200 })
    : cb => setTimeout(cb, 0);
  function processNext() {
    if (i >= cols.length) { onDone(dist); return; }
    const col  = cols[i++];
    const vals = new Set();
    for (const r of rows) {
      const v = r[col.key];
      if (Array.isArray(v)) { for (const x of v) vals.add(String(x)); }
      else if (v != null && v !== '') vals.add(String(v));
    }
    dist[col.key] = [...vals].sort((a, b) => {
      const na = parseFloat(a), nb = parseFloat(b);
      return (!isNaN(na) && !isNaN(nb)) ? na - nb : a.localeCompare(b);
    });
    schedule(processNext);
  }
  schedule(processNext);
}

/* Empty placeholder — populated by bootstrap after first paint. */
let COL_DISTINCT = Object.create(null);
COLS.forEach(c => { COL_DISTINCT[c.key] = []; });
