"""HTML report generator for kcommit-analysis-pipeline.

v8.11 changes vs v8.10:
  - Analysis date injected into <title> and page header subtitle.
  - Full visual redesign: Satoshi font (Fontshare CDN), gradient header,
    card hover shadows, dark/light mode toggle (persisted in localStorage).
  - Score columns redesigned: Security/Performance/Product/Stable direct-score
    columns removed (those dimensions no longer contribute to the score in v8.11).
    Replaced by a single Flags column showing CVE / Fix / Stable / Perf badges
    derived from commit['scoring']['meta'].
  - 4-band score badge colouring: critical (>=300), high (>=150), medium (>=50),
    low (<50) — replacing the old 2-band sh/sm/sl scheme.
  - Profile tags styled with teal accent; badges visually distinct from tags.
  - Stat cards show filter stats (total scored, filtered, kept) when available.
  - CSS override path key renamed from 'summary_css' to 'css_override';
    'summary_css' still accepted as a fallback for backward compatibility.
"""
import html as _html
import json
import os
import time

from lib.config   import load_json
from lib.manifest import VERSION


_CSS = """
@import url('https://api.fontshare.com/v2/css?f[]=satoshi@400,500,600,700&display=swap');

:root {
  --bg:      #f7f6f2; --surf:   #ffffff; --surf2:  #f1f0ec; --surf3: #e8e6e1;
  --pri:     #01696f; --pri-d:  #0a4e53; --pri-hi: rgba(1,105,111,.09);
  --txt:     #1a1a1a; --mut:    #6b7280; --faint:  #9ca3af;
  --bdr:     rgba(0,0,0,.09); --bdr2: rgba(0,0,0,.05);
  --shd-sm:  0 1px 3px rgba(0,0,0,.07),0 1px 2px rgba(0,0,0,.04);
  --shd-md:  0 4px 14px rgba(0,0,0,.09),0 2px 4px rgba(0,0,0,.05);
  --shd-lg:  0 12px 32px rgba(0,0,0,.11),0 4px 8px rgba(0,0,0,.05);
  --r:       .6rem;  --r-sm: .35rem;  --r-lg: 1rem;
  --c-crit: #dc2626; --c-high: #d97706; --c-med: #b45309; --c-low: #6b7280;
  --trans:   180ms cubic-bezier(.16,1,.3,1);
}
[data-theme=dark] {
  --bg:#171614; --surf:#1c1b19; --surf2:#242320; --surf3:#2c2a27;
  --pri:#4f98a3; --pri-d:#1a626b; --pri-hi:rgba(79,152,163,.1);
  --txt:#d4d3d0; --mut:#7a7977; --faint:#4a4946;
  --bdr:rgba(255,255,255,.08); --bdr2:rgba(255,255,255,.04);
  --shd-sm:0 1px 3px rgba(0,0,0,.3); --shd-md:0 4px 14px rgba(0,0,0,.4);
  --shd-lg:0 12px 32px rgba(0,0,0,.5);
  --c-crit:#f87171; --c-high:#fbbf24; --c-med:#f59e0b; --c-low:#9ca3af;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth;-webkit-font-smoothing:antialiased}
body{font-family:'Satoshi','Segoe UI',system-ui,sans-serif;
     background:var(--bg);color:var(--txt);font-size:14px;line-height:1.55}
/* -- Inline flags (kernel commit annotations: CVE / Fix / Stable / Syzbot) -- */
.flag{display:inline-flex;align-items:center;padding:.08rem .36rem;
  border-radius:var(--r-sm);font-size:.63rem;font-weight:700;
  letter-spacing:.04em;margin:.1rem .1rem 0 0;white-space:nowrap}
.flag-cve{background:rgba(220,38,38,.08);color:#dc2626;
          border:1px solid rgba(220,38,38,.2)}
.flag-fix{background:rgba(3,105,161,.08);color:#0369a1;
          border:1px solid rgba(3,105,161,.2)}
.flag-stb{background:rgba(5,150,105,.08);color:#059669;
          border:1px solid rgba(5,150,105,.2)}
.flag-syb{background:rgba(161,87,5,.08);color:#a15705;
          border:1px solid rgba(161,87,5,.2)}/* .flag-perf removed: performance is an analysis category -- use profile tags */
/* ── Profile tags ── */
.pt{display:inline-block;background:var(--pri-hi);color:var(--pri);
    border-radius:var(--r-sm);padding:.1rem .38rem;font-size:.64rem;
    margin:.1rem .1rem 0 0;font-weight:500;
    border:1px solid rgba(1,105,111,.15)}
/* ── Section headings ── */
h2.sec{font-size:.88rem;font-weight:600;margin:1.4rem 0 .55rem;
       color:var(--txt);display:flex;align-items:center;gap:.5rem}
h2.sec::after{content:'';flex:1;height:1px;background:var(--bdr)}
/* ── Profile summary table ── */
.ptbl{width:auto;border-collapse:collapse;background:var(--surf);
  border:1px solid var(--bdr);border-radius:var(--r);overflow:hidden;
  box-shadow:var(--shd-sm);margin-bottom:1.5rem}
.ptbl th{background:var(--surf2);padding:.45rem .7rem;font-size:.68rem;
  font-weight:600;text-transform:uppercase;letter-spacing:.055em;color:var(--mut)}
.ptbl td{padding:.45rem .7rem;border-top:1px solid var(--bdr2);font-size:.8rem;
         font-variant-numeric:tabular-nums}
.ptbl tr:hover td{background:var(--pri-hi)}
/* ── Footer ── */
footer{text-align:center;padding:1.3rem;color:var(--faint);font-size:.69rem;
  border-top:1px solid var(--bdr);margin-top:.5rem}
/* ── Responsive ── */
@media(max-width:640px){
  .wrap{padding:1rem .75rem}
  .cards{grid-template-columns:repeat(2,1fr)}
  header{padding:.9rem 1rem}
}
"""

_JS = r"""
(function(){
  'use strict';

  /* ── Dark/light toggle ───────────────────────────────────────────────── */
  var root = document.documentElement;
  var tgl  = document.getElementById('themetgl');
  var stored;
  try { stored = localStorage.getItem('kc-theme'); } catch(e) {}
  var dark = stored ? stored === 'dark'
                    : matchMedia('(prefers-color-scheme:dark)').matches;
  function applyTheme(d) {
    dark = d;
    root.setAttribute('data-theme', d ? 'dark' : 'light');
    if (tgl) tgl.textContent = d ? '\u2600 Light' : '\u25d0 Dark';
    try { localStorage.setItem('kc-theme', d ? 'dark' : 'light'); } catch(e) {}
  }
  applyTheme(dark);
  if (tgl) tgl.addEventListener('click', function(){ applyTheme(!dark); });

  /* ── Table filter + sort ─────────────────────────────────────────────── */
  var tbl = document.getElementById('ctbl');
  if (!tbl) return;
  var tb   = tbl.querySelector('tbody');
  var fi   = [].slice.call(tbl.querySelectorAll('tr.fr input[data-col]'));
  var gi   = document.getElementById('gsearch');
  var st   = document.getElementById('fstat');
  var rows = [].slice.call(tb.querySelectorAll('tr.dr'));
  var sc   = -1, sd = 0;

  function nm(t, f) {
    var v = parseFloat(t); if (isNaN(v)) return t.includes(f);
    var m = f.match(/^([><=!]{1,2})\s*(-?\d+(?:\.\d+)?)$/);
    if (!m) return t.includes(f);
    var n = parseFloat(m[2]), op = m[1];
    if (op==='>') return v>n; if (op==='>=') return v>=n;
    if (op==='<') return v<n; if (op==='<=') return v<=n;
    if (op==='!='||op==='<>') return v!==n; return v===n;
  }

  function go() {
    var gv = gi ? gi.value.trim().toLowerCase() : '', vis = 0;
    rows.forEach(function(r) {
      var cs = [].slice.call(r.querySelectorAll('td'));
      var ok = fi.every(function(inp) {
        var v = inp.value.trim().toLowerCase(); if (!v) return true;
        var c = cs[+inp.dataset.col]; if (!c) return true;
        var t = c.textContent.trim().toLowerCase();
        return inp.dataset.num ? nm(t,v) : t.includes(v);
      }) && (!gv || cs.some(function(c){
        return c.textContent.toLowerCase().includes(gv);
      }));
      r.classList.toggle('hi', !ok); if (ok) vis++;
    });
    if (st) st.textContent = 'Showing ' + vis + ' of ' + rows.length +
                             ' commit' + (rows.length !== 1 ? 's' : '');
  }

  function sortBy(ci, num) {
    if (sc === ci) { sd = sd===1 ? -1 : sd===-1 ? 0 : 1; }
    else           { sc = ci; sd = 1; }
    var ths = [].slice.call(tbl.querySelectorAll('thead tr:first-child th'));
    ths.forEach(function(h){ h.classList.remove('asc','desc'); });
    if (sd !== 0) {
      var h = ths[ci]; if (h) h.classList.add(sd===1 ? 'asc' : 'desc');
    }
    if (sd === 0) { go(); return; }
    rows.slice().sort(function(a,b){
      var ta = ((a.querySelectorAll('td')[ci])||{textContent:''}).textContent.trim();
      var tb2= ((b.querySelectorAll('td')[ci])||{textContent:''}).textContent.trim();
      var cmp= num ? (parseFloat(ta)||0)-(parseFloat(tb2)||0) : ta.localeCompare(tb2);
      return sd * cmp;
    }).forEach(function(r){ tb.appendChild(r); });
    go();
  }

  fi.forEach(function(i){ i.addEventListener('input', go); });
  if (gi) gi.addEventListener('input', go);
  [].slice.call(tbl.querySelectorAll('thead tr:first-child th.sort')).forEach(function(th){
    var ci = +th.dataset.col, num = th.dataset.num === '1';
    th.addEventListener('click', function(){ sortBy(ci, num); });
  });
  go();
})();
"""

_LOGO_SVG = (
    '<svg class="hdr-logo" width="34" height="34" viewBox="0 0 34 34" '
    'fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    '<rect width="34" height="34" rx="7" fill="rgba(255,255,255,.15)"/>'
    '<path d="M7 17 L13 11 L13 23 Z" fill="white" opacity=".95"/>'
    '<path d="M15 9.5 L27 9.5 L27 12.5 L15 12.5 Z" fill="white"/>'
    '<path d="M15 15.5 L23 15.5 L23 18.5 L15 18.5 Z" fill="white" opacity=".72"/>'
    '<path d="M15 21.5 L25 21.5 L25 24.5 L15 24.5 Z" fill="white" opacity=".48"/>'
    '</svg>'
)


def _e(s):
    return _html.escape(str(s or ''))


def _sc(v):
    """Return CSS class for score badge based on 4-band threshold."""
    if v >= 300: return 'sc'   # critical
    if v >= 150: return 'sh'   # high
    if v >= 50:  return 'sm'   # medium
    return 'sl'                 # low


# Controls which commit meta keys get a badge and how they look.
# Extend this list to add new kernel annotation badges without
# touching any other report code.
_FLAG_DEFS = [
    ('has_cve',       'CVE',    'flag-cve'),
    ('is_fix',        'Fix',    'flag-fix'),
    ('has_stable_cc', 'Stable', 'flag-stb'),
    ('has_syzbot',    'Syzbot', 'flag-syb'),
]

# Human-readable labels for meta-flag KPI cards.
_META_CARD_LABELS = [
    ('has_cve',       'CVE references'),
    ('is_fix',        'Fixes: tags'),
    ('has_stable_cc', 'Stable CC'),
    ('has_syzbot',    'Syzbot'),
]


def _flags(commit):
    """Build inline flag badges from commit['meta'] (kernel annotations only).

    Analysis categories (security, performance) are shown via profile tags,
    not here.  Add entries to _FLAG_DEFS to expose additional meta keys.
    """
    meta = (commit.get('meta')
            or (commit.get('scoring') or {}).get('meta')
            or commit.get('stable_hints')   # backward compat
            or {})
    return ''.join(
        f'<span class="flag {cls}">{label}</span>'
        for key, label, cls in _FLAG_DEFS
        if meta.get(key)
    )




# Table column definitions: (label, is_numeric, is_sortable)
# Order must match the cells emitted in the data-rows loop below.
_COLS = [
    ('#',        True,  True),   # rank
    ('Commit',   False, False),  # SHA
    ('Subject',  False, True),   # subject
    ('Score',    True,  True),   # score badge
    ('Flags',    False, False),  # CVE/Fix/Stable/Syzbot badges
    ('Profiles', False, False),  # matched profile tags
]

def generate_html_report(work_dir, cfg):
    outdir    = os.path.join(work_dir, 'output')
    scored    = load_json(os.path.join(outdir, 'relevant_commits.json'), default=[]) or []
    stats     = load_json(os.path.join(outdir, 'report_stats.json'),    default={}) or {}
    p_summary = load_json(os.path.join(outdir, 'profile_summary.json'), default={}) or {}

    tmpl   = cfg.get('templates', {}) or {}
    top_n  = int(tmpl.get('top_n', 100) or 100)
    title  = _e(tmpl.get('report_title', 'kcommit Analysis Report'))
    ts     = time.strftime('%Y-%m-%d %H:%M')
    cov          = stats.get('profile_coverage', {}) or {}
    filter_stats = stats.get('filter_stats', {}) or {}
    thr    = stats.get('min_score_threshold', 0) or 0

    # ── CSS override (accepts both 'css_override' and legacy 'summary_css') ──
    css_extra = ''
    css_path  = tmpl.get('css_override') or tmpl.get('summary_css')
    if css_path:
        meta = cfg.get('_meta', {}) or {}
        if not os.path.isabs(css_path):
            css_path = os.path.join(meta.get('config_dir', ''), css_path)
        if os.path.exists(css_path):
            with open(css_path, encoding='utf-8') as f:
                css_extra = f.read()

    # ── KPI stat cards (fully dynamic -- no hardcoded category names) ─────
    card_defs = [
        ('Commits scored', stats.get('total_scored_commits', len(scored))),
    ]
    if filter_stats.get('dropped', 0):
        card_defs.append(('Pre-filtered out', filter_stats['dropped']))
        card_defs.append(('Kept for scoring', filter_stats.get('kept', '-')))
    # One card per active profile (profile names come from data, not code)
    for pname, cnt in sorted((stats.get('per_profile_counts') or {}).items()):
        card_defs.append((pname.replace('_', ' ').title(), cnt))
    # Kernel annotation counts (Linux commit convention detections)
    _mf = stats.get('meta_flag_counts') or {}
    for _flag, _label in _META_CARD_LABELS:
        if _mf.get(_flag):
            card_defs.append((_label, _mf[_flag]))
    if thr:
        card_defs.append((f'Min score \u2265{int(thr)}', len(scored)))
    cards = ''.join(
        f'<div class="card"><div class="v">{_e(str(v))}</div>'
        f'<div class="l">{_e(lb)}</div></div>'
        for lb, v in card_defs)

    # ── Profile coverage panel ────────────────────────────────────────────────
    cov_html = (
        '<div class="cov"><h2>Profile Coverage</h2><dl>'
        f'<dt>Zero profiles</dt>'
        f'<dd>{cov.get("commits_matched_zero_profiles", "-")}</dd>'
        f'<dt>One profile</dt>'
        f'<dd>{cov.get("commits_matched_one_profile", "-")}</dd>'
        f'<dt>Multiple profiles</dt>'
        f'<dd>{cov.get("commits_matched_multiple_profiles", "-")}</dd>'
        '</dl></div>')

    # ── Table header + filter rows ────────────────────────────────────────────
    def th(lbl, ci, num, srt):
        n = ' data-num="1"' if num else ''
        s = f' class="sort" data-col="{ci}"{n}' if srt else f' data-col="{ci}"'
        a = '<i class="sa">\u21c5</i>' if srt else ''
        return f'<th{s}>{_e(lbl)}{a}</th>'

    def fi(ci, num):
        if num:
            ph = '&gt;N / &lt;N'
        else:
            ph = 'filter\u2026'
        n = ' data-num="1"' if num else ''
        return f'<th><input data-col="{ci}"{n} placeholder="{ph}"></th>'

    hrow = ''.join(th(lb, i, nu, so) for i, (lb, nu, so) in enumerate(_COLS))
    frow = ''.join(fi(i, nu)          for i, (_, nu, __)  in enumerate(_COLS))

    # ── Data rows ─────────────────────────────────────────────────────────────
    display = min(top_n, len(scored))
    drows   = []
    for c in scored[:display]:
        scv  = int(c.get('score', 0) or 0)
        sha  = _e((c.get('commit') or '')[:12])
        sbj  = _e(c.get('subject', ''))
        pts  = ''.join(f'<span class="pt">{_e(p)}</span>'
                       for p in (c.get('matched_profiles') or []))
        flgs = _flags(c)
        drows.append(
            f'<tr class="dr">'
            f'<td class="rk">{c.get("_rank","")}</td>'
            f'<td><code>{sha}</code></td>'
            f'<td>{sbj}</td>'
            f'<td><span class="sbadge {_sc(scv)}">{scv}</span></td>'
            f'<td>{flgs}</td>'
            f'<td>{pts}</td></tr>')

    table = (
        '<table id="ctbl">'
        f'<thead><tr>{hrow}</tr><tr class="fr">{frow}</tr></thead>'
        f'<tbody>{"".join(drows)}</tbody></table>')

    sbar = (
        '<div class="sbar">'
        '<input id="gsearch" type="search" placeholder="Search all columns\u2026">'
        f'<span id="fstat">Showing {display} of {len(scored)} commits</span>'
        '</div>')

    # ── Profile summary table ─────────────────────────────────────────────────
    if p_summary and isinstance(next(iter(p_summary.values()), None), dict):
        prows = ''.join(
            f'<tr><td>{_e(pn)}</td>'
            f'<td>{pv.get("count", "-")}</td>'
            f'<td>{pv.get("total_score", "-")}</td>'
            f'<td>{pv.get("avg_score", "-")}</td></tr>'
            for pn, pv in sorted(p_summary.items(),
                                  key=lambda kv: kv[1].get('total_score', 0),
                                  reverse=True))
        prof = (
            '<h2 class="sec">Profile Summary</h2>'
            '<table class="ptbl">'
            '<thead><tr><th>Profile</th><th>Commits</th>'
            '<th>Total score</th><th>Avg score</th></tr></thead>'
            f'<tbody>{prows}</tbody></table>')
    else:
        prof = ''   # no profile summary available

    # ── Full page ─────────────────────────────────────────────────────────────
    page = (
        f'<!doctype html><html lang="en" data-theme="light"><head>'
        f'<meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{title} \u2014 {ts}</title>'
        f'<style>{_CSS}{css_extra}</style></head><body>'
        # Header
        f'<header>'
        f'<div class="hdr-left">'
        f'{_LOGO_SVG}'
        f'<div class="hdr-title"><h1>{title}</h1>'
        f'<div class="sub">Analysis date: {ts}'
        f' &middot; kcommit-analysis-pipeline {VERSION}</div></div>'
        f'</div>'
        f'<button id="themetgl" aria-label="Toggle colour scheme">\u25d0 Dark</button>'
        f'</header>'
        # Body
        f'<div class="wrap">'
        f'<div class="cards">{cards}</div>'
        f'{cov_html}'
        f'<h2 class="sec">Top {display} Commits</h2>'
        f'{sbar}'
        f'<div class="tscroll">{table}</div>'
        f'{prof}</div>'
        f'<footer>kcommit-analysis-pipeline {VERSION} &middot; {ts}</footer>'
        f'<script>{_JS}</script></body></html>')

    out = os.path.join(outdir, 'summary.html')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(page)
    return out
