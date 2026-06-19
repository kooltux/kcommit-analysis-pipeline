/* summary_04_theme.js — kcommit-analysis-pipeline
 *
 * Dark / light theme: apply, persist, toggle button wiring.
 *
 * v18.3.0 — localStorage access wrapped in try/catch to prevent
 *           SecurityError crashes in sandboxed iframes and file:// origins.
 *           applyTheme() now always sets data-theme even when storage
 *           is unavailable.
 */

const html = document.documentElement;

function applyTheme(t) {
  html.setAttribute('data-theme', t);
  try { localStorage.setItem('kc-theme', t); } catch(_) {}
  const btn=document.getElementById('kc-theme-btn');
  if(btn) btn.title=`Switch to ${t==='dark'?'light':'dark'} mode`;
  const icon=document.getElementById('kc-theme-icon');
  if(icon) icon.textContent=t==='dark'?'\u2600\ufe0f':'\ud83c\udf19';
}

const savedTheme=(()=>{ try { return localStorage.getItem('kc-theme'); } catch(_) { return null; } })()
  ||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
applyTheme(savedTheme);
document.getElementById('kc-theme-btn')?.addEventListener('click',()=>applyTheme(html.getAttribute('data-theme')==='dark'?'light':'dark'));
