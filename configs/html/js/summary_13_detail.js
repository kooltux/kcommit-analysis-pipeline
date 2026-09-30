/* Commit detail panel: imported AI assessments remain advisory. */
const detailBody = document.getElementById('kc-detail-body');
const tabOverview = document.getElementById('kc-tab-overview');
const tabScoring = document.getElementById('kc-tab-scoring');
const tabFiles = document.getElementById('kc-tab-files');
const tabRaw = document.getElementById('kc-tab-raw');
const detailTabBtns = document.querySelectorAll('.kc-detail-tabs .kc-tab');

let activeSha12 = null;
let activeDetailTab = 'overview';

function switchDetailTab(name) {
  activeDetailTab = name;
  detailTabBtns.forEach(btn => {
    const active = btn.dataset.tab === name;
    btn.classList.toggle('kc-active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.querySelectorAll('.kc-tab-panel').forEach(p => {
    p.classList.toggle('kc-active', p.id === `kc-tab-${name}`);
  });
}

detailTabBtns.forEach(btn => {
  btn.addEventListener('click', () => switchDetailTab(btn.dataset.tab));
});

function clearDetailPanel() {
  activeSha12 = null;
  if (tabOverview) tabOverview.innerHTML =
    '<p class="kc-detail-placeholder">Click a commit SHA in the table to inspect it.</p>';
  if (tabScoring) tabScoring.innerHTML = '';
  if (tabFiles) tabFiles.innerHTML = '';
  if (tabRaw) tabRaw.innerHTML = '';
  document.querySelectorAll('tr.kc-row-active').forEach(r => r.classList.remove('kc-row-active'));
}

function fetchCommit(sha) {
  if (STORE) {
    const entry = STORE[sha] || STORE[sha.slice(0, 12)];
    if (entry) return Promise.resolve(entry);
  }
  const url = `${DROOT}/${sha[0]}/${sha.slice(1, 3)}.json`;
  return fetch(url).then(r => {
    if (!r.ok) throw new Error(`HTTP ${r.status} fetching ${url}`);
    return r.json();
  }).then(shard => {
    const entry = shard[sha] || shard[sha.slice(0, 12)];
    if (!entry) throw new Error(`Commit ${sha.slice(0, 12)} not found in shard ${url}`);
    return entry;
  });
}

function renderProfileTrace(profileName, traceData) {
  if (!traceData || !traceData.rules) return '<p class="kc-muted">No trace data.</p>';
  const rows = Object.entries(traceData.rules).map(([rName, rData]) => {
    const matched = rData.matched ? '✓' : '–';
    const score = rData.matched ? esc(String(rData.score || 0)) : '<span class="kc-muted">—</span>';
    let matchDetail = '';
    if (rData.matches) {
      const parts = [];
      for (const [mtype, items] of Object.entries(rData.matches)) {
        if (Array.isArray(items) && items.length) {
          parts.push(items.map(m =>
            `<code>${esc(m.pattern || m.value || JSON.stringify(m))}</code>`).join(' '));
        }
      }
      if (parts.length) matchDetail = `<div class="kc-trace-matches">${parts.join(' ')}</div>`;
    }
    return `<tr class="${rData.matched ? 'kc-trace-hit' : 'kc-trace-miss'}">
      <td>${esc(rName)}</td><td class="kc-td-num">${matched}</td>
      <td class="kc-td-num">${score}</td><td>${matchDetail}</td></tr>`;
  }).join('');
  const blocked = traceData.blocked
    ? `<div class="kc-trace-blocked">⛔ Blocked: ${esc(traceData.block_reason || '')}</div>` : '';
  return `${blocked}<table class="kc-trace-table">
    <thead><tr><th>Rule</th><th>Hit</th><th>Score</th><th>Matches</th></tr></thead>
    <tbody>${rows}</tbody></table><div class="kc-trace-summary">
    Raw total: <b>${esc(String(traceData.raw_rule_total || 0))}</b>
    → final: <b>${scorePill(traceData.final_score || 0)}</b></div>`;
}

function renderAiAssessment(ai) {
  if (!ai || typeof ai !== 'object') return '';
  const list = key => Array.isArray(ai[key]) ? ai[key].join(', ') : '';
  const fields = [
    ['Recommendation', ai.ai_backport_recommendation],
    ['Summary', ai.ai_summary],
    ['Impact', ai.ai_impact_on_product],
    ['Impact rationale', ai.ai_impact_description],
    ['Classification rationale', ai.ai_categorisation_rationale],
    ['Backport effort', ai.ai_backport_effort],
    ['Effort rationale', ai.ai_backport_effort_reason],
    ['Risks if not backported', list('ai_risks_if_not_backported')],
    ['CVE IDs', list('ai_cve_ids')],
    ['CVE relevance (%)', list('ai_cve_probabilities')],
  ];
  const flags = [
    ['Security fix', ai.ai_is_security_fix],
    ['Bug fix', ai.ai_is_bug_fix],
    ['Performance enhancement', ai.ai_is_performance_enhancement],
    ['New feature', ai.ai_is_new_feature],
    ['New security feature', ai.ai_is_new_security_feature],
  ];
  const rows = fields.filter(([, value]) => value !== undefined && value !== '')
    .map(([label, value]) => kv(label, esc(value))).join('');
  const flagRows = flags.filter(([, value]) => typeof value === 'boolean')
    .map(([label, value]) => kv(label, value ? 'Yes' : 'No')).join('');
  return detailCard('AI analysis (advisory)',
    '<p class="kc-muted">Independent assessment; human review required. ' +
    'Does not change pipeline score, rank or cherry-pick result.</p>' +
    `<div class="kc-kv-grid">${rows}${flagRows}</div>`);
}

function populateDetail(commit) {
  if (!commit) { clearDetailPanel(); return; }
  const sha = commit.commit || commit.sha || '';
  const subject = commit.subject || '';
  const body = commit.body || '';
  const authorName = commit.author_name || '';
  const authorEmail = commit.author_email || '';
  const authorOrg = commit.author_org || '';
  const date = fmtDate(commit.author_time);
  const score = commit.score != null ? commit.score : '—';
  const profiles = commit.matched_profiles || [];
  const evidence = commit.product_evidence || [];
  const ovStats = commit.stats || {};
  const ovFiles = ovStats.files_changed;
  const ovLines = ovStats.lines_changed;
  const ovHunks = ovStats.hunks;
  const ovCx = commit.backport_complexity;
  const ovScoreN = commit.score_norm;
  const ovPriority = commit.pick_priority;
  const cherryOk = commit.cherry_pickable;
  const cherryPill = cherryOk != null
    ? heatPill(cherryOk ? 100 : 0, {scale: 100, polarity: 'higher-better'},
               cherryOk ? '✔️ Yes' : '✖️ No') : '';
  const indicatorRows = [
    ovPriority != null ? kv('Pick Priority', heatPill(ovPriority, {scale: 100, polarity: 'higher-better'})) : '',
    ovScoreN != null ? kv('Score', heatPill(ovScoreN, {scale: 100, polarity: 'higher-better'})) : '',
    ovCx != null ? kv('Complexity', heatPill(ovCx, {scale: 100, polarity: 'higher-worse'})) : '',
    cherryPill ? kv('Cherry-pick', cherryPill) : '',
    kv('Files changed', ovFiles != null ? esc(ovFiles) : '<span class="kc-muted">0</span>'),
    kv('Lines changed', ovLines != null ? esc(ovLines) : '<span class="kc-muted">0</span>'),
    kv('Hunks', ovHunks != null ? esc(ovHunks) : '<span class="kc-muted">0</span>'),
  ].join('');
  const overviewHtml = detailCard('Commit', `
    <div class="kc-kv-grid">
      ${kv('SHA', `<code>${esc(sha)}</code>`)}
      ${kv('Author', esc(authorName))}
      ${kv('Author Email', esc(authorEmail))}
      ${kv('Organization', esc(authorOrg))}
      ${kv('Date', esc(date))}
      ${kv('Score', esc(score))}
      ${indicatorRows}
      ${profiles.length ? kv('Profiles', profileBullets(profiles) + ' ' + chips(profiles)) : ''}
    </div>
    <div class="kc-commit-subject">${esc(subject)}</div>
    ${body ? `<pre class="kc-commit-body">${esc(body)}</pre>` : ''}
  `) + (evidence.length ? detailCard('Product evidence',
    `<ul class="kc-evidence-list">${evidence.map(e => `<li>${esc(e)}</li>`).join('')}</ul>`) : '')
    + renderAiAssessment(commit.ai_analysis);
  if (tabOverview) tabOverview.innerHTML = overviewHtml;
  const scoring = commit.scoring || {};
  const traceData = (scoring.trace && scoring.trace.profiles) || {};
  const profScores = scoring.profiles || {};
  if (tabScoring) {
    if (Object.keys(traceData).length) {
      tabScoring.innerHTML = Object.entries(traceData).map(([pName, tData]) =>
        detailCard(`Profile: ${pName}`, renderProfileTrace(pName, tData))).join('');
    } else if (Object.keys(profScores).length) {
      tabScoring.innerHTML = detailCard('Scores',
        `<div class="kc-kv-grid">${Object.entries(profScores).map(([p, s]) => kv(p, scorePill(s))).join('')}</div>`);
    } else {
      tabScoring.innerHTML = '<p class="kc-muted kc-detail-placeholder">No scoring data.</p>';
    }
  }
  const files = commit.files || [];
  if (tabFiles) {
    tabFiles.innerHTML = files.length
      ? detailCard('Changed files',
          `<ul class="kc-file-list">${files.map(f => `<li><code>${esc(f)}</code></li>`).join('')}</ul>`)
      : '<p class="kc-muted kc-detail-placeholder">No file list available.</p>';
  }
  if (tabRaw) {
    tabRaw.innerHTML = detailCard('Raw JSON',
      `<pre class="kc-raw-json">${esc(JSON.stringify(commit, null, 2))}</pre>`);
  }
}

function openDetail(sha12, sha, tabName) {
  document.querySelectorAll('tr.kc-row-active').forEach(r => r.classList.remove('kc-row-active'));
  const rows = document.querySelectorAll(`tr[data-sha12="${CSS.escape(sha12)}"]`);
  rows.forEach(r => r.classList.add('kc-row-active'));
  activeSha12 = sha12;
  const fullSha = sha || sha12;
  if (tabOverview) tabOverview.innerHTML =
    '<p class="kc-detail-placeholder kc-loading">Loading…</p>';
  fetchCommit(fullSha).then(commit => populateDetail(commit)).catch(err => {
    if (tabOverview) tabOverview.innerHTML =
      `<p class="kc-detail-placeholder kc-error">Failed to load commit: ${esc(String(err))}</p>`;
  });
  switchDetailTab(tabName || activeDetailTab);
  const rPane = document.getElementById('kc-pane-right');
  if (rPane && rPane.classList.contains('kc-collapsed')) {
    rPane.classList.remove('kc-collapsed');
    const rb = document.getElementById('kc-right-toggle');
    if (rb) rb.textContent = '›';
  }
}

document.addEventListener('click', e => {
  const scoreTd = e.target.closest('.kc-td-score');
  if (scoreTd) {
    const row = scoreTd.closest('tr[data-sha12]');
    if (row) {
      e.preventDefault();
      openDetail(row.dataset.sha12, row.dataset.sha || row.dataset.sha12, 'scoring');
      return;
    }
  }
  const link = e.target.closest('.kc-sha-link');
  if (link) {
    e.preventDefault();
    openDetail(link.dataset.sha12, link.dataset.sha);
    return;
  }
  const row = e.target.closest('tr[data-sha12]');
  if (row) openDetail(row.dataset.sha12, row.dataset.sha || row.dataset.sha12);
});

document.addEventListener('keydown', e => {
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;
  if (e.key === 'Escape') { clearDetailPanel(); return; }
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
  e.preventDefault();
  if (!filteredRows || filteredRows.length === 0) return;
  let idx = activeSha12 ? filteredRows.findIndex(r => r.sha12 === activeSha12) : -1;
  if (e.key === 'ArrowDown') idx = Math.min(filteredRows.length - 1, idx + 1);
  else idx = Math.max(0, idx - 1);
  const next = filteredRows[idx];
  if (!next) return;
  openDetail(next.sha12, next.sha || next.sha12);
  const activeRow = document.querySelector(`tr[data-sha12="${CSS.escape(next.sha12)}"]`);
  activeRow?.scrollIntoView({ block: 'nearest' });
});
