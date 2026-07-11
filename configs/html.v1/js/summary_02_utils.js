/* summary_02_utils.js — kcommit-analysis-pipeline
 *
 * Pure helper functions: escaping, formatting, UI atoms.
 * No DOM access, no side effects.
 */

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/[&<>"']/g, m => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[m]));
}

function escNl(s) {
  return esc(s).replace(/\\n/g, '<br>').replace(/\n/g, '<br>');
}

function fmtDate(ts) {
  if (!ts) return '';
  const n = Number(ts);
  if (!Number.isNaN(n) && n > 1e8) {
    const d = new Date(n * 1000);
    const p = x => String(x).padStart(2, '0');
    return `${d.getUTCFullYear()}-${p(d.getUTCMonth()+1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
  }
  return String(ts).slice(0, 16);
}

function scoreClass(v) {
  v = parseFloat(v) || 0;
  return v >= 70 ? 'kc-hi' : v >= 30 ? 'kc-mid' : 'kc-low';
}

function scorePill(v) {
  return `<span class="kc-score-pill ${scoreClass(v)}">${esc(v)}</span>`;
}

function chips(arr) {
  return (arr || []).map(p => `<span class="kc-chip">${esc(p)}</span>`).join(' ');
}

function stageBadge(stage) {
  const cls = stage === 'prefilter' ? 'kc-chip-prefilter' : 'kc-chip-postfilter';
  return `<span class="kc-chip ${cls}">${esc(stage || '\u2014')}</span>`;
}

function kv(label, val, tip) {
  const tipHtml = tip
    ? `<i class="kc-info-icon" role="button" aria-label="${esc(label)} help" tabindex="0">i<span class="kc-tooltip">${esc(tip)}</span></i>`
    : '';
  const labelHtml = tip
    ? `<span class="kc-kv-label"><span class="kc-kv-label-wrap">${esc(label)}${tipHtml}</span></span>`
    : `<span class="kc-kv-label">${esc(label)}</span>`;
  return `<div class="kc-kv">${labelHtml}<span class="kc-kv-value">${val}</span></div>`;
}

function detailCard(title, bodyHtml, icon) {
  const ico = icon ? `<span>${icon}</span>` : '';
  return `<div class="kc-detail-card">
    <div class="kc-detail-card-head">${ico}${esc(title)}</div>
    <div class="kc-detail-card-body">${bodyHtml}</div>
  </div>`;
}

/* ========= Tooltip positioning ========= */
function positionTooltip(icon) {
  const tip = icon.querySelector('.kc-tooltip');
  if (!tip) return;
  tip.style.left='0'; tip.style.top='0';
  const iconRect=icon.getBoundingClientRect();
  const tipW=tip.offsetWidth||220,tipH=tip.offsetHeight||40;
  const GAP=8,MARGIN=8;
  let left=iconRect.left+iconRect.width/2-tipW/2;
  let top=iconRect.top-tipH-GAP;
  left=Math.max(MARGIN,Math.min(left,window.innerWidth-tipW-MARGIN));
  if(top<MARGIN){ top=iconRect.bottom+GAP; tip.classList.add('kc-tooltip-below'); }
  else { tip.classList.remove('kc-tooltip-below'); }
  tip.style.left=`${Math.round(left)}px`; tip.style.top=`${Math.round(top)}px`;
}
