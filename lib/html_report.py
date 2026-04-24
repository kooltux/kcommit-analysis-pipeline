"""HTML report generator for kcommit-analysis-pipeline.

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
:root {
  --bg: #f8fafc;
  --surface: rgba(255, 255, 255, 0.8);
  --surface-solid: #ffffff;
  --primary: #0f172a;
  --primary-muted: #334155;
  --accent: #0284c7;
  --muted: #64748b;
  --border: rgba(226, 232, 240, 0.8);
  --text: #1e293b;
  --shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
  --glass-bg: rgba(255, 255, 255, 0.7);
  --glass-blur: 10px;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f172a;
    --surface: rgba(30, 41, 59, 0.8);
    --surface-solid: #1e293b;
    --primary: #f8fafc;
    --primary-muted: #cbd5e1;
    --accent: #38bdf8;
    --muted: #94a3b8;
    --border: rgba(51, 65, 85, 0.8);
    --text: #f1f5f9;
    --glass-bg: rgba(15, 23, 42, 0.7);
  }
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
  font-size: 14px;
  line-height: 1.5;
  transition: background-color 0.3s ease;
}

header {
  background: var(--surface-solid);
  border-bottom: 1px solid var(--border);
  padding: 1.25rem 2rem;
  display: flex;
  align-items: center;
  gap: 1rem;
  position: sticky;
  top: 0;
  z-index: 100;
  backdrop-filter: blur(var(--glass-blur));
}

header h1 { font-size: 1.25rem; font-weight: 700; letter-spacing: -0.025em; }

.container { max-width: 1400px; margin: 0 auto; padding: 2rem; }

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 1.5rem;
  margin-bottom: 2rem;
}

.card {
  background: var(--glass-bg);
  backdrop-filter: blur(var(--glass-blur));
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.5rem;
  text-align: center;
  box-shadow: var(--shadow);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.card:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.1);
}

.card .value { font-size: 2.25rem; font-weight: 800; color: var(--accent); margin-bottom: 0.25rem; }
.card .label { font-size: 0.875rem; font-weight: 500; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }

.coverage {
  background: var(--glass-bg);
  backdrop-filter: blur(var(--glass-blur));
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.5rem;
  margin-bottom: 2rem;
  box-shadow: var(--shadow);
}

.coverage h2 { font-size: 1rem; font-weight: 700; margin-bottom: 1rem; color: var(--primary-muted); }
.coverage dl { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; }
.coverage dt { font-size: 0.875rem; color: var(--muted); margin-bottom: 0.25rem; }
.coverage dd { font-size: 1.125rem; font-weight: 700; color: var(--text); }

table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  background: var(--surface-solid);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: var(--shadow);
}

th {
  background: var(--bg);
  padding: 0.75rem 1rem;
  text-align: left;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
  border-bottom: 1px solid var(--border);
}

td {
  padding: 1rem;
  border-bottom: 1px solid var(--border);
  font-size: 0.875rem;
  vertical-align: top;
}

tr:last-child td { border-bottom: none; }

td code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.8125rem;
  color: var(--accent);
  background: rgba(2, 132, 199, 0.1);
  padding: 0.125rem 0.375rem;
  border-radius: 4px;
}

tr:hover { background: rgba(241, 245, 249, 0.5); }
@media (prefers-color-scheme: dark) {
  tr:hover { background: rgba(30, 41, 59, 0.5); }
}

.score-high { color: #10b981; font-weight: 800; }
.score-mid  { color: #f59e0b; font-weight: 700; }
.score-low  { color: var(--muted); }

.profile-tag {
  display: inline-block;
  background: rgba(2, 132, 199, 0.1);
  color: var(--accent);
  border: 1px solid rgba(2, 132, 199, 0.2);
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 0.75rem;
  font-weight: 500;
  margin: 2px;
}

footer { text-align: center; padding: 3rem 1.5rem; color: var(--muted); font-size: 0.875rem; }
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
        sb   = c.get('score_bonus', {}) or {}
        sha  = c.get('commit', '')[:12]
        subj = _esc(c.get('subject', ''))
        scv  = c.get('score_total', 0) or 0
        sec  = sb.get('security', 0)
        perf = sb.get('performance', 0)
        prod = sb.get('product', 0)
        stbl = sb.get('stable', 0)
        prof_tags = ''.join(
            '<span class="profile-tag">%s</span>' % _esc(p)
            for p in (c.get('matched_profiles') or [])
        )
        rows_html_parts.append(
            '<tr>'
            '<td><code>%s</code></td>'
            '<td>%s</td>'
            '<td class="%s">%.1f</td>'
            '<td>%.1f</td><td>%.1f</td><td>%.1f</td><td>%.1f</td>'
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
            '<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                _esc(pn),
                pv.get('count', '-'),
                pv.get('total_score', '-'),
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
            '<thead><tr><th>Profile</th><th>Commits</th><th>Total score</th></tr></thead>'
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
        '<footer>Generated by kcommit-analysis-pipeline v7.20 · %s</footer>'
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
