/* summary_13_detail.js — kcommit-analysis-pipeline
 *
 * Right-pane commit detail panel.
 *
 * Public API (called from other modules):
 *   openDetail(sha12, sha)    — highlight row, fetch & render detail
 *   clearDetailPanel()        — reset right pane to placeholder
 *
 * Internals:
 *   fetchCommit(sha)          — resolve commit object from STORE / sidecar URL
 *   populateDetail(commit)    — fill all four tab panels
 *   renderProfileTrace(trace) — build the kc-trace-table scoring breakdown
 *
 * Keyboard navigation:
 *   ArrowDown / ArrowUp       — move to next/previous row in filteredRows
 *   Escape                    — close detail panel
 */

/* ── DOM refs ─────────────────────────────────────────────────────────── */
const detailBody     = document.getElementById('kc-detail-body');
const tabOverview    = document.getElementById('kc-tab-overview');
const tabScoring     = document.getElementById('kc-tab-scoring');
const tabFiles       = document.getElementById('kc-tab-files');
const tabRaw         = document.getElementById('kc-tab-raw');
const detailTabBtns  = document.querySelectorAll('.kc-detail-tabs .kc-tab');

/* ── Active detail state ─────────────────────────────────────────────── */
let activeSha12 = null;
let activeDetailTab = 'overview';

/* ── Tab switching ───────────────────────────────────────────────────── */
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

/* ── clearDetailPanel ────────────────────────────────────────────────── */
function clearDetailPanel() {
  activeSha12 = null;
  if (tabOverview) tabOverview.innerHTML =
    '<p class="kc-detail-placeholder">Click a commit SHA in the table to inspect it.</p>';
  if (tabScoring) tabScoring.innerHTML = '';
  if (tabFiles)   tabFiles.innerHTML   = '';
  if (tabRaw)     tabRaw.innerHTML     = '';
  /* Deactivate any highlighted row */
  document.querySelectorAll('tr.kc-row-active').forEach(r => r.classList.remove('kc-row-active'));
}

/* ── fetchCommit ─────────────────────────────────────────────────────── */
function fetchCommit(sha) {
  /* 1. Inline embedded store (embedded or sidecar-index mode) */
  if (STORE && STORE[sha]) return Promise.resolve(STORE[sha]);

  /* 2. Bucket shard layout: commits/<sha[0]>/<sha[1:3]>.json
   *    Each shard is a {fullSha: commitData} dict (G.4, v18.1.0).
   *    sha is expected to be the full 40-char SHA; sha12 fallback
   *    is attempted when the full-SHA key is absent. */
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

/* ── renderProfileTrace ──────────────────────────────────────────────── */
function renderProfileTrace(profileName, traceData) {
  if (!traceData || !traceData.rules) return '<p class="kc-muted">No trace data.</p>';

  const rows = Object.entries(traceData.rules).map(([rName, rData]) => {
    const matched = rData.matched ? '✓' : '–';
    const score   = rData.matched ? esc(String(rData.score || 0)) : '<span class="kc-muted">—</span>';
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
      <td>${esc(rName)}</td>
      <td class="kc-td-num">${matched}</td>
      <td class="kc-td-num">${score}</td>
      <td>${matchDetail}</td>
    </tr>`;
  }).join('');

  const blocked = traceData.blocked
    ? `<div class="kc-trace-blocked">⛔ Blocked: ${esc(traceData.block_reason || '')}</div>` : '';

  return `${blocked}
  <table class="kc-trace-table">
    <thead><tr><th>Rule</th><th>Hit</th><th>Score</th><th>Matches</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>
  <div class="kc-trace-summary">
    Raw total: <b>${esc(String(traceData.raw_rule_total || 0))}</b>
    → capped: <b>${esc(String(traceData.raw_rule_total_capped || 0))}</b>
    → final: <b>${scorePill(traceData.final_score || 0)}</b>
  </div>`;
}

/* ── populateDetail ──────────────────────────────────────────────────── */
function populateDetail(commit) {
  if (!commit) {
    clearDetailPanel();
    return;
  }

  /* ---- Overview tab ---- */
  const sha      = commit.commit || commit.sha || '';
  const subject  = commit.subject || '';
  const body     = commit.body || '';
  const author   = commit.author_name || '';
  const date     = fmtDate(commit.author_time);
  const score    = commit.score != null ? commit.score : '—';
  const profiles = (commit.matched_profiles || []);
  const evidence = (commit.product_evidence || []);

  const overviewHtml = detailCard('Commit', `
    <div class="kc-kv-grid">
      ${kv('SHA',     `<code>${esc(sha)}</code>`)}
      ${kv('Author',  esc(author))}
      ${kv('Date',    esc(date))}
      ${kv('Score',   scorePill(score))}
      ${profiles.length ? kv('Profiles', chips(profiles)) : ''}
    </div>
    <div class="kc-commit-subject">${esc(subject)}</div>
    ${body ? `<pre class="kc-commit-body">${esc(body)}</pre>` : ''}
  `) + (evidence.length ? detailCard('Product evidence',
    `<ul class="kc-evidence-list">${evidence.map(e => `<li>${esc(e)}</li>`).join('')}</ul>`
  ) : '');

  if (tabOverview) tabOverview.innerHTML = overviewHtml;

  /* ---- Scoring tab ---- */
  const scoring    = commit.scoring   || {};
  const traceData  = (scoring.trace && scoring.trace.profiles) || {};
  const profScores = scoring.profiles || {};

  if (tabScoring) {
    if (Object.keys(traceData).length) {
      tabScoring.innerHTML = Object.entries(traceData).map(([pName, tData]) =>
        detailCard(
          `Profile: ${pName}`,
          renderProfileTrace(pName, tData)
        )
      ).join('');
    } else if (Object.keys(profScores).length) {
      tabScoring.innerHTML = detailCard('Scores',
        `<div class="kc-kv-grid">${
          Object.entries(profScores).map(([p, s]) => kv(p, scorePill(s))).join('')
        }</div>`);
    } else {
      tabScoring.innerHTML = '<p class="kc-muted kc-detail-placeholder">No scoring data.</p>';
    }
  }

  /* ---- Files tab ---- */
  const files = commit.files || [];
  if (tabFiles) {
    tabFiles.innerHTML = files.length
      ? detailCard('Changed files',
          `<ul class="kc-file-list">${files.map(f =>
            `<li><code>${esc(f)}</code></li>`).join('')}</ul>`)
      : '<p class="kc-muted kc-detail-placeholder">No file list available.</p>';
  }

  /* ---- Raw JSON tab ---- */
  if (tabRaw) {
    tabRaw.innerHTML = detailCard('Raw JSON',
      `<pre class="kc-raw-json">${esc(JSON.stringify(commit, null, 2))}</pre>`);
  }
}

/* ── openDetail ──────────────────────────────────────────────────────── */
function openDetail(sha12, sha, tabName) {
  /* Mark active row */
  document.querySelectorAll('tr.kc-row-active').forEach(r => r.classList.remove('kc-row-active'));
  const rows = document.querySelectorAll(`tr[data-sha12="${CSS.escape(sha12)}"]`);
  rows.forEach(r => r.classList.add('kc-row-active'));

  activeSha12 = sha12;
  const fullSha = sha || sha12;

  /* Show loading state immediately */
  if (tabOverview) tabOverview.innerHTML =
    '<p class="kc-detail-placeholder kc-loading">Loading\u2026</p>';

  fetchCommit(fullSha)
    .then(commit => populateDetail(commit))
    .catch(err => {
      if (tabOverview) tabOverview.innerHTML =
        `<p class="kc-detail-placeholder kc-error">Failed to load commit: ${esc(String(err))}</p>`;
    });

  switchDetailTab(tabName || activeDetailTab);

  /* Ensure right pane is visible */
  const rPane = document.getElementById('kc-pane-right');
  if (rPane && rPane.classList.contains('kc-collapsed')) {
    rPane.classList.remove('kc-collapsed');
    const rb = document.getElementById('kc-right-toggle');
    if (rb) rb.textContent = '\u203a';
  }
}

/* ── Row click delegation ────────────────────────────────────────────── */
document.addEventListener('click', e => {
  /* Score cell → detail + scoring tab */
  const scoreTd = e.target.closest('.kc-td-score');
  if (scoreTd) {
    const row = scoreTd.closest('tr[data-sha12]');
    if (row) {
      e.preventDefault();
      openDetail(row.dataset.sha12, row.dataset.sha || row.dataset.sha12, 'scoring');
      return;
    }
  }

  /* SHA link → detail + overview */
  const link = e.target.closest('.kc-sha-link');
  if (link) {
    e.preventDefault();
    openDetail(link.dataset.sha12, link.dataset.sha);
    return;
  }

  /* Any other click on a data row → detail + overview */
  const row = e.target.closest('tr[data-sha12]');
  if (row) {
    openDetail(row.dataset.sha12, row.dataset.sha || row.dataset.sha12);
  }
});

/* ── Keyboard navigation ─────────────────────────────────────────────── */
document.addEventListener('keydown', e => {
  /* Only handle when no input/textarea is focused */
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;

  if (e.key === 'Escape') {
    clearDetailPanel();
    return;
  }

  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
  e.preventDefault();

  /* filteredRows is owned by summary_10_table.js */
  if (!filteredRows || filteredRows.length === 0) return;

  let idx = activeSha12
    ? filteredRows.findIndex(r => r.sha12 === activeSha12)
    : -1;

  if (e.key === 'ArrowDown') idx = Math.min(filteredRows.length - 1, idx + 1);
  else                        idx = Math.max(0, idx - 1);

  const next = filteredRows[idx];
  if (!next) return;

  openDetail(next.sha12, next.sha || next.sha12);

  /* Scroll the active row into view */
  const activeRow = document.querySelector(`tr[data-sha12="${CSS.escape(next.sha12)}"]`);
  activeRow?.scrollIntoView({ block: 'nearest' });
});
