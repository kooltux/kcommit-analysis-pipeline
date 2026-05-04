import json
import os
import time
from lib.manifest import VERSION, TEMPLATE_DIR

_TEMPLATE_CACHE = {}


def _get_template(name, default=''):
    """Return cached template file contents, loading on first access."""
    if name not in _TEMPLATE_CACHE:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        path = os.path.join(root, TEMPLATE_DIR, name)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                _TEMPLATE_CACHE[name] = f.read()
        except Exception:
            _TEMPLATE_CACHE[name] = default
    return _TEMPLATE_CACHE[name]


def generate_html_report(commits, profile_summary, report_stats, output_path,
                         title='kcommit-analysis-pipeline'):
    tpl       = _get_template('report.html', '__BODY__')
    css       = _get_template('summary.css')
    js        = _get_template('summary.js')
    generated = time.strftime('%Y-%m-%d %H:%M:%S')

    rows = []
    for i, c in enumerate(commits or [], 1):
        sha      = (c.get('commit') or '')[:12]
        subject  = c.get('subject') or ''
        score    = c.get('score', 0)
        profiles = ', '.join(c.get('matched_profiles', []) or [])
        rows.append(
            f'<tr><td>{i}</td><td><code>{sha}</code></td>'
            f'<td>{subject}</td><td>{score}</td><td>{profiles}</td></tr>')

    p_rows = []
    for pname, pd in sorted((profile_summary or {}).items(),
                             key=lambda x: -x[1].get('total_score', 0)):
        p_rows.append(
            f'<tr><td>{pname}</td><td>{pd.get("count", 0)}</td>'
            f'<td>{pd.get("total_score", 0)}</td>'
            f'<td>{pd.get("avg_score", 0):.1f}</td></tr>')

    stats_pre = json.dumps(report_stats or {}, indent=2)
    body = (
        f'<main>'
        f'<header><h1>{title} {VERSION}</h1>'
        f'<p>Analysis date: {generated}</p></header>'
        f'<section><h2>Commits</h2>'
        f'<table><thead><tr><th>#</th><th>Commit</th><th>Subject</th>'
        f'<th>Score</th><th>Profiles</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></section>'
        f'<section><h2>Profile Summary</h2>'
        f'<table><thead><tr><th>Profile</th><th>Commits</th>'
        f'<th>Total score</th><th>Avg score</th></tr></thead>'
        f'<tbody>{"".join(p_rows)}</tbody></table></section>'
        f'<section><h2>Run Stats</h2><pre>{stats_pre}</pre></section>'
        f'</main>'
    )
    out = (tpl
           .replace('__TITLE__', f'{title} {VERSION}')
           .replace('__CSS__',   css)
           .replace('__JS__',    js)
           .replace('__BODY__',  body))
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(out)
