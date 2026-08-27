/* summary_07_sidebar.js — kcommit-analysis-pipeline
 *
 * Left pane renderer: Analysis Context, Pipeline Funnel, Stage 04/05/06,
 * Patch Signals annotations, tooltip event wiring.
 */

(function () {
  const body = document.getElementById('kc-left-body');
  if (!body) return;
  let html = '';

  const TIPS = {
    'Collected':           'Total commits fetched from git in the configured SHA range.',
    'Prefilter dropped':   'Commits removed by stage 04 before scoring (e.g. no Kconfig coverage, path blacklist).',
    'Scored':              'Commits that reached the scoring engine (stage 05).',
    'Postfilter dropped':  'Scored commits below the minimum score threshold \u2014 excluded from the report.',
    'Final report':        'Commits that passed all pipeline stages and appear in this report.',
    'Pass rate':           'Percentage of collected commits that made it into the final report.',
    'Total scored':        'Number of commits processed by the scoring engine in stage 05.',
    'Zero-score':          'Commits where every scoring rule evaluated to 0 \u2014 no profile matched or all weights were zero.',
    'Multi-profile':       'Commits matched by more than one profile simultaneously; their scores are summed.',
    'Threshold':           'Minimum score a commit must achieve to be included in the final report (stage 06 postfilter).',
    'Kept':                'Commits at or above the threshold \u2014 included in the report.',
    'Dropped':             'Commits below the threshold \u2014 excluded from the report.',
    'Top score':           'Highest score seen among all scored commits.',
    'Bottom kept':         'Lowest score among commits that passed the postfilter threshold.',
    'is_fix':              'Commits whose message contains a Fixes: tag referencing a prior commit.',
    'has_cve':             'Commits that mention a CVE identifier in their message body.',
    'has_syzbot':          'Commits that reference a syzbot bug report.',
    'stable_cc':           'Commits with a Cc: stable@vger.kernel.org line requesting stable backport.',
  };

  /* ---- Analysis Context (v16.9.0) ------------------------------------ */
  (function renderContext() {
    const hasAny = CTX.rev_range || CTX.git_range || CTX.kernel_version
      || (CTX.profiles && CTX.profiles.length)
      || (CTX.artifacts && Object.keys(CTX.artifacts).length);
    if (!hasAny) return;

    html += `<div class="kc-section-head">Scope</div>`;
    html += `<div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\ud83d\udd00</span>Revision range</div><div class="kc-stat-block-body">`;
    const range = CTX.rev_range || CTX.git_range;
    if (range) {
      const parts = String(range).split('..');
      if (parts.length === 2) {
        html += kv('From', `<code class="kc-mono">${esc(parts[0].trim())}</code>`);
        html += kv('To',   `<code class="kc-mono">${esc(parts[1].trim())}</code>`);
      } else {
        html += kv('Range', `<code class="kc-mono">${esc(range)}</code>`);
      }
    }
    if (CTX.kernel_version) html += kv('Kernel', `<code class="kc-mono">${esc(CTX.kernel_version)}</code>`);
    html += `</div></div>`;

    const artEntries = Object.entries(CTX.artifacts || {});
    if (artEntries.length) {
      const ARTIFACT_LABELS = {
        build_dir:         'Build dir',
        kernel_build_log:  'Kernel build log',
        yocto_build_log:   'Yocto build log',
        kernel_config:     'Kernel config',
        dts_roots:         'DTS roots',
      };
      html += `<div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\ud83e\udde9</span>Build inputs</div><div class="kc-stat-block-body">`;
      artEntries.forEach(([key, val]) => {
        const label = ARTIFACT_LABELS[key] || key.replace(/_/g, ' ');
        const badge = val === 'yes'
          ? `<span class="kc-badge kc-badge-yes">\u2714\ufe0f yes</span>`
          : `<span class="kc-badge kc-badge-no">\u2014 no</span>`;
        html += kv(label, badge);
      });
      html += `</div></div>`;
    }

    if (CTX.profiles && CTX.profiles.length) {
      /* Colour legend: each profile gets a deterministic coloured bullet
       * (profileColor()) reused by the table "Profiles" column, so a reader
       * can map a row's bullets back to profile names here. */
      html += `<div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\ud83c\udfaf</span>Scoring profiles</div><div class="kc-stat-block-body"><div class="kc-prof-legend">`;
      CTX.profiles.forEach(p => { html += profileBullet(p, true); });
      html += `</div></div></div>`;
    }
  })();

  /* ---- Pipeline Funnel ----------------------------------------------- */
  const f = SB.funnel || {};
  if (f.collected != null) {
    const total = f.collected || 1;
    function fRow(label, val, cls) {
      const pct = Math.round((val / total) * 100);
      const tip = TIPS[label] || '';
      const tipHtml = tip
        ? `<i class="kc-info-icon" role="button" aria-label="${esc(label)} help" tabindex="0">i<span class="kc-tooltip">${esc(tip)}</span></i>`
        : '';
      return `<div class="kc-funnel-row ${cls}"><span class="kc-fn-label"><span class="kc-kv-label-wrap">${esc(label)}${tipHtml}</span></span><div class="kc-fbar"><div class="kc-fbar-fill" style="width:${pct}%"></div></div><span class="kc-fn-val">${val}</span></div>`;
    }
    html += `<div class="kc-section-head">Pipeline Funnel</div>`
          + `<div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\ud83d\udd0d</span>Commit flow</div><div class="kc-stat-block-body">`
          + `<div class="kc-funnel-bar">`
          + fRow('Collected',         f.collected        || 0, '')
          + fRow('Prefilter dropped',  f.prefilter_dropped || 0, 'drop')
          + fRow('Scored',             f.scored            || 0, '')
          + fRow('Postfilter dropped', f.postfilter_dropped|| 0, 'drop')
          + fRow('Final report',       f.final_report      || 0, 'kept')
          + `</div>`
          + kv('Pass rate', `<strong>${esc(f.pass_rate_pct || 0)}%</strong>`, TIPS['Pass rate'])
          + `</div></div>`;
  }

  /* ---- Stage 04 — Prefilter ----------------------------------------- */
  const st4 = SB.stage_04 || {};
  if (Object.keys(st4).length) {
    html += `<div class="kc-section-head">Stage 04 \u2014 Prefilter</div>`
          + `<div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\ud83d\udeab</span>Drop reasons</div><div class="kc-stat-block-body">`;
    ((st4.drop_reasons || {}).items || []).forEach(item => {
      html += kv(item.reason, `<strong>${item.count}</strong>`);
    });
    html += `</div></div>`;
    if ((st4.dropped_subsystems || {}).items?.length) {
      html += `<div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\ud83d\udcc2</span>Top dropped subsystems</div><div class="kc-stat-block-body">`;
      (st4.dropped_subsystems.items || []).slice(0, 8).forEach(item => {
        html += kv(item.subsystem, `<strong>${item.count}</strong>`);
      });
      html += `</div></div>`;
    }
  }

  /* ---- Stage 05 — Scoring ------------------------------------------- */
  const st5 = SB.stage_05 || {};
  if (Object.keys(st5).length) {
    html += `<div class="kc-section-head">SCORING</div>`;
    html += `<div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\u2605</span>Score summary</div><div class="kc-stat-block-body">`
          + kv('Total scored',  `<strong>${esc(st5.total_scored  || 0)}</strong>`, TIPS['Total scored'])
          + kv('Zero-score',    `<strong>${esc(st5.zero_score_commits  || 0)}</strong>`, TIPS['Zero-score'])
          + kv('Multi-profile', `<strong>${esc(st5.multi_profile_commits || 0)}</strong>`, TIPS['Multi-profile'])
          + `</div></div>`;

    const ss = st5.score_stats || {}, dist = ss.distribution || [];
    if (dist.length || ss.score_max != null) {
      html += `<div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\ud83d\udcca</span>Score % distribution</div><div class="kc-stat-block-body kc-chart-body">${renderScoreChart(dist, ss)}</div></div>`;
    }

    const profs = st5.profiles || {};
    if (Object.keys(profs).length) {
      html += `<div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\ud83c\udff7\ufe0f</span>Profiles</div><div class="kc-stat-block-body"><ul class="kc-profile-list">`;
      Object.keys(profs).sort().forEach(p => {
        const d = profs[p], metaParts = [];
        if (d.score_avg != null) metaParts.push(`<span class="kc-pmeta-item">avg <strong>${d.score_avg}</strong></span>`);
        if (d.score_min != null && d.score_min !== d.score_max) metaParts.push(`<span class="kc-pmeta-item">min <strong>${d.score_min}</strong></span>`);
        if (d.score_max != null) metaParts.push(`<span class="kc-pmeta-item">max <strong>${d.score_max}</strong></span>`);
        const metaRow  = metaParts.length ? `<div class="kc-profile-meta">${metaParts.join('')}</div>` : '';
        const profHist = (d.score_distribution || []).length ? renderHistogram(d.score_distribution) : '';
        html += `<li style="flex-direction:column;align-items:flex-start;gap:2px;padding:6px 2px">`
              + `<div style="display:flex;align-items:baseline;gap:6px;width:100%"><span class="kc-pname">${esc(p)}</span><span class="kc-pbadge">${d.commits_scored}</span></div>`
              + metaRow + profHist
              + `</li>`;
      });
      html += `</ul></div></div>`;
    }
  }

  /* ---- Stage 06 — Postfilter ---------------------------------------- */
  const st6 = SB.stage_06 || {};
  if (Object.keys(st6).length) {
    html += `<div class="kc-section-head">POSTFILTER</div>`
          + `<div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\u2705</span>Threshold filter</div><div class="kc-stat-block-body">`
          + kv('Threshold',   `<strong>${esc(st6.threshold ?? '\u2014')}</strong>`, TIPS['Threshold'])
          + kv('Kept',        `<strong>${esc(st6.kept    || 0)}</strong>`, TIPS['Kept'])
          + kv('Dropped',     `<strong>${esc(st6.dropped || 0)}</strong>`, TIPS['Dropped'])
          + kv('Top score',   `<strong>${esc(st6.top_score           || 0)}</strong>`, TIPS['Top score'])
          + kv('Bottom kept', `<strong>${esc(st6.bottom_kept_score   || 0)}</strong>`, TIPS['Bottom kept'])
          + `</div></div>`;
  }

  /* ---- Patch Signals / Annotations ----------------------------------- */
  const ann = SB.annotations || {};
  if (ann.total_commits) {
    html += `<div class="kc-section-head">Patch Signals</div>`
          + `<div class="kc-stat-block"><div class="kc-stat-block-head"><span class="kc-icon">\ud83d\udd16</span>Flags (total \u2192 kept)</div><div class="kc-stat-block-body">`
          + kv('is_fix',    `${esc(ann.is_fix    || 0)} \u2192 ${esc(ann.is_fix_and_kept    || 0)}`, TIPS['is_fix'])
          + kv('has_cve',   `${esc(ann.has_cve   || 0)} \u2192 ${esc(ann.has_cve_and_kept   || 0)}`, TIPS['has_cve'])
          + kv('has_syzbot',`${esc(ann.has_syzbot|| 0)} \u2192 ${esc(ann.has_syzbot_and_kept|| 0)}`, TIPS['has_syzbot'])
          + kv('stable_cc', `${esc(ann.has_stable_cc|| 0)} \u2192 ${esc(ann.has_stable_cc_and_kept|| 0)}`, TIPS['stable_cc'])
          + `</div></div>`;
  }

  body.innerHTML = html;

  /* ---- Tooltip event wiring ----------------------------------------- */
  body.addEventListener('mouseenter', e => {
    const icon = e.target.closest('.kc-info-icon'); if (!icon) return; positionTooltip(icon);
  }, true);
  body.addEventListener('focusin', e => {
    const icon = e.target.closest('.kc-info-icon'); if (!icon) return; positionTooltip(icon);
  });
  body.addEventListener('click', e => {
    const icon = e.target.closest('.kc-info-icon');
    if (!icon) {
      body.querySelectorAll('.kc-info-icon.kc-tip-open').forEach(el => el.classList.remove('kc-tip-open'));
      return;
    }
    e.stopPropagation();
    const wasOpen = icon.classList.contains('kc-tip-open');
    body.querySelectorAll('.kc-info-icon.kc-tip-open').forEach(el => el.classList.remove('kc-tip-open'));
    if (!wasOpen) { positionTooltip(icon); icon.classList.add('kc-tip-open'); }
  });
  body.addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const icon = e.target.closest('.kc-info-icon'); if (!icon) return;
    e.preventDefault();
    const opening = !icon.classList.contains('kc-tip-open');
    if (opening) positionTooltip(icon);
    icon.classList.toggle('kc-tip-open');
  });
})();
