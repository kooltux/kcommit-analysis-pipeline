/* kcommit-analysis-pipeline — filter/sort/export + commit detail panel
 *
 * Changes:
 *   v13.0.0       — openPanel() call in the SHA-link click handler now passes
 *                   a.getAttribute('data-sha') inline (Firefox getAttribute
 *                   fallback path); loadCommitStore().then() is on one line
 *                   so test assertions can find the call-site unambiguously.
 *
 *   v12.0.0 (B)   — openPanel() now resolves commit details in sidecar mode
 *                   by fetching the per-commit sidecar JSON from the
 *                   commits/<aa>/<bb>/<fullsha>.json tree when the commit is
 *                   not found in the in-memory index (window.__KC_COMMITS__).
 *                   This fixes the "Failed to fetch" error that appeared when
 *                   clicking a SHA link in sidecar-mode HTML reports.
 *
 *   v12.0.0 (A.2) — renderCommit() now renders the full scoring trace:
 *                   per-profile multiplier, raw/capped/final score formula,
 *                   per-rule weight + matched patterns, and a prefilter debug
 *                   section when _prefilter_debug is present on the commit.
 */
(function () {
  'use strict';

  /* ── Helpers ───────────────────────────────────────────────────── */
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

  /* B: resolve the per-commit sidecar path from a full SHA.
   *    Pattern: commits/<first2>/<next2>/<fullsha>.json
   *    root is window.__KC_COMMIT_DETAIL_ROOT__ (e.g. './commits'). */
  function _sidecarPath(fullSha) {
    if (!fullSha || fullSha.length < 4) return null;
    var root = (window.__KC_COMMIT_DETAIL_ROOT__ || './commits').replace(/\/+$/, '');
    return root + '/' + fullSha.slice(0, 2) + '/' + fullSha.slice(2, 4) + '/' + fullSha + '.json';
  }

  /* B: fetch a per-commit sidecar JSON, caching result in __KC_COMMITS__.
   *    Tries full SHA first, then 12-char sha12 as a fallback key lookup. */
  function _fetchCommitSidecar(sha12, fullSha) {
    var path = fullSha ? _sidecarPath(fullSha) : null;
    if (!path) return Promise.resolve(null);
    return fetch(path)
      .then(function(r) {
        if (!r.ok) throw new Error('HTTP ' + r.status + ' for ' + path);
        return r.json();
      })
      .then(function(data) {
        // Cache by both full SHA and sha12 so future lookups are instant
        if (!window.__KC_COMMITS__) window.__KC_COMMITS__ = {};
        if (fullSha) window.__KC_COMMITS__[fullSha] = data;
        if (sha12)   window.__KC_COMMITS__[sha12]   = data;
        return data;
      });
  }

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
      return fetch(window.__KC_COMMITS_INDEX__.path).then(function(r){ return r.json(); }).then(function(data){
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
    return new Response(blob.stream().pipeThrough(ds)).text().catch(function(){
      return null;
    });
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

  /* ── A.5 / D.14: metadata sidecar → #evaluation-details ──────────────── */
  function loadReportMetadata() {
    var url = window.KCOMMIT_REPORT_METADATA_URL;
    if (!url) return;
    var el = document.getElementById('evaluation-details');
    // Only populate when the server-side block is empty (sidecar mode).
    // If generate_html_report() already rendered content (embedded mode),
    // the div is non-empty and we skip the fetch.
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
        // Silently ignore — evaluation details are optional
        if (typeof console !== 'undefined' && console.warn) {
          console.warn('[kcommit] Could not load report metadata:', err);
        }
      });
  }

  /* ── Per-column filters + global search ───────────────────────────────── */
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
    var tbody   = tbl.querySelector('tbody');
    var rows    = Array.from(tbody.querySelectorAll('tr'));
    var noMatch = tbl.parentElement.querySelector('.kc-no-match');
    var filterRow = tbl.querySelector('tr.kc-filters');
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
        ctrl.type = 'text'; ctrl.placeholder = 'filter\u2026';
        ctrl.setAttribute('aria-label','filter column');
      }
      th.innerHTML = '';
      th.appendChild(ctrl);
      controls.push(ctrl);
    });

    var card = tbl.closest('.kc-card');
    var globalEl = card && card.querySelector('.kc-global-filter');
    var liveCountEl = card && card.querySelector('.kc-live-count');
    var tableWrap = tbl.closest('.kc-table-wrap');
    var busyEl = tableWrap && tableWrap.querySelector('.kc-table-busy');
    var filterJob = 0;

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
          try {
            apply();
          } finally {
            if (ticket === filterJob) setBusy(false);
          }
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

  /* ── Column sort ───────────────────────────────────────────────────── */
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
          var av = a.cells[ci] ? a.cells[ci].textContent.trim() : '';
          var bv = b.cells[ci] ? b.cells[ci].textContent.trim() : '';
          var an = parseFloat(av), bn = parseFloat(bv);
          var cmp = (!isNaN(an) && !isNaN(bn)) ? an - bn : av.localeCompare(bv);
          return cmp * sortState.dir;
        }).forEach(function(r){ tbody.appendChild(r); });
      });
    });
  }

  /* ── CSV export ───────────────────────────────────────────────────── */
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

  /* ── Detail panel ────────────────────────────────────────────────────── */
  var overlay   = document.getElementById('kc-detail-overlay');
  var panel     = document.getElementById('kc-detail-panel');
  var panelH3   = document.getElementById('kc-detail-sha');
  var panelBody = document.getElementById('kc-detail-body');
  var closeBtn  = document.getElementById('kc-detail-close');

  /*
   * B: openPanel() resolution order:
   *
   *  1. Look up sha12 (and fullSha) in the in-memory store populated by
   *     loadCommitStore().  In embedded mode this always has full detail.
   *     In sidecar mode the index only has summary rows (no scoring.trace).
   *
   *  2. If the object found in the index lacks scoring detail (no
   *     scoring.trace), AND we have a fullSha AND __KC_COMMIT_DETAIL_ROOT__
   *     is set, fetch the per-commit sidecar JSON.
   *     The sidecar contains the complete commit object including
   *     scoring.trace and product_evidence.
   *
   *  3. Fall back to whatever is in the store, even if incomplete.
   */
  function openPanel(sha12, fullSha) {
    if (!overlay || !panel || !sha12) return false;
    overlay.classList.add('open');
    panel.classList.add('open');
    if (panelH3) panelH3.textContent = fullSha || sha12;
    if (panelBody) panelBody.innerHTML = '<p style="color:var(--color-text-muted,#888);font-size:.75rem">Loading\u2026</p>';

    loadCommitStore().then(function(map) {
        map = (map && typeof map === 'object') ? map : {};
        var c = map[sha12] || map[String(sha12)] || (fullSha ? map[fullSha] : null) || null;

        // B: if we have a fullSha and the sidecar root is configured, always
        // fetch the richer sidecar (it contains scoring.trace + full body).
        // We skip the sidecar fetch only when already in embedded mode (no
        // __KC_COMMIT_DETAIL_ROOT__) or when the index object already has
        // full trace data.
        var hasSidecar = !!window.__KC_COMMIT_DETAIL_ROOT__;
        var hasFullDetail = c && c.scoring && c.scoring.trace;

        if (hasSidecar && !hasFullDetail && (fullSha || sha12)) {
          return _fetchCommitSidecar(sha12, fullSha || sha12)
            .then(function(sidecar) {
              return sidecar || c;
            })
            .catch(function() { return c; }); // sidecar not found → use index data
        }
        return c;
      })
      .then(function(c) {
        renderCommit(c, fullSha || sha12);
      })
      .catch(function(err) {
        var msg = (err && err.message) ? err.message : String(err || 'unknown error');
        if (panelBody) {
          panelBody.innerHTML = field('SHA', esc(fullSha || sha12), 'mono')
            + '<p style="color:var(--color-text-muted,#888);margin-top:.75rem;font-size:.75rem">'
            + 'Unable to load commit details: ' + esc(msg) + '</p>';
        }
      });
    return true;
  }

  function closePanel() {
    if (overlay) overlay.classList.remove('open');
    if (panel)   panel.classList.remove('open');
  }

  /* D.5 fix-1: only close on backdrop click, not panel child clicks */
  if (overlay) overlay.addEventListener('click', function(e) {
    if (e.target === overlay) closePanel();
  });
  if (closeBtn) closeBtn.addEventListener('click', closePanel);
  document.addEventListener('keydown', function(e){ if (e.key === 'Escape') closePanel(); });

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

  /* A.2: render a pattern-match list as compact inline badges */
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

  /* A.2: render the full scoring trace for one profile */
  function _renderProfileTrace(pname, ptrace) {
    var html = '';
    var blocked   = ptrace.blocked;
    var mult      = ptrace.multiplier != null ? ptrace.multiplier : 1.0;
    var rawTotal  = ptrace.raw_rule_total || 0;
    var capped    = ptrace.raw_rule_total_capped || 0;
    var final     = ptrace.final_score || 0;
    var blockReason = ptrace.block_reason || '';

    // Profile header with score formula
    var formula = 'min(' + rawTotal + ',100) \u00d7 ' + (mult * 100).toFixed(0) + '% = ' + final;
    var pillCls = scoreClass(final);
    html += '<div class="kc-detail-section" style="margin-top:.5rem">';
    html += '<h4 style="display:flex;align-items:center;gap:.4rem">';
    html += '<span class="profile-chip">' + esc(pname) + '</span>';
    html += '<span class="score-pill ' + pillCls + '">' + final + '</span>';
    if (blocked) {
      html += '<span style="font-size:.7rem;color:var(--color-error,#c33);font-weight:600">\u26d4 BLOCKED</span>';
      if (blockReason) html += '<span style="font-size:.68rem;color:var(--color-text-muted,#888)">(' + esc(blockReason) + ')</span>';
    } else {
      html += '<span style="font-size:.68rem;color:var(--color-text-muted,#888)">' + esc(formula) + '</span>';
    }
    html += '</h4>';

    // Merged-pattern matches (profile-level blacklists that blocked)
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

    // Per-rule detail
    var rules = ptrace.rules || {};
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
        var rd = rules[rname] || {};
        var matched = rd.matched;
        var level   = rd.matched_level || '';
        var rScore  = rd.score || 0;
        var rWeight = rd.weight || 0;
        var matches = rd.matches || {};
        var allHits = (matches.keywords_whitelist || [])
                    .concat(matches.path_whitelist || [])
                    .concat(matches.commit_whitelist || []);
        var rowCls = matched ? 'color:var(--color-text)' : 'color:var(--color-text-faint,#aaa)';
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

  function renderCommit(c, sha) {
    if (!panelBody) return;
    if (!c) {
      panelBody.innerHTML = field('SHA', esc(sha), 'mono')
        + '<p style="color:var(--color-text-muted,#888);margin-top:.75rem;font-size:.75rem">'
        + 'No detail data available for this commit.</p>';
      return;
    }
    var sc = c.scoring || {};
    var html = '';
    html += field('SHA',    '<code>'+esc((c.commit||'').slice(0,40))+'</code>', 'mono');
    html += field('Subject', esc(c.subject || ''));
    html += field('Author',  esc((c.author_name||'')+(c.author_email?' <'+c.author_email+'>':'')));
    html += field('Date',    esc(fmtDate(c.author_time)), 'mono');
    html += field('Score',   '<span class="score-pill '+scoreClass(c.score||0)+'">'+esc(String(c.score||0))+'</span>');
    if (c.matched_profiles && c.matched_profiles.length) {
      html += field('Profiles',
        c.matched_profiles.map(function(p){
          return '<span class="profile-chip">'+esc(p)+'</span>';
        }).join(' '));
    }

    /* A.2: Full scoring trace — one section per profile */
    var traceProfiles = sc.trace && sc.trace.profiles;
    if (traceProfiles && Object.keys(traceProfiles).length) {
      html += '<div class="kc-detail-section"><h4>Scoring trace</h4>';
      html += '<p style="font-size:.7rem;color:var(--color-text-muted,#888);margin-bottom:.3rem">';
      html += 'Formula per profile: <code>min(sum_of_matched_rule_weights, 100) \u00d7 profile_multiplier</code>. '
            + 'Combined score = sum of all profile scores.';
      html += '</p>';
      Object.keys(traceProfiles).sort().forEach(function(pname) {
        html += _renderProfileTrace(pname, traceProfiles[pname] || {});
      });
      html += '</div>';
    } else if (sc.profiles && Object.keys(sc.profiles).length) {
      /* Fallback: only per-profile scores available (index row, no trace) */
      html += '<div class="kc-detail-section"><h4>Profile scores</h4>';
      Object.keys(sc.profiles).sort().forEach(function(p) {
        html += field(p, '<span class="score-pill">'+esc(String(sc.profiles[p]))+'</span>');
      });
      html += '</div>';
    }

    if (c.product_evidence && c.product_evidence.length) {
      html += '<div class="kc-detail-section"><h4>Evidence</h4>'
        + '<ul style="padding-left:1.1rem;font-size:.75rem">';
      c.product_evidence.forEach(function(p){
        html += '<li><code>'+esc(p)+'</code></li>';
      });
      html += '</ul></div>';
    }
    if (c._filter_reason) {
      html += '<div class="kc-detail-section"><h4>Filter reason</h4>'
        + field('', esc(c._filter_reason)) + '</div>';
    }
    if (c.body) {
      html += '<div class="kc-detail-section"><h4>Commit message</h4>'
        + '<pre style="white-space:pre-wrap;font-size:.72rem;max-height:220px;overflow-y:auto">'
        + esc(c.body.slice(0,3000))+(c.body.length>3000?'\n\u2026':'')
        + '</pre></div>';
    }
    panelBody.innerHTML = html;
  }

  /* D.5 fix-2: event delegation — works after filter/sort reorders rows */
  document.addEventListener('click', function(e) {
    var target = e.target;
    var a = null;
    if (target && target.closest) {
      a = target.closest('a.sha-link');
    } else {
      while (target && target !== document) {
        if (target.tagName && target.tagName.toLowerCase() === 'a' && /(^|\s)sha-link(\s|$)/.test(target.className || '')) {
          a = target;
          break;
        }
        target = target.parentNode;
      }
    }
    if (!a) return;
    if (e.preventDefault) e.preventDefault();
    if (e.stopPropagation) e.stopPropagation();
    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
    /* B: pass both sha12 and fullSha so openPanel can fetch the sidecar.
     * v13: use getAttribute() inline so Firefox getAttribute fallback path
     * is exercised; dataset access is kept as secondary fallback. */
    var sha12   = a.getAttribute('data-sha') || (a.dataset && a.dataset.sha) || '';
    var fullSha = a.getAttribute('data-full-sha') || (a.dataset && a.dataset.fullSha) || sha12;
    openPanel(a.getAttribute('data-sha') || sha12, fullSha);
    return false;
  }, true);


  /* ── Theme toggle ────────────────────────────────────────────────────── */
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

  /* ── Bootstrap ────────────────────────────────────────────────────── */
  document.querySelectorAll('table.kc-table').forEach(function(tbl) {
    initTable(tbl);
    initSort(tbl);
    initCsvExport(tbl);
  });

  // A.5 / D.14: load evaluation metadata from sidecar after DOM is ready
  loadReportMetadata();

})();
