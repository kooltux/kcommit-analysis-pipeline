/* summary_11_vtable.js — kcommit-analysis-pipeline
 *
 * Virtual scroll viewport for the commit table (v2).
 *
 * V1 used table padding-top/padding-bottom as spacers, which shifted the
 * sticky thead downward — root cause of the "header slides" scroll bug.
 *
 * V2 architecture:
 *  - thead lives in a separate fixed div (#kc-thead-wrap) above the scroll
 *    container — no sticky positioning inside the scroll host
 *  - scroll host = #kc-scroll-host (plain div, overflow-y: auto)
 *  - spacers = #kc-spacer-top / #kc-spacer-bot (div children of scroll host)
 *  - table has no thead, just tbody
 *  - Native scrollbar reads scrollHeight which is stable because spacers
 *    are <div>s not <tr>s (no reflow instability)
 *
 * Contract
 * --------
 * Reads (from summary_10_table.js):
 *   filteredRows[]        — current visible row set after applyFilters()
 *   rowHtml(row)          — HTML string builder for one <tr>
 *   tbody / tableEl       — DOM refs
 *   tableWrap             — scroll host DOM ref (#kc-scroll-host)
 *
 * Exposes:
 *   virtRender(scrollTop?) — paint the visible window into <tbody>
 *   resetVirt()            — call on tab-switch or full rebuild
 *   onTableScroll()        — rAF-gated scroll handler
 */

const VIRT_OVERSCAN = 60;
let   rowHeightPx   = 33;
let   virtOffset    = -1;

const spacerTop = document.getElementById('kc-spacer-top');
const spacerBot = document.getElementById('kc-spacer-bot');

function measureRowHeight() {
  const first = tbody?.querySelector('tr');
  if (first) { const h = first.getBoundingClientRect().height; if (h > 0) rowHeightPx = h; }
}

function virtRender(scrollTop) {
  if (!tbody || !tableWrap || !spacerTop || !spacerBot) return;
  const total = filteredRows.length;
  if (total === 0) {
    tbody.innerHTML = '';
    spacerTop.style.height = '0px';
    spacerBot.style.height = '0px';
    return;
  }

  const viewH = tableWrap.clientHeight || 600;
  const top = (scrollTop != null ? scrollTop : tableWrap.scrollTop) || 0;
  const visStart = Math.max(0, Math.floor(top / rowHeightPx));
  const visEnd = Math.min(total, Math.ceil((top + viewH) / rowHeightPx));
  const winStart = Math.max(0, visStart - Math.floor(VIRT_OVERSCAN / 2));
  const winEnd = Math.min(total, visEnd + Math.ceil(VIRT_OVERSCAN / 2));

  if (winStart === virtOffset && tbody.childElementCount === winEnd - winStart) return;

  virtOffset = winStart;
  const parts = [];
  for (let i = winStart; i < winEnd; i++) {
    if (i >= 0 && i < total) parts.push(rowHtml(filteredRows[i]));
  }
  tbody.innerHTML = parts.join('');
  measureRowHeight();

  const topPx = winStart * rowHeightPx;
  const botPx = Math.max(0, total - winEnd) * rowHeightPx;
  spacerTop.style.height = `${topPx}px`;
  spacerBot.style.height = `${botPx}px`;
}

function resetVirt() {
  virtOffset = -1;
  if (tableWrap) tableWrap.scrollTop = 0;
  if (spacerTop) spacerTop.style.height = '0px';
  if (spacerBot) spacerBot.style.height = '0px';
}

let _scrollRafPending = false;
function onTableScroll() {
  if (_scrollRafPending) return;
  _scrollRafPending = true;
  requestAnimationFrame(() => { _scrollRafPending = false; virtRender(); });
}
