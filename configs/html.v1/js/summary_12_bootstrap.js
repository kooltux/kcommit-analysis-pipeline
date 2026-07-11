/* summary_12_bootstrap.js — kcommit-analysis-pipeline
 *
 * Bootstrap: build table header, show loader, kick off initial render.
 *
 * buildDistinct() is the single most expensive synchronous operation
 * on large datasets (rows × cols → Set construction). It must NOT run
 * before the first paint.
 *
 * Sequence:
 *   1. buildHead() with empty COL_DISTINCT — header + empty dropdowns appear.
 *   2. showLoader() — progress bar visible.
 *   3. renderRowsAsync() — 5-tick synthetic animation (~150 ms), then
 *      applyFilters() + virtRender() paint the first VIRT_OVERSCAN rows.
 *   4. hideLoader() — loader dismissed, table is visible and usable.
 *   5. buildDistinctAsync() — processes one column per idle/timeout tick
 *      so it never blocks the main thread on large datasets (perf B.1).
 *   6. buildHead() again — filter dropdowns rebuilt with real distinct values.
 *   7. applyFilters() — re-apply in case any dropdown default changed.
 */

/* Step 1-2 — empty dropdowns, loader on screen. */
COL_DISTINCT = Object.create(null);
COLS.forEach(c => { COL_DISTINCT[c.key] = []; });
buildHead();
showLoader(ROWS.length);

/* Step 3-7 */
renderRowsAsync(
  (done, total) => updateLoaderProgress(done, total),
  () => {
    hideLoader();   /* step 4 — table visible, usable */
    buildDistinctAsync(COLS, ROWS, dist => {  /* step 5 — chunked, non-blocking */
      COL_DISTINCT = dist;
      buildHead();     /* step 6 */
      applyFilters();  /* step 7 */
    });
  }
);
