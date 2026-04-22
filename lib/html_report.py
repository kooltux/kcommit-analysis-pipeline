from __future__ import print_function
import html
import json
import os


def _load_json(path, default):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default


def _default_css():
    return """
:root{--bg:#f6f7fb;--fg:#1f2937;--muted:#6b7280;--card:#ffffff;--line:#e5e7eb;--accent:#0f766e;--accent2:#0ea5e9}
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 Arial,sans-serif;background:var(--bg);color:var(--fg)}
.wrap{max-width:1200px;margin:0 auto;padding:32px 20px}
h1{margin:0 0 8px;font-size:32px}
h2{margin:24px 0 12px;font-size:22px}
.sub{color:var(--muted);margin-bottom:24px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.k{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
.v{font-size:26px;font-weight:700;margin-top:6px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden}
th,td{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:#f9fafb;font-size:13px}
tr:last-child td{border-bottom:none}
pre{background:#0b1020;color:#dbe4ff;padding:16px;border-radius:14px;overflow:auto}
code{font-family:Consolas,Monaco,monospace}
"""


def generate_html_report(work_dir, cfg):
    """Generate an HTML summary report under <work_dir>/output/summary.html.

    The function uses scored_commits.json, profile_summary.json, and
    report_stats.json produced by earlier pipeline stages. Styling and
    structure can be customized via templates under configs/templates/ when
    available, falling back to a built-in layout otherwise.
    """
    outdir = os.path.join(work_dir, 'output')
    rows = _load_json(os.path.join(outdir, 'scored_commits.json'), []) or []
    summary = _load_json(os.path.join(outdir, 'profile_summary.json'), {}) or {}
    stats = _load_json(os.path.join(outdir, 'report_stats.json'), {}) or {}

    templates_cfg = cfg.get('templates', {}) or {}
    title = templates_cfg.get('report_title', 'Kernel commit analysis report')
    top_n = int(templates_cfg.get('top_n_commits', 100) or 100)

    meta = cfg.get('_meta', {}) or {}
    vars_map = meta.get('vars', {}) or {}
    tooldir = vars_map.get('TOOLDIR') or os.environ.get('TOOLDIR') or os.path.abspath(os.path.join(meta.get('config_dir', os.getcwd()), '..'))
    template_dir = os.path.join(tooldir, 'configs', 'templates')

    css_path = os.path.join(template_dir, 'summary.css')
    if os.path.exists(css_path):
        with open(css_path, 'r', encoding='utf-8') as f:
            css = f.read()
    else:
        css = _default_css()

    # Build the inner body (between <body> tags).
    parts = []
    parts.append('<div class="wrap">')
    parts.append('<h1>%s</h1>' % html.escape(str(title)))
    parts.append('<div class="sub">Generated from pipeline outputs with execution statistics and scored commits.</div>')

    cards = [
        ('Reported commits', len(rows)),
        ('Security-scored', stats.get('commits_with_security_score', 0)),
        ('Performance-scored', stats.get('commits_with_performance_score', 0)),
        ('With product evidence', stats.get('commits_with_product_evidence', 0)),
    ]
    cards_html = ''.join(
        '<div class="card"><div class="k">%s</div><div class="v">%s</div></div>'
        % (html.escape(str(k)), html.escape(str(v))) for k, v in cards
    )
    parts.append('<div class="grid">%s</div>' % cards_html)

    parts.append('<h2>Top scored commits</h2>')
    parts.append('<table><thead><tr><th>SHA</th><th>Subject</th><th>Candidate</th><th>Security</th><th>Performance</th><th>Product</th></tr></thead><tbody>')
    for row in rows[:top_n]:
        parts.append(
            '<tr><td><code>%s</code></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
            % (
                html.escape(str(row.get('commit', ''))),
                html.escape(str(row.get('subject', ''))),
                html.escape(str(row.get('candidate_score', ''))),
                html.escape(str(row.get('security_score', ''))),
                html.escape(str(row.get('performance_score', ''))),
                html.escape(str(row.get('product_score', ''))),
            )
        )
    parts.append('</tbody></table>')

    parts.append('<h2>Profile summary</h2><pre>%s</pre>' % html.escape(json.dumps(summary, indent=2, sort_keys=True)))
    parts.append('<h2>Execution stats</h2><pre>%s</pre>' % html.escape(json.dumps(stats, indent=2, sort_keys=True)))
    parts.append('</div>')  # .wrap

    body_html = ''.join(parts)

    base_tpl_path = os.path.join(template_dir, 'base.html')
    if os.path.exists(base_tpl_path):
        with open(base_tpl_path, 'r', encoding='utf-8') as f:
            tpl = f.read()
        html_out = (
            tpl.replace('{{TITLE}}', html.escape(str(title)))
               .replace('{{CSS}}', css)
               .replace('{{BODY}}', body_html)
        )
    else:
        html_out = (
            '<!doctype html><html><head><meta charset="utf-8">'
            '<title>%s</title><style>%s</style></head><body>%s</body></html>'
        ) % (html.escape(str(title)), css, body_html)

    out_path = os.path.join(outdir, 'summary.html')
    with open(out_path, 'w', encoding='utf-8') as fd:
        fd.write(html_out)

    return out_path
