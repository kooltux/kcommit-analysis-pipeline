/* kcommit-analysis-pipeline — v17.0.0 UI
 *
 * v17.0.0: Tab-switch loader overlay with real chunked-render progress bar.
 *   — initLoader() injects a .kc-loader-bar / .kc-loader-bar-fill element
 *     into the overlay alongside the spinner and label.
 *   — showLoader(n) resets the bar to 0% before revealing the overlay.
 *   — updateLoaderProgress(done, total) advances the bar and rewrites the
 *     label ("Loading 1,800 / 5,000 commits…") after every chunk.
 *   — renderRowsAsync(onProgress, onDone) replaces the old single-shot
 *     renderRows()+setTimeout(0) pattern with a 500-row-per-tick loop so
 *     the browser can repaint the bar between chunks.
 *   — hideLoader() flashes the bar to 100% then fades the overlay out.
 *   — switchTab() and the bootstrap call both now use renderRowsAsync.
 *   — No external CSS changes required; bar styles are inline with CSS
 *     variable hooks (--kc-loader-bar-bg, --kc-loader-bar-fill).
 *   — Loader panel is fixed-width (320 px) and centered for readability.
 *
 * v16.14.0: Unified two-tab HTML report.
 *   — Reads window.__KC_UI__.tabs to detect two-tab mode.
 *   — Tab bar rendered above the table toolbar when tabs are present.
 *   — switchTab(name) swaps the active dataset (columns + rows + store),
 *     rebuilds the table head, re-renders rows, resets filters, and
 *     clears the right detail panel.
 *   — Filtered tab uses filtered_columns / filtered_rows from KC_UI
 *     and window.__KC_FILTERED_COMMITS__ as its detail store.
 *   — rowHtml() dispatches on activeTab: filtered rows render a
 *     filter_stage badge + drop reason; no score pill, no profile chips.
 *   — openDetail() dispatches on activeTab: filtered tab calls
 *     populateFilteredDetail() which shows metadata + drop decision
 *     (prefilter_debug) + commit message; hides scoring tabs.
 *   — liveCount and export CSV filename update per active tab.
 *   — Legacy single-tab mode (no UI.tabs) is fully unchanged.
 *
 * v16.12.6: Bug fixes from audit:
 *   BUG-02 updateFilterOffset() measures sortRow.offsetHeight after
 *          buildHead() and on window resize; writes the value as a
 *          CSS custom property on .kc-table-wrap so the filter row's
 *          `top` is always exact, even when column labels wrap.
 *   BUG-04 Right-pane drag: sign is correct for a left-edge handle
 *          (drag left = grow, drag right = shrink). Added comment to
 *          document the intentional direction; no behaviour change.
 * v16.12.3: Remove "Stage 05 — " and "Stage 06 — " prefixes from section
 *           labels; keep only "SCORING" and "POSTFILTER".
 */
(function () {
  'use strict';

  /* ========= Globals ========= */
  const UI    = window.__KC_UI__              || {};
  const STORE = window.__KC_COMMITS__         || {};
  const FSTORE= window.__KC_FILTERED_COMMITS__|| {};
  const META  = UI.meta    || {};
  const CTX   = UI.context || {};
  const SB    = UI.sidebar || {};
  const DROOT = (UI.detail_root || './commits').replace(/\/+$/, '');

  /* ---- Two-tab mode detection ---------------------------------------- */
  const TABS_CFG = UI.tabs || null;

  /* ---- Relevant tab dataset ------------------------------------------ */
  const BASE_COLS   = UI.columns || [];
  const PROFILE_NAMES = (() => {
    const names = new Set();
    (UI.rows || []).forEach(r => (r.profiles || []).forEach(p => names.add(p)));
    return [...names].sort();
  })();

  const REL_COLS = (() => {
    const out = [];
    for (const col of BASE_COLS) {
      out.push(col);
      if (col.key === 'score' && PROFILE_NAMES.length) {
        for (const p of PROFILE_NAMES)
          out.push({ key: `score_${p}`, label: p, type: 'number', _profile: p });
      }
    }
    return out.filter(c => c.key !== 'profile_scores');
  })();

  const REL_ROWS = (UI.rows || []).map(r => {
    const out = Object.assign({}, r);
    for (const p of PROFILE_NAMES) {
      const k = `score_${p}`;
      if (out[k] == null) out[k] = 0;
    }
    return out;
  });

  /* ---- Filtered tab dataset ------------------------------------------ */
  const FILT_COLS = UI.filtered_columns || [];
  const FILT_ROWS = UI.filtered_rows    || [];

  /* ---- Active dataset state (mutable) --------------------------------- */
  let activeTab  = 'relevant';
  let COLS       = REL_COLS;
  let ROWS       = REL_ROWS;
  let sortedRows = REL_ROWS.slice();

  /* ---- SHA → row lookup (both datasets) ------------------------------ */
  const rowBySha = Object.create(null);
  REL_ROWS.forEach(r => { rowBySha[r.sha12] = r; if (r.sha) rowBySha[r.sha] = r; });

  const filtRowBySha = Object.create(null);
  FILT_ROWS.forEach(r => { filtRowBySha[r.sha12] = r; if (r.sha) filtRowBySha[r.sha] = r; });

  /* ---- Per-column distinct value cache -------------------------------- */
  function buildDistinct(cols, rows) {
    const dist = Object.create(null);
    cols.forEach(col => {
      const vals = new Set();
      rows.forEach(r => {
        const v = r[col.key];
        if (Array.isArray(v)) v.forEach(x => vals.add(String(x)));
        else if (v != null && v !== '') vals.add(String(v));
      });
      dist[col.key] = [...vals].sort((a, b) => {
        const na = parseFloat(a), nb = parseFloat(b);
        return (!isNaN(na) && !isNaN(nb)) ? na - nb : a.localeCompare(b);
      });
    });
    return dist;
  }

  let COL_DISTINCT = buildDistinct(REL_COLS, REL_ROWS);

  /* ========= Helpers ========= */

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

  /* =========================================================
   * renderScoreChart(distItems, ss)
   * =========================================================
   */
  function renderScoreChart(distItems, ss) {
    if (!distItems || !distItems.length) return '';
    let statsHtml = '';
    if (ss) {
      const pills = [];
      if (ss.score_max    != null) pills.push(['Max',    ss.score_max]);
      if (ss.score_min    != null) pills.push(['Min',    ss.score_min]);
      if (ss.score_avg    != null) pills.push(['Avg',    ss.score_avg]);
      if (ss.score_median != null) pills.push(['Median', ss.score_median]);
      if (pills.length) {
        statsHtml = `<div class="kc-dist-stats">${
          pills.map(([label, val]) =>
            `<div class="kc-dist-stat">
              <span class="kc-dist-stat-label">${esc(label)}</span>
              <span class="kc-dist-stat-value">${esc(val)}</span>
            </div>`
          ).join('')
        }</div>`;
      }
    }
    const W=240,H=130,ML=28,MR=8,MT=20,MB=28;
    const PW=W-ML-MR, PH=H-MT-MB;
    const N=distItems.length;
    const counts=distItems.map(b=>b.count||0);
    const BW=1.0;
    const kdeRaw=counts.map((_,xi)=>{
      let sum=0;
      counts.forEach((c,i)=>{ const u=(xi-i)/BW; sum+=c*Math.exp(-0.5*u*u); });
      return sum;
    });
    const kdeMax=Math.max(1,...kdeRaw);
    function ptX(i){ return N<2?ML+PW/2:ML+(i/(N-1))*PW; }
    function ptY(kde){ return MT+PH-(kde/kdeMax)*PH*0.90; }
    const pts=kdeRaw.map((k,i)=>({x:ptX(i),y:ptY(k)}));
    function crToCubic(p0,p1,p2,p3){
      const alpha=0.5;
      const cp1x=p1.x+(p2.x-p0.x)/6*alpha*2;
      const cp1y=p1.y+(p2.y-p0.y)/6*alpha*2;
      const cp2x=p2.x-(p3.x-p1.x)/6*alpha*2;
      const cp2y=p2.y-(p3.y-p1.y)/6*alpha*2;
      return {cp1x,cp1y,cp2x,cp2y};
    }
    let curvePath=`M ${pts[0].x.toFixed(1)},${pts[0].y.toFixed(1)}`;
    for(let i=0;i<pts.length-1;i++){
      const p0=pts[Math.max(0,i-1)],p1=pts[i],p2=pts[i+1],p3=pts[Math.min(pts.length-1,i+2)];
      const {cp1x,cp1y,cp2x,cp2y}=crToCubic(p0,p1,p2,p3);
      curvePath+=` C ${cp1x.toFixed(1)},${cp1y.toFixed(1)} ${cp2x.toFixed(1)},${cp2y.toFixed(1)} ${p2.x.toFixed(1)},${p2.y.toFixed(1)}`;
    }
    const baseline=MT+PH;
    const fillPath=`${curvePath} L ${pts[pts.length-1].x.toFixed(1)},${baseline} L ${pts[0].x.toFixed(1)},${baseline} Z`;
    const gradId=`kc-curve-grad-${Math.random().toString(36).slice(2,8)}`;
    const defs=`<defs><linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="var(--kc-chart-curve-fill)" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="var(--kc-chart-curve-fill)" stop-opacity="0.06"/>
    </linearGradient></defs>`;
    const fillElem=`<path d="${fillPath}" fill="url(#${gradId})"/>`;
    const strokeElem=`<path d="${curvePath}" fill="none" stroke="var(--kc-chart-curve-stroke)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`;
    const hitTargets=distItems.map((b,i)=>{
      const cx=ptX(i),tw=N<2?PW:PW/(N-1),tx=cx-tw/2;
      return `<rect x="${tx.toFixed(1)}" y="${MT}" width="${tw.toFixed(1)}" height="${PH}" fill="transparent" stroke="none"><title>${esc(b.label||'')}: ${b.count||0}</title></rect>`;
    }).join('');
    const baseRule=`<line x1="${ML}" y1="${baseline}" x2="${ML+PW}" y2="${baseline}" stroke="var(--kc-chart-axis-label)" stroke-width="0.6" opacity="0.35"/>`;
    const xAxis=distItems.map((b,i)=>{
      const cx=ptX(i),ty=baseline+4;
      return `<line x1="${cx.toFixed(1)}" y1="${baseline}" x2="${cx.toFixed(1)}" y2="${(baseline+3).toFixed(1)}" stroke="var(--kc-chart-axis-label)" stroke-width="0.7" opacity="0.5"/>
        <text transform="rotate(-40,${cx.toFixed(1)},${ty})" x="${cx.toFixed(1)}" y="${ty}" text-anchor="end" font-size="6" fill="var(--kc-chart-axis-label)" font-family="inherit">${esc(b.label||'')}</text>`;
    }).join('');
    function scoreToX(score){
      const s=parseFloat(score);
      if(isNaN(s)||!distItems.length) return null;
      for(let i=0;i<distItems.length;i++){
        const lo=Number(distItems[i].lo),hi=Number(distItems[i].hi);
        if(s>=lo&&s<=hi){
          if(i===distItems.length-1||hi<=lo) return ptX(i);
          const frac=(s-lo)/(hi-lo);
          return ptX(i)+frac*(ptX(i+1)-ptX(i));
        }
      }
      if(s<Number(distItems[0].lo)) return ptX(0);
      return ptX(distItems.length-1);
    }
    const pillH=11,pillR=3;
    let markers='';
    if(ss){
      let avgX=null,medX=null;
      if(ss.score_avg!=null){
        avgX=scoreToX(ss.score_avg)??(ML+PW/2);
        const label=`avg ${ss.score_avg}`,pw=label.length*4.2+6;
        const px=Math.min(W-pw-2,Math.max(2,avgX-pw/2)),textY=MT-4;
        markers+=`<line x1="${avgX.toFixed(1)}" y1="${MT}" x2="${avgX.toFixed(1)}" y2="${baseline}" stroke="var(--kc-chart-avg-line)" stroke-width="1.2" stroke-dasharray="3,2.5" opacity="0.9"/>
          <rect x="${px.toFixed(1)}" y="${(textY-pillH+2).toFixed(1)}" width="${pw.toFixed(1)}" height="${pillH}" rx="${pillR}" ry="${pillR}" fill="var(--kc-chart-avg-line)" opacity="0.15"/>
          <text x="${avgX.toFixed(1)}" y="${textY.toFixed(1)}" text-anchor="middle" font-size="7" fill="var(--kc-chart-avg-line)" font-family="inherit" font-weight="600">${esc(String(label))}</text>`;
      }
      if(ss.score_median!=null){
        medX=scoreToX(ss.score_median)??(ML+PW/2);
        const label=`med ${ss.score_median}`,pw=label.length*4.2+6;
        const px=Math.min(W-pw-2,Math.max(2,medX-pw/2));
        const textY=(avgX!=null&&Math.abs(avgX-medX)<18)?MT-14:MT-4;
        markers+=`<line x1="${medX.toFixed(1)}" y1="${MT}" x2="${medX.toFixed(1)}" y2="${baseline}" stroke="var(--kc-chart-med-line)" stroke-width="1.2" stroke-dasharray="3,2.5" opacity="0.9"/>
          <rect x="${px.toFixed(1)}" y="${(textY-pillH+2).toFixed(1)}" width="${pw.toFixed(1)}" height="${pillH}" rx="${pillR}" ry="${pillR}" fill="var(--kc-chart-med-line)" opacity="0.15"/>
          <text x="${medX.toFixed(1)}" y="${textY.toFixed(1)}" text-anchor="middle" font-size="7" fill="var(--kc-chart-med-line)" font-family="inherit" font-weight="600">${esc(String(label))}</text>`;
      }
    }
    return statsHtml+`<svg class="kc-score-svg" viewBox="0 0 ${W} ${H}" width="100%" aria-label="Score distribution curve" role="img">${defs}${baseRule}${fillElem}${strokeElem}${hitTargets}${markers}${xAxis}</svg>`;
  }

  function renderHistogram(distItems) {
    if (!distItems || !distItems.length) return '';
    const maxCount = Math.max(1, ...distItems.map(b => b.count || 0));
    return `<div class="kc-histogram">${
      distItems.map(b => {
        const cnt=b.count||0,pct=Math.round((cnt/maxCount)*100),label=b.label||'';
        const isZero=cnt===0,cls='kc-hist-bar'+(isZero?' kc-hist-zero':'');
        const cntCls=isZero?'kc-hist-count kc-muted':'kc-hist-count';
        return `<div class="kc-hist-row"><span class="kc-hist-bucket">${esc(label)}</span><div class="kc-hist-bar-wrap"><div class="${cls}" style="width:${pct}%"></div></div><span class="${cntCls}">${cnt}</span></div>`;
      }).join('')
    }</div>`;
  }

  function sidecarPath(sha) {
    if (!sha || sha.length < 4) return null;
    return `${DROOT}/${sha.slice(0,2)}/${sha.slice(2,4)}/${sha}.json`;
  }

  function fetchCommit(sha12, fullSha) {
    const cached = STORE[fullSha] || STORE[sha12];
    if (cached) return Promise.resolve(cached);
    const path = sidecarPath(fullSha || sha12);
    if (!path) return Promise.resolve(null);
    return fetch(path)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) { STORE[fullSha]=STORE[sha12]=data; } return data; })
      .catch(() => null);
  }

  function fetchFilteredCommit(sha12, fullSha) {
    return Promise.resolve(FSTORE[fullSha] || FSTORE[sha12] || null);
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

  /* ========= Theme ========= */
  const html = document.documentElement;

  function applyTheme(t) {
    html.setAttribute('data-theme', t);
    localStorage.setItem('kc-theme', t);
    const btn=document.getElementById('kc-theme-btn');
    if(btn) btn.title=`Switch to ${t==='dark'?'light':'dark'} mode`;
    const icon=document.getElementById('kc-theme-icon');
    if(icon) icon.textContent=t==='dark'?'\u2600\ufe0f':'\ud83c\udf19';
  }

  const savedTheme=localStorage.getItem('kc-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
  applyTheme(savedTheme);
  document.getElementById('kc-theme-btn')?.addEventListener('click',()=>applyTheme(html.getAttribute('data-theme')==='dark'?'light':'dark'));

  /* ========= Pane collapse / resize ========= */
  function rootFontSizePx(){ return parseFloat(getComputedStyle(document.documentElement).fontSize)||16; }

  function initPane(pane,storageKey,btnId){
    if(!pane) return;
    if(localStorage.getItem(storageKey)==='1') pane.classList.add('kc-collapsed');
    const btn=document.getElementById(btnId);
    if(btn) btn.addEventListener('click',()=>{
      pane.classList.toggle('kc-collapsed');
      localStorage.setItem(storageKey,pane.classList.contains('kc-collapsed')?'1':'0');
      updateCollapseIcons();
    });
  }

  function updateCollapseIcons(){
    const left=document.getElementById('kc-pane-left'),right=document.getElementById('kc-pane-right');
    const lb=document.getElementById('kc-left-toggle'),rb=document.getElementById('kc-right-toggle');
    if(lb) lb.textContent=(left&&left.classList.contains('kc-collapsed'))?'\u203a':'\u2039';
    if(rb) rb.textContent=(right&&right.classList.contains('kc-collapsed'))?'\u2039':'\u203a';
  }

  initPane(document.getElementById('kc-pane-left'),'kc-left-collapsed','kc-left-toggle');
  initPane(document.getElementById('kc-pane-right'),'kc-right-collapsed','kc-right-toggle');
  updateCollapseIcons();

  document.querySelectorAll('.kc-handle').forEach(handle=>{
    if(handle.id==='kc-right-handle') return;
    const target=handle.previousElementSibling;
    if(!target) return;
    let startX,startW;
    handle.addEventListener('mousedown',e=>{ startX=e.clientX; startW=target.getBoundingClientRect().width; handle.classList.add('dragging'); document.body.style.cursor='col-resize'; document.body.style.userSelect='none'; });
    window.addEventListener('mousemove',e=>{ if(!handle.classList.contains('dragging')) return; const rem=rootFontSizePx(),newW=Math.max(180,Math.min(700,startW+e.clientX-startX)); target.style.width=`${(newW/rem).toFixed(3)}rem`; });
    window.addEventListener('mouseup',()=>{ handle.classList.remove('dragging'); document.body.style.cursor=''; document.body.style.userSelect=''; });
  });

  (function(){
    const rHandle=document.getElementById('kc-right-handle'),rPane=document.getElementById('kc-pane-right');
    if(!rHandle||!rPane) return;
    let startX,startW;
    rHandle.addEventListener('mousedown',e=>{ startX=e.clientX; startW=rPane.getBoundingClientRect().width; rHandle.classList.add('dragging'); document.body.style.cursor='col-resize'; document.body.style.userSelect='none'; });
    window.addEventListener('mousemove',e=>{ if(!rHandle.classList.contains('dragging')) return; const rem=rootFontSizePx(),newW=Math.max(220,Math.min(700,startW+startX-e.clientX)); rPane.style.width=`${(newW/rem).toFixed(3)}rem`; });
    window.addEventListener('mouseup',()=>{ rHandle.classList.remove('dragging'); document.body.style.cursor=''; document.body.style.userSelect=''; });
  })();

  /* ========= Topbar meta pills ========= */
  (function(){
    const bar=document.getElementById('kc-topbar-pills');
    if(!bar) return;
    const pills=[];
    function localTzLabel(){ try{ const parts=new Intl.DateTimeFormat(undefined,{hour:'2-digit',minute:'2-digit',timeZoneName:'short'}).formatToParts(new Date()); const tz=parts.find(p=>p.type==='timeZoneName'); return tz?tz.value:''; }catch(_){ return ''; } }
    if(META.version) pills.push(esc(META.version));
    if(META.generated_at){ const ts=String(META.generated_at).slice(0,16),tz=localTzLabel(); pills.push(`Run: ${esc(ts)}${tz?` ${esc(tz)}`:''}`); }
    if(META.git_range){ const parts=String(META.git_range).split('..'); if(parts.length===2) pills.push(`From ${esc(parts[0].trim())} to ${esc(parts[1].trim())}`); else pills.push(`Range: ${esc(META.git_range)}`); }
    if(META.kernel_ver) pills.push(`Kernel: ${esc(META.kernel_ver)}`);
    bar.innerHTML=pills.map(p=>`<span class="kc-meta-pill">${p}</span>`).join('');
  })();

  /* ========= Left sidebar ========= */
  (function(){
    const body=document.getElementById('kc-left-body');
    if(!body) return;
    let html='';
    const TIPS={
      'Collected':'Total commits fetched from git in the configured SHA range.',
      'Prefilter dropped':'Commits removed by stage 04 before scoring (e.g. no Kconfig coverage, path blacklist).',
      'Scored':'Commits that reached the scoring engine (stage 05).',
      'Postfilter dropped':'Scored commits below the minimum score threshold — excluded from the report.',
      'Final report':'Commits that passed all pipeline stages and appear in this report.',
      'Pass rate':'Percentage of collected commits that made it into the final report.',
      'Total scored':'Number of commits processed by the scoring engine in stage 05.',
      'Zero-score':'Commits where every scoring rule evaluated to 0 — no profile matched or all weights were zero.',
      'Multi-profile':'Commits matched by more than one profile simultaneously; their scores are summed.',
      'Threshold':'Minimum score a commit must achieve to be included in the final report (stage 06 postfilter).',
      'Kept':'Commits at or above the threshold — included in the report.',
      'Dropped':'Commits below the threshold — excluded from the report.',
      'Top score':'Highest score seen among all scored commits.',
      'Bottom kept':'Lowest score among commits that passed the postfilter threshold.',
      'is_fix':'Commits whose message contains a Fixes: tag referencing a prior commit.',
      'has_cve':'Commits that mention a CVE identifier in their message body.',
      'has_syzbot':'Commits that reference a syzbot bug report.',
      'stable_cc':'Commits with a Cc: stable@vger.kernel.org line requesting stable backport.',
    };

    /* =========================================================
     * Analysis Context section (v16.9.0)
     * Reads UI.context (CTX) to render the scope block.
     * =========================================================
     */
    (function renderContext(){
      const hasAny=CTX.rev_range||CTX.git_range||CTX.kernel_version||(CTX.profiles&&CTX.profiles.length)||(CTX.artifacts&&Object.keys(CTX.artifacts).length);
      if(!hasAny) return;
      html+=`<div class="kc-section-head">Scope</div>`;
      html+=`<div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\ud83d\udd00</span>Revision range</div><div class="kc-stat-block-body">`;
      const range=CTX.rev_range||CTX.git_range;
      if(range){ const parts=String(range).split('..'); if(parts.length===2){ html+=kv('From',`<code class="kc-mono">${esc(parts[0].trim())}</code>`); html+=kv('To',`<code class="kc-mono">${esc(parts[1].trim())}</code>`); } else html+=kv('Range',`<code class="kc-mono">${esc(range)}</code>`); }
      if(CTX.kernel_version) html+=kv('Kernel',`<code class="kc-mono">${esc(CTX.kernel_version)}</code>`);
      html+=`</div></div>`;
      const artEntries=Object.entries(CTX.artifacts||{});
      if(artEntries.length){
        const ARTIFACT_LABELS={build_dir:'Build dir',kernel_build_log:'Kernel build log',yocto_build_log:'Yocto build log',kernel_config:'Kernel config',dts_roots:'DTS roots'};
        html+=`<div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\ud83e\udde9</span>Build inputs</div><div class="kc-stat-block-body">`;
        artEntries.forEach(([key,val])=>{ const label=ARTIFACT_LABELS[key]||key.replace(/_/g,' '); const badge=val==='yes'?`<span class="kc-badge kc-badge-yes">\u2714\ufe0f yes</span>`:`<span class="kc-badge kc-badge-no">\u2014 no</span>`; html+=kv(label,badge); });
        html+=`</div></div>`;
      }
      if(CTX.profiles&&CTX.profiles.length){
        html+=`<div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\ud83c\udfaf</span>Scoring profiles</div><div class="kc-stat-block-body"><div style="display:flex;flex-wrap:wrap;gap:4px;padding:2px 0">`;
        CTX.profiles.forEach(p=>{ html+=`<span class="kc-chip">${esc(p)}</span>`; });
        html+=`</div></div></div>`;
      }
    })();

    const f=SB.funnel||{};
    if(f.collected!=null){
      const total=f.collected||1;
      function fRow(label,val,cls){ const pct=Math.round((val/total)*100),tip=TIPS[label]||'',tipHtml=tip?`<i class="kc-info-icon" role="button" aria-label="${esc(label)} help" tabindex="0">i<span class="kc-tooltip">${esc(tip)}</span></i>`:''; return `<div class="kc-funnel-row ${cls}"><span class="kc-fn-label"><span class="kc-kv-label-wrap">${esc(label)}${tipHtml}</span></span><div class="kc-fbar"><div class="kc-fbar-fill" style="width:${pct}%"></div></div><span class="kc-fn-val">${val}</span></div>`; }
      html+=`<div class="kc-section-head">Pipeline Funnel</div><div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\ud83d\udd0d</span>Commit flow</div><div class="kc-stat-block-body"><div class="kc-funnel-bar">${fRow('Collected',f.collected||0,'')}${fRow('Prefilter dropped',f.prefilter_dropped||0,'drop')}${fRow('Scored',f.scored||0,'')}${fRow('Postfilter dropped',f.postfilter_dropped||0,'drop')}${fRow('Final report',f.final_report||0,'kept')}</div>${kv('Pass rate',`<strong>${esc(f.pass_rate_pct||0)}%</strong>`,TIPS['Pass rate'])}</div></div>`;
    }

    const st4=SB.stage_04||{};
    if(Object.keys(st4).length){
      html+=`<div class="kc-section-head">Stage 04 \u2014 Prefilter</div><div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\ud83d\udeab</span>Drop reasons</div><div class="kc-stat-block-body">`;
      ((st4.drop_reasons||{}).items||[]).forEach(item=>{ html+=kv(item.reason,`<strong>${item.count}</strong>`); });
      html+=`</div></div>`;
      if((st4.dropped_subsystems||{}).items?.length){
        html+=`<div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\ud83d\udcc2</span>Top dropped subsystems</div><div class="kc-stat-block-body">`;
        (st4.dropped_subsystems.items||[]).slice(0,8).forEach(item=>{ html+=kv(item.subsystem,`<strong>${item.count}</strong>`); });
        html+=`</div></div>`;
      }
    }

    const st5=SB.stage_05||{};
    if(Object.keys(st5).length){
      html+=`<div class="kc-section-head">SCORING</div>`;
      html+=`<div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\u2605</span>Score summary</div><div class="kc-stat-block-body">${kv('Total scored',`<strong>${esc(st5.total_scored||0)}</strong>`,TIPS['Total scored'])}${kv('Zero-score',`<strong>${esc(st5.zero_score_commits||0)}</strong>`,TIPS['Zero-score'])}${kv('Multi-profile',`<strong>${esc(st5.multi_profile_commits||0)}</strong>`,TIPS['Multi-profile'])}</div></div>`;
      const ss=st5.score_stats||{},dist=ss.distribution||[];
      if(dist.length||ss.score_max!=null){
        html+=`<div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\ud83d\udcca</span>Score distribution</div><div class="kc-stat-block-body kc-chart-body">${renderScoreChart(dist,ss)}</div></div>`;
      }
      const profs=st5.profiles||{};
      if(Object.keys(profs).length){
        html+=`<div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\ud83c\udff7\ufe0f</span>Profiles</div><div class="kc-stat-block-body"><ul class="kc-profile-list">`;
        Object.keys(profs).sort().forEach(p=>{
          const d=profs[p],metaParts=[];
          if(d.score_avg!=null) metaParts.push(`<span class="kc-pmeta-item">avg <strong>${d.score_avg}</strong></span>`);
          if(d.score_min!=null&&d.score_min!==d.score_max) metaParts.push(`<span class="kc-pmeta-item">min <strong>${d.score_min}</strong></span>`);
          if(d.score_max!=null) metaParts.push(`<span class="kc-pmeta-item">max <strong>${d.score_max}</strong></span>`);
          const metaRow=metaParts.length?`<div class="kc-profile-meta">${metaParts.join('')}</div>`:'',profHist=(d.score_distribution||[]).length?renderHistogram(d.score_distribution):'';
          html+=`<li style="flex-direction:column;align-items:flex-start;gap:2px;padding:6px 2px"><div style="display:flex;align-items:baseline;gap:6px;width:100%"><span class="kc-pname">${esc(p)}</span><span class="kc-pbadge">${d.commits_scored}</span></div>${metaRow}${profHist}</li>`;
        });
        html+=`</ul></div></div>`;
      }
    }

    const st6=SB.stage_06||{};
    if(Object.keys(st6).length){
      html+=`<div class="kc-section-head">POSTFILTER</div><div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\u2705</span>Threshold filter</div><div class="kc-stat-block-body">${kv('Threshold',`<strong>${esc(st6.threshold??'\u2014')}</strong>`,TIPS['Threshold'])}${kv('Kept',`<strong>${esc(st6.kept||0)}</strong>`,TIPS['Kept'])}${kv('Dropped',`<strong>${esc(st6.dropped||0)}</strong>`,TIPS['Dropped'])}${kv('Top score',`<strong>${esc(st6.top_score||0)}</strong>`,TIPS['Top score'])}${kv('Bottom kept',`<strong>${esc(st6.bottom_kept_score||0)}</strong>`,TIPS['Bottom kept'])}</div></div>`;
    }

    const ann=SB.annotations||{};
    if(ann.total_commits){
      html+=`<div class="kc-section-head">Patch Signals</div><div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\ud83d\udd16</span>Flags (total \u2192 kept)</div><div class="kc-stat-block-body">${kv('is_fix',`${esc(ann.is_fix||0)} \u2192 ${esc(ann.is_fix_and_kept||0)}`,TIPS['is_fix'])}${kv('has_cve',`${esc(ann.has_cve||0)} \u2192 ${esc(ann.has_cve_and_kept||0)}`,TIPS['has_cve'])}${kv('has_syzbot',`${esc(ann.has_syzbot||0)} \u2192 ${esc(ann.has_syzbot_and_kept||0)}`,TIPS['has_syzbot'])}${kv('stable_cc',`${esc(ann.has_stable_cc||0)} \u2192 ${esc(ann.has_stable_cc_and_kept||0)}`,TIPS['stable_cc'])}</div></div>`;
    }

    body.innerHTML=html;
    body.addEventListener('mouseenter',e=>{ const icon=e.target.closest('.kc-info-icon'); if(!icon) return; positionTooltip(icon); },true);
    body.addEventListener('focusin',e=>{ const icon=e.target.closest('.kc-info-icon'); if(!icon) return; positionTooltip(icon); });
    body.addEventListener('click',e=>{ const icon=e.target.closest('.kc-info-icon'); if(!icon){ body.querySelectorAll('.kc-info-icon.kc-tip-open').forEach(el=>el.classList.remove('kc-tip-open')); return; } e.stopPropagation(); const wasOpen=icon.classList.contains('kc-tip-open'); body.querySelectorAll('.kc-info-icon.kc-tip-open').forEach(el=>el.classList.remove('kc-tip-open')); if(!wasOpen){ positionTooltip(icon); icon.classList.add('kc-tip-open'); } });
    body.addEventListener('keydown',e=>{ if(e.key!=='Enter'&&e.key!==' ') return; const icon=e.target.closest('.kc-info-icon'); if(!icon) return; e.preventDefault(); const opening=!icon.classList.contains('kc-tip-open'); if(opening) positionTooltip(icon); icon.classList.toggle('kc-tip-open'); });
  })();

  /* ========= Report-level tab bar (two-tab mode only) ========= */
  (function(){
    if(!TABS_CFG) return;
    const toolbar=document.getElementById('kc-toolbar');
    if(!toolbar) return;
    const bar=document.createElement('div');
    bar.className='kc-report-tab-bar';
    bar.setAttribute('role','tablist');
    bar.setAttribute('aria-label','Report tabs');
    TABS_CFG.forEach(tab=>{
      const btn=document.createElement('button');
      btn.className='kc-report-tab'+(tab.id==='relevant'?' kc-active':'');
      btn.dataset.reportTab=tab.id;
      btn.setAttribute('role','tab');
      btn.setAttribute('aria-selected',tab.id==='relevant'?'true':'false');
      btn.innerHTML=`${esc(tab.label)} <span class="kc-tab-count">${esc(String(tab.count))}</span>`;
      btn.addEventListener('click',()=>switchTab(tab.id));
      bar.appendChild(btn);
    });
    toolbar.insertAdjacentElement('beforebegin',bar);
  })();

  /* =========================================================
   * Table loader overlay — v17.0.0
   * Injected once into #kc-table-wrap at boot.
   * showLoader(n) resets bar to 0% and computes ETA.
   * updateLoaderProgress(done, total) advances bar + label + % badge.
   * hideLoader() flashes bar to 100% then fades overlay out.
   *
   * Layout: spinner  +  centered panel (label row + bar).
   * Bar is fixed 320 px wide (capped to viewport) so it reads as a
   * deliberate progress element rather than a full-width stripe.
   * =========================================================
   */
  const tableWrap=document.getElementById('kc-table-wrap');
  let loaderEl=null, loaderLabelEl=null, loaderBarFillEl=null, loaderPctEl=null;

  (function initLoader(){
    if(!tableWrap) return;
    loaderEl=document.createElement('div');
    loaderEl.className='kc-table-loader';
    loaderEl.innerHTML=
      '<div class="kc-spinner"></div>'+
      '<div class="kc-loader-panel" style="display:flex;flex-direction:column;align-items:center;gap:0;margin-top:10px">'+
        '<div class="kc-loader-label-row" style="display:flex;align-items:baseline;gap:8px;margin-bottom:6px">'+
          '<span class="kc-loader-label" id="kc-loader-label" style="font-size:13px;font-weight:500;letter-spacing:0.01em">Loading\u2026</span>'+
          '<span class="kc-loader-pct" id="kc-loader-pct" style="font-size:11px;font-weight:600;opacity:0;min-width:34px;text-align:right;transition:opacity 0.2s"></span>'+
        '</div>'+
        '<div class="kc-loader-bar" style="width:320px;max-width:min(320px,calc(100vw - 120px));height:8px;background:var(--kc-loader-bar-bg,rgba(128,128,128,0.18));border-radius:999px;overflow:hidden;box-shadow:inset 0 0 0 1px rgba(0,0,0,0.07)">'+
          '<div class="kc-loader-bar-fill" style="height:100%;width:0%;background:var(--kc-loader-bar-fill,var(--accent,#4a9eff));border-radius:999px;transition:width 0.35s ease"></div>'+
        '</div>'+
      '</div>';
    tableWrap.appendChild(loaderEl);
    loaderLabelEl=loaderEl.querySelector('#kc-loader-label');
    loaderBarFillEl=loaderEl.querySelector('.kc-loader-bar-fill');
    loaderPctEl=loaderEl.querySelector('#kc-loader-pct');
  })();

  function showLoader(rowCount){
    if(!loaderEl) return;
    const eta=Math.round(rowCount/1000);
    const etaText=eta<1?'a moment':eta===1?'~1 s':`~${eta} s`;
    if(loaderLabelEl) loaderLabelEl.textContent=`Loading ${rowCount.toLocaleString()} commits\u2026 (${etaText})`;
    if(loaderBarFillEl){ loaderBarFillEl.style.transition='none'; loaderBarFillEl.style.width='0%'; }
    if(loaderPctEl){ loaderPctEl.textContent=''; loaderPctEl.style.opacity='0'; }
    loaderEl.classList.add('kc-loader-active');
  }

  function updateLoaderProgress(done,total){
    if(!loaderBarFillEl||!loaderLabelEl) return;
    const pct=total>0?Math.round((done/total)*100):0;
    loaderBarFillEl.style.transition='width 0.35s ease';
    loaderBarFillEl.style.width=pct+'%';
    loaderLabelEl.textContent=`Loading ${done.toLocaleString()} / ${total.toLocaleString()} commits\u2026`;
    if(loaderPctEl){ loaderPctEl.textContent=pct+'%'; loaderPctEl.style.opacity='1'; }
  }

  function hideLoader(){
    if(!loaderEl) return;
    if(loaderBarFillEl){ loaderBarFillEl.style.transition='width 0.15s ease'; loaderBarFillEl.style.width='100%'; }
    if(loaderPctEl){ loaderPctEl.textContent='100%'; }
    setTimeout(()=>loaderEl.classList.remove('kc-loader-active'),300);
  }

  /* ========= Dataset switcher ========= */
  function switchTab(name){
    if(name===activeTab) return;
    activeTab=name;
    COLS=name==='filtered'?FILT_COLS:REL_COLS;
    ROWS=name==='filtered'?FILT_ROWS:REL_ROWS;
    document.querySelectorAll('.kc-report-tab').forEach(btn=>{
      const active=btn.dataset.reportTab===name;
      btn.classList.toggle('kc-active',active);
      btn.setAttribute('aria-selected',active?'true':'false');
    });
    clearDetailPanel();
    buildHead();
    sortedRows=ROWS.slice(); sortKey=null; sortDir=1;
    COL_DISTINCT=buildDistinct(COLS,ROWS);
    showLoader(ROWS.length);
    renderRowsAsync(
      (done,total)=>updateLoaderProgress(done,total),
      ()=>{ applyFilters(); hideLoader(); }
    );
  }

  /* ========= Table ========= */
  const tbody     =document.getElementById('kc-tbody');
  const thead     =document.getElementById('kc-thead');
  const globalSrch=document.getElementById('kc-global-search');
  const liveCount =document.getElementById('kc-live-count');
  const noMatch   =document.getElementById('kc-no-match');
  const clearBtn  =document.getElementById('kc-clear-filters');
  const exportBtn =document.getElementById('kc-export-csv');

  let sortKey=null,sortDir=1,visibleCount=ROWS.length;
  const colFilters=Object.create(null);
  COLS.forEach(c=>{ colFilters[c.key]=''; });

  function updateFilterOffset(){
    if(!thead||!tableWrap) return;
    const sortRow=thead.querySelector('tr.kc-sort-row');
    if(!sortRow) return;
    tableWrap.style.setProperty('--thead-sort-h',`${sortRow.offsetHeight}px`);
  }

  function buildFilterCtrl(col,fth){
    const distinct=COL_DISTINCT[col.key]||[];
    const useList=(col.type==='select'&&(col.options||[]).length)||(distinct.length>0&&distinct.length<20);
    if(useList){
      const options=col.options?.length?col.options:distinct;
      const sel=document.createElement('select');
      sel.dataset.filterKey=col.key; sel.dataset.filterRole='select';
      sel.innerHTML=`<option value="">All</option>`+options.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');
      sel.addEventListener('change',scheduleFilter);
      fth.appendChild(sel);
      if(col.type==='number'){
        const inp=document.createElement('input');
        inp.type='text'; inp.placeholder='> < ='; inp.style.width='48px'; inp.style.marginTop='2px';
        inp.dataset.filterKey=col.key; inp.dataset.filterRole='text';
        inp.addEventListener('input',scheduleFilter);
        fth.appendChild(inp);
      }
    } else {
      const inp=document.createElement('input');
      inp.type='text'; inp.placeholder='Filter\u2026';
      inp.dataset.filterKey=col.key; inp.dataset.filterRole='text';
      inp.addEventListener('input',scheduleFilter);
      fth.appendChild(inp);
    }
  }

  function buildHead(){
    if(!thead) return;
    const sortRow=document.createElement('tr'); sortRow.className='kc-sort-row';
    const filterRow=document.createElement('tr'); filterRow.className='kc-filter-row';
    COLS.forEach(col=>{
      const th=document.createElement('th');
      th.innerHTML=`${esc(col.label)} <em class="kc-sort-icon" data-key="${esc(col.key)}"></em>`;
      th.addEventListener('click',()=>{ if(sortKey===col.key) sortDir=-sortDir; else{ sortKey=col.key; sortDir=1; } updateSortIcons(); applySort(); renderRows(); applyFilters(); });
      sortRow.appendChild(th);
      const fth=document.createElement('th');
      buildFilterCtrl(col,fth);
      filterRow.appendChild(fth);
    });
    thead.innerHTML=''; thead.appendChild(sortRow); thead.appendChild(filterRow);
    requestAnimationFrame(updateFilterOffset);
  }

  function updateSortIcons(){
    document.querySelectorAll('.kc-sort-icon').forEach(el=>{ el.className='kc-sort-icon'; if(el.dataset.key===sortKey) el.classList.add(sortDir===1?'asc':'desc'); });
  }

  function cellValue(row,key){ const v=row[key]; if(v==null) return ''; if(Array.isArray(v)) return v.join('; '); return String(v); }

  function rowHtml(r){
    if(activeTab==='filtered'){
      const cells=COLS.map(col=>{
        let v=r[col.key]; if(v==null) v='';
        if(col.key==='sha12') return `<td class="kc-td-sha"><a href="#" class="kc-sha-link" data-sha12="${esc(r.sha12)}" data-sha="${esc(r.sha||r.sha12)}">${esc(r.sha12)}</a></td>`;
        if(col.key==='filter_stage') return `<td>${stageBadge(v)}</td>`;
        if(col.key==='date') return `<td class="kc-td-num">${esc(fmtDate(v))}</td>`;
        return `<td>${esc(Array.isArray(v)?v.join('; '):v)}</td>`;
      }).join('');
      return `<tr data-sha12="${esc(r.sha12)}" data-sha="${esc(r.sha||r.sha12)}">${cells}</tr>`;
    }
    const cells=COLS.map(col=>{
      let v=r[col.key]; if(v==null) v='';
      if(col.key==='sha12') return `<td class="kc-td-sha"><a href="#" class="kc-sha-link" data-sha12="${esc(r.sha12)}" data-sha="${esc(r.sha||r.sha12)}">${esc(r.sha12)}</a></td>`;
      if(col.key==='score'||col._profile){ const num=parseFloat(v)||0; return `<td class="kc-td-num">${num>0?scorePill(num):'<span class="kc-muted">\u2014</span>'}</td>`; }
      if(col.key==='profiles') return `<td>${chips(Array.isArray(v)?v:[v])}</td>`;
      if(col.key==='date') return `<td class="kc-td-num">${esc(fmtDate(v))}</td>`;
      return `<td>${esc(Array.isArray(v)?v.join('; '):v)}</td>`;
    }).join('');
    return `<tr data-sha12="${esc(r.sha12)}" data-sha="${esc(r.sha||r.sha12)}">${cells}</tr>`;
  }

  function applySort(){
    if(!sortKey) return;
    sortedRows.sort((a,b)=>{ const av=cellValue(a,sortKey),bv=cellValue(b,sortKey),an=parseFloat(av),bn=parseFloat(bv),cmp=(!isNaN(an)&&!isNaN(bn))?an-bn:av.localeCompare(bv,undefined,{numeric:true}); return cmp*sortDir; });
  }

  function renderRows(){
    if(!tbody) return;
    tbody.innerHTML=sortedRows.map(rowHtml).join('');
  }

  /* renderRowsAsync — chunked DOM build with per-chunk progress callbacks.
   * Processes CHUNK_SIZE rows per setTimeout(0) tick so the browser can
   * repaint the progress bar between chunks. */
  const CHUNK_SIZE=500;
  function renderRowsAsync(onProgress,onDone){
    if(!tbody){ onDone&&onDone(); return; }
    const rows=sortedRows,total=rows.length;
    if(total===0){ tbody.innerHTML=''; onDone&&onDone(); return; }
    tbody.innerHTML='';
    let offset=0;
    function nextChunk(){
      if(offset>=total){ onDone&&onDone(); return; }
      const end=Math.min(offset+CHUNK_SIZE,total),frag=document.createDocumentFragment();
      for(let i=offset;i<end;i++){ const t=document.createElement('template'); t.innerHTML=rowHtml(rows[i]); frag.appendChild(t.content); }
      tbody.appendChild(frag);
      offset=end;
      onProgress&&onProgress(offset,total);
      setTimeout(nextChunk,0);
    }
    setTimeout(nextChunk,0);
  }

  let filterTimer=0;
  function scheduleFilter(){ clearTimeout(filterTimer); filterTimer=setTimeout(applyFilters,60); }

  function matchToken(text,token){
    if(!token) return true;
    const t=token.trim().toLowerCase(),s=text.toLowerCase();
    if(t.startsWith('>'))  { const n=parseFloat(t.slice(1)); return !isNaN(n)&&parseFloat(s)>n; }
    if(t.startsWith('<'))  { const n=parseFloat(t.slice(1)); return !isNaN(n)&&parseFloat(s)<n; }
    if(t.startsWith('=')) return s===t.slice(1);
    const pat=t.replace(/[.+?^${}()|[\]\\]/g,'\\$&').replace(/\*/g,'.*');
    try{ return new RegExp(pat).test(s); } catch{ return s.includes(t); }
  }

  function applyFilters(){
    const selectVals=Object.create(null),textVals=Object.create(null);
    document.querySelectorAll('[data-filter-key]').forEach(el=>{ const key=el.dataset.filterKey,role=el.dataset.filterRole||'text'; if(role==='select') selectVals[key]=el.value||''; else textVals[key]=el.value||''; colFilters[key]=el.value||''; });
    const global=(globalSrch?.value||'').trim().toLowerCase(),gTokens=global?global.split(/\s+/).filter(Boolean):[];
    let shown=0;
    sortedRows.forEach(r=>{
      const tr=tbody?.querySelector(`tr[data-sha12="${CSS.escape(r.sha12)}"]`);
      if(!tr) return;
      let ok=COLS.every(col=>{ const sv=(selectVals[col.key]||'').trim(),tv=(textVals[col.key]||'').trim(),cv=cellValue(r,col.key); if(sv&&!matchToken(cv,sv)) return false; if(tv&&!matchToken(cv,tv)) return false; return true; });
      if(ok&&gTokens.length){ const hay=Object.values(r).map(v=>Array.isArray(v)?v.join(' '):String(v??'')).join(' ').toLowerCase(); ok=gTokens.every(t=>hay.includes(t)); }
      tr.classList.toggle('kc-hidden',!ok);
      if(ok) shown++;
    });
    visibleCount=shown;
    if(liveCount) liveCount.textContent=`Showing ${shown} of ${ROWS.length} commits`;
    if(noMatch) noMatch.classList.toggle('kc-visible',shown===0);
  }

  clearBtn?.addEventListener('click',()=>{ document.querySelectorAll('[data-filter-key]').forEach(el=>{ el.value=''; }); if(globalSrch) globalSrch.value=''; applyFilters(); });
  globalSrch?.addEventListener('input',scheduleFilter);

  exportBtn?.addEventListener('click',()=>{
    const header=COLS.map(c=>`"${c.label.replace(/"/g,'""')}"`).join(','),lines=[header];
    (tbody?.querySelectorAll('tr:not(.kc-hidden)')||[]).forEach(tr=>{ lines.push(Array.from(tr.querySelectorAll('td')).map(td=>`"${td.textContent.trim().replace(/"/g,'""')}"`).join(',')); });
    const blob=new Blob([lines.join('\r\n')],{type:'text/csv;charset=utf-8'}),a=document.createElement('a');
    a.href=URL.createObjectURL(blob);
    a.download=activeTab==='filtered'?'kcommit-filtered.csv':'kcommit-report.csv';
    a.click(); setTimeout(()=>URL.revokeObjectURL(a.href),2000);
  });

  /* ========= Detail panel ========= */
  const rightPane=document.getElementById('kc-pane-right');

  function clearDetailPanel(){
    tbody?.querySelectorAll('tr').forEach(tr=>tr.classList.remove('kc-row-active'));
    document.querySelectorAll('.kc-tab-panel').forEach(p=>{ p.innerHTML=''; p.classList.remove('kc-active'); });
  }

  function activateTab(name){
    document.querySelectorAll('.kc-tab').forEach(t=>{ const active=t.dataset.tab===name; t.classList.toggle('kc-active',active); t.setAttribute('aria-selected',active?'true':'false'); });
    document.querySelectorAll('.kc-tab-panel').forEach(p=>p.classList.toggle('kc-active',p.id===`kc-tab-${name}`));
  }

  document.querySelectorAll('.kc-tab').forEach(t=>t.addEventListener('click',()=>activateTab(t.dataset.tab)));

  function renderDecision(row,commit){
    const score=parseFloat(row.score)||0,dropped=!!(row.reason)&&score===0,reason=row.reason||'';
    const KEEP_MAP={commit_whitelist:'SHA is explicitly whitelisted in config.',build_artifact:'Touched files include kernel build artifacts for this product.',default:'Passed all prefilter checks and scored above threshold.',no_files_layer:'Zero-file commit kept as a structural commit.',filter_disabled:'Prefilter is disabled in config; all commits pass.'};
    const DROP_MAP={commit_blacklist:'SHA is explicitly blacklisted in config.',path_blacklist_all:'Every touched file matched the path blacklist.',no_kconfig_coverage:'No Kconfig build evidence for any touched file.',score_below_threshold:`Score ${score} is below the minimum threshold (${SB.stage_06?.threshold??'?'}).`,no_files_layer:'Zero-file structural commit \u2014 included without scoring.'};
    const cls=dropped?'kc-decision-dropped':'kc-decision-kept',label=dropped?'\u2718 Dropped':'\u2714 Kept';
    let items=[];
    if(reason&&!dropped) items.push(KEEP_MAP[reason]||`Keep reason: ${reason}`);
    else if(reason&&dropped) items.push(DROP_MAP[reason]||`Drop reason: ${reason}`);
    else items.push(score>0?'Passed pipeline and scored above threshold.':'No explicit reason recorded.');
    if(!dropped&&score>0) items.push(`Final score: ${score}`);
    if(!dropped&&(row.profiles||[]).length) items.push(`Matched profiles: ${(row.profiles||[]).join(', ')}`);
    return `<div class="${cls}"><div class="kc-decision-title">${label}</div><ul class="kc-decision-items">${items.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`;
  }

  function matchExcerpt(value,start,end,ctx){
    ctx=(ctx==null)?60:ctx;
    if(start==null||end==null||start<0) return '';
    const str=String(value||''),lo=Math.max(0,start-ctx),hi=Math.min(str.length,end+ctx);
    const pre=str.slice(lo,start).replace(/[\r\n]/g,'\u21b5'),mid=str.slice(start,end).replace(/[\r\n]/g,'\u21b5'),post=str.slice(end,hi).replace(/[\r\n]/g,'\u21b5');
    const ld=lo>0?'\u2026':'',rd=hi<str.length?'\u2026':'';
    return `<span class="kc-match-excerpt">${esc(ld)}${esc(pre)}<mark class="kc-match-hl">${esc(mid)}</mark>${esc(post)}${esc(rd)}</span>`;
  }

  function pathStem(p){ const base=String(p||'').replace(/\\/g,'/').split('/').pop(),dot=base.lastIndexOf('.'); return dot>0?base.slice(0,dot):base; }
  function ruleNameFromPath(p){ const parts=String(p||'').replace(/\\/g,'/').split('/'); return parts.length>=2?parts[parts.length-2]:''; }

  function renderProfileTrace(pname,pt){
    const score=pt.final_score||0,mult=pt.multiplier!=null?pt.multiplier:1,blocked=pt.blocked,rules=pt.rules||{},cls=scoreClass(score);
    let html=`<div class="kc-detail-card"><div class="kc-detail-card-head"><span class="kc-chip">${esc(pname)}</span><span class="kc-score-pill ${cls}">${esc(score)}</span>${blocked?`<span style="color:var(--danger);font-weight:700">\u26d4 BLOCKED${pt.block_reason?` \u2014 ${esc(pt.block_reason)}`:''}</span>`:`<span class="kc-muted" style="font-size:11px">\u00d7${mult}</span>`}</div><div class="kc-detail-card-body">`;
    if(Object.keys(rules).length){
      html+=`<table class="kc-trace-table"><thead><tr><th>Rule</th><th>Wt</th><th>Match</th><th>Score</th><th>Patterns matched</th></tr></thead><tbody>`;
      Object.keys(rules).sort().forEach(rname=>{
        const rd=rules[rname]||{},matched=rd.matched,allHits=Object.values(rd.matches||{}).flat();
        const rowCls=blocked?'kc-rule-blocked':(matched?'kc-rule-matched':''),icon=blocked?'\u25a0':(matched?'\u2714':'\u2715'),iconCol=blocked?'var(--muted)':(matched?'var(--success)':'var(--muted)');
        let badgesHtml='<span class="kc-muted">\u2014</span>';
        if(allHits.length){ badgesHtml=allHits.map(m=>{ const pat=m.pattern||'',srcFile=m.source_file||null,srcLine=m.source_line||null,start=m.match_start,end=m.match_end,value=m.value||''; let srcBadge=''; if(srcFile){ const label=`${ruleNameFromPath(srcFile)||rname}:${pathStem(srcFile)}:${srcLine}`; srcBadge=`<span class="kc-src-badge" title="${esc(srcFile)}">${esc(label)}</span>`; } const excerpt=(start!=null&&end!=null)?matchExcerpt(value,start,end,60):`<span class="kc-match-excerpt kc-muted">${esc(value.slice(0,120))}${value.length>120?'\u2026':''}</span>`; return `<span class="kc-match-hit"><span class="kc-match-badge" title="${esc(pat)}">${esc(pat)}</span>${srcBadge}<span class="kc-match-excerpt-wrap">${excerpt}</span></span>`; }).join(''); }
        html+=`<tr class="${rowCls}"><td class="kc-mono">${esc(rname)}</td><td>${esc(rd.weight||0)}</td><td style="color:${iconCol};font-weight:700;text-align:center">${icon}</td><td class="kc-td-num">${matched?esc(rd.score||0):'\u2014'}</td><td>${badgesHtml}</td></tr>`;
      });
      html+=`</tbody></table>`;
    } else { html+=`<span class="kc-muted">No rule detail available.</span>`; }
    html+=`</div></div>`;
    return html;
  }

  function renderFiles(commit){
    const files=(commit||{}).files||[],covSet=new Set((commit||{}).coverage||[]);
    if(!files.length) return `<p class="kc-muted">No files recorded for this commit.</p>`;
    return `<table class="kc-files-table"><thead><tr><th>File</th><th>Build coverage</th></tr></thead><tbody>${files.map(f=>`<tr><td>${esc(f)}</td><td class="${covSet.has(f)?'kc-coverage-y':'kc-coverage-n'}">${covSet.has(f)?'\u2714 covered':'\u2014'}</td></tr>`).join('')}</tbody></table>`;
  }

  function populateDetail(row,commit){
    const c=commit||{},sc=c.scoring||{},profiles=sc.profiles||{};
    let overview='';
    overview+=detailCard('Commit',[kv('SHA',`<code class="kc-mono">${esc(c.commit||row.sha||row.sha12)}</code>`),kv('Subject',esc(c.subject||row.subject||'')),kv('Author',esc((c.author_name||row.author||'')+(c.author_email?` <${c.author_email}>`:''))) ,kv('Date',esc(fmtDate(c.author_time||row.date))),kv('Score',scorePill(c.score??row.score)),kv('Profiles',chips(c.matched_profiles||row.profiles||[]))].join(''),'\ud83d\udcc4');
    overview+=detailCard('Decision',renderDecision(row,c),'\u2696\ufe0f');
    if((c.product_evidence||[]).length){ overview+=detailCard('Product Evidence',`<ul style="padding-left:1.2rem;margin:0">${(c.product_evidence||[]).map(e=>`<li><code class="kc-mono">${esc(e)}</code></li>`).join('')}</ul>`,'\ud83d\udce6'); }
    if(c.body){ const bodyPreview=c.body.length>4000?c.body.slice(0,4000)+'\n\u2026':c.body; overview+=detailCard('Full Commit Message',`<div class="kc-commit-body">${escNl(bodyPreview)}</div>`,'\ud83d\udcdd'); }
    document.getElementById('kc-tab-overview').innerHTML=overview;
    const traceProfiles=((sc.trace||{}).profiles)||{};
    let scoring='';
    if(Object.keys(traceProfiles).length){ scoring+=`<p class="kc-muted" style="font-size:11.5px;margin:0 0 8px">Formula per profile: <code>raw_rule_total &times; profile_weight/100</code>. Combined score = &sum; of all profile final scores. Pattern badges show the <strong>matched pattern</strong>, source <em>rule:file:line</em>, and a highlighted excerpt.</p>`; Object.keys(traceProfiles).sort().forEach(p=>scoring+=renderProfileTrace(p,traceProfiles[p]||{})); }
    else if(Object.keys(profiles).length){ scoring+=detailCard('Profile Scores',Object.keys(profiles).sort().map(p=>kv(p,scorePill(profiles[p]))).join(''),'\u2605'); }
    else{ scoring=`<p class="kc-muted">No scoring data available for this commit.</p>`; }
    document.getElementById('kc-tab-scoring').innerHTML=scoring;
    document.getElementById('kc-tab-files').innerHTML=renderFiles(c);
    document.getElementById('kc-tab-raw').innerHTML=`<pre class="kc-raw-pre">${esc(JSON.stringify(c,null,2))}</pre>`;
    activateTab('overview');
  }

  function populateFilteredDetail(row,commit){
    const c=commit||{},dbg=c.prefilter_debug||{};
    let overview='';
    overview+=detailCard('Commit',[kv('SHA',`<code class="kc-mono">${esc(c.commit||row.sha||row.sha12)}</code>`),kv('Subject',esc(c.subject||row.subject||'')),kv('Author',esc((c.author_name||row.author||'')+(c.author_email?` <${c.author_email}>`:''))) ,kv('Date',esc(fmtDate(c.author_time||row.date))),kv('Filter stage',stageBadge(row.filter_stage||'')),kv('Drop reason',esc(row.reason||dbg.drop_reason||'\u2014'))].join(''),'\ud83d\udcc4');
    const decItems=[];
    if(dbg.drop_reason) decItems.push(kv('Reason code',esc(dbg.drop_reason)));
    if(dbg.matched_subsystems?.length) decItems.push(kv('Matched subsystems',esc(dbg.matched_subsystems.join(', '))));
    if(dbg.unmatched_paths?.length) decItems.push(kv('Unmatched paths',esc(dbg.unmatched_paths.join(', '))));
    if(dbg.all_files_blacklisted!=null) decItems.push(kv('All files blacklisted',esc(String(dbg.all_files_blacklisted))));
    if(decItems.length){ overview+=detailCard('Drop Decision',decItems.join(''),'\u2696\ufe0f'); }
    if(c.body){ const bodyPreview=c.body.length>4000?c.body.slice(0,4000)+'\n\u2026':c.body; overview+=detailCard('Full Commit Message',`<div class="kc-commit-body">${escNl(bodyPreview)}</div>`,'\ud83d\udcdd'); }
    document.getElementById('kc-tab-overview').innerHTML=overview;
    document.getElementById('kc-tab-scoring').innerHTML=`<p class="kc-muted" style="padding:var(--space-4)">Not applicable \u2014 this commit was dropped before or after scoring and is not in the final report.</p>`;
    document.getElementById('kc-tab-files').innerHTML=`<p class="kc-muted" style="padding:var(--space-4)">Not applicable \u2014 file coverage data is only available for relevant commits.</p>`;
    document.getElementById('kc-tab-raw').innerHTML=`<pre class="kc-raw-pre">${esc(JSON.stringify(c,null,2))}</pre>`;
    activateTab('overview');
  }

  function openDetail(sha12,fullSha){
    const lookup=activeTab==='filtered'?filtRowBySha:rowBySha;
    const row=lookup[sha12]||lookup[fullSha]||{};
    tbody?.querySelectorAll('tr').forEach(tr=>tr.classList.toggle('kc-row-active',tr.dataset.sha12===sha12));
    document.querySelectorAll('.kc-tab-panel').forEach(p=>{ p.innerHTML=''; p.classList.remove('kc-active'); });
    const ov=document.getElementById('kc-tab-overview');
    if(ov){ ov.innerHTML=`<p class="kc-muted">Loading\u2026</p>`; ov.classList.add('kc-active'); }
    if(rightPane?.classList.contains('kc-collapsed')){ rightPane.classList.remove('kc-collapsed'); localStorage.setItem('kc-right-collapsed','0'); updateCollapseIcons(); }
    if(activeTab==='filtered'){ fetchFilteredCommit(sha12,fullSha||sha12).then(commit=>populateFilteredDetail(row,commit)); }
    else { fetchCommit(sha12,fullSha||sha12).then(commit=>populateDetail(row,commit)); }
  }

  document.addEventListener('click',e=>{ const a=e.target.closest('.kc-sha-link'); if(!a) return; e.preventDefault(); e.stopImmediatePropagation(); openDetail(a.dataset.sha12||a.dataset.sha,a.dataset.sha||a.dataset.sha12); },true);

  document.addEventListener('keydown',e=>{
    if(e.key==='Escape') tbody?.querySelectorAll('tr').forEach(tr=>tr.classList.remove('kc-row-active'));
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){
      const visible=Array.from(tbody?.querySelectorAll('tr:not(.kc-hidden)')||[]);
      if(!visible.length) return;
      const active=tbody?.querySelector('tr.kc-row-active'),idx=visible.indexOf(active);
      const next=e.key==='ArrowDown'?visible[idx+1]||visible[0]:visible[idx-1]||visible[visible.length-1];
      if(next){ openDetail(next.dataset.sha12,next.dataset.sha); next.scrollIntoView({block:'nearest'}); }
    }
  });

  window.addEventListener('resize',updateFilterOffset);

  /* ========= Bootstrap ========= */
  buildHead();
  showLoader(ROWS.length);
  renderRowsAsync(
    (done,total)=>updateLoaderProgress(done,total),
    ()=>{ applyFilters(); hideLoader(); }
  );

})();
