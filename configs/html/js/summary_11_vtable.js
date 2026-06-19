/* summary_11_vtable.js — kcommit-analysis-pipeline
 *
 * Virtual scroll viewport for the commit table.
 *
 * Contract
 * --------
 * Reads (from summary_10_table.js, declared before this file):
 *   filteredRows[]        — current visible row set after applyFilters()
 *   rowHtml(row)          — HTML string builder for one <tr>
 *   tbody / tableEl / tableWrap — DOM refs
 *
 * Exposes:
 *   virtRender(scrollTop?) — paint the visible window into <tbody>
 *   resetVirt()            — call on tab-switch or full rebuild
 *   onTableScroll()        — rAF-gated scroll handler (attach to tableWrap)
 *
 * Only VIRT_OVERSCAN rows live in <tbody> at any time.
 * padding-top / padding-bottom on <table> simulate full dataset height
 * so the scrollbar thumb correctly reflects the total row count.
 *
 * v18.5.1 — resetVirt() now sets virtOffset = -1 (sentinel) instead of 0.
 *
 *   The skip guard in virtRender() is:
 *     if (winStart === virtOffset && tbody.childElementCount === winEnd - winStart) return;
 *
 *   After applyFilters() calls resetVirt() then virtRender(0), winStart is
 *   always 0 (scroll is at top).  If virtOffset was also 0 AND the viewport
 *   holds the same number of rows as before the filter (e.g. a filter that
 *   reduces 500 rows to 490 rows while the viewport shows 60 rows), both
 *   conditions are satisfied and the repaint is silently skipped — leaving
 *   stale rows on screen.  This caused all three reported symptoms:
 *
 *     • Filter has no visible effect (rows not repainted after applyFilters)
 *     • Sort has no visible effect after a filter has been applied
 *     • Filtering on the second tab shows nothing / shows wrong rows
 *
 *   Fix: resetVirt() sets virtOffset = -1.  virtRender() always finds
 *   winStart (≥ 0) ≠ virtOffset (-1) on the first call after a reset,
 *   so the skip guard always fails and a full repaint occurs.  The guard
 *   then functions correctly for subsequent scroll events where no data
 *   has changed.
 */

const VIRT_OVERSCAN = 60;   /* rows above+below visible window kept in DOM */
let   rowHeightPx   = 33;   /* estimated; updated after first real paint    */
let   virtOffset    = -1;   /* -1 = sentinel: force repaint on next virtRender() */

function setTablePadding(topRows, bottomRows) {
  if (!tableEl) return;
  tableEl.style.paddingTop    = topRows    > 0 ? `${topRows    * rowHeightPx}px` : '';
  tableEl.style.paddingBottom = bottomRows > 0 ? `${bottomRows * rowHeightPx}px` : '';
}

function measureRowHeight() {
  const first = tbody?.querySelector('tr');
  if (first) { const h = first.getBoundingClientRect().height; if (h > 0) rowHeightPx = h; }
}

/* virtRender — core virtual-scroll painter.
 *
 * Computes the visible window from scrollTop + clientHeight, adds
 * VIRT_OVERSCAN rows as buffer above and below, then replaces <tbody>
 * only when the window has actually moved.  All rows outside the window
 * are represented by padding on <table> rather than DOM nodes.
 *
 * The skip guard (winStart === virtOffset && childCount === winEnd - winStart)
 * is only satisfied after a real scroll event where no data changed.  It is
 * never satisfied immediately after resetVirt() because resetVirt() sets
 * virtOffset = -1 and winStart is always >= 0.
 */
function virtRender(scrollTop) {
  if (!tbody || !tableWrap || !tableEl) return;
  const total    = filteredRows.length;
  const viewH    = tableWrap.clientHeight || 600;
  const top      = (scrollTop != null ? scrollTop : tableWrap.scrollTop) || 0;
  const visStart = Math.floor(top / rowHeightPx);
  const visEnd   = Math.ceil((top + viewH) / rowHeightPx);
  const winStart = Math.max(0,     visStart - Math.floor(VIRT_OVERSCAN / 2));
  const winEnd   = Math.min(total, visEnd   + Math.ceil(VIRT_OVERSCAN  / 2));

  /* Skip repaint when viewport window has not changed.  virtOffset = -1
   * (set by resetVirt) guarantees this never fires on a forced repaint. */
  if (winStart === virtOffset && tbody.childElementCount === winEnd - winStart) return;

  virtOffset = winStart;
  const parts = [];
  for (let i = winStart; i < winEnd; i++) parts.push(rowHtml(filteredRows[i]));
  tbody.innerHTML = parts.join('');
  measureRowHeight();
  setTablePadding(winStart, Math.max(0, total - winEnd));
}

/* resetVirt — call before a full re-filter or tab switch.
 *
 * Sets virtOffset = -1 (sentinel) so the skip guard in virtRender() always
 * fails on the immediately following virtRender(0) call from applyFilters().
 * Without this, a filter or sort that leaves the visible row count unchanged
 * would satisfy both guard conditions and silently skip the repaint.
 */
function resetVirt() {
  virtOffset = -1;   /* sentinel: next virtRender() must repaint unconditionally */
  if (tableWrap) tableWrap.scrollTop = 0;
  setTablePadding(0, 0);
}

/* onTableScroll — rAF-gated handler; attach once per buildHead() call. */
let _scrollRafPending = false;
function onTableScroll() {
  if (_scrollRafPending) return;
  _scrollRafPending = true;
  requestAnimationFrame(() => { _scrollRafPending = false; virtRender(); });
}
