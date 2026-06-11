/* kcommit-analysis-pipeline — filter/sort/export + commit detail panel
 *
 * Changes:
 *   v13.0.4 (L)   — Fixed "Loading…" stuck state: openPanel() was setting
 *                   panelBody.innerHTML = 'Loading…' which destroyed the
 *                   static #tab-overview / #tab-scoring / #tab-files /
 *                   #tab-raw child divs.  renderCommit() then called
 *                   getElementById('tab-overview') → null → all four
 *                   innerHTML writes were silent no-ops → "Loading…" stayed
 *                   forever (no console error because null-guards swallowed
 *                   every write).
 *                   Fix: show loading state via panel.classList ('loading')
 *                   instead of clobbering panelBody.  The null-commit
 *                   fallback now writes into #tab-overview instead of
 *                   panelBody so the tab structure is always preserved.
 *
 *   v13.0.3 (K)   — Fixed critical regression: renderCommit() and all tab
 *                   renderers were duplicated outside the IIFE where esc(),
 *                   field(), panelBody etc. are not in scope.
 *
 *   v13.0.0       — openPanel() uses a.getAttribute('data-sha') inline;
 *                   loadCommitStore().then() on one line.
 *
 *   v12.0.0 (B)   — Sidecar JSON fetch for commits not in index.
 *   v12.0.0 (A.2) — Full scoring trace in renderCommit().
 */
(function () {
  'use strict';

  /* ── Helpers ──────────────────────────────────────────────── */
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function b64ToBytes(b64) {
    var bin = atob(b64), out = new Uint8Array(bin.length), i;
    for (i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function fmtDate(ts) {
    if (!ts) return '';
    var n = Number(ts);
    if (!isNaN(n) && n > 1e8) {
      var d = new Date(n * 1000);
      var p = function(x){ return String(x).padStart(2,'0'); };
      return d.getUTCFullYear()+'-'+p(d.getUTCMonth()+1)+'-'+p(d.getUTCDate())
             +' '+p(d.getUTCHours())+':'+p(d.getUTCMinutes());
    }
    return String(ts).slice(0,16);
  }

  function scoreClass(s) {
    s = parseFloat(s) || 0;
    return s >= 70 ? 'hi' : s >= 30 ? 'mid' : 'low';
  }

  function field(label, value, cls) {
    return '<div class="kc-detail-field">'
      + '<div class="field-label">'+esc(label)+'</div>'
      + '<div class="field-value'+(cls?' '+cls:'')+'">'+value+'</div>'
      + '</div>';
  }

  /* ── Sidecar helpers ─────────────────────────────────────────── */
  function _sidecarPath(fullSha) {
    if (!fullSha || fullSha.length < 4) return null;
    var root = (window.__KC_COMMIT_DETAIL_ROOT__ || './commits').replace(/\/+$/, '');
    return root + '/' + fullSha.slice(0, 2) + '/' + fullSha.slice(2, 4) + '/' + fullSha + '.json';
  }

  function _fetchCommitSidecar(sha12, fullSha) {
    var path = fullSha ? _sidecarPath(fullSha) : null;
    if (!path) return Promise.resolve(null);
    return fetch(path)
      .then(function(r) {
        if (!r.ok) throw new Error('HTTP ' + r.status + ' for ' + path);
        return r.json();
      })
      .then(function(data) {
        if (!window.__KC_COMMITS__) window.__KC_COMMITS__ = {};
        if (fullSha) window.__KC_COMMITS__[fullSha] = data;
        if (sha12)   window.__KC_COMMITS__[sha12]   = data;
        return data;
      });
  }

  /* ── Commit store ───────────────────────────────────────────── */
  function loadCommitStore() {
    if (window.__KC_COMMITS__) return Promise.resolve(window.__KC_COMMITS__);
    if (window.__KC_COMMITS_COMPRESSED__ && window.__KC_COMMITS_COMPRESSION__ === 'zlib') {
      return decodeEmbeddedCommitStore().then(function(map){
        if (map && Object.keys(map).length) return map;
        if (window.__KC_COMMITS_FALLBACK__) {
          window.__KC_COMMITS__ = window.__KC_COMMITS_FALLBACK__;
          return window.__KC_COMMITS__;
        }
        return {};
      });
    }
    if (window.__KC_COMMITS_INDEX__ && window.__KC_COMMITS_INDEX__.mode === 'sidecar') {
      return fetch(window.__KC_COMMITS_INDEX__.path)
        .then(function(r){ return r.json(); })
        .then(function(data){
          var rows = Array.isArray(data) ? data : ((data && data.rows) || []);
          var map = {};
          rows.forEach(function(c){
            var full = String(c.commit || '');
            var shortSha = String(c.sha || full.slice(0, 12));
            if (shortSha) map[shortSha] = c;
            if (full) map[full] = c;
          });
          window.__KC_COMMITS__ = map;
          return map;
        });
    }
    window.__KC_COMMITS__ = {};
    return Promise.resolve(window.__KC_COMMITS__);
  }

  function triggerDownload(blob, filename) {
    var a = document.createElement('a');
    var url = URL.createObjectURL(blob);
    a.href = url;
    a.download = filename;
    a.style.display = 'none';
    a.setAttribute('rel', 'noopener');
    document.body.appendChild(a);
    try {
      if (typeof MouseEvent === 'function') {
        a.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
      } else if (typeof a.click === 'function') {
        a.click();
      }
    } catch (err) {
      if (typeof a.click === 'function') a.click();
    }
    setTimeout(function(){
      if (a.parentNode) a.parentNode.removeChild(a);
      URL.revokeObjectURL(url);
    }, 1000);
  }

  function inflateZlibPayload(b64) {
    if (typeof DecompressionStream === 'undefined') return Promise.resolve(null);
    var ds = new DecompressionStream('deflate');
    var blob = new Blob([b64ToBytes(b64)]);
    return new Response(blob.stream().pipeThrough(ds)).text().catch(function(){ return null; });
  }

  function decodeEmbeddedCommitStore() {
    if (window.__KC_COMMITS__) return Promise.resolve(window.__KC_COMMITS__);
    if (!window.__KC_COMMITS_COMPRESSED__) return Promise.resolve({});
    return inflateZlibPayload(window.__KC_COMMITS_COMPRESSED__).then(function(txt){
      if (!txt) return {};
      window.__KC_COMMITS__ = JSON.parse(txt);
      return window.__KC_COMMITS__;
    });
  }

  /* ── Metadata sidecar ───────────────────────────────────────── */
  function loadReportMetadata() {
    var url = window.KCOMMIT_REPORT_METADATA_URL;
    if (!url) return;
    var el = document.getElementById('evaluation-details');
    if (!el || el.children.length > 0) return;
    fetch(url)
      .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function(meta) {
        var rs  = (meta && meta.report_stats) || {};
        var ev  = rs.evaluation || {};
        var git = (meta && meta.git) || {};
        var an  = (meta && meta.analysis) || {};
        var pairs = [
          ['Git source',       ev.git_source       || (git.repo_url  ? git.repo_url + (git.branch ? ' (' + git.branch + ')' : '') : null)],
          ['Git baseline',     ev.git_baseline     || git.base_rev || null],
          ['Git range',        ev.git_range        || (git.base_rev && git.head_rev ? git.base_rev + '..' + git.head_rev : null)],
          ['Kernel revision',  ev.kernel_revision  || null],
          ['Profiles',         ev.profiles         || (an.active_profiles && an.active_profiles.join(', ')) || null],
          ['Top N',            ev.top_n            || (an.top_n != null ? String(an.top_n) : null)],
          ['Min score',        ev.min_score        || ((an.filter && an.filter.min_score) ? String(an.filter.min_score) : null)],
          ['HTML detail mode', ev.html_detail_mode || an.html_detail_mode || null],
          ['Outputs',          ev.outputs          || (an.outputs && an.outputs.join(', ')) || null],
        ];
        var html = '<h3>Evaluation</h3>';
        pairs.forEach(function(pair) {
          var label = pair[0], value = pair[1];
          if (value == null || value === '') return;
          html += '<div class="kc-stat-row">'
               +  '<span class="kc-stat-label">' + esc(label) + '</span>'
               +  '<span class="kc-stat-value">' + esc(String(value)) + '</span>'
               +  '</div>';
        });
        el.innerHTML = html;
      })
      .catch(function(err) {
        if (typeof console !== 'undefined' && console.warn)
          console.warn('[kcommit] Could not load report metadata:', err);
      });
  }

  /* ── Per-column filters + global search ───────────────────────── */
  var MULTISELECT_MAX = 20;

  function distinctVals(rows, ci) {
    var seen = Object.create(null), vals = [];
    rows.forEach(function(r) {
      var text = r.cells[ci] ? String(r.cells[ci]).trim() : '';
      text.split(/[;,]\s*/).forEach(function(p) {
        p = p.trim();
        if (p && !seen[p]) { seen[p] = true; vals.push(p); }
      });
    });
    return vals.sort(function(a,b){ return a.localeCompare(b); });
  }

  function buildSelect(vals) {
    var sel = document.createElement('select');
    sel.multiple = true; sel.className = 'kc-ms';
    sel.setAttribute('aria-label','filter column');
    var all = document.createElement('option');
    all.value = '__all__'; all.text = '(all)'; all.selected = true;
    sel.appendChild(all);
    vals.forEach(function(v) {
      var o = document.createElement('option'); o.value = o.text = v;
      sel.appendChild(o);
    });
    return sel;
  }

  function matchesToken(text, tok) {
    if (!tok) return true;
    if (tok[0] === '>') { var n = parseFloat(tok.slice(1)); return !isNaN(n) && parseFloat(text) > n; }
    if (tok[0] === '<') { var n = parseFloat(tok.slice(1)); return !isNaN(n) && parseFloat(text) < n; }
    if (tok[0] === '=') return text === tok.slice(1).toLowerCase();
    var pat = tok.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g,'.*');
    try { return new RegExp(pat).test(text); } catch(e) { return text.includes(tok); }
  }

  function initTable(tbl) {
    var tbody      = tbl.querySelector('tbody');
    var rows       = Array.from(tbody.querySelectorAll('tr'));
    var noMatch    = tbl.parentElement.querySelector('.kc-no-match');
    var filterRow  = tbl.querySelector('tr.kc-filters');
    if (!filterRow) return;

    var rowData = rows.map(function(row) {
      return {
        row: row,
        cells: Array.from(row.cells).map(function(cell) {
          return (cell.textContent || '').trim();
        })
      };
    });

    var controls = [];
    Array.from(filterRow.querySelectorAll('th')).forEach(function(th, ci) {
      var vals = distinctVals(rowData, ci);
      var ctrl;
      if (vals.length > 0 && vals.length <= MULTISELECT_MAX) {
        ctrl = buildSelect(vals);
      } else {
        ctrl = document.createElement('input');
        ctrl.type = 'text'; ctrl.placeholder = 'filter…';
        ctrl.setAttribute('aria-label','filter column');
      }
      th.innerHTML = '';
      th.appendChild(ctrl);
      controls.push(ctrl);
    });

    var card        = tbl.closest('.kc-card');
    var globalEl    = card && card.querySelector('.kc-global-filter');
    var liveCountEl = card && card.querySelector('.kc-live-count');
    var tableWrap   = tbl.closest('.kc-table-wrap');
    var busyEl      = tableWrap && tableWrap.querySelector('.kc-table-busy');
    var filterJob   = 0;

    function setBusy(isBusy) {
      if (!tableWrap) return;
      tableWrap.setAttribute('aria-busy', isBusy ? 'true' : 'false');
      if (busyEl) {
        busyEl.classList.toggle('visible', !!isBusy);
        busyEl.setAttribute('aria-hidden', isBusy ? 'false' : 'true');
      }
    }

    function updateLiveCount(visible) {
      if (!liveCountEl) return;
      liveCountEl.textContent = 'Showing ' + visible + ' of ' + rows.length + ' commits';
    }

    function apply() {
      var colFilters = controls.map(function(c) {
        if (c.tagName === 'SELECT') {
          var sel = Array.from(c.options)
            .filter(function(o){ return o.selected && o.value !== '__all__'; })
            .map(function(o){ return o.value.toLowerCase(); });
          return sel.length ? sel : null;
        }
        return c.value.trim().toLowerCase() || null;
      });
      var global = globalEl ? globalEl.value.trim().toLowerCase() : '';
      var globalNeedles = global ? global.split(/\s+/).filter(Boolean) : null;
      var visible = 0;
      rowData.forEach(function(entry) {
        var colOk = colFilters.every(function(f, ci) {
          if (!f) return true;
          var text = (entry.cells[ci] || '').toLowerCase();
          if (Array.isArray(f)) return f.some(function(v){ return text.includes(v); });
          return f.split(/\s+/).every(function(tok){ return matchesToken(text, tok); });
        });
        var glOk = !globalNeedles || globalNeedles.every(function(tok){
          var hay = entry._haystack || (entry._haystack = entry.cells.join(' ').toLowerCase());
          return hay.includes(tok);
        });
        var show = colOk && glOk;
        entry.row.classList.toggle('hidden', !show);
        if (show) visible++;
      });
      if (noMatch) noMatch.classList.toggle('visible', visible === 0);
      updateLiveCount(visible);
    }

    function scheduleApply() {
      var ticket = ++filterJob;
      setBusy(true);
      requestAnimationFrame(function() {
        setTimeout(function() {
          if (ticket !== filterJob) return;
          try { apply(); } finally { if (ticket === filterJob) setBusy(false); }
        }, 0);
      });
    }

    controls.forEach(function(c) {
      c.addEventListener(c.tagName === 'SELECT' ? 'change' : 'input', scheduleApply);
    });
    if (globalEl) globalEl.addEventListener('input', scheduleApply);

    var clearBtn = card && card.querySelector('.kc-clear-filters');
    if (clearBtn) clearBtn.addEventListener('click', function() {
      controls.forEach(function(c) {
        if (c.tagName === 'SELECT') {
          Array.from(c.options).forEach(function(o){ o.selected = o.value === '__all__'; });
        } else { c.value = ''; }
      });
      if (globalEl) globalEl.value = '';
      scheduleApply();
    });

    apply();
  }

  /* ── Column sort ─────────────────────────────────────────────── */
  function initSort(tbl) {
    var tbody   = tbl.querySelector('tbody');
    var rows    = Array.from(tbody.querySelectorAll('tr'));
    var headers = Array.from(tbl.querySelectorAll('tr.kc-col-headers th'));
    var sortState = { col: -1, dir: 1 };

    headers.forEach(function(th, ci) {
      var icon = th.querySelector('.sort-icon');
      th.addEventListener('click', function() {
        sortState.dir = (sortState.col === ci) ? -sortState.dir : 1;
        sortState.col = ci;
        headers.forEach(function(h) {
          var ic = h.querySelector('.sort-icon');
          if (ic) ic.className = 'sort-icon';
        });
        if (icon) icon.className = 'sort-icon ' + (sortState.dir === 1 ? 'asc' : 'desc');
        rows.slice().sort(function(a, b) {
          var av = a.cells[ci] ? a.cells[ci].getAttribute('data-sort') || a.cells[ci].textContent.trim() : '';
          var bv = b.cells[ci] ? b.cells[ci].getAttribute('data-sort') || b.cells[ci].textContent.trim() : '';
          var an = parseFloat(av), bn = parseFloat(bv);
          var cmp = (!isNaN(an) && !isNaN(bn)) ? an - bn : av.localeCompare(bv);
          return cmp * sortState.dir;
        }).forEach(function(r){ tbody.appendChild(r); });
      });
    });
  }

  /* ── CSV export ──────────────────────────────────────────────── */
  function initCsvExport(tbl) {
    var card = tbl.closest('.kc-card');
    if (!card) return;
    var btn = card.querySelector('.kc-export-filtered-csv');
    if (!btn) return;
    btn.title = 'Export visible rows as CSV';
    btn.addEventListener('click', function() {
      var hdrs = Array.from(tbl.querySelectorAll('tr.kc-col-headers th'))
        .map(function(th){ return '"'+th.textContent.replace(/[\u21c5\u25b2\u25bc]/g,'').trim().replace(/"/g,'""')+'"'; });
      var lines = [hdrs.join(',')];
      Array.from(tbl.querySelectorAll('tbody tr:not(.hidden)')).forEach(function(r) {
        lines.push(Array.from(r.cells).map(function(td){
          return '"'+td.textContent.trim().replace(/"/g,'""')+'"';
        }).join(','));
      });
      var blob = new Blob([lines.join('\r\n')], {type:'text/csv;charset=utf-8'});
      triggerDownload(blob, 'kcommit-export.csv');
    });
  }

  /* ── Detail panel ─────────────────────────────────────────────── */
  var overlay   = document.getElementById('kc-detail-overlay');
  var panel     = document.getElementById('kc-detail-panel');
  var panelH3   = document.getElementById('kc-detail-sha');
  var panelBody = document.getElementById('kc-detail-body');
  var closeBtn  = document.getElementById('kc-detail-close');

  /* ── Tab management ───────────────────────────────────────────── */
  function activateDetailTab(tabName) {
    document.querySelectorAll('#kc-detail-header .kc-tab').forEach(function(t) {
      t.classList.toggle('active', t.getAttribute('data-tab') === tabName);
    });
    document.querySelectorAll('#kc-detail-body .kc-tab-content').forEach(function(c) {
      c.classList.remove('active');
    });
    var active = document.getElementById('tab-' + tabName);
    if (active) active.classList.add('active');
  }

  document.querySelectorAll('#kc-detail-header .kc-tab').forEach(function(tab) {
    tab.addEventListener('click', function() {
      activateDetailTab(this.getAttribute('data-tab'));
    });
  });

  /* ── Scoring trace rendering ──────────────────────────────────────── */
  function _matchBadges(matches) {
    if (!matches || !matches.length) return '<em style="color:var(--color-text-faint,#aaa)">none</em>';
    return matches.map(function(m) {
      var p = esc(m.pattern || ''), v = esc(m.value || '');
      return '<span style="display:inline-block;margin:.1rem .2rem;padding:.1rem .35rem;'
           + 'background:var(--color-primary-highlight,#cde);border-radius:3px;'
           + 'font-size:.7rem;font-family:monospace" title="matched value: ' + v + '">'
           + p + '</span>';
    }).join('');
  }

  function _renderProfileTrace(pname, ptrace) {
    var html = '';
    var blocked     = ptrace.blocked;
    var mult        = ptrace.multiplier != null ? ptrace.multiplier : 1.0;
    var rawTotal    = ptrace.raw_rule_total || 0;
    var capped      = ptrace.raw_rule_total_capped || 0;
    var final_score = ptrace.final_score || 0;
    var blockReason = ptrace.block_reason || '';
    var formula     = 'min(' + rawTotal + ',100) × ' + (mult * 100).toFixed(0) + '% = ' + final_score;
    var pillCls     = scoreClass(final_score);

    html += '<div class="kc-detail-section" style="margin-top:.5rem">';
    html += '<h4 style="display:flex;align-items:center;gap:.4rem">';
    html += '<span class="profile-chip">' + esc(pname) + '</span>';
    html += '<span class="score-pill ' + pillCls + '">' + final_score + '</span>';
    if (blocked) {
      html += '<span style="font-size:.7rem;color:var(--color-error,#c33);font-weight:600">⛔ BLOCKED</span>';
      if (blockReason) html += '<span style="font-size:.68rem;color:var(--color-text-muted,#888)">(' + esc(blockReason) + ')</span>';
    } else {
      html += '<span style="font-size:.68rem;color:var(--color-text-muted,#888)">' + esc(formula) + '</span>';
    }
    html += '</h4>';

    if (blocked) {
      var mm = ptrace.merged_matches || {};
      var blHits = (mm.keywords_blacklist || []).concat(mm.path_blacklist || []).concat(mm.commit_blacklist || []);
      if (blHits.length) {
        html += '<div style="font-size:.72rem;margin:.2rem 0 .4rem 0">';
        html += '<span style="color:var(--color-error,#c33);font-weight:600">Blacklist hits: </span>';
        html += _matchBadges(blHits);
        html += '</div>';
      }
    }

    var rules  = ptrace.rules || {};
    var rnames = Object.keys(rules).sort();
    if (rnames.length) {
      html += '<table style="width:100%;font-size:.7rem;border-collapse:collapse;margin-top:.25rem">';
      html += '<tr style="color:var(--color-text-muted,#888);border-bottom:1px solid var(--color-divider,#ddd)">';
      html += '<th style="text-align:left;padding:.1rem .25rem">Rule</th>';
      html += '<th style="text-align:right;padding:.1rem .25rem">Wt</th>';
      html += '<th style="text-align:center;padding:.1rem .25rem">Match</th>';
      html += '<th style="text-align:right;padding:.1rem .25rem">Pts</th>';
      html += '<th style="text-align:left;padding:.1rem .25rem">Patterns matched</th>';
      html += '</tr>';
      rnames.forEach(function(rname) {
        var rd      = rules[rname] || {};
        var matched = rd.matched;
        var rScore  = rd.score  || 0;
        var rWeight = rd.weight || 0;
        var matches = rd.matches || {};
        var allHits = (matches.keywords_whitelist || [])
                    .concat(matches.path_whitelist || [])
                    .concat(matches.commit_whitelist || []);
        var rowCls    = matched ? 'color:var(--color-text)' : 'color:var(--color-text-faint,#aaa)';
        var matchIcon = blocked ? '\u25a0' : (matched ? '\u2714' : '\u2715');
        var matchColor = blocked
          ? 'color:var(--color-text-faint,#aaa)'
          : (matched ? 'color:var(--color-success,green);font-weight:700' : 'color:var(--color-text-faint,#aaa)');
        html += '<tr style="border-bottom:1px solid var(--color-divider,#eee);' + rowCls + '">';
        html += '<td style="padding:.15rem .25rem;font-family:monospace">' + esc(rname) + '</td>';
        html += '<td style="text-align:right;padding:.15rem .25rem">' + rWeight + '</td>';
        html += '<td style="text-align:center;padding:.15rem .25rem;' + matchColor + '">' + matchIcon + '</td>';
        html += '<td style="text-align:right;padding:.15rem .25rem;font-weight:600">' + (matched ? rScore : '\u2014') + '</td>';
        html += '<td style="padding:.15rem .25rem">' + (allHits.length ? _matchBadges(allHits) : '<span style="color:var(--color-text-faint,#aaa)">\u2014</span>') + '</td>';
        html += '</tr>';
      });
      html += '</table>';
    }
    html += '</div>';
    return html;
  }

  /* ── Tab content renderers ─────────────────────────────────────────── */
  function _renderOverview(c) {
    var html = '';
    var sc   = c.scoring || {};

    html += field('SHA',     '<code>'+esc((c.commit||'').slice(0,40))+'</code>', 'mono');
    html += field('Subject', esc(c.subject || ''));
    html += field('Author',  esc((c.author_name||'')+(c.author_email?' <'+c.author_email+'>':'')));
    html += field('Date',    esc(fmtDate(c.author_time)), 'mono');
    html += field('Score',   '<span class="score-pill '+scoreClass(c.score||0)+'">'+esc(String(c.score||0))+'</span>');
    if (c.matched_profiles && c.matched_profiles.length) {
      html += field('Profiles',
        c.matched_profiles.map(function(p){ return '<span class="profile-chip">'+esc(p)+'</span>'; }).join(' '));
    }

    html += '<div class="kc-detail-section"><h4>Why This Commit Was Kept</h4>';
    var keptReasons = [];
    if (sc.trace && sc.trace.profiles && Object.keys(sc.trace.profiles).length) {
      keptReasons.push('Passed prefilter checks');
    }
    if (c.matched_profiles && c.matched_profiles.length) {
      keptReasons.push('Matched profiles: ' + c.matched_profiles.map(esc).join(', '));
    }
    if (c.score != null) {
      keptReasons.push('Score ' + esc(String(c.score)) + ' met minimum threshold');
    }
    if (!keptReasons.length) keptReasons.push('Commit passed all filtering stages');
    html += '<div class="decision-section kept-reason"><strong>Kept</strong>';
    html += '<ul style="margin:.25rem 0 0 1rem;font-size:.75rem">';
    keptReasons.forEach(function(r){ html += '<li>' + r + '</li>'; });
    html += '</ul></div></div>';

    if (c.product_evidence && c.product_evidence.length) {
      html += '<div class="kc-detail-section"><h4>Evidence</h4>'
        + '<ul style="padding-left:1.1rem;font-size:.75rem">';
      c.product_evidence.forEach(function(p){ html += '<li><code>'+esc(p)+'</code></li>'; });
      html += '</ul></div>';
    }

    if (c.body) {
      html += '<div class="kc-detail-section"><h4>Commit message</h4>'
        + '<pre style="white-space:pre-wrap;font-size:.72rem;max-height:220px;overflow-y:auto">'
        + esc(c.body.slice(0,3000))+(c.body.length>3000?'\n\u2026':'')
        + '</pre></div>';
    }
    return html;
  }

  function _renderScoring(c) {
    var html = '';
    var sc   = c.scoring || {};
    var traceProfiles = sc.trace && sc.trace.profiles;

    if (traceProfiles && Object.keys(traceProfiles).length) {
      html += '<div class="kc-detail-section"><h4>Score Breakdown</h4>';
      html += '<p style="font-size:.7rem;color:var(--color-text-muted,#888);margin-bottom:.3rem">';
      html += 'Formula per profile: <code>min(&sum;rule_weights, 100) &times; profile_multiplier</code>. '
            + 'Combined score = &sum; of all profile scores.</p>';
      Object.keys(traceProfiles).sort().forEach(function(pname) {
        html += _renderProfileTrace(pname, traceProfiles[pname] || {});
      });
      html += '</div>';
    } else if (sc.profiles && Object.keys(sc.profiles).length) {
      html += '<div class="kc-detail-section"><h4>Final:</h4>';
      Object.keys(sc.profiles).sort().forEach(function(p) {
        html += field(p, '<span class="score-pill">'+esc(String(sc.profiles[p]))+'</span>');
      });
      html += '</div>';
    } else {
      html += '<p style="color:var(--color-text-muted,#888);font-style:italic">No scoring data available.</p>';
    }
    return html;
  }

  function _renderFiles(c) {
    var files = c.files || [];
    if (!files.length) {
      return '<p style="color:var(--color-text-muted,#888);font-style:italic">No files recorded for this commit.</p>';
    }
    var html = '<div class="kc-detail-section"><h4>Changed Files (' + files.length + ')</h4>';
    var productMap    = window.__KC_PRODUCT_MAP__ || {};
    var configToPaths = productMap.config_to_paths || {};
    var coveredFiles  = Object.create(null);
    (productMap.enabled_configs || []).forEach(function(cfg) {
      (configToPaths[cfg] || []).forEach(function(p){ coveredFiles[p] = true; });
    });
    html += '<table style="width:100%;font-size:.75rem;border-collapse:collapse">';
    html += '<thead><tr style="color:var(--color-text-muted,#888);border-bottom:1px solid var(--color-divider,#ddd)">';
    html += '<th style="text-align:left;padding:.15rem .3rem">File</th>';
    html += '<th style="text-align:center;padding:.15rem .3rem">Product coverage</th>';
    html += '</tr></thead><tbody>';
    files.forEach(function(f) {
      var covered = !!coveredFiles[f];
      var badge   = covered
        ? '<span style="color:var(--color-success,green);font-weight:600">✔ covered</span>'
        : '<span style="color:var(--color-text-faint,#aaa)">—</span>';
      html += '<tr style="border-bottom:1px solid var(--color-divider,#eee)">';
      html += '<td style="padding:.15rem .3rem;font-family:monospace;font-size:.7rem">' + esc(f) + '</td>';
      html += '<td style="text-align:center;padding:.15rem .3rem">' + badge + '</td>';
      html += '</tr>';
    });
    html += '</tbody></table></div>';
    return html;
  }

  /* ── renderCommit ─────────────────────────────────────────────── */
  function renderCommit(c, sha) {
    /* L: never clobber panelBody — the tab divs live inside it.
     *    Remove the loading class set by openPanel instead. */
    if (panel) panel.classList.remove('loading');

    var tabOverview = document.getElementById('tab-overview');
    var tabScoring  = document.getElementById('tab-scoring');
    var tabFiles    = document.getElementById('tab-files');
    var tabRaw      = document.getElementById('tab-raw');

    if (!c) {
      /* Commit not found — write a notice into the overview tab */
      if (tabOverview) tabOverview.innerHTML =
        field('SHA', esc(sha), 'mono')
        + '<p style="color:var(--color-text-muted,#888);margin-top:.75rem;font-size:.75rem">'
        + 'No detail data available for this commit.</p>';
      if (tabScoring) tabScoring.innerHTML = '';
      if (tabFiles)   tabFiles.innerHTML   = '';
      if (tabRaw)     tabRaw.innerHTML     = '';
      activateDetailTab('overview');
      return;
    }

    if (tabOverview) tabOverview.innerHTML = _renderOverview(c);
    if (tabScoring)  tabScoring.innerHTML  = _renderScoring(c);
    if (tabFiles)    tabFiles.innerHTML    = _renderFiles(c);
    if (tabRaw)      tabRaw.innerHTML      =
      '<pre style="white-space:pre-wrap;font-size:.7rem;overflow-y:auto;max-height:60vh">'
      + esc(JSON.stringify(c, null, 2)) + '</pre>';
    activateDetailTab('overview');
  }

  /* ── openPanel ─────────────────────────────────────────────────── */
  function openPanel(sha12, fullSha) {
    if (!overlay || !panel || !sha12) return false;
    overlay.classList.add('open');
    panel.classList.add('open');
    if (panelH3) panelH3.textContent = fullSha || sha12;

    /* L: signal loading via CSS class — do NOT touch panelBody.innerHTML
     *    because the static tab divs (#tab-overview etc.) live inside it. */
    panel.classList.add('loading');

    loadCommitStore().then(function(map) {
        map = (map && typeof map === 'object') ? map : {};
        var c = map[sha12] || map[String(sha12)] || (fullSha ? map[fullSha] : null) || null;
        var hasSidecar    = !!window.__KC_COMMIT_DETAIL_ROOT__;
        var hasFullDetail = c && c.scoring && c.scoring.trace;
        if (hasSidecar && !hasFullDetail && (fullSha || sha12)) {
          return _fetchCommitSidecar(sha12, fullSha || sha12)
            .then(function(sidecar){ return sidecar || c; })
            .catch(function(){ return c; });
        }
        return c;
      })
      .then(function(c) { renderCommit(c, fullSha || sha12); })
      .catch(function(err) {
        if (panel) panel.classList.remove('loading');
        var msg = (err && err.message) ? err.message : String(err || 'unknown error');
        var tabOverview = document.getElementById('tab-overview');
        if (tabOverview) {
          tabOverview.innerHTML = field('SHA', esc(fullSha || sha12), 'mono')
            + '<p style="color:var(--color-text-muted,#888);margin-top:.75rem;font-size:.75rem">'
            + 'Unable to load commit details: ' + esc(msg) + '</p>';
        }
        activateDetailTab('overview');
      });
    return true;
  }

  function closePanel() {
    if (overlay) overlay.classList.remove('open');
    if (panel)   panel.classList.remove('open', 'loading');
  }

  if (overlay) overlay.addEventListener('click', function(e) {
    if (e.target === overlay) closePanel();
  });
  if (closeBtn) closeBtn.addEventListener('click', closePanel);
  document.addEventListener('keydown', function(e){ if (e.key === 'Escape') closePanel(); });

  /* D.5: event delegation for SHA links — survives filter/sort reorders */
  document.addEventListener('click', function(e) {
    var target = e.target;
    var a = null;
    if (target && target.closest) {
      a = target.closest('a.sha-link');
    } else {
      while (target && target !== document) {
        if (target.tagName && target.tagName.toLowerCase() === 'a'
            && /(^|\s)sha-link(\s|$)/.test(target.className || '')) {
          a = target; break;
        }
        target = target.parentNode;
      }
    }
    if (!a) return;
    if (e.preventDefault) e.preventDefault();
    if (e.stopPropagation) e.stopPropagation();
    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
    var sha12   = a.getAttribute('data-sha')      || (a.dataset && a.dataset.sha)     || '';
    var fullSha = a.getAttribute('data-full-sha') || (a.dataset && a.dataset.fullSha) || sha12;
    openPanel(a.getAttribute('data-sha') || sha12, fullSha);
    return false;
  }, true);

  /* ── Theme toggle ──────────────────────────────────────────────── */
  (function(){
    var SVG_NS = 'http://www.w3.org/2000/svg';

    function makeSunPaths(svg) {
      var c = document.createElementNS(SVG_NS, 'circle');
      c.setAttribute('cx', '12'); c.setAttribute('cy', '12'); c.setAttribute('r', '5');
      svg.appendChild(c);
      ['M12 1v2','M12 21v2','M4.22 4.22l1.42 1.42','M18.36 18.36l1.42 1.42',
       'M1 12h2','M21 12h2','M4.22 19.78l1.42-1.42','M18.36 5.64l1.42-1.42'].forEach(function(d) {
        var path = document.createElementNS(SVG_NS, 'path'); path.setAttribute('d', d);
        svg.appendChild(path);
      });
    }

    function makeMoonPaths(svg) {
      var path = document.createElementNS(SVG_NS, 'path');
      path.setAttribute('d', 'M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z');
      svg.appendChild(path);
    }

    function setIcon(svg, isDark) {
      if (!svg) return;
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      if (isDark) makeSunPaths(svg); else makeMoonPaths(svg);
    }

    var html  = document.documentElement;
    var btn   = document.getElementById('kc-theme-toggle');
    var icon  = document.getElementById('kc-theme-icon');
    var theme = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    html.setAttribute('data-theme', theme);
    setIcon(icon, theme === 'dark');

    if (btn) {
      btn.addEventListener('click', function(e) {
        if (e && e.preventDefault) e.preventDefault();
        theme = (html.getAttribute('data-theme') === 'dark') ? 'light' : 'dark';
        html.setAttribute('data-theme', theme);
        setIcon(icon, theme === 'dark');
        btn.setAttribute('aria-label', 'Switch to ' + (theme === 'dark' ? 'light' : 'dark') + ' theme');
      });
    }
  })();

  /* ── Bootstrap ────────────────────────────────────────────────── */
  document.querySelectorAll('table.kc-table').forEach(function(tbl) {
    initTable(tbl);
    initSort(tbl);
    initCsvExport(tbl);
  });

  loadReportMetadata();

})();
