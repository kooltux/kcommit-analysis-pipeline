/* summary_05_panes.js — kcommit-analysis-pipeline
 *
 * V2 layout: left pane is a push drawer, right pane is side column.
 * Left pane toggled via close button / overlay click.
 * Right pane collapse/expand and resize handle (same as v1).
 */

function rootFontSizePx() {
  return parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
}

/* ── Right pane collapse (same as v1) ────────────────────────────── */
(function () {
  const pane = document.getElementById('kc-pane-right');
  if (!pane) return;
  try { if (localStorage.getItem('kc-right-collapsed') === '1') pane.classList.add('kc-collapsed'); } catch(_) {}
  const btn = document.getElementById('kc-right-toggle');
  if (btn) {
    btn.textContent = pane.classList.contains('kc-collapsed') ? '\u2039' : '\u203a';
    btn.addEventListener('click', () => {
      pane.classList.toggle('kc-collapsed');
      try { localStorage.setItem('kc-right-collapsed', pane.classList.contains('kc-collapsed') ? '1' : '0'); } catch(_) {}
      btn.textContent = pane.classList.contains('kc-collapsed') ? '\u2039' : '\u203a';
    });
  }
})();

/* ── Left pane collapse (mirror of right pane) ──────────────────────── */
(function () {
  const pane = document.getElementById('kc-pane-left');
  if (!pane) return;
  try { if (localStorage.getItem('kc-left-collapsed') === '1') pane.classList.add('kc-collapsed'); } catch(_) {}
  const btn = document.getElementById('kc-left-toggle');
  if (btn) {
    /* Set initial icon: open = left-pointing, collapsed = right-pointing */
    btn.textContent = pane.classList.contains('kc-collapsed') ? '\u203a' : '\u2039';
    btn.addEventListener('click', () => {
      pane.classList.toggle('kc-collapsed');
      try { localStorage.setItem('kc-left-collapsed', pane.classList.contains('kc-collapsed') ? '1' : '0'); } catch(_) {}
      btn.textContent = pane.classList.contains('kc-collapsed') ? '\u203a' : '\u2039';
    });
  }
})();

/* ── Right-pane drag handle (same as v1) ─────────────────────────── */
(function () {
  const rHandle = document.getElementById('kc-right-handle');
  const rPane   = document.getElementById('kc-pane-right');
  if (!rHandle || !rPane) return;
  let startX, startW;
  rHandle.addEventListener('mousedown', e => {
    if (rPane.classList.contains('kc-collapsed')) return;
    startX = e.clientX;
    startW = rPane.getBoundingClientRect().width;
    rHandle.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  });
  window.addEventListener('mousemove', e => {
    if (!rHandle.classList.contains('dragging')) return;
    const rem = rootFontSizePx();
    const newW = Math.max(220, Math.min(700, startW + startX - e.clientX));
    rPane.style.width = `${(newW / rem).toFixed(3)}rem`;
  });
  window.addEventListener('mouseup', () => {
    rHandle.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  });
})();

/* ── Right pane maximise/restore ──────────────────────────────────── */
(function () {
  const pane = document.getElementById('kc-pane-right');
  const btn  = document.getElementById('kc-right-maximize');
  if (!pane || !btn) return;
  btn.addEventListener('click', () => {
    const currentStyle = pane.style.width;
    const current = currentStyle ? parseFloat(currentStyle) : 23.75;
    if (isNaN(current) || current < 40) {
      pane.style.width = '43.75rem';
      btn.textContent = '\u229f';
      btn.title = 'Restore detail pane';
    } else {
      pane.style.width = '';
      btn.textContent = '\u229e';
      btn.title = 'Maximize detail pane';
    }
  });
})();

/* ── Left pane maximise/restore ─────────────────────────────────────── */
(function () {
  const pane = document.getElementById('kc-pane-left');
  const btn  = document.getElementById('kc-left-maximize');
  if (!pane || !btn) return;
  btn.addEventListener('click', () => {
    const currentStyle = pane.style.width;
    const current = currentStyle ? parseFloat(currentStyle) : 18.75;
    if (isNaN(current) || current < 30) {
      pane.style.width = '43.75rem';
      btn.textContent = '\u229f';
      btn.title = 'Restore context pane';
    } else {
      pane.style.width = '';
      btn.textContent = '\u229e';
      btn.title = 'Maximize context pane';
    }
  });
})();

/* ── Left-pane drag handle ────────────────────────────────────────── */
(function () {
  const lHandle = document.getElementById('kc-left-handle');
  const lPane   = document.getElementById('kc-pane-left');
  if (!lHandle || !lPane) return;
  let startX, startW;
  lHandle.addEventListener('mousedown', e => {
    if (lPane.classList.contains('kc-collapsed')) return;
    startX = e.clientX;
    startW = lPane.getBoundingClientRect().width;
    lHandle.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  });
  window.addEventListener('mousemove', e => {
    if (!lHandle.classList.contains('dragging')) return;
    const rem = rootFontSizePx();
    const newW = Math.max(200, Math.min(500, startW + e.clientX - startX));
    lPane.style.width = `${(newW / rem).toFixed(3)}rem`;
  });
  window.addEventListener('mouseup', () => {
    lHandle.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  });
})();
