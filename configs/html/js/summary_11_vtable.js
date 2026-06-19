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
 */

const VIRT_OVERSCAN = 60;   /* rows above+below visible window kept in DOM */
let   rowHeightPx   = 33;   /* estimated; updated after first real paint    */
let   virtOffset    = 0;    /* index of the first row currently in <tbody>  */

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

  /* Skip repaint when viewport window has not changed. */
  if (winStart === virtOffset && tbody.childElementCount === winEnd - winStart) return;

  virtOffset = winStart;
  const parts = [];
  for (let i = winStart; i < winEnd; i++) parts.push(rowHtml(filteredRows[i]));
  tbody.innerHTML = parts.join('');
  measureRowHeight();
  setTablePadding(winStart, Math.max(0, total - winEnd));
}

/* resetVirt — call before a full re-filter or tab switch.
 * Scrolls the table back to the top and clears the padding state. */
function resetVirt() {
  virtOffset = 0;
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
