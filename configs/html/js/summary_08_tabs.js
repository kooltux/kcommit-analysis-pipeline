/* summary_08_tabs.js — kcommit-analysis-pipeline
 *
 * Report-level tab bar (two-tab mode only) and switchTab() dataset switcher.
 *
 * V2: tabs live in #kc-report-tabs inside the top bar, not a separate strip.
 */

(function () {
  if (!TABS_CFG) return;
  const container = document.getElementById('kc-report-tabs');
  if (!container) return;
  TABS_CFG.forEach(tab => {
    const btn = document.createElement('button');
    btn.className = 'kc-report-tab' + (tab.id === 'relevant' ? ' kc-active' : '');
    btn.dataset.reportTab = tab.id;
    btn.setAttribute('role', 'tab');
    btn.setAttribute('aria-selected', tab.id === 'relevant' ? 'true' : 'false');
    btn.textContent = esc(tab.label);
    btn.addEventListener('click', () => switchTab(tab.id));
    container.appendChild(btn);
  });
})();

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
  sortedRows = ROWS.slice(); sortKey = null; sortDir = 1;
  /* Restore the server default sort on the relevant tab; filtered tab keeps
   * natural rank order. */
  if (name !== 'filtered' && DEFAULT_SORT && DEFAULT_SORT.key &&
      COLS.some(c => c.key === DEFAULT_SORT.key)) {
    sortKey = DEFAULT_SORT.key;
    sortDir = DEFAULT_SORT.dir === -1 ? -1 : 1;
  }
  haystackRows = null;
  /* Re-sort rows after switching tabs or restoring default sort. */
  if (sortKey) applySort();

  Object.keys(colFilters).forEach(k => { delete colFilters[k]; });
  COLS.forEach(c => { colFilters[c.key] = ''; });
  if (globalSrch) globalSrch.value = '';

  COL_DISTINCT = Object.create(null);
  COLS.forEach(c => { COL_DISTINCT[c.key] = []; });
  buildHead();
  showLoader(ROWS.length);
  renderRowsAsync(
    (done, total) => updateLoaderProgress(done, total),
    () => {
      hideLoader();
      buildDistinctAsync(COLS, ROWS, dist => {
        COL_DISTINCT = dist;
        rebuildFilterDropdowns();
        applyFilters();
      });
    }
  );
}
