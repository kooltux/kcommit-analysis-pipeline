/* kcommit-analysis-pipeline — filter/sort/export + commit detail panel */
(function () {
  'use strict';

  /* ── Helpers ──────────────────────────────────────────────────────────── */
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

  function loadCommitStore() {
    if (window.__KC_COMMITS__) return Promise.resolve(window.__KC_COMMITS__);
    if (window.__KC_COMMITS_COMPRESSED__ && window.__KC_COMMITS_COMPRESSION__ === 'zlib' && typeof DecompressionStream !== 'undefined') {
      var ds = new DecompressionStream('deflate');
      var blob = new Blob([b64ToBytes(window.__KC_COMMITS_COMPRESSED__)]);
      return new Response(blob.stream().pipeThrough(ds)).text().then(function(txt){
        window.__KC_COMMITS__ = JSON.parse(txt);
        return window.__KC_COMMITS__;
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

  /* ── Per-column filters + global search ──────────────────────────────── */
  var MULTISELECT_MAX = 20;

  function distinctVals(rows, ci) {
    var seen = Object.create(null), vals = [];
    rows.forEach(function(r) {
      var text = r.cells[ci] ? r.cells[ci].textContent.trim() : '';
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

    var controls = [];
    Array.from(filterRow.querySelectorAll('th')).forEach(function(th, ci) {
      var vals = distinctVals(rows, ci);
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
      var visible = 0;
      rows.forEach(function(row) {
        var cells = Array.from(row.cells);
        var colOk = colFilters.every(function(f, ci) {
          if (!f) return true;
          var text = cells[ci] ? cells[ci].textContent.trim().toLowerCase() : '';
          if (Array.isArray(f)) return f.some(function(v){ return text.includes(v); });
          return f.split(/\s+/).every(function(tok){ return matchesToken(text, tok); });
        });
        var glOk = !global || cells.some(function(c){
          return c.textContent.toLowerCase().includes(global);
        });
        var show = colOk && glOk;
        row.classList.toggle('hidden', !show);
        if (show) visible++;
      });
      if (noMatch) noMatch.classList.toggle('visible', visible === 0);
    }

    controls.forEach(function(c) {
      c.addEventListener(c.tagName === 'SELECT' ? 'change' : 'input', apply);
    });
    if (globalEl) globalEl.addEventListener('input', apply);

    var clearBtn = card && card.querySelector('.kc-filter-bar button');
    if (clearBtn) clearBtn.addEventListener('click', function() {
      controls.forEach(function(c) {
        if (c.tagName === 'SELECT') {
          Array.from(c.options).forEach(function(o){ o.selected = o.value === '__all__'; });
        } else { c.value = ''; }
      });
      if (globalEl) globalEl.value = '';
      apply();
    });
  }

  /* ── Column sort ──────────────────────────────────────────────────────── */
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

  /* ── CSV export ───────────────────────────────────────────────────────── */
  function initCsvExport(tbl) {
    var card = tbl.closest('.kc-card');
    if (!card) return;
    var bar = card.querySelector('.kc-filter-bar');
    if (!bar) return;
    var btn = document.createElement('button');
    btn.textContent = '\u2193 CSV'; btn.title = 'Export visible rows as CSV';
    bar.appendChild(btn);
    btn.addEventListener('click', function() {
      var hdrs = Array.from(tbl.querySelectorAll('tr.kc-col-headers th'))
        .map(function(th){ return '"'+th.textContent.replace(/[⇅▲▼]/g,'').trim().replace(/"/g,'""')+'"'; });
      var lines = [hdrs.join(',')];
      Array.from(tbl.querySelectorAll('tbody tr:not(.hidden)')).forEach(function(r) {
        lines.push(Array.from(r.cells).map(function(td){
          return '"'+td.textContent.trim().replace(/"/g,'""')+'"';
        }).join(','));
      });
      var blob = new Blob([lines.join('\r\n')], {type:'text/csv'});
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = 'kcommit-export.csv';
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(function(){ URL.revokeObjectURL(a.href); }, 10000);
    });
  }

  /* ── Detail panel ─────────────────────────────────────────────────────── */
  var overlay   = document.getElementById('kc-detail-overlay');
  var panel     = document.getElementById('kc-detail-panel');
  var panelH3   = document.getElementById('kc-detail-sha');
  var panelBody = document.getElementById('kc-detail-body');
  var closeBtn  = document.getElementById('kc-detail-close');

  function openPanel(sha) {
    if (!overlay || !panel) return;
    overlay.classList.add('open');
    panel.classList.add('open');
    if (panelH3) panelH3.textContent = sha;
    if (panelBody) panelBody.innerHTML = '';
    var map = (window.__KC_COMMITS__ && typeof window.__KC_COMMITS__ === 'object')
              ? window.__KC_COMMITS__ : {};
    renderCommit(map[sha] || null, sha);
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

  function renderCommit(c, sha) {
    if (!panelBody) return;
    if (!c) {
      panelBody.innerHTML = field('SHA', esc(sha), 'mono')
        + '<p style="color:var(--text-muted);margin-top:.75rem;font-size:.75rem">'
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
    if (sc.profiles && Object.keys(sc.profiles).length) {
      html += '<div class="kc-detail-section"><h4>Profile scores</h4>';
      Object.keys(sc.profiles).sort().forEach(function(p) {
        html += field(p, '<span class="score-pill">'+esc(String(sc.profiles[p]))+'</span>');
      });
      html += '</div>';
    }
    if (c.product_evidence && c.product_evidence.length) {
      html += '<div class="kc-detail-section"><h4>Product evidence</h4>'
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
    var a = e.target.closest && e.target.closest('a.sha-link');
    if (a) { e.preventDefault(); openPanel(a.dataset.sha); }
  });

  /* ── Bootstrap ────────────────────────────────────────────────────────── */
  document.querySelectorAll('table.kc-table').forEach(function(tbl) {
    initTable(tbl);
    initSort(tbl);
    initCsvExport(tbl);
  });

})();
