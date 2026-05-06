/* kcommit-analysis-pipeline — table autofilter, column sort, commit detail panel */
(function () {
  'use strict';

  /* ── Autofilter ──────────────────────────────────────────────────────── */

  /* Columns with at most this many distinct values get a multiselect dropdown
     instead of a free-text input.  Adjust to taste. */
  var MULTISELECT_THRESHOLD = 20;

  function getDistinctValues(rows, colIdx) {
    var seen = Object.create(null);
    var vals = [];
    rows.forEach(function (row) {
      var cell = row.cells[colIdx];
      var text = cell ? cell.textContent.trim() : '';
      /* Split on '; ' to handle multi-value cells (profiles, evidence) */
      var parts = text ? text.split(/;\s*/) : [''];
      parts.forEach(function (p) {
        p = p.trim();
        if (p && !seen[p]) { seen[p] = true; vals.push(p); }
      });
    });
    vals.sort(function (a, b) { return a.localeCompare(b); });
    return vals;
  }

  function buildMultiselect(vals) {
    var sel = document.createElement('select');
    sel.multiple = true;
    sel.setAttribute('aria-label', 'filter column');
    sel.className = 'kc-ms';
    /* "All" option — selecting it means no filter */
    var allOpt = document.createElement('option');
    allOpt.value    = '__all__';
    allOpt.text     = '(all)';
    allOpt.selected = true;
    sel.appendChild(allOpt);
    vals.forEach(function (v) {
      var o = document.createElement('option');
      o.value = v; o.text = v;
      sel.appendChild(o);
    });
    return sel;
  }

  function initFilters(table) {
    var filterRow = table.querySelector('tr.kc-filters');
    if (!filterRow) return;
    var filterCells = Array.from(filterRow.querySelectorAll('th'));
    var rows        = Array.from(table.tBodies[0].rows);
    var noMatch     = table.closest('.kc-card')
                           .querySelector('.kc-no-match');

    /* For each column decide: multiselect or free-text */
    var controls = filterCells.map(function (th, colIdx) {
      var distinct = getDistinctValues(rows, colIdx);
      if (distinct.length > 0 && distinct.length <= MULTISELECT_THRESHOLD) {
        var sel = buildMultiselect(distinct);
        th.innerHTML = '';
        th.appendChild(sel);
        return { type: 'multi', el: sel };
      } else {
        /* Keep or create a text input */
        var inp = th.querySelector('input') || (function () {
          var i = document.createElement('input');
          i.type = 'text'; i.placeholder = 'filter\u2026';
          i.setAttribute('aria-label', 'filter column');
          th.innerHTML = ''; th.appendChild(i); return i;
        }());
        return { type: 'text', el: inp };
      }
    });

    /* ── Smart match helpers ───────────────────────────────────────────── */

    /* Convert a glob pattern (foo*, *bar, fo?b) to a RegExp. */
    function globToRe(pat) {
      var escaped = pat.replace(/[.+^${}()|[\]\\]/g, '\\$&')
                       .replace(/\*/g, '.*')
                       .replace(/\?/g, '.');
      return new RegExp('^' + escaped + '$', 'i');
    }

    /* Parse a numeric expression: >N <N >=N <=N =N !N
       Returns a function(cellNum) → bool, or null if not a numeric expr. */
    function numericMatcher(term) {
      var m = term.match(/^(>=|<=|>|<|=|!)\s*(-?[\d.]+)$/);
      if (!m) return null;
      var op  = m[1];
      var val = parseFloat(m[2]);
      return function(n) {
        switch(op) {
          case '>':  return n >  val;
          case '<':  return n <  val;
          case '>=': return n >= val;
          case '<=': return n <= val;
          case '=':  return n === val;
          case '!':  return n !== val;
        }
        return true;
      };
    }

    /* Match a single raw cell text against a term string.
       Numeric operators take priority; then glob (*/?); then substring. */
    function matchText(cellText, term) {
      if (!term) return true;
      term = term.trim();
      if (!term) return true;
      var numFn = numericMatcher(term);
      if (numFn !== null) {
        var n = parseFloat(cellText);
        if (isNaN(n)) return false;
        return numFn(n);
      }
      if (term.indexOf('*') !== -1 || term.indexOf('?') !== -1) {
        return globToRe(term).test(cellText);
      }
      return cellText.toLowerCase().indexOf(term.toLowerCase()) !== -1;
    }

    function applyFilters() {
      var visible = 0;
      rows.forEach(function (row) {
        var cells = Array.from(row.cells);
        var show  = controls.every(function (ctrl, i) {
          var cell = cells[i];
          var cellText = cell ? cell.textContent.trim() : '';
          if (ctrl.type === 'text') {
            var term = ctrl.el.value.trim();
            return !term || matchText(cellText, term);
          } else {
            /* multiselect: pass if (all) selected or any selected value matches */
            var opts = Array.from(ctrl.el.selectedOptions);
            if (!opts.length) return true;
            if (opts.some(function (o) { return o.value === '__all__'; })) return true;
            var selected = opts.map(function (o) { return o.value; });
            /* cell may contain multiple values separated by '; ' */
            var cellParts = cellText ? cellText.split(/;\s*/) : [];
            return selected.some(function (s) {
              return cellParts.some(function (p) {
                return p.trim() === s;
              });
            });
          }
        });
        row.classList.toggle('hidden', !show);
        if (show) visible++;
      });
      if (noMatch) noMatch.style.display = visible === 0 ? 'block' : 'none';
    }

    controls.forEach(function (ctrl) {
      var evt = ctrl.type === 'multi' ? 'change' : 'input';
      ctrl.el.addEventListener(evt, applyFilters);
    });

    /* clear-all button */
    var bar = table.closest('.kc-card').querySelector('.kc-filter-bar button');
    if (bar) {
      bar.addEventListener('click', function () {
        controls.forEach(function (ctrl) {
          if (ctrl.type === 'text') {
            ctrl.el.value = '';
          } else {
            /* reset to (all) */
            Array.from(ctrl.el.options).forEach(function (o) {
              o.selected = o.value === '__all__';
            });
          }
        });
        applyFilters();
      });
    }
  }

  /* ── Column sort ─────────────────────────────────────────────────────── */
  function initSort(table) {
    var headerRow = table.querySelector('tr.kc-col-headers');
    if (!headerRow) return;
    var ths  = Array.from(headerRow.cells);
    var body = table.tBodies[0];

    ths.forEach(function (th, colIdx) {
      th.dataset.sortDir = '';
      th.addEventListener('click', function () {
        var dir = th.dataset.sortDir === 'asc' ? 'desc' : 'asc';
        ths.forEach(function (h) {
          h.dataset.sortDir = '';
          h.classList.remove('sorted-asc', 'sorted-desc');
          var si = h.querySelector('.sort-icon');
          if (si) si.textContent = '\u21c5';
        });
        th.dataset.sortDir = dir;
        th.classList.add('sorted-' + dir);
        var si = th.querySelector('.sort-icon');
        if (si) si.textContent = dir === 'asc' ? '\u25b2' : '\u25bc';

        var rows = Array.from(body.rows);
        rows.sort(function (a, b) {
          var av = a.cells[colIdx] ? a.cells[colIdx].textContent.trim() : '';
          var bv = b.cells[colIdx] ? b.cells[colIdx].textContent.trim() : '';
          var an = parseFloat(av), bn = parseFloat(bv);
          if (!isNaN(an) && !isNaN(bn)) return dir === 'asc' ? an - bn : bn - an;
          return dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
        });
        rows.forEach(function (r) { body.appendChild(r); });
      });
    });
  }

  /* ── Detail panel ────────────────────────────────────────────────────── */
  var overlay = document.getElementById('kc-detail-overlay');
  var panel   = document.getElementById('kc-detail-panel');
  var panelH3 = document.getElementById('kc-detail-sha');
  var body    = document.getElementById('kc-detail-body');
  var closeBtn= document.getElementById('kc-detail-close');

  function openPanel(sha) {
    if (!overlay || !panel) return;
    overlay.classList.add('open');
    panel.classList.add('open');
    if (panelH3) panelH3.textContent = sha;
    body.innerHTML = '';

    /* Inline data map injected at report-generation time */
    var map = (typeof window.__KC_COMMITS__ === 'object' && window.__KC_COMMITS__)
              ? window.__KC_COMMITS__ : {};
    var commit = map[sha] || null;
    renderCommit(commit, sha);
  }

  function closePanel() {
    if (!overlay || !panel) return;
    overlay.classList.remove('open');
    panel.classList.remove('open');
  }

  if (closeBtn) closeBtn.addEventListener('click',  closePanel);
  if (overlay)  overlay.addEventListener('click',   closePanel);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closePanel(); });

  function scoreClass(s) {
    s = parseFloat(s) || 0;
    if (s >= 70) return 'score-hi';
    if (s >= 30) return 'score-mid';
    return 'score-low';
  }

  function esc(s) {
    return String(s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function field(label, value, cls) {
    return '<div class="kc-detail-field">'
      + '<div class="field-label">' + esc(label) + '</div>'
      + '<div class="field-value' + (cls ? ' ' + cls : '') + '">' + value + '</div>'
      + '</div>';
  }

  function renderCommit(c, sha) {
    if (!c) {
      body.innerHTML = field('SHA', esc(sha), 'mono')
        + '<p style="color:var(--text-muted);margin-top:1rem;font-size:.75rem">'
        + 'Commit detail not found in inline data.</p>';
      return;
    }
    var score = c.score || 0;
    var sc    = c.scoring || {};
    var html  = '';
    html += field('SHA',     '<code>' + esc((c.commit||'').slice(0,40)) + '</code>', 'mono');
    html += field('Subject', esc(c.subject || ''));
    html += field('Author',  esc((c.author_name||'') + ' <' + (c.author_email||'') + '>'));
    html += field('Date',    esc(c.author_time || ''), 'mono');
    html += field('Score',   '<span class="score-pill ' + scoreClass(score) + '">' + score + '</span>');

    if (c.matched_profiles && c.matched_profiles.length) {
      html += field('Profiles',
        c.matched_profiles.map(function(p){ return '<span class="profile-chip">'+esc(p)+'</span>'; }).join(' '));
    }

    var profiles_sc = (sc && sc.profiles) ? sc.profiles : null;
    if (profiles_sc && Object.keys(profiles_sc).length) {
      html += '<div class="kc-detail-section"><h4>Profile scores</h4>';
      Object.keys(profiles_sc).sort().forEach(function(p) {
        html += field(p, '<span class="score-pill">' + esc(String(profiles_sc[p])) + '</span>');
      });
      html += '</div>';
    }

    if (c.product_evidence && c.product_evidence.length) {
      html += '<div class="kc-detail-section"><h4>Product evidence</h4><ul style="padding-left:1rem">';
      c.product_evidence.forEach(function(p){ html += '<li><code>' + esc(p) + '</code></li>'; });
      html += '</ul></div>';
    }

    if (c.body) {
      html += '<div class="kc-detail-section"><h4>Commit message body</h4>'
        + '<pre style="max-height:180px;overflow-y:auto">' + esc(c.body.slice(0,2000))
        + (c.body.length > 2000 ? '\n\u2026' : '') + '</pre></div>';
    }

    body.innerHTML = html;
  }

  function initShaLinks() {
    document.querySelectorAll('a.sha-link').forEach(function (a) {
      a.addEventListener('click', function (e) {
        e.preventDefault();
        openPanel(a.dataset.sha);
      });
    });
  }

  /* ── Bootstrap ───────────────────────────────────────────────────────── */
  document.querySelectorAll('table.kc-table').forEach(function (tbl) {
    initFilters(tbl);
    initSort(tbl);
  });
  initShaLinks();

})();
