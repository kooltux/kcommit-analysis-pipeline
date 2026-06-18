/* summary_12_bootstrap.js — kcommit-analysis-pipeline
 *
 * Three bootstrap calls: build the table header, show the loader,
 * then kick off the async chunked row render.
 *
 * onDone is wrapped in requestAnimationFrame so the browser gets one
 * paint frame to render all appended rows before applyFilters() runs
 * its layout recalc — eliminates the post-100% freeze on large reports.
 */

buildHead();
showLoader(ROWS.length);
renderRowsAsync(
  (done, total) => updateLoaderProgress(done, total),
  () => requestAnimationFrame(() => { applyFilters(); hideLoader(); })
);
