#!/usr/bin/env python3
from __future__ import print_function
import argparse, html, json, os

def load_json(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work-dir', required=True)
    args = ap.parse_args()
    outdir = os.path.join(args.work_dir, 'output')
    rows = load_json(os.path.join(outdir, 'scored_commits.json')) or []
    summary = load_json(os.path.join(outdir, 'profile_summary.json')) or {}
    stats = load_json(os.path.join(outdir, 'report_stats.json')) or {}
    css = """
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
    parts = []
    parts.append('<!doctype html><html><head><meta charset="utf-8"><title>Kernel commit analysis report</title><style>%s</style></head><body>' % css)
    parts.append('<div class="wrap">')
    parts.append('<h1>Kernel commit analysis report</h1>')
    parts.append('<div class="sub">Generated from pipeline outputs with execution statistics and scored commits.</div>')
    cards = [
        ('Reported commits', len(rows)),
        ('Security-scored', stats.get('commits_with_security_score', 0)),
        ('Performance-scored', stats.get('commits_with_performance_score', 0)),
        ('With product evidence', stats.get('commits_with_product_evidence', 0)),
    ]
    parts.append('<div class="grid">' + ''.join('<div class="card"><div class="k">%s</div><div class="v">%s</div></div>' % (html.escape(str(k)), html.escape(str(v))) for k, v in cards) + '</div>')
    parts.append('<h2>Top scored commits</h2>')
    parts.append('<table><thead><tr><th>SHA</th><th>Subject</th><th>Candidate</th><th>Security</th><th>Performance</th><th>Product</th></tr></thead><tbody>')
    for row in rows[:100]:
        parts.append('<tr><td><code>%s</code></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            html.escape(str(row.get('sha', ''))),
            html.escape(str(row.get('subject', ''))),
            html.escape(str(row.get('candidate_score', ''))),
            html.escape(str(row.get('security_score', ''))),
            html.escape(str(row.get('performance_score', ''))),
            html.escape(str(row.get('product_score', ''))),
        ))
    parts.append('</tbody></table>')
    parts.append('<h2>Profile summary</h2><pre>%s</pre>' % html.escape(json.dumps(summary, indent=2, sort_keys=True)))
    parts.append('<h2>Execution stats</h2><pre>%s</pre>' % html.escape(json.dumps(stats, indent=2, sort_keys=True)))
    parts.append('</div></body></html>')
    out = os.path.join(outdir, 'summary.html')
    with open(out, 'w', encoding='utf-8') as fd:
        fd.write(''.join(parts))
    print(out)

if __name__ == '__main__':
    main()
