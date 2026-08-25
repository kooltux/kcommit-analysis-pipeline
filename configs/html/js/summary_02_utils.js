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

/* ========= Profile colour legend =========
 * Deterministic per-profile colour derived from a hash of the profile name,
 * so the same profile always gets the same hue across the sidebar legend and
 * the table "Profiles" column.  Hues are constrained to 180..330° (cyan →
 * blue → purple → magenta) to deliberately avoid the red/orange/green band
 * (0..150°) used by the numeric heat-pill scheme on Score %, Backport Cx and Pick Priority. */
function profileHue(name) {
  const s = String(name == null ? '' : name);
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return 180 + (h % 151);   /* 180..330 inclusive */
}

function profileColor(name) {
  return `hsl(${profileHue(name)}, 65%, 55%)`;
}

function profileBullet(name, withLabel) {
  const color = profileColor(name);
  const dot = `<span class="kc-prof-bullet" style="background:${color}" aria-hidden="true"></span>`;
  return withLabel
    ? `<span class="kc-prof-legend-item"><span title="${esc(name)}">${dot}</span>${esc(name)}</span>`
    : `<span class="kc-prof-dot-wrap" title="${esc(name)}">${dot}</span>`;
}

function profileBullets(arr) {
  return `<span class="kc-prof-bullets">${
    (arr || []).filter(p => p != null && p !== '').map(p => profileBullet(p, false)).join('')
  }</span>`;
}

/* ========= 4-level heat coloring =========
 *
 * heatLevel(value, scale) → 1..4 (even quartiles of value/scale, clamped)
 * heatPill(value, {scale, polarity}) → pill with .kc-heat-1..4; polarity:
 *   'higher-better' → level 1=green(top)…4=red(bottom)
 *   'higher-worse' → level 1=red(top)…4=green(bottom)
 */
function heatLevel(value, scale) {
  const v = parseFloat(value) || 0;
  const s = parseFloat(scale) || 1;
  const q = Math.min(100, Math.max(0, Math.round(100 * v / s)));
  return q >= 75 ? 4 : q >= 50 ? 3 : q >= 25 ? 2 : 1;
}

function heatPill(value, {scale, polarity}) {
  const level = heatLevel(value, scale);
  const v = parseFloat(value);
  if (!Number.isFinite(v)) return '<span class="kc-muted">—</span>';
  /* heat classes: 1=green (best), 2=lime, 3=orange, 4=red (worst)
   * higher-better (score%, pick_priority): invert so low level → red, high level → green
   * higher-worse (backport_cx): keep direct so low level → green, high level → red */
  const cls = polarity === 'higher-better' ? [4, 3, 2, 1][level - 1] : level;
  return `<span class="kc-heat-pill kc-heat-${cls}">${esc(v)}</span>`;
}

function stageBadge(stage) {
  const cls = stage === 'prefilter' ? 'kc-chip-prefilter' : 'kc-chip-postfilter';
  return `<span class="kc-chip ${cls}">${esc(stage || '—')}</span>`;
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
