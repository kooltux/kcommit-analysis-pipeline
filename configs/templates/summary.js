/* kcommit-analysis-pipeline — table autofilter, column sort, commit detail panel */
(function () {
  'use strict';

  /* ── Autofilter ──────────────────────────────────────────────────────── */
  function initFilters(table) {
    var filterRow = table.querySelector('tr.kc-filters');
    if (!filterRow) return;
    var inputs = Array.from(filterRow.querySelectorAll('input'));
    var rows   = Array.from(table.tBodies[0].rows);
    var noMatch = table.closest('.kc-card')
                       .querySelector('.kc-no-match');

    function applyFilters() {
      var terms = inputs.map(function (inp) {
        return inp.value.trim().toLowerCase();
      });
      var visible = 0;
      rows.forEach(function (row) {
        var cells = Array.from(row.cells);
        var show  = terms.every(function (t, i) {
          if (!t) return true;
          var cell = cells[i];
          return cell && cell.textContent.toLowerCase().indexOf(t) !== -1;
        });
        row.classList.toggle('hidden', !show);
        if (show) visible++;
      });
      if (noMatch) noMatch.style.display = visible === 0 ? 'block' : 'none';
    }

    inputs.forEach(function (inp) {
      inp.addEventListener('input', applyFilters);
    });

    /* clear-all button */
    var bar = table.closest('.kc-card').querySelector('.kc-filter-bar button');
    if (bar) {
      bar.addEventListener('click', function () {
        inputs.forEach(function (inp) { inp.value = ''; });
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
          if (si) si.textContent = '⇅';
        });
        th.dataset.sortDir = dir;
        th.classList.add('sorted-' + dir);
        var si = th.querySelector('.sort-icon');
        if (si) si.textContent = dir === 'asc' ? '▲' : '▼';

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
    body.innerHTML = '<div id="kc-detail-spinner">Loading…</div>';

    /* Try to load from output/<sha>.json relative to this HTML file */
    var base = (document.currentScript || {src: ''}).src;
    /* Prefer same-directory output/ folder */
    var urls = [
      './output/' + sha + '.json',
      '../output/' + sha + '.json',
      'output/' + sha + '.json'
    ];

    function tryNext(idx) {
      if (idx >= urls.length) {
        renderCommit(null, sha);
        return;
      }
      fetch(urls[idx])
        .then(function (r) {
          if (!r.ok) throw new Error(r.status);
          return r.json();
        })
        .then(function (data) { renderCommit(data, sha); })
        .catch(function () { tryNext(idx + 1); });
    }
    tryNext(0);
  }

  function closePanel() {
    if (!overlay || !panel) return;
    overlay.classList.remove('open');
    panel.classList.remove('open');
  }

  if (closeBtn)  closeBtn.addEventListener('click',  closePanel);
  if (overlay)   overlay.addEventListener('click',   closePanel);

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closePanel();
  });

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
        + 'Commit detail file not found.<br>'
        + 'Place <code>output/' + esc(sha) + '.json</code> next to this HTML file.</p>';
      return;
    }
    var score = c.score || 0;
    var sc    = c.scoring || {};
    var html  = '';
    html += field('SHA',     '<code>' + esc((c.commit||'').slice(0,40)) + '</code>', 'mono');
    html += field('Subject', esc(c.subject || ''), '');
    html += field('Author',  esc((c.author_name||'') + ' &lt;' + (c.author_email||'') + '&gt;'), '');
    html += field('Date',    esc(c.author_time || ''), 'mono');
    html += field('Score',   '<span class="score-pill ' + scoreClass(score) + '">' + score + '</span>', '');

    if (c.matched_profiles && c.matched_profiles.length) {
      html += field('Profiles',
        c.matched_profiles.map(function(p){ return '<span class="profile-chip">'+esc(p)+'</span>'; }).join(' '));
    }

    /* Scoring breakdown — profile-based (no legacy sub-score keys) */
    var profiles_sc = (sc && sc.profiles) ? sc.profiles : null;
    if (profiles_sc && Object.keys(profiles_sc).length) {
      html += '<div class="kc-detail-section"><h4>Profile scores</h4>';
      Object.keys(profiles_sc).sort().forEach(function(p) {
        var v = profiles_sc[p];
        html += field(p, '<span class="score-pill">' + esc(String(v)) + '</span>');
      });
      html += '</div>';
    } else if (sc && Object.keys(sc).length) {
      /* Fallback: render whatever scoring keys exist */
      html += '<div class="kc-detail-section"><h4>Scoring breakdown</h4>';
      Object.keys(sc).forEach(function(k) {
        if (k === 'profiles') return; /* already rendered above */
        var v = sc[k];
        if (typeof v === 'object' && v !== null) {
          html += field(k, '<pre>' + esc(JSON.stringify(v, null, 2)) + '</pre>');
        } else {
          html += field(k, esc(String(v)), 'mono');
        }
      });
      html += '</div>';
    }

    /* Product evidence */
    if (c.product_evidence && c.product_evidence.length) {
      html += '<div class="kc-detail-section"><h4>Product evidence</h4>';
      html += '<ul style="padding-left:1rem">';
      c.product_evidence.forEach(function(p){
        html += '<li><code>' + esc(p) + '</code></li>';
      });
      html += '</ul></div>';
    }

    /* Body excerpt */
    if (c.body) {
      html += '<div class="kc-detail-section"><h4>Commit message body</h4>'
        + '<pre style="max-height:180px;overflow-y:auto">' + esc(c.body.slice(0,2000))
        + (c.body.length > 2000 ? '\n…' : '') + '</pre></div>';
    }

    body.innerHTML = html;
  }

  /* ── SHA link wiring ─────────────────────────────────────────────────── */
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
