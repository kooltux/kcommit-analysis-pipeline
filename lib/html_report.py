"""HTML report generator for kcommit-analysis-pipeline.

v8.5:
  - Rank column (_rank, set by stage 06 after sorting+threshold).
  - Per-column filter row: input under each header, numeric ops >/</>=/<=/!=.
  - Global search box; "Showing X of Y" live counter.
  - Column sort: click header to cycle ASC -> DESC -> reset.
  - avg_score rendered in Profile Summary table.
  - f-strings throughout; open() replaces io.open().
"""
import html as _html
import json
import os
import time

from lib.config   import load_json
from lib.manifest import VERSION


_CSS = """
:root{--bg:#f7f6f2;--surf:#fff;--pri:#01696f;--mut:#6b7280;
      --bdr:#e5e7eb;--txt:#1a1a1a;--fi:#f0f9f9}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);
     color:var(--txt);font-size:14px}
header{background:var(--pri);color:#fff;padding:.9rem 2rem;
       display:flex;align-items:center;gap:1rem}
header h1{font-size:1.15rem;font-weight:600}
.wrap{max-width:1600px;margin:0 auto;padding:1.5rem 2rem}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));
       gap:1rem;margin-bottom:1.5rem}
.card{background:var(--surf);border:1px solid var(--bdr);border-radius:8px;
      padding:1rem;text-align:center}
.card .v{font-size:1.9rem;font-weight:700;color:var(--pri)}
.card .l{font-size:.72rem;color:var(--mut);margin-top:3px}
.cov{background:var(--surf);border:1px solid var(--bdr);border-radius:8px;
     padding:1rem;margin-bottom:1.5rem}
.cov h2{font-size:.85rem;margin-bottom:.5rem}
.cov dl{display:grid;grid-template-columns:repeat(3,1fr);gap:.4rem}
.cov dt{font-size:.72rem;color:var(--mut)} .cov dd{font-weight:600}
.sbar{display:flex;align-items:center;gap:.6rem;margin-bottom:.4rem}
.sbar input{flex:1;max-width:360px;padding:.3rem .6rem;
  border:1px solid var(--bdr);border-radius:6px;font-size:.8rem}
.sbar input:focus{outline:2px solid var(--pri);outline-offset:1px}
#fstat{font-size:.72rem;color:var(--mut)}
.tscroll{overflow-x:auto;margin-bottom:1.5rem}
table{width:100%;border-collapse:collapse;background:var(--surf);
      border:1px solid var(--bdr);border-radius:8px;overflow:hidden}
th{background:#f1f5f9;padding:.4rem .55rem;text-align:left;
   font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;white-space:nowrap}
th.sort{cursor:pointer;user-select:none} th.sort:hover{background:#e2e8f0}
th .sa{margin-left:3px;opacity:.3;font-size:.68rem}
th.asc .sa,th.desc .sa{opacity:1}
tr.fr th{background:var(--fi);padding:.2rem .35rem}
tr.fr input{width:100%;padding:.18rem .35rem;border:1px solid #cbd5e1;
  border-radius:4px;font-size:.7rem;font-family:inherit}
tr.fr input:focus{outline:2px solid var(--pri)}
tr.fr input:not(:placeholder-shown){border-color:var(--pri)}
td{padding:.35rem .55rem;border-top:1px solid var(--bdr);
   font-size:.78rem;vertical-align:top}
tr.dr:hover{background:#f8fafc} tr.dr.hi{display:none}
.rk{color:var(--mut);font-size:.7rem;text-align:right;
    padding-right:.6rem;min-width:2.2rem}
.sh{color:#059669;font-weight:700} .sm{color:#d97706;font-weight:600}
.sl{color:var(--mut)}
.pt{display:inline-block;background:#e0f2fe;color:#0369a1;
    border-radius:4px;padding:1px 5px;font-size:.66rem;margin:1px}
h2.sec{font-size:.95rem;margin:1.5rem 0 .5rem}
footer{text-align:center;padding:1.2rem;color:var(--mut);font-size:.72rem}
"""

_JS = r"""
(function(){
  'use strict';
  var tbl=document.getElementById('ctbl');
  if(!tbl) return;
  var tb=tbl.querySelector('tbody');
  var fi=[].slice.call(tbl.querySelectorAll('tr.fr input[data-col]'));
  var gi=document.getElementById('gsearch');
  var st=document.getElementById('fstat');
  var rows=[].slice.call(tb.querySelectorAll('tr.dr'));
  var sc=-1,sd=0;
  function nm(t,f){
    var v=parseFloat(t); if(isNaN(v)) return t.includes(f);
    var m=f.match(/^([><=!]{1,2})\s*(-?\d+(?:\.\d+)?)$/);
    if(!m) return t.includes(f);
    var n=parseFloat(m[2]),op=m[1];
    if(op==='>') return v>n; if(op==='>=') return v>=n;
    if(op==='<') return v<n; if(op==='<=') return v<=n;
    if(op==='!='||op==='<>') return v!==n; return v===n;
  }
  function go(){
    var gv=gi?gi.value.trim().toLowerCase():'',vis=0;
    rows.forEach(function(r){
      var cs=[].slice.call(r.querySelectorAll('td'));
      var ok=fi.every(function(inp){
        var v=inp.value.trim().toLowerCase(); if(!v) return true;
        var c=cs[+inp.dataset.col]; if(!c) return true;
        var t=c.textContent.trim().toLowerCase();
        return inp.dataset.num?nm(t,v):t.includes(v);
      })&&(!gv||cs.some(function(c){return c.textContent.toLowerCase().includes(gv);}));
      r.classList.toggle('hi',!ok); if(ok) vis++;
    });
    if(st) st.textContent='Showing '+vis+' of '+rows.length+' commit'+(rows.length!==1?'s':'');
  }
  function sortBy(ci,num){
    if(sc===ci){sd=sd===1?-1:sd===-1?0:1;}else{sc=ci;sd=1;}
    var ths=[].slice.call(tbl.querySelectorAll('thead tr:first-child th'));
    ths.forEach(function(h){h.classList.remove('asc','desc');});
    if(sd!==0){var h=ths[ci];if(h)h.classList.add(sd===1?'asc':'desc');}
    if(sd===0){go();return;}
    rows.slice().sort(function(a,b){
      var ta=((a.querySelectorAll('td')[ci])||{textContent:''}).textContent.trim();
      var tb2=((b.querySelectorAll('td')[ci])||{textContent:''}).textContent.trim();
      var cmp=num?(parseFloat(ta)||0)-(parseFloat(tb2)||0):ta.localeCompare(tb2);
      return sd*cmp;
    }).forEach(function(r){tb.appendChild(r);});
    go();
  }
  fi.forEach(function(i){i.addEventListener('input',go);});
  if(gi) gi.addEventListener('input',go);
  [].slice.call(tbl.querySelectorAll('thead tr:first-child th.sort')).forEach(function(th){
    var ci=+th.dataset.col, num=th.dataset.num==='1';
    th.addEventListener('click',function(){sortBy(ci,num);});
  });
  go();
})();
"""


def _e(s): return _html.escape(str(s or ''))
def _sc(v): return 'sh' if v >= 200 else 'sm' if v >= 80 else 'sl'

# col: (label, numeric, sortable)
_COLS = [
    ('#',           False, False),
    ('SHA',         False, True),
    ('Subject',     False, True),
    ('Score',       True,  True),
    ('Security',    True,  True),
    ('Performance', True,  True),
    ('Product',     True,  True),
    ('Stable',      True,  True),
    ('Profiles',    False, True),
]


def generate_html_report(work_dir, cfg):
    outdir = os.path.join(work_dir, 'output')
    scored    = load_json(os.path.join(outdir, 'relevant_commits.json'), default=[]) or []
    stats     = load_json(os.path.join(outdir, 'report_stats.json'),    default={}) or {}
    p_summary = load_json(os.path.join(outdir, 'profile_summary.json'), default={}) or {}

    tmpl   = cfg.get('templates', {}) or {}
    top_n  = int(tmpl.get('top_n', 100) or 100)
    title  = _e(tmpl.get('report_title', 'kcommit Analysis Report'))
    ts     = time.strftime('%Y-%m-%d %H:%M:%S')
    cov    = stats.get('profile_coverage', {}) or {}
    thr    = stats.get('min_score_threshold', 0) or 0

    # ── CSS override ──────────────────────────────────────────────────────────
    css_extra = ''
    css_path  = tmpl.get('summary_css')
    if css_path:
        meta = cfg.get('_meta', {}) or {}
        if not os.path.isabs(css_path):
            css_path = os.path.join(meta.get('config_dir', ''), css_path)
        if os.path.exists(css_path):
            with open(css_path, encoding='utf-8') as f:
                css_extra = f.read()

    # ── stat cards ────────────────────────────────────────────────────────────
    card_defs = [
        ('Total commits',      stats.get('total_scored_commits', len(scored))),
        ('Security scored',    stats.get('commits_with_security_score', 0)),
        ('Performance scored', stats.get('commits_with_performance_score', 0)),
        ('Stable fixes',       stats.get('commits_with_stable_score', 0)),
        ('Product evidence',   stats.get('commits_with_product_evidence', 0)),
    ]
    if thr:
        card_defs.append((f'Min score \u2265{int(thr)}', len(scored)))
    cards = ''.join(
        f'<div class="card"><div class="v">{_e(str(v))}</div>'
        f'<div class="l">{_e(lb)}</div></div>'
        for lb, v in card_defs)

    cov_html = (
        '<div class="cov"><h2>Profile Coverage</h2><dl>'
        f'<dt>Zero profiles</dt><dd>{cov.get("commits_matched_zero_profiles","-")}</dd>'
        f'<dt>One profile</dt><dd>{cov.get("commits_matched_one_profile","-")}</dd>'
        f'<dt>Multiple profiles</dt><dd>{cov.get("commits_matched_multiple_profiles","-")}</dd>'
        '</dl></div>')

    # ── header + filter rows ──────────────────────────────────────────────────
    def th(lbl, ci, num, srt):
        n = ' data-num="1"' if num else ''
        s = f' class="sort" data-col="{ci}"{n}' if srt else ''
        a = '<i class="sa">\u21c5</i>' if srt else ''
        return f'<th{s}>{_e(lbl)}{a}</th>'

    def fi(ci, num):
        ph = '&gt;N / &lt;N' if num else 'filter\u2026'
        n  = ' data-num="1"' if num else ''
        return f'<th><input data-col="{ci}"{n} placeholder="{ph}"></th>'

    hrow = ''.join(th(lb,i,nu,so) for i,(lb,nu,so) in enumerate(_COLS))
    frow = ''.join(fi(i, nu)       for i,(_,nu,__)  in enumerate(_COLS))

    # ── data rows ─────────────────────────────────────────────────────────────
    display = min(top_n, len(scored))
    drows   = []
    for c in scored[:display]:
        sc  = c.get('scoring', {}) or {}
        scv = int(c.get('score', 0) or 0)
        sha = _e((c.get('commit') or '')[:12])
        sbj = _e(c.get('subject', ''))
        pts = ''.join(f'<span class="pt">{_e(p)}</span>'
                      for p in (c.get('matched_profiles') or []))
        drows.append(
            f'<tr class="dr">'
            f'<td class="rk">{c.get("_rank","")}</td>'
            f'<td><code>{sha}</code></td>'
            f'<td>{sbj}</td>'
            f'<td class="{_sc(scv)}">{scv}</td>'
            f'<td>{sc.get("security",0) or 0}</td>'
            f'<td>{sc.get("performance",0) or 0}</td>'
            f'<td>{sc.get("product",0) or 0}</td>'
            f'<td>{sc.get("stable",0) or 0}</td>'
            f'<td>{pts}</td></tr>')

    table = (
        '<table id="ctbl">'
        f'<thead><tr>{hrow}</tr><tr class="fr">{frow}</tr></thead>'
        f'<tbody>{"".join(drows)}</tbody></table>')

    sbar = (
        '<div class="sbar">'
        '<input id="gsearch" type="search" placeholder="Search all columns\u2026">'
        '<span id="fstat"></span></div>')

    # ── profile summary table ─────────────────────────────────────────────────
    if p_summary and isinstance(next(iter(p_summary.values()), None), dict):
        prows = ''.join(
            f'<tr><td>{_e(pn)}</td>'
            f'<td>{pv.get("count","-")}</td>'
            f'<td>{pv.get("total_score","-")}</td>'
            f'<td>{pv.get("avg_score","-")}</td></tr>'
            for pn, pv in sorted(p_summary.items(),
                                  key=lambda kv: kv[1].get('count', 0),
                                  reverse=True))
        prof = (
            '<h2 class="sec">Profile Summary</h2>'
            '<table style="width:auto;margin-bottom:1.5rem">'
            '<thead><tr><th>Profile</th><th>Commits</th>'
            '<th>Total score</th><th>Avg score</th></tr></thead>'
            f'<tbody>{prows}</tbody></table>')
    else:
        prof = (
            '<h2 class="sec">Profile Summary</h2>'
            f'<pre style="background:#f1f5f9;padding:1rem;border-radius:8px;'
            f'font-size:.72rem;overflow-x:auto">'
            f'{_e(json.dumps(p_summary, indent=2))}</pre>')

    page = (
        f'<!doctype html><html lang="en"><head>'
        f'<meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{title}</title>'
        f'<style>{_CSS}{css_extra}</style></head><body>'
        f'<header><h1>{title}</h1>'
        f'<span style="margin-left:auto;font-size:.78rem;opacity:.8">{ts}</span></header>'
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
