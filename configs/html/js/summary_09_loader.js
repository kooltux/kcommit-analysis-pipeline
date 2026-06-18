/* summary_09_loader.js — kcommit-analysis-pipeline
 *
 * v17.0.0 table-loader overlay: spinner + centered progress bar + % badge.
 * showLoader(n)               — reset bar to 0% and reveal overlay.
 * updateLoaderProgress(d, t)  — advance bar fill, update label and % badge.
 * hideLoader()                — flash to 100%, then fade overlay out.
 */

const tableWrap = document.getElementById('kc-table-wrap');
let loaderEl = null, loaderLabelEl = null, loaderBarFillEl = null, loaderPctEl = null;

(function initLoader() {
  if (!tableWrap) return;
  loaderEl = document.createElement('div');
  loaderEl.className = 'kc-table-loader';
  loaderEl.innerHTML =
    '<div class="kc-spinner"></div>' +
    '<div class="kc-loader-panel" style="display:flex;flex-direction:column;align-items:center;gap:0;margin-top:10px">' +
      '<div class="kc-loader-label-row" style="display:flex;align-items:baseline;gap:8px;margin-bottom:6px">' +
        '<span class="kc-loader-label" id="kc-loader-label" style="font-size:13px;font-weight:500;letter-spacing:0.01em">Loading\u2026</span>' +
        '<span class="kc-loader-pct"   id="kc-loader-pct"   style="font-size:11px;font-weight:600;opacity:0;min-width:34px;text-align:right;transition:opacity 0.2s"></span>' +
      '</div>' +
      '<div class="kc-loader-bar" style="width:320px;max-width:min(320px,calc(100vw - 120px));height:8px;background:var(--kc-loader-bar-bg,rgba(128,128,128,0.18));border-radius:999px;overflow:hidden;box-shadow:inset 0 0 0 1px rgba(0,0,0,0.07)">' +
        '<div class="kc-loader-bar-fill" style="height:100%;width:0%;background:var(--kc-loader-bar-fill,var(--accent,#4a9eff));border-radius:999px;transition:width 0.35s ease"></div>' +
      '</div>' +
    '</div>';
  tableWrap.appendChild(loaderEl);
  loaderLabelEl   = loaderEl.querySelector('#kc-loader-label');
  loaderBarFillEl = loaderEl.querySelector('.kc-loader-bar-fill');
  loaderPctEl     = loaderEl.querySelector('#kc-loader-pct');
})();

function showLoader(rowCount) {
  if (!loaderEl) return;
  const eta = Math.round(rowCount / 1000);
  const etaText = eta < 1 ? 'a moment' : eta === 1 ? '~1 s' : `~${eta} s`;
  if (loaderLabelEl)   loaderLabelEl.textContent = `Loading ${rowCount.toLocaleString()} commits\u2026 (${etaText})`;
  if (loaderBarFillEl) { loaderBarFillEl.style.transition = 'none'; loaderBarFillEl.style.width = '0%'; }
  if (loaderPctEl)     { loaderPctEl.textContent = ''; loaderPctEl.style.opacity = '0'; }
  loaderEl.classList.add('kc-loader-active');
}

function updateLoaderProgress(done, total) {
  if (!loaderBarFillEl || !loaderLabelEl) return;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  loaderBarFillEl.style.transition = 'width 0.35s ease';
  loaderBarFillEl.style.width = pct + '%';
  loaderLabelEl.textContent = `Loading ${done.toLocaleString()} / ${total.toLocaleString()} commits\u2026`;
  if (loaderPctEl) { loaderPctEl.textContent = pct + '%'; loaderPctEl.style.opacity = '1'; }
}

function hideLoader() {
  if (!loaderEl) return;
  if (loaderBarFillEl) { loaderBarFillEl.style.transition = 'width 0.15s ease'; loaderBarFillEl.style.width = '100%'; }
  if (loaderPctEl)     { loaderPctEl.textContent = '100%'; }
  setTimeout(() => loaderEl.classList.remove('kc-loader-active'), 300);
}
