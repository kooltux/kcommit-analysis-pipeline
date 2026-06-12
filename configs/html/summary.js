/* kcommit-analysis-pipeline — v15.0.0 UI
 *
 * Reads everything from window.__KC_UI__ (serialised by html_report.py at
 * generation time from config + JSON outputs — zero hardcoding).
 *
 * Structure of __KC_UI__:
 *   meta          – tool version, run date, git range, title, subtitle
 *   columns       – [{key, label, type, options?}] for table columns
 *   rows          – flat commit rows for the table
 *   sidebar       – {funnel, stages, profiles, evaluation, annotations}
 *   detail_root   – path prefix for per-commit sidecar JSON (e.g. './commits')
 *   is_filtered   – bool: this is the filtered-commits view
 */
(function () {
  'use strict';

  /* ========= Globals ========= */
  const UI    = window.__KC_UI__      || {};
  const STORE = window.__KC_COMMITS__ || {};
  const META  = UI.meta    || {};
  const SB    = UI.sidebar || {};
  const DROOT = (UI.detail_root || './commits').replace(/\/+$/, '');

  /* ---- Build effective column list -----------------------------------
   * The generator emits a base set of columns.  We expand it here by
   * injecting one numeric column per profile  (key = "score_<profile>")
   * immediately after the combined "score" column.  This is done on the
   * client so the generator does not need to enumerate profiles twice.
   * -------------------------------------------------------------------*/
  const BASE_COLS   = UI.columns || [];
  const PROFILE_NAMES = (() => {
    const names = new Set();
    (UI.rows || []).forEach(r => (r.profiles || []).forEach(p => names.add(p)));
    return [...names].sort();
  })();

  // Insert per-profile score columns after the "score" column
  const COLS = (() => {
    const out = [];
    for (const col of BASE_COLS) {
      out.push(col);
      if (col.key === 'score' && PROFILE_NAMES.length) {
        for (const p of PROFILE_NAMES) {
          out.push({ key: `score_${p}`, label: p, type: 'number', _profile: p });
        }
      }
    }
    // Remove the old combined profile_scores column (replaced by per-profile)
    return out.filter(c => c.key !== 'profile_scores');
  })();

  // Enrich rows with per-profile score keys
  const ROWS = (UI.rows || []).map(r => {
    const scoring = (r._scoring_profiles) || {};
    // Per-profile scores are stored by html_report.py on each row as
    // score_<profile>.  Fall back to 0 if absent.
    const out = Object.assign({}, r);
    for (const p of PROFILE_NAMES) {
      const k = `score_${p}`;
      if (out[k] == null) out[k] = 0;
    }
    return out;
  });

  /* Row lookup by sha12 or full sha */
  const rowBySha = Object.create(null);
  ROWS.forEach(r => { rowBySha[r.sha12] = r; if (r.sha) rowBySha[r.sha] = r; });

  /* ---- Distinct-value index for autofilter selects ------------------*/
  const COL_DISTINCT = Object.create(null);
  COLS.forEach(col => {
    const vals = new Set();
    ROWS.forEach(r => {
      const v = r[col.key];
      if (Array.isArray(v)) v.forEach(x => vals.add(String(x)));
      else if (v != null && v !== '') vals.add(String(v));
    });
    COL_DISTINCT[col.key] = [...vals].sort((a, b) => {
      const na = parseFloat(a), nb = parseFloat(b);
      return (!isNaN(na) && !isNaN(nb)) ? na - nb : a.localeCompare(b);
    });
  });

  /* ========= Helpers ========= */

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/[&<>"']/g, m => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[m]));
  }

  function escNl(s) {
    return esc(s)
      .replace(/\\n/g, '<br>')
      .replace(/\n/g,  '<br>');
  }

  function fmtDate(ts) {
    if (!ts) return '';
    const n = Number(ts);
    if (!Number.isNaN(n) && n > 1e8) {
      const d = new Date(n * 1000);
      const p = x => String(x).padStart(2, '0');
      return `${d.getUTCFullYear()}-${p(d.getUTCMonth()+1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
    }
    // Already a string — ensure HH:MM is preserved (up to 16 chars = "YYYY-MM-DD HH:MM")
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

  function kv(label, val) {
    return `<div class="kc-kv"><span class="kc-kv-label">${esc(label)}</span><span class="kc-kv-value">${val}</span></div>`;
  }

  function detailCard(title, bodyHtml, icon) {
    const ico = icon ? `<span>${icon}</span>` : '';
    return `<div class="kc-detail-card">
      <div class="kc-detail-card-head">${ico}${esc(title)}</div>
      <div class="kc-detail-card-body">${bodyHtml}</div>
    </div>`;
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
      .then(data => {
        if (data) { STORE[fullSha] = STORE[sha12] = data; }
        return data;
      })
      .catch(() => null);
  }

  /* ========= Theme ========= */
  const html = document.documentElement;

  function applyTheme(t) {
    html.setAttribute('data-theme', t);
    localStorage.setItem('kc-theme', t);
    const btn = document.getElementById('kc-theme-btn');
    if (btn) btn.title = `Switch to ${t === 'dark' ? 'light' : 'dark'} mode`;
    const icon = document.getElementById('kc-theme-icon');
    if (icon) icon.textContent = t === 'dark' ? '\u2600\ufe0f' : '\ud83c\udf19';
  }

  const savedTheme = localStorage.getItem('kc-theme') ||
    (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  applyTheme(savedTheme);

  document.getElementById('kc-theme-btn')
    ?.addEventListener('click', () =>
      applyTheme(html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark'));

  /* ========= Pane collapse / resize ========= */
  function initPane(pane, storageKey, btnId) {
    if (!pane) return;
    const stored = localStorage.getItem(storageKey);
    if (stored === '1') pane.classList.add('kc-collapsed');
    const btn = document.getElementById(btnId);
    if (btn) {
      btn.addEventListener('click', () => {
        pane.classList.toggle('kc-collapsed');
        localStorage.setItem(storageKey, pane.classList.contains('kc-collapsed') ? '1' : '0');
        updateCollapseIcons();
      });
    }
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

  document.querySelectorAll('.kc-handle').forEach(handle => {
    if (handle.id === 'kc-right-handle') return;
    const target = handle.previousElementSibling;
    if (!target) return;
    let startX, startW;
    handle.addEventListener('mousedown', e => {
      startX = e.clientX; startW = target.getBoundingClientRect().width;
      handle.classList.add('dragging');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    });
    window.addEventListener('mousemove', e => {
      if (!handle.classList.contains('dragging')) return;
      target.style.width = Math.max(180, Math.min(700, startW + e.clientX - startX)) + 'px';
    });
    window.addEventListener('mouseup', () => {
      handle.classList.remove('dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    });
  });

  (function () {
    const rHandle = document.getElementById('kc-right-handle');
    const rPane   = document.getElementById('kc-pane-right');
    if (!rHandle || !rPane) return;
    let startX, startW;
    rHandle.addEventListener('mousedown', e => {
      startX = e.clientX; startW = rPane.getBoundingClientRect().width;
      rHandle.classList.add('dragging');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    });
    window.addEventListener('mousemove', e => {
      if (!rHandle.classList.contains('dragging')) return;
      rPane.style.width = Math.max(220, Math.min(700, startW + startX - e.clientX)) + 'px';
    });
    window.addEventListener('mouseup', () => {
      rHandle.classList.remove('dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    });
  })();

  /* ========= Topbar meta pills ========= */
  (function () {
    const bar = document.getElementById('kc-topbar-pills');
    if (!bar) return;
    const pills = [];

    /* FIX 1: VERSION already includes the leading 'v' — do not add another */
    if (META.version) pills.push(esc(META.version));

    /* FIX 2: Show full datetime HH:MM, not just the date */
    if (META.generated_at) pills.push(`Run: ${esc(String(META.generated_at).slice(0, 16))}`);

    /* FIX 3: Git range as "from <sha> to <sha>" */
    if (META.git_range) {
      const parts = String(META.git_range).split('..');
      if (parts.length === 2) {
        pills.push(`From ${esc(parts[0].trim())} to ${esc(parts[1].trim())}`);
      } else {
        pills.push(`Range: ${esc(META.git_range)}`);
      }
    }

    if (META.kernel_ver) pills.push(`Kernel: ${esc(META.kernel_ver)}`);
    bar.innerHTML = pills.map(p => `<span class="kc-meta-pill">${p}</span>`).join('');
  })();

  /* ========= Left sidebar ========= */
  (function () {
    const body = document.getElementById('kc-left-body');
    if (!body) return;

    let html = '';

    /* — Funnel — */
    const f = SB.funnel || {};
    if (f.collected != null) {
      const total = f.collected || 1;

      /* FIX 4: simplified funnel — drop "kept" rows, keep logical flow */
      function fRow(label, val, cls) {
        const pct = Math.round((val / total) * 100);
        return `<div class="kc-funnel-row ${cls}">
          <span class="kc-fn-label">${esc(label)}</span>
          <div class="kc-fbar"><div class="kc-fbar-fill" style="width:${pct}%"></div></div>
          <span class="kc-fn-val">${val}</span>
        </div>`;
      }

      html += `<div class="kc-section-head">Pipeline Funnel</div>`;
      html += `<div class="kc-stat-block">
        <div class="kc-stat-block-head"><span class="kc-icon">\ud83d\udd0d</span>Commit flow</div>
        <div class="kc-stat-block-body">
          <div class="kc-funnel-bar">
            ${fRow('Collected',          f.collected          || 0, '')}
            ${fRow('Prefilter dropped',  f.prefilter_dropped  || 0, 'drop')}
            ${fRow('Scored',             f.scored             || 0, '')}
            ${fRow('Postfilter dropped', f.postfilter_dropped || 0, 'drop')}
            ${fRow('Final report',       f.final_report       || 0, 'kept')}
          </div>
          ${kv('Pass rate', `<strong>${esc(f.pass_rate_pct || 0)}%</strong>`)}
        </div>
      </div>`;
    }

    /* — Stage 04 prefilter — */
    const st4 = SB.stage_04 || {};
    if (Object.keys(st4).length) {
      html += `<div class="kc-section-head">Stage 04 — Prefilter</div>
        <div class="kc-stat-block">
          <div class="kc-stat-block-head"><span class="kc-icon">\ud83d\udeab</span>Drop reasons</div>
          <div class="kc-stat-block-body">`;
      ((st4.drop_reasons || {}).items || []).forEach(item => {
        html += kv(item.reason, `<strong>${item.count}</strong>`);
      });
      html += `</div></div>`;

      if ((st4.dropped_subsystems || {}).items?.length) {
        html += `<div class="kc-stat-block">
          <div class="kc-stat-block-head"><span class="kc-icon">\ud83d\udcc2</span>Top dropped subsystems</div>
          <div class="kc-stat-block-body">`;
        (st4.dropped_subsystems.items || []).slice(0, 8).forEach(item => {
          html += kv(item.subsystem, `<strong>${item.count}</strong>`);
        });
        html += `</div></div>`;
      }
    }

    /* — Stage 05 scoring — */
    const st5 = SB.stage_05 || {};
    if (Object.keys(st5).length) {
      html += `<div class="kc-section-head">Stage 05 — Scoring</div>
        <div class="kc-stat-block">
          <div class="kc-stat-block-head"><span class="kc-icon">\u2605</span>Score summary</div>
          <div class="kc-stat-block-body">
            ${kv('Total scored',  `<strong>${esc(st5.total_scored || 0)}</strong>`)}
            ${kv('Zero-score',    `<strong>${esc(st5.zero_score_commits || 0)}</strong>`)}
            ${kv('Multi-profile',`<strong>${esc(st5.multi_profile_commits || 0)}</strong>`)}
          </div>
        </div>`;

      const profs = st5.profiles || {};
      if (Object.keys(profs).length) {
        html += `<div class="kc-stat-block">
          <div class="kc-stat-block-head"><span class="kc-icon">\ud83c\udff7\ufe0f</span>Profiles</div>
          <div class="kc-stat-block-body"><ul class="kc-profile-list">`;
        Object.keys(profs).sort().forEach(p => {
          const d = profs[p];
          html += `<li>
            <span class="kc-pname">${esc(p)}</span>
            <span class="kc-pbadge">${d.commits_scored}</span>
            <span class="kc-muted" style="font-size:11px">ø${d.score_avg}</span>
          </li>`;
        });
        html += `</ul></div></div>`;
      }
    }

    /* — Stage 06 postfilter — */
    const st6 = SB.stage_06 || {};
    if (Object.keys(st6).length) {
      html += `<div class="kc-section-head">Stage 06 — Postfilter</div>
        <div class="kc-stat-block">
          <div class="kc-stat-block-head"><span class="kc-icon">\u2705</span>Threshold filter</div>
          <div class="kc-stat-block-body">
            ${kv('Threshold',      `<strong>${esc(st6.threshold ?? '\u2014')}</strong>`)}
            ${kv('Kept',           `<strong>${esc(st6.kept      || 0)}</strong>`)}
            ${kv('Dropped',        `<strong>${esc(st6.dropped   || 0)}</strong>`)}
            ${kv('Top score',      `<strong>${esc(st6.top_score || 0)}</strong>`)}
            ${kv('Bottom kept',    `<strong>${esc(st6.bottom_kept_score || 0)}</strong>`)}
          </div>
        </div>`;
    }

    /* — Kernel annotations — */
    const ann = SB.annotations || {};
    if (ann.total_commits) {
      html += `<div class="kc-section-head">Kernel Annotations</div>
        <div class="kc-stat-block">
          <div class="kc-stat-block-head"><span class="kc-icon">\ud83d\udd16</span>Flags (total → kept)</div>
          <div class="kc-stat-block-body">
            ${kv('is_fix',     `${esc(ann.is_fix||0)} \u2192 ${esc(ann.is_fix_and_kept||0)}`)}
            ${kv('has_cve',    `${esc(ann.has_cve||0)} \u2192 ${esc(ann.has_cve_and_kept||0)}`)}
            ${kv('has_syzbot', `${esc(ann.has_syzbot||0)} \u2192 ${esc(ann.has_syzbot_and_kept||0)}`)}
            ${kv('stable_cc',  `${esc(ann.has_stable_cc||0)} \u2192 ${esc(ann.has_stable_cc_and_kept||0)}`)}
          </div>
        </div>`;
    }

    /* — Evaluation config — */
    const ev = SB.evaluation || {};
    if (Object.keys(ev).length) {
      html += `<div class="kc-section-head">Evaluation Config</div>
        <div class="kc-stat-block">
          <div class="kc-stat-block-head"><span class="kc-icon">\u2699\ufe0f</span>Parameters</div>
          <div class="kc-stat-block-body">`;
      Object.entries(ev).forEach(([k, v]) => {
        if (v != null && v !== '') html += kv(k.replace(/_/g, ' '), esc(String(v)));
      });
      html += `</div></div>`;
    }

    body.innerHTML = html;
  })();

  /* ========= Table ========= */
  const tbody     = document.getElementById('kc-tbody');
  const thead     = document.getElementById('kc-thead');
  const globalSrch= document.getElementById('kc-global-search');
  const liveCount = document.getElementById('kc-live-count');
  const noMatch   = document.getElementById('kc-no-match');
  const clearBtn  = document.getElementById('kc-clear-filters');
  const exportBtn = document.getElementById('kc-export-csv');

  let sortKey = null, sortDir = 1;
  let visibleCount = ROWS.length;
  const colFilters = Object.create(null);
  COLS.forEach(c => { colFilters[c.key] = ''; });

  /* FIX 5: autofilter — render a <select> + text <input> combo when a
   * column has fewer than 20 distinct values, otherwise just text input.
   * Both controls share the same data-filter-key so applyFilters() reads
   * the select value when non-empty and falls back to the text input. */
  function buildFilterCtrl(col, fth) {
    const distinct = COL_DISTINCT[col.key] || [];
    const useList  = (col.type === 'select' && (col.options || []).length) ||
                     (distinct.length > 0 && distinct.length < 20);

    if (useList) {
      const options = col.options?.length ? col.options : distinct;
      const sel = document.createElement('select');
      sel.dataset.filterKey  = col.key;
      sel.dataset.filterRole = 'select';
      sel.innerHTML = `<option value="">All</option>` +
        options.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
      sel.addEventListener('change', scheduleFilter);
      fth.appendChild(sel);

      /* Also add a free-text input for >/< and regex on numeric cols */
      if (col.type === 'number') {
        const inp = document.createElement('input');
        inp.type = 'text';
        inp.placeholder = '> < =';
        inp.style.width = '48px';
        inp.style.marginTop = '2px';
        inp.dataset.filterKey  = col.key;
        inp.dataset.filterRole = 'text';
        inp.addEventListener('input', scheduleFilter);
        fth.appendChild(inp);
      }
    } else {
      const inp = document.createElement('input');
      inp.type = 'text';
      inp.placeholder = 'Filter…';
      inp.dataset.filterKey  = col.key;
      inp.dataset.filterRole = 'text';
      inp.addEventListener('input', scheduleFilter);
      fth.appendChild(inp);
    }
  }

  function buildHead() {
    if (!thead) return;
    const sortRow   = document.createElement('tr');
    sortRow.className = 'kc-sort-row';
    const filterRow = document.createElement('tr');
    filterRow.className = 'kc-filter-row';

    COLS.forEach(col => {
      const th = document.createElement('th');
      th.innerHTML = `${esc(col.label)} <em class="kc-sort-icon" data-key="${esc(col.key)}"></em>`;
      th.addEventListener('click', () => {
        if (sortKey === col.key) sortDir = -sortDir;
        else { sortKey = col.key; sortDir = 1; }
        updateSortIcons();
        applySort();
        renderRows();
        applyFilters();
      });
      sortRow.appendChild(th);

      const fth = document.createElement('th');
      buildFilterCtrl(col, fth);
      filterRow.appendChild(fth);
    });

    thead.innerHTML = '';
    thead.appendChild(sortRow);
    thead.appendChild(filterRow);
  }

  function updateSortIcons() {
    document.querySelectorAll('.kc-sort-icon').forEach(el => {
      el.className = 'kc-sort-icon';
      if (el.dataset.key === sortKey)
        el.classList.add(sortDir === 1 ? 'asc' : 'desc');
    });
  }

  function cellValue(row, key) {
    const v = row[key];
    if (v == null) return '';
    if (Array.isArray(v)) return v.join('; ');
    return String(v);
  }

  /* FIX 6: per-profile score columns rendered as scorePill */
  function rowHtml(r) {
    const cells = COLS.map(col => {
      let v = r[col.key];
      if (v == null) v = '';
      if (col.key === 'sha12') {
        return `<td class="kc-td-sha"><a href="#" class="kc-sha-link"
          data-sha12="${esc(r.sha12)}" data-sha="${esc(r.sha || r.sha12)}">${esc(r.sha12)}</a></td>`;
      }
      if (col.key === 'score' || col._profile) {
        const num = parseFloat(v) || 0;
        return `<td class="kc-td-num">${num > 0 ? scorePill(num) : '<span class="kc-muted">—</span>'}</td>`;
      }
      if (col.key === 'profiles') {
        return `<td>${chips(Array.isArray(v) ? v : [v])}</td>`;
      }
      if (col.key === 'date') {
        return `<td class="kc-td-num">${esc(fmtDate(v))}</td>`;
      }
      return `<td>${esc(Array.isArray(v) ? v.join('; ') : v)}</td>`;
    }).join('');
    return `<tr data-sha12="${esc(r.sha12)}" data-sha="${esc(r.sha || r.sha12)}">${cells}</tr>`;
  }

  let sortedRows = ROWS.slice();

  function applySort() {
    if (!sortKey) return;
    sortedRows.sort((a, b) => {
      const av = cellValue(a, sortKey), bv = cellValue(b, sortKey);
      const an = parseFloat(av), bn = parseFloat(bv);
      const cmp = (!isNaN(an) && !isNaN(bn)) ? an - bn
        : av.localeCompare(bv, undefined, { numeric: true });
      return cmp * sortDir;
    });
  }

  function renderRows() {
    if (!tbody) return;
    tbody.innerHTML = sortedRows.map(rowHtml).join('');
  }

  let filterTimer = 0;
  function scheduleFilter() {
    clearTimeout(filterTimer);
    filterTimer = setTimeout(applyFilters, 60);
  }

  function matchToken(text, token) {
    if (!token) return true;
    const t = token.trim().toLowerCase(), s = text.toLowerCase();
    if (t.startsWith('>')) { const n = parseFloat(t.slice(1)); return !isNaN(n) && parseFloat(s) > n; }
    if (t.startsWith('<')) { const n = parseFloat(t.slice(1)); return !isNaN(n) && parseFloat(s) < n; }
    if (t.startsWith('=')) return s === t.slice(1);
    const pat = t.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
    try { return new RegExp(pat).test(s); } catch { return s.includes(t); }
  }

  /* FIX 5 (cont.): applyFilters reads select value first, then text input.
   * For a column that has both controls, the select acts as primary and the
   * text input as secondary — both must match (AND logic). */
  function applyFilters() {
    // Rebuild per-column filter values from all controls
    const selectVals = Object.create(null);
    const textVals   = Object.create(null);
    document.querySelectorAll('[data-filter-key]').forEach(el => {
      const key  = el.dataset.filterKey;
      const role = el.dataset.filterRole || 'text';
      if (role === 'select') selectVals[key] = el.value || '';
      else                   textVals[key]   = el.value || '';
      colFilters[key] = el.value || '';  // legacy compat
    });

    const global  = (globalSrch?.value || '').trim().toLowerCase();
    const gTokens = global ? global.split(/\s+/).filter(Boolean) : [];

    let shown = 0;
    sortedRows.forEach(r => {
      const tr = tbody?.querySelector(`tr[data-sha12="${CSS.escape(r.sha12)}"]`);
      if (!tr) return;

      let ok = COLS.every(col => {
        const sv = (selectVals[col.key] || '').trim();
        const tv = (textVals[col.key]   || '').trim();
        const cv = cellValue(r, col.key);
        if (sv && !matchToken(cv, sv)) return false;
        if (tv && !matchToken(cv, tv)) return false;
        return true;
      });

      if (ok && gTokens.length) {
        const hay = Object.values(r)
          .map(v => Array.isArray(v) ? v.join(' ') : String(v ?? '')).join(' ').toLowerCase();
        ok = gTokens.every(t => hay.includes(t));
      }
      tr.classList.toggle('kc-hidden', !ok);
      if (ok) shown++;
    });

    visibleCount = shown;
    if (liveCount) liveCount.textContent = `Showing ${shown} of ${ROWS.length} commits`;
    if (noMatch)   noMatch.classList.toggle('kc-visible', shown === 0);
  }

  clearBtn?.addEventListener('click', () => {
    document.querySelectorAll('[data-filter-key]').forEach(el => { el.value = ''; });
    if (globalSrch) globalSrch.value = '';
    applyFilters();
  });
  globalSrch?.addEventListener('input', scheduleFilter);

  exportBtn?.addEventListener('click', () => {
    const header = COLS.map(c => `"${c.label.replace(/"/g, '""')}"`).join(',');
    const lines  = [header];
    (tbody?.querySelectorAll('tr:not(.kc-hidden)') || []).forEach(tr => {
      lines.push(Array.from(tr.querySelectorAll('td'))
        .map(td => `"${td.textContent.trim().replace(/"/g, '""')}"`).join(','));
    });
    const blob = new Blob([lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = UI.is_filtered ? 'kcommit-filtered.csv' : 'kcommit-report.csv';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  });

  /* ========= Detail panel ========= */
  const rightPane  = document.getElementById('kc-pane-right');

  function activateTab(name) {
    document.querySelectorAll('.kc-tab').forEach(t => {
      const active = t.dataset.tab === name;
      t.classList.toggle('kc-active', active);
      t.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    document.querySelectorAll('.kc-tab-panel').forEach(p =>
      p.classList.toggle('kc-active', p.id === `kc-tab-${name}`));
  }

  document.querySelectorAll('.kc-tab').forEach(t =>
    t.addEventListener('click', () => activateTab(t.dataset.tab)));

  function renderDecision(row, commit) {
    const score   = parseFloat(row.score) || 0;
    const dropped = !!(row.reason) && score === 0;
    const reason  = row.reason || '';
    const KEEP_MAP = {
      commit_whitelist: 'SHA is explicitly whitelisted in config.',
      build_artifact:   'Touched files include kernel build artifacts for this product.',
      default:          'Passed all prefilter checks and scored above threshold.',
      no_files_layer:   'Zero-file commit kept as a structural commit.',
      filter_disabled:  'Prefilter is disabled in config; all commits pass.',
    };
    const DROP_MAP = {
      commit_blacklist:      'SHA is explicitly blacklisted in config.',
      path_blacklist_all:    'Every touched file matched the path blacklist.',
      no_kconfig_coverage:   'No Kconfig build evidence for any touched file.',
      score_below_threshold: `Score ${score} is below the minimum threshold (${SB.stage_06?.threshold ?? '?'}).`,
      no_files_layer:        'Zero-file structural commit — included without scoring.',
    };
    const cls   = dropped ? 'kc-decision-dropped' : 'kc-decision-kept';
    const label = dropped ? '\u2718 Dropped' : '\u2714 Kept';
    let items = [];
    if (reason && !dropped)  items.push(KEEP_MAP[reason] || `Keep reason: ${reason}`);
    else if (reason && dropped) items.push(DROP_MAP[reason] || `Drop reason: ${reason}`);
    else items.push(score > 0 ? 'Passed pipeline and scored above threshold.' : 'No explicit reason recorded.');
    if (!dropped && score > 0)           items.push(`Final score: ${score}`);
    if (!dropped && (row.profiles||[]).length)
      items.push(`Matched profiles: ${(row.profiles||[]).join(', ')}`);
    return `<div class="${cls}">
      <div class="kc-decision-title">${label}</div>
      <ul class="kc-decision-items">${items.map(x => `<li>${esc(x)}</li>`).join('')}</ul>
    </div>`;
  }

  function matchExcerpt(value, start, end, ctx) {
    ctx = (ctx == null) ? 60 : ctx;
    if (start == null || end == null || start < 0) return '';
    const str  = String(value || '');
    const lo   = Math.max(0, start - ctx);
    const hi   = Math.min(str.length, end + ctx);
    const pre  = str.slice(lo, start).replace(/[\r\n]/g, '\u21b5');
    const mid  = str.slice(start, end).replace(/[\r\n]/g, '\u21b5');
    const post = str.slice(end, hi).replace(/[\r\n]/g, '\u21b5');
    const ld   = lo > 0          ? '\u2026' : '';
    const rd   = hi < str.length ? '\u2026' : '';
    return `<span class="kc-match-excerpt">${esc(ld)}${esc(pre)}<mark class="kc-match-hl">${esc(mid)}</mark>${esc(post)}${esc(rd)}</span>`;
  }

  function pathStem(p) {
    const base = String(p || '').replace(/\\/g, '/').split('/').pop();
    const dot  = base.lastIndexOf('.');
    return dot > 0 ? base.slice(0, dot) : base;
  }

  function ruleNameFromPath(p) {
    const parts = String(p || '').replace(/\\/g, '/').split('/');
    return parts.length >= 2 ? parts[parts.length - 2] : '';
  }

  function renderProfileTrace(pname, pt) {
    const score   = pt.final_score || 0;
    const mult    = pt.multiplier  != null ? pt.multiplier : 1;
    const blocked = pt.blocked;
    const rules   = pt.rules || {};
    const cls     = scoreClass(score);

    let html = `<div class="kc-detail-card">
      <div class="kc-detail-card-head">
        <span class="kc-chip">${esc(pname)}</span>
        <span class="kc-score-pill ${cls}">${esc(score)}</span>
        ${blocked
          ? `<span style="color:var(--danger);font-weight:700">\u26d4 BLOCKED${pt.block_reason ? ` \u2014 ${esc(pt.block_reason)}` : ''}</span>`
          : `<span class="kc-muted" style="font-size:11px">×${mult}</span>`}
      </div>
      <div class="kc-detail-card-body">`;

    if (Object.keys(rules).length) {
      html += `<table class="kc-trace-table">
        <thead><tr>
          <th>Rule</th><th>Wt</th><th>Match</th><th>Score</th><th>Patterns matched</th>
        </tr></thead><tbody>`;
      Object.keys(rules).sort().forEach(rname => {
        const rd      = rules[rname] || {};
        const matched = rd.matched;
        const allHits = Object.values(rd.matches || {}).flat();
        const rowCls  = blocked ? 'kc-rule-blocked' : (matched ? 'kc-rule-matched' : '');
        const icon    = blocked ? '\u25a0' : (matched ? '\u2714' : '\u2715');
        const iconCol = blocked ? 'var(--muted)' : (matched ? 'var(--success)' : 'var(--muted)');

        let badgesHtml = '<span class="kc-muted">\u2014</span>';
        if (allHits.length) {
          badgesHtml = allHits.map(m => {
            const pat     = m.pattern     || '';
            const srcFile = m.source_file || null;
            const srcLine = m.source_line || null;
            const start   = m.match_start;
            const end     = m.match_end;
            const value   = m.value       || '';
            let srcBadge = '';
            if (srcFile) {
              const label = `${ruleNameFromPath(srcFile) || rname}:${pathStem(srcFile)}:${srcLine}`;
              srcBadge = `<span class="kc-src-badge" title="${esc(srcFile)}">${esc(label)}</span>`;
            }
            const excerpt = (start != null && end != null)
              ? matchExcerpt(value, start, end, 60)
              : `<span class="kc-match-excerpt kc-muted">${esc(value.slice(0,120))}${value.length>120?'\u2026':''}</span>`;
            return `<span class="kc-match-hit">
              <span class="kc-match-badge" title="${esc(pat)}">${esc(pat)}</span>${srcBadge}
              <span class="kc-match-excerpt-wrap">${excerpt}</span>
            </span>`;
          }).join('');
        }
        html += `<tr class="${rowCls}">
          <td class="kc-mono">${esc(rname)}</td>
          <td>${esc(rd.weight||0)}</td>
          <td style="color:${iconCol};font-weight:700;text-align:center">${icon}</td>
          <td class="kc-td-num">${matched ? esc(rd.score||0) : '\u2014'}</td>
          <td>${badgesHtml}</td>
        </tr>`;
      });
      html += `</tbody></table>`;
    } else {
      html += `<span class="kc-muted">No rule detail available.</span>`;
    }
    html += `</div></div>`;
    return html;
  }

  function renderFiles(commit) {
    const files  = (commit || {}).files || [];
    const covSet = new Set((commit || {}).coverage || []);
    if (!files.length) return `<p class="kc-muted">No files recorded for this commit.</p>`;
    return `<table class="kc-files-table">
      <thead><tr><th>File</th><th>Build coverage</th></tr></thead>
      <tbody>${files.map(f => `<tr>
        <td>${esc(f)}</td>
        <td class="${covSet.has(f)?'kc-coverage-y':'kc-coverage-n'}">${covSet.has(f)?'\u2714 covered':'\u2014'}</td>
      </tr>`).join('')}</tbody>
    </table>`;
  }

  function populateDetail(row, commit) {
    const c  = commit || {};
    const sc = c.scoring || {};
    const profiles = sc.profiles || {};

    let overview = '';
    overview += detailCard('Commit', [
      kv('SHA',      `<code class="kc-mono">${esc(c.commit || row.sha || row.sha12)}</code>`),
      kv('Subject',  esc(c.subject  || row.subject || '')),
      kv('Author',   esc((c.author_name || row.author || '') + (c.author_email ? ` <${c.author_email}>` : ''))),
      kv('Date',     esc(fmtDate(c.author_time || row.date))),
      kv('Score',    scorePill(c.score ?? row.score)),
      kv('Profiles', chips(c.matched_profiles || row.profiles || [])),
    ].join(''), '\ud83d\udcc4');

    overview += detailCard('Decision', renderDecision(row, c), '\u2696\ufe0f');

    if ((c.product_evidence || []).length) {
      overview += detailCard('Product Evidence',
        `<ul style="padding-left:1.2rem;margin:0">${
          (c.product_evidence||[]).map(e=>`<li><code class="kc-mono">${esc(e)}</code></li>`).join('')
        }</ul>`, '\ud83d\udce6');
    }

    if (c.body) {
      const bodyPreview = c.body.length > 4000 ? c.body.slice(0,4000)+'\n\u2026' : c.body;
      overview += detailCard('Full Commit Message',
        `<div class="kc-commit-body">${escNl(bodyPreview)}</div>`, '\ud83d\udcdd');
    }

    document.getElementById('kc-tab-overview').innerHTML = overview;

    /* ---- Scoring tab ---- */
    const traceProfiles = ((sc.trace||{}).profiles) || {};
    let scoring = '';
    if (Object.keys(traceProfiles).length) {
      scoring += `<p class="kc-muted" style="font-size:11.5px;margin:0 0 8px">
        Formula per profile: <code>min(&sum;rule_weights,100)&times;multiplier</code>.
        Combined score=&sum; of all profile final scores.
        Pattern badges show the <strong>matched pattern</strong>,
        source <em>rule:file:line</em>, and a highlighted excerpt.</p>`;
      Object.keys(traceProfiles).sort().forEach(p =>
        scoring += renderProfileTrace(p, traceProfiles[p]||{}));
    } else if (Object.keys(profiles).length) {
      scoring += detailCard('Profile Scores',
        Object.keys(profiles).sort().map(p=>kv(p,scorePill(profiles[p]))).join(''), '\u2605');
    } else {
      scoring = `<p class="kc-muted">No scoring data available for this commit.</p>`;
    }
    document.getElementById('kc-tab-scoring').innerHTML = scoring;

    document.getElementById('kc-tab-files').innerHTML = renderFiles(c);
    document.getElementById('kc-tab-raw').innerHTML =
      `<pre class="kc-raw-pre">${esc(JSON.stringify(c,null,2))}</pre>`;

    activateTab('overview');
  }

  function openDetail(sha12, fullSha) {
    const row = rowBySha[sha12] || rowBySha[fullSha] || {};
    tbody?.querySelectorAll('tr').forEach(tr =>
      tr.classList.toggle('kc-row-active', tr.dataset.sha12 === sha12));
    document.querySelectorAll('.kc-tab-panel').forEach(p => { p.innerHTML=''; p.classList.remove('kc-active'); });
    const ov = document.getElementById('kc-tab-overview');
    if (ov) { ov.innerHTML=`<p class="kc-muted">Loading\u2026</p>`; ov.classList.add('kc-active'); }
    if (rightPane?.classList.contains('kc-collapsed')) {
      rightPane.classList.remove('kc-collapsed');
      localStorage.setItem('kc-right-collapsed','0');
      updateCollapseIcons();
    }
    fetchCommit(sha12, fullSha||sha12).then(commit => populateDetail(row, commit));
  }

  document.addEventListener('click', e => {
    const a = e.target.closest('.kc-sha-link');
    if (!a) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    openDetail(a.dataset.sha12||a.dataset.sha, a.dataset.sha||a.dataset.sha12);
  }, true);

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape')
      tbody?.querySelectorAll('tr').forEach(tr => tr.classList.remove('kc-row-active'));
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      const visible = Array.from(tbody?.querySelectorAll('tr:not(.kc-hidden)')||[]);
      if (!visible.length) return;
      const active = tbody?.querySelector('tr.kc-row-active');
      const idx    = visible.indexOf(active);
      const next   = e.key === 'ArrowDown'
        ? visible[idx+1] || visible[0]
        : visible[idx-1] || visible[visible.length-1];
      if (next) { openDetail(next.dataset.sha12, next.dataset.sha); next.scrollIntoView({block:'nearest'}); }
    }
  });

  /* ========= Bootstrap ========= */
  buildHead();
  renderRows();
  applyFilters();

})();
