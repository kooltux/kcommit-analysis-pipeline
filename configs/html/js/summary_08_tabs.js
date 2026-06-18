/* summary_08_tabs.js — kcommit-analysis-pipeline
 *
 * Report-level tab bar (two-tab mode only) and switchTab() dataset switcher.
 * In single-tab mode (no UI.tabs) this file is a no-op except for
 * declaring switchTab() which is referenced by bootstrap.
 */

/* ---- Tab bar rendering (two-tab mode only) -------------------------- */
(function () {
  if (!TABS_CFG) return;
  const toolbar = document.getElementById('kc-toolbar');
  if (!toolbar) return;
  const bar = document.createElement('div');
  bar.className = 'kc-report-tab-bar';
  bar.setAttribute('role', 'tablist');
  bar.setAttribute('aria-label', 'Report tabs');
  TABS_CFG.forEach(tab => {
    const btn = document.createElement('button');
    btn.className = 'kc-report-tab' + (tab.id === 'relevant' ? ' kc-active' : '');
    btn.dataset.reportTab = tab.id;
    btn.setAttribute('role', 'tab');
    btn.setAttribute('aria-selected', tab.id === 'relevant' ? 'true' : 'false');
    btn.innerHTML = `${esc(tab.label)} <span class="kc-tab-count">${esc(String(tab.count))}</span>`;
    btn.addEventListener('click', () => switchTab(tab.id));
    bar.appendChild(btn);
  });
  toolbar.insertAdjacentElement('beforebegin', bar);
})();

/* ---- Dataset switcher ---------------------------------------------- */
function switchTab(name) {
  if (name === activeTab) return;
  activeTab = name;
  COLS = name === 'filtered' ? FILT_COLS : REL_COLS;
  ROWS = name === 'filtered' ? FILT_ROWS : REL_ROWS;
  document.querySelectorAll('.kc-report-tab').forEach(btn => {
    const active = btn.dataset.reportTab === name;
    btn.classList.toggle('kc-active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  clearDetailPanel();
  buildHead();
  sortedRows = ROWS.slice(); sortKey = null; sortDir = 1;
  COL_DISTINCT = buildDistinct(COLS, ROWS);
  showLoader(ROWS.length);
  renderRowsAsync(
    (done, total) => updateLoaderProgress(done, total),
    /* onDone: give the browser one rAF to paint all appended rows before
     * running applyFilters() — avoids the post-100% freeze caused by a
     * synchronous full-table layout recalc in the same setTimeout tick. */
    () => requestAnimationFrame(() => { applyFilters(); hideLoader(); })
  );
}
