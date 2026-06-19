/* summary_08_tabs.js — kcommit-analysis-pipeline
 *
 * Report-level tab bar (two-tab mode only) and switchTab() dataset switcher.
 *
 * v18.4.0 — switchTab() now resets colFilters to the new column set and
 *           clears the global search input before rebuilding the head.
 *           Previously, stale filter values from the departing tab bled
 *           into the incoming tab's buildHead() input restoration, causing
 *           filters and sorting to appear broken after the first tab switch
 *           (and permanently after switching back).
 */

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
  haystackRows = null;   /* invalidate haystack cache for new dataset */

  /* Reset column filters to the new column set so stale keys from the
   * previous tab do not bleed into buildHead() input restoration.
   * Also clear the global search so the new dataset starts unfiltered. */
  Object.keys(colFilters).forEach(k => { delete colFilters[k]; });
  COLS.forEach(c => { colFilters[c.key] = ''; });
  if (globalSrch) globalSrch.value = '';

  /* Show loader immediately, build head with empty COL_DISTINCT so the
   * UI is responsive instantly, then build the real distinct map async
   * (one column per idle tick, perf B.1) and rebuild dropdowns once ready. */
  COL_DISTINCT = Object.create(null);
  COLS.forEach(c => { COL_DISTINCT[c.key] = []; });
  buildHead();
  showLoader(ROWS.length);
  renderRowsAsync(
    (done, total) => updateLoaderProgress(done, total),
    () => {
      hideLoader();
      /* Defer the expensive distinct scan so hideLoader() paints first.
       * buildDistinctAsync processes one column per idle/timeout tick (B.1). */
      buildDistinctAsync(COLS, ROWS, dist => {
        COL_DISTINCT = dist;
        rebuildFilterDropdowns();  /* lightweight: only replaces filter <th> contents */
        applyFilters();            /* re-run in case any dropdown default changed */
      });
    }
  );
}
