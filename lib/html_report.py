"""HTML report generator for kcommit-analysis-pipeline.

v9.9 changes:
  - _commit_row(): removed legacy fixed sub-score columns
    columns. Columns now match COMMIT_COLS exactly (Rank, SHA, Subject,
    Author, Date, Score, Profiles, Product Evidence [+ Filter reason]).
  - _table(): filter row now rendered as part of <thead> with class
    'kc-filters'; sticky offset is handled in CSS, not here.
  - Profile Summary table no longer uses _table() (no per-column filters
    needed); rendered as a plain <table class="kc-table"> to avoid the
    filter-row overlapping regular rows.
"""
import functools
import json
import os
import time

from lib.manifest    import VERSION, TEMPLATE_DIR
from lib.spreadsheet import COMMIT_COLS, SUMMARY_COLS, MATRIX_COLS


@functools.lru_cache(maxsize=None)
def _get_template(name, default=''):
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    path = os.path.join(root, TEMPLATE_DIR, name)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return default


def _logo():
    return _get_template('logo.svg', '')


def _score_pill(score):
    try:
        s = float(score)
    except (TypeError, ValueError):
        s = 0.0
    cls = 'hi' if s >= 70 else ('mid' if s >= 30 else 'low')
    return f'<span class="score-pill {cls}">{score}</span>'


def _profile_chips(profiles):
    return ' '.join(
        f'<span class="profile-chip">{p}</span>' for p in (profiles or []))


def _th(label):
    return (f'<th><span class="col-label">{label}</span>'
            f'<i class="sort-icon">⇅</i></th>')


def _filter_input():
    return '<input type="text" placeholder="filter…  >N <N foo*" aria-label="filter column">'


def _table(headers, rows_html, table_id=''):
    """Table with sticky header row + per-column filter row."""
    id_attr = f' id="{table_id}"' if table_id else ''
    thead = (
        '<thead>'
        '<tr class="kc-col-headers">'
        + ''.join(_th(h) for h in headers)
        + '</tr>'
        '<tr class="kc-filters">'
        + ''.join(f'<th>{_filter_input()}</th>' for _ in headers)
        + '</tr>'
        '</thead>'
    )
    return (
        f'<table class="kc-table"{id_attr}>'
        + thead
        + '<tbody>' + ''.join(rows_html) + '</tbody>'
        + '</table>'
        + '<p class="kc-no-match">No rows match the current filters.</p>'
    )


def _plain_table(headers, rows_html, table_id=''):
    """Plain table with only a header row (no filter inputs)."""
    id_attr = f' id="{table_id}"' if table_id else ''
    thead = (
        '<thead><tr class="kc-col-headers">'
        + ''.join(_th(h) for h in headers)
        + '</tr></thead>'
    )
    return (
        f'<table class="kc-table"{id_attr}>'
        + thead
        + '<tbody>' + ''.join(rows_html) + '</tbody>'
        + '</table>'
    )


def _commit_row_html(i, c, with_reason=False):
    """Build a <tr> for a commit.  Matches COMMIT_COLS exactly."""
    sha    = (c.get('commit') or '')
    sha12  = sha[:12]
    subj   = c.get('subject') or ''
    author = c.get('author_name') or ''
    date   = c.get('author_time') or ''
    score  = c.get('score', 0) or 0
    profs  = c.get('matched_profiles') or []
    evid   = '; '.join(c.get('product_evidence') or [])

    sha_link = (
        f'<a class="sha-link" data-sha="{sha12}" href="#"'
        f' title="Show commit details">{sha12}</a>'
    )

    cells = [
        f'<td class="rank">{i}</td>',
        f'<td class="sha">{sha_link}</td>',
        f'<td>{subj}</td>',
        f'<td>{author}</td>',
        f'<td class="num">{date}</td>',
        f'<td class="num">{_score_pill(score)}</td>',
        f'<td>{_profile_chips(profs)}</td>',
        f'<td><small>{evid}</small></td>',
    ]
    if with_reason:
        reason = c.get('_filter_reason', '')
        cells.append(f'<td><small>{reason}</small></td>')
    return '<tr>' + ''.join(cells) + '</tr>'


def _section(title, badge, content, anchor=''):
    id_attr = f' id="{anchor}"' if anchor else ''
    return (
        f'<section class="kc-card"{id_attr}>'
        f'<div class="kc-card-header"><h2>{title}</h2>'
        f'<span class="kc-badge">{badge}</span></div>'
        + content
        + '</section>'
    )


def generate_html_report(commits, profile_summary, report_stats, output_path,
                         title='kcommit-analysis-pipeline',
                         is_filtered=False):
    """Write HTML report to *output_path*.

    Section order: Run Stats → Profile Summary → Commits table.
    Commit table columns match COMMIT_COLS (no legacy sub-score columns).
    """
    tpl       = _get_template('report.html', '__BODY__')
    css       = _get_template('summary.css')
    js        = _get_template('summary.js')
    logo      = _logo()
    generated = time.strftime('%Y-%m-%d %H:%M:%S')
    commits   = commits or []

    # ── Nav ───────────────────────────────────────────────────────────────
    nav = (
        '<nav class="kc-nav">'
        '<a href="#stats">Stats</a>'
        '<a href="#profiles">Profiles</a>'
        '<a href="#commits">Commits</a>'
        '</nav>'
    )

    header = (
        '<header class="kc-header">'
        f'<div class="kc-logo">{logo}</div>'
        '<div class="kc-header-text">'
        f'<h1>{title}</h1>'
        f'<p>{VERSION} &nbsp;·&nbsp; generated {generated}</p>'
        '</div>'
        + nav
        + '</header>'
    )

    # ── Stats cards ───────────────────────────────────────────────────────
    rs      = report_stats or {}
    total   = rs.get('total_scored_commits', len(commits))
    min_s   = rs.get('min_score_threshold', '—')
    n_profs = len(profile_summary or {})
    cov     = rs.get('profile_coverage', {})
    cov_pct = f'{cov.get("pct", 0):.0f}%' if isinstance(cov, dict) else str(cov)

    def stat_card(label, value):
        return (
            f'<div class="kc-stat-card">'
            f'<div class="stat-label">{label}</div>'
            f'<div class="stat-value">{value}</div>'
            f'</div>'
        )

    stats_grid = (
        '<div class="kc-stats-grid">'
        + stat_card('Total scored', total)
        + stat_card('Min score', min_s)
        + stat_card('Active profiles', n_profs)
        + stat_card('Profile coverage', cov_pct)
        + '</div>'
    )
    stats_pre    = json.dumps(rs, indent=2, default=str)
    stats_detail = (
        '<details style="padding:0 1rem 1rem">'
        '<summary style="cursor:pointer;color:var(--text-muted);'
        'font-size:.75rem;padding:.5rem 0">Full run stats JSON</summary>'
        f'<pre>{stats_pre}</pre>'
        '</details>'
    )
    stats_section = _section(
        'Run Stats', str(len(commits)) + ' commits',
        stats_grid + stats_detail, anchor='stats')

    # ── Profile summary — plain table (no per-column filter inputs) ───────
    p_rows = []
    for pname, pd in sorted((profile_summary or {}).items(),
                             key=lambda x: -x[1].get('total_score', 0)):
        avg = pd.get('avg_score', 0)
        p_rows.append(
            '<tr>'
            f'<td><span class="profile-chip">{pname}</span></td>'
            f'<td class="num">{pd.get("count", 0)}</td>'
            f'<td class="num">{pd.get("total_score", 0)}</td>'
            f'<td class="num">{avg:.1f}</td>'
            '</tr>'
        )
    prof_content = (
        '<div class="kc-table-wrap">'
        + _plain_table(SUMMARY_COLS, p_rows, table_id='tbl-profiles')
        + '</div>'
    )
    prof_section = _section(
        'Profile Summary',
        str(len(profile_summary or {})) + ' profiles',
        prof_content, anchor='profiles')

    # ── Commits table ──────────────────────────────────────────────────────
    commit_headers = list(COMMIT_COLS)
    if is_filtered:
        commit_headers = commit_headers + ['Filter reason']

    c_rows = [_commit_row_html(i, c, with_reason=is_filtered)
              for i, c in enumerate(commits, 1)]
    commits_content = (
        '<div class="kc-filter-bar"><label>Filter:</label>'
        '<button type="button">Clear all</button></div>'
        '<div class="kc-table-wrap">'
        + _table(commit_headers, c_rows, table_id='tbl-commits')
        + '</div>'
    )
    commits_section = _section(
        'Filtered commits' if is_filtered else 'Relevant commits',
        str(len(commits)) + ' rows',
        commits_content, anchor='commits')

    body = (
        header
        + '<main class="kc-main">'
        + stats_section
        + prof_section
        + commits_section
        + '</main>'
    )

    # Build a SHA→commit lookup and embed it inline so the detail panel
    # needs no network fetch and works from any filesystem location.
    commit_map = {(c.get('commit') or '')[:12]: c for c in commits}
    commits_json = json.dumps(commit_map, default=str)
    inline_data  = f'<script>window.__KC_COMMITS__={commits_json};</script>'

    out = (tpl
           .replace('__TITLE__', f'{title} {VERSION}')
           .replace('__CSS__',   css)
           .replace('__JS__',    js)
           .replace('__BODY__',  body)
           .replace('__COMMITS_DATA__', inline_data))

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(out)
