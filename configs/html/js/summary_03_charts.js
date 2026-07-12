/* summary_03_charts.js — kcommit-analysis-pipeline
 *
 * Score distribution chart (SVG/KDE curve), histogram renderer,
 * and commit data fetch helpers (embedded store + sidecar).
 */

/* =========================================================
 * renderScoreChart(distItems, ss)
 * KDE-smoothed SVG curve over score distribution buckets.
 * ss = score_stats object with score_avg / score_median.
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

/* ---- Commit data fetchers ------------------------------------------ */
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
