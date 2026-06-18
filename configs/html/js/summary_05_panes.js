/* summary_05_panes.js — kcommit-analysis-pipeline
 *
 * Three-pane layout: collapse/expand toggles and drag-resize handles
 * for the left pane (left-edge handle) and right pane (right-edge handle).
 */

function rootFontSizePx() {
  return parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
}

function initPane(pane, storageKey, btnId) {
  if (!pane) return;
  if (localStorage.getItem(storageKey) === '1') pane.classList.add('kc-collapsed');
  const btn = document.getElementById(btnId);
  if (btn) btn.addEventListener('click', () => {
    pane.classList.toggle('kc-collapsed');
    localStorage.setItem(storageKey, pane.classList.contains('kc-collapsed') ? '1' : '0');
    updateCollapseIcons();
  });
}

function updateCollapseIcons() {
  const left  = document.getElementById('kc-pane-left');
  const right = document.getElementById('kc-pane-right');
  const lb    = document.getElementById('kc-left-toggle');
  const rb    = document.getElementById('kc-right-toggle');
  if (lb) lb.textContent = (left  && left.classList.contains('kc-collapsed'))  ? '\u203a' : '\u2039';
  if (rb) rb.textContent = (right && right.classList.contains('kc-collapsed')) ? '\u2039' : '\u203a';
}

initPane(document.getElementById('kc-pane-left'),  'kc-left-collapsed',  'kc-left-toggle');
initPane(document.getElementById('kc-pane-right'), 'kc-right-collapsed', 'kc-right-toggle');
updateCollapseIcons();

/* ---- Left-pane drag handle (drag right edge of left pane) ----------- */
document.querySelectorAll('.kc-handle').forEach(handle => {
  if (handle.id === 'kc-right-handle') return;
  const target = handle.previousElementSibling;
  if (!target) return;
  let startX, startW;
  handle.addEventListener('mousedown', e => {
    startX = e.clientX;
    startW = target.getBoundingClientRect().width;
    handle.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  });
  window.addEventListener('mousemove', e => {
    if (!handle.classList.contains('dragging')) return;
    const rem = rootFontSizePx();
    const newW = Math.max(180, Math.min(700, startW + e.clientX - startX));
    target.style.width = `${(newW / rem).toFixed(3)}rem`;
  });
  window.addEventListener('mouseup', () => {
    handle.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  });
});

/* ---- Right-pane drag handle (left edge of right pane)
 *      Sign is intentionally inverted: drag left = grow, drag right = shrink.
 * -------------------------------------------------------------------- */
(function () {
  const rHandle = document.getElementById('kc-right-handle');
  const rPane   = document.getElementById('kc-pane-right');
  if (!rHandle || !rPane) return;
  let startX, startW;
  rHandle.addEventListener('mousedown', e => {
    startX = e.clientX;
    startW = rPane.getBoundingClientRect().width;
    rHandle.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  });
  window.addEventListener('mousemove', e => {
    if (!rHandle.classList.contains('dragging')) return;
    const rem = rootFontSizePx();
    /* startX - e.clientX: drag left increases width (left-edge handle). */
    const newW = Math.max(220, Math.min(700, startW + startX - e.clientX));
    rPane.style.width = `${(newW / rem).toFixed(3)}rem`;
  });
  window.addEventListener('mouseup', () => {
    rHandle.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  });
})();
