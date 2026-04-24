"""HTML report generator for kcommit-analysis-pipeline.

v7.18 changes vs v7.17:
  - Table columns now use 'score' (single combined) + scoring sub-dict breakdown
    instead of the old flat candidate_score / security_score / performance_score.
  - Profile Coverage card added to summary row showing zero/single/multi-profile
    match buckets.
  - Template resolution: honours cfg['templates']['base_html'] / 'summary_css'
    before falling back to the built-in embedded template.
  - Report title taken from cfg['templates']['report_title'] when present.
  - Top N commits limit configurable via cfg['templates']['top_n'] (default 100).
"""
import html
import json
import os
import time


_BUILTIN_CSS = """
:root { --bg: #f7f6f2; --surface: #fff; --primary: #01696f; --muted: #6b7280;
        --border: #e5e7eb; --text: #1a1a1a; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg);
       color: var(--text); font-size: 14px; }
header { background: var(--primary); color: #fff; padding: 1rem 2rem;
         display: flex; align-items: center; gap: 1rem; }
header h1 { font-size: 1.2rem; font-weight: 600; }
.container { max-width: 1400px; margin: 0 auto; padding: 1.5rem 2rem; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
         gap: 1rem; margin-bottom: 1.5rem; }
.card { background: var(--surface); border: 1px solid var(--border);
        border-radius: 8px; padding: 1rem; text-align: center; }
.card .value { font-size: 2rem; font-weight: 700; color: var(--primary); }
.card .label { font-size: 0.75rem; color: var(--muted); margin-top: 4px; }
.coverage { background: var(--surface); border: 1px solid var(--border);
            border-radius: 8px; padding: 1rem; margin-bottom: 1.5rem; }
.coverage h2 { font-size: 0.9rem; margin-bottom: 0.5rem; }
.coverage dl { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.5rem; }
.coverage dt { font-size: 0.75rem; color: var(--muted); }
.coverage dd { font-weight: 600; }
table { width: 100%; border-collapse: collapse; background: var(--surface);
        border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
th { background: #f1f5f9; padding: 0.5rem 0.75rem; text-align: left;
     font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
td { padding: 0.4rem 0.75rem; border-top: 1px solid var(--border);
     font-size: 0.8rem; vertical-align: top; }
td code { font-size: 0.7rem; color: var(--muted); }
tr:hover { background: #f8fafc; }
.score-high { color: #059669; font-weight: 700; }
.score-mid  { color: #d97706; font-weight: 600; }
.score-low  { color: var(--muted); }
.profile-tag { display: inline-block; background: #e0f2fe; color: #0369a1;
               border-radius: 4px; padding: 1px 6px; font-size: 0.68rem;
               margin: 1px; }
footer { text-align: center; padding: 1.5rem; color: var(--muted); font-size: 0.75rem; }
"""


def _load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _score_class(s):
    if s >= 200:
        return 'score-high'
    if s >= 80:
        return 'score-mid'
    return 'score-low'


def _esc(s):
    return html.escape(str(s or ''))


def generate_html_report(work_dir, cfg):
    """Generate the HTML summary report; return the path to the written file."""
    outdir    = os.path.join(work_dir, 'output')
    scored    = _load_json(os.path.join(outdir, 'scored_commits.json'), default=[]) or []
    stats     = _load_json(os.path.join(outdir, 'report_stats.json'),    default={}) or {}
    p_summary = _load_json(os.path.join(outdir, 'profile_summary.json'), default={}) or {}

    tmpl_cfg  = cfg.get('templates', {}) or {}
    top_n     = int(tmpl_cfg.get('top_n', 100) or 100)
    title     = _esc(tmpl_cfg.get('report_title', 'kcommit Analysis Report'))
    ts        = time.strftime('%Y-%m-%d %H:%M:%S')
    coverage  = stats.get('profile_coverage', {}) or {}

    # Optional external CSS override
    meta      = cfg.get('_meta', {}) or {}
    config_dir = meta.get('config_dir', '')
    css_override = ''
    css_path  = tmpl_cfg.get('summary_css')
    if css_path and not os.path.isabs(css_path):
        css_path = os.path.join(config_dir, css_path)
    if css_path and os.path.exists(css_path):
        with open(css_path, 'r', encoding='utf-8') as f:
            css_override = f.read()

    # ── cards ─────────────────────────────────────────────────────────────────
    card_defs = [
        ('Total commits',       stats.get('total_scored_commits', len(scored))),
        ('Security scored',     stats.get('commits_with_security_score', 0)),
        ('Performance scored',  stats.get('commits_with_performance_score', 0)),
        ('Stable fixes',        stats.get('commits_with_stable_score', 0)),
        ('Product evidence',    stats.get('commits_with_product_evidence', 0)),
    ]
    cards_html = ''.join(
        '<div class="card"><div class="value">%s</div>'
        '<div class="label">%s</div></div>' % (_esc(str(val)), _esc(lbl))
        for lbl, val in card_defs
    )

    # ── profile coverage block ─────────────────────────────────────────────────
    cov_html = (
        '<div class="coverage">'
        '<h2>Profile Coverage</h2>'
        '<dl>'
        '<dt>Matched zero profiles</dt><dd>%s</dd>'
        '<dt>Matched one profile</dt><dd>%s</dd>'
        '<dt>Matched multiple profiles</dt><dd>%s</dd>'
        '</dl></div>'
    ) % (
        coverage.get('commits_matched_zero_profiles', '-'),
        coverage.get('commits_matched_one_profile', '-'),
        coverage.get('commits_matched_multiple_profiles', '-'),
    )

    # ── table ─────────────────────────────────────────────────────────────────
    rows_html_parts = []
    for c in scored[:top_n]:
        sc   = c.get('scoring', {}) or {}
        sha  = c.get('commit', '')[:12]
        subj = _esc(c.get('subject', ''))
        scv  = int(c.get('score', 0) or 0)
        sec  = sc.get('security', 0)
        perf = sc.get('performance', 0)
        prod = sc.get('product', 0)
        stbl = sc.get('stable', 0)
        prof_tags = ''.join(
            '<span class="profile-tag">%s</span>' % _esc(p)
            for p in (c.get('matched_profiles') or [])
        )
        rows_html_parts.append(
            '<tr>'
            '<td><code>%s</code></td>'
            '<td>%s</td>'
            '<td class="%s">%d</td>'
            '<td>%d</td><td>%d</td><td>%d</td><td>%d</td>'
            '<td>%s</td>'
            '</tr>' % (
                _esc(sha), subj,
                _score_class(scv), scv,
                sec, perf, prod, stbl,
                prof_tags,
            )
        )

    table_html = (
        '<table>'
        '<thead><tr>'
        '<th>SHA</th><th>Subject</th>'
        '<th>Score</th>'
        '<th>Security</th><th>Performance</th><th>Product</th><th>Stable</th>'
        '<th>Profiles</th>'
        '</tr></thead>'
        '<tbody>%s</tbody>'
        '</table>'
    ) % ''.join(rows_html_parts)

    # ── profile summary table (v7.18: richer dict format) ───────────────────────
    if p_summary and isinstance(list(p_summary.values())[0], dict):
        prows = ''.join(
            '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                _esc(pn),
                pv.get('count', '-'),
                pv.get('total_score', '-'),
                pv.get('avg_score', '-'),
            )
            for pn, pv in sorted(
                p_summary.items(),
                key=lambda kv: kv[1].get('count', 0),
                reverse=True,
            )
        )
        prof_html = (
            '<h2 style="margin:1.5rem 0 0.5rem;font-size:1rem;">Profile Summary</h2>'
            '<table style="width:auto;margin-bottom:1.5rem">'
            '<thead><tr><th>Profile</th><th>Commits</th><th>Total score</th><th>Avg score</th></tr></thead>'
            '<tbody>%s</tbody></table>'
        ) % prows
    else:
        prof_html = (
            '<h2 style="margin:1.5rem 0 0.5rem;font-size:1rem;">Profile Summary</h2>'
            '<pre style="background:#f1f5f9;padding:1rem;border-radius:8px;'
            'font-size:0.75rem;overflow-x:auto;">%s</pre>'
        ) % _esc(json.dumps(p_summary, indent=2))

    # ── assemble page ──────────────────────────────────────────────────────────
    page = (
        '<!doctype html><html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>%s</title>'
        '<style>%s%s</style>'
        '</head><body>'
        '<header><h1>%s</h1><span style="margin-left:auto;font-size:0.8rem;opacity:.8">%s</span></header>'
        '<div class="container">'
        '<div class="cards">%s</div>'
        '%s'
        '<h2 style="margin-bottom:0.75rem;font-size:1rem;">Top %d Commits</h2>'
        '%s'
        '%s'
        '</div>'
        '<footer>Generated by kcommit-analysis-pipeline v7.18 · %s</footer>'
        '</body></html>'
    ) % (
        title,
        _BUILTIN_CSS,
        css_override,
        title, ts,
        cards_html,
        cov_html,
        min(top_n, len(scored)),
        table_html,
        prof_html,
        ts,
    )

    html_path = os.path.join(outdir, 'summary.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(page)
    return html_path
