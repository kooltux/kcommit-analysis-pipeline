"""HTML report generator for kcommit-analysis-pipeline.

Generates self-contained HTML reports with embedded or sidecar-backed
commit detail panes. Commit details include rule-match/score analysis
from scoring.trace when present.

Column definitions (COMMIT_COLS, SUMMARY_COLS, MATRIX_COLS) are the
canonical source in lib.manifest and imported here via lib.spreadsheet.
"""
import base64
import json
import os
import time
import zlib

from lib.manifest    import VERSION
from lib.scoring     import order_commit_details
from lib.spreadsheet import COMMIT_COLS, SUMMARY_COLS, MATRIX_COLS


def _esc(text):
    return (str(text or '')
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('\"', '&quot;'))



def _get_template(name, templates_dir, default=''):
    path = os.path.join(templates_dir, name)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return default


def _logo(templates_dir):
    return _get_template('logo.svg', templates_dir, '')


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


def _profile_scores_text(commit):
    profiles = (((commit or {}).get('scoring') or {}).get('profiles') or {})
    parts = []
    for pname in sorted(profiles):
        try:
            score = float(profiles.get(pname, 0) or 0)
        except (TypeError, ValueError):
            score = 0.0
        parts.append(f'{pname}:{score:g}')
    return '; '.join(parts)


def _th(label):
    return (f'<th><span class="col-label">{label}</span>'
            f'<i class="sort-icon">⇅</i></th>')


def _table(headers, rows_html, table_id=''):
    """Table with sticky header row + per-column filter row."""
    id_attr = f' id="{table_id}"' if table_id else ''
    thead = (
        '<thead>'
        '<tr class="kc-col-headers">'
        + ''.join(_th(h) for h in headers)
        + '</tr>'
        '<tr class="kc-filters">'
        + ''.join('<th><input type="text" placeholder="filter…  >N <N foo*" aria-label="filter column"></th>' for _ in headers)
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



def _commit_row_html(i, c, with_reason=False):
    """Build a <tr> for a commit.  Matches COMMIT_COLS (from lib.manifest)."""
    sha    = (c.get('commit') or '')
    sha12  = sha[:12]
    subj   = c.get('subject') or ''
    author = c.get('author_name') or ''
    _ts    = c.get('author_time') or ''
    try:
        import datetime as _dt
        date = _dt.datetime.fromtimestamp(int(_ts), tz=_dt.timezone.utc).strftime('%Y-%m-%d %H:%M') if _ts else ''
    except (TypeError, ValueError):
        date = str(_ts)[:16]
    score  = c.get('score', 0) or 0
    profs  = c.get('matched_profiles') or []
    prof_scores = _profile_scores_text(c)
    evid   = '; '.join(c.get('product_evidence') or [])

    sha_link = (
        f'<a class="sha-link" data-sha="{sha12}" data-full-sha="{sha}" href="#"'
        f' title="Show commit details">{sha12}</a>'
    )

    cells = [
        f'<td class="rank">{i}</td>',
        f'<td class="sha">{sha_link}</td>',
        f'<td>{subj}</td>',
        f'<td>{author}</td>',
        f'<td class="num">{date}</td>',
        f'<td class="num" data-sort="{float(score or 0):.6f}">{_score_pill(score)}</td>',
        f'<td>{_profile_chips(profs)}</td>',
        f'<td><small>{prof_scores}</small></td>',
        f'<td><small>{evid}</small></td>',
    ]
    if with_reason:
        reason = c.get('_filter_reason', '')
        cells.append(f'<td><small>{reason}</small></td>')
    return '<tr>' + ''.join(cells) + '</tr>'


def _section(title, badge, content, anchor):
    assert anchor, "_section() requires a non-empty anchor"
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
                         is_filtered=False, templates_dir=None,
                         detail_mode='embedded', commit_index_path=None,
                         commit_detail_root=None, embed_compression='none'):
    """Write HTML report to *output_path*.

    Section order: Run Stats → Profile Summary → Commits table.
    Commit table columns match COMMIT_COLS imported from lib.manifest.
    """
    if templates_dir is None:
        templates_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'configs', 'html')
    tpl  = _get_template('report.html', templates_dir, '__BODY__')
    if '__BODY__' not in tpl:
        raise RuntimeError(
            'HTML template missing or invalid: expected __BODY__ marker in '
            + os.path.join(templates_dir, 'report.html'))
    css  = _get_template('summary.css', templates_dir)
    js   = _get_template('summary.js', templates_dir)
    logo = _logo(templates_dir)
    generated = time.strftime('%Y-%m-%d %H:%M:%S')
    commits   = commits or []

    # ── Header ────────────────────────────────────────────────────────────
    rs      = report_stats or {}
    total   = rs.get('total_scored_commits', len(commits))
    min_s   = rs.get('min_score_threshold', '—')
    n_profs = len(profile_summary or {})
    cov     = rs.get('profile_coverage', {})
    cov_pct = f'{cov.get("pct", 0):.0f}%' if isinstance(cov, dict) else str(cov)

    header = (
        '<header class="kc-header">'
        f'<div class="kc-logo">{logo}</div>'
        '<div class="kc-header-text">'
        f'<h1>{title}</h1>'
        f'<p>{VERSION} &nbsp;·&nbsp; generated {generated}</p>'
        '</div>'
        '<div class="kc-header-spacer"></div>'
        '<nav class="kc-nav"><a href="#commits">Commits</a></nav>'
        '</header>'
    )

    # ── Sidebar ───────────────────────────────────────────────────────────
    def stat_card(label, value):
        return (
            f'<div class="kc-stat-card">'
            f'<div class="stat-label">{label}</div>'
            f'<div class="stat-value">{value}</div>'
            f'</div>'
        )

    sidebar_stats = (
        '<div class="kc-sidebar-section"><h3>Run Stats</h3>'
        + stat_card('Commits', total)
        + stat_card('Min score', min_s)
        + stat_card('Profiles', n_profs)
        + stat_card('Coverage', cov_pct)
        + '</div>'
    )

    prof_items = []
    for pname, pd in sorted((profile_summary or {}).items(),
                             key=lambda x: -x[1].get('total_score', 0)):
        cnt = pd.get('commit_count', pd.get('count', 0))
        prof_items.append(
            f'<li><span class="pname">{pname}</span>'
            f'<span class="pbadge">{cnt} commits</span></li>'
        )
    sidebar_profiles = (
        '<div class="kc-sidebar-section"><h3>Profiles</h3>'
        f'<ul class="kc-profile-list">{"".join(prof_items)}</ul>'
        '</div>'
    ) if prof_items else ''

    sidebar = (
        '<aside class="kc-sidebar">'
        + sidebar_stats
        + sidebar_profiles
        + '</aside>'
    )

    # ── Commits table ─────────────────────────────────────────────────────
    commit_headers = list(COMMIT_COLS)
    if is_filtered:
        commit_headers = commit_headers + ['Filter reason']

    c_rows = [_commit_row_html(i, c, with_reason=is_filtered)
              for i, c in enumerate(commits, 1)]
    commits_content = (
        '<div class="kc-filter-bar">'
        '<label>Search:</label>'
        '<input class="kc-global-filter" type="text"'
        ' placeholder="search all columns…" aria-label="global search">'
        '<button type="button">Clear all</button>'
        '</div>'
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
        + '<div class="kc-layout">'
        + sidebar
        + '<main class="kc-main">'
        + commits_section
        + '</main>'
        + '</div>'
    )

    commit_map = {(c.get('commit') or '')[:12]: order_commit_details(c) for c in commits}
    boot = []
    if commit_detail_root:
        boot.append('window.__KC_COMMIT_DETAIL_ROOT__=' + json.dumps(commit_detail_root) + ';')
    if detail_mode == 'sidecar' and commit_index_path:
        boot.append('window.__KC_COMMITS_INDEX__=' + json.dumps({'mode': 'sidecar', 'path': commit_index_path}) + ';')
    else:
        commits_json = json.dumps(commit_map, default=str, separators=(',', ':'))
        if embed_compression == 'zlib':
            compressed = base64.b64encode(zlib.compress(commits_json.encode('utf-8'), 9)).decode('ascii')
            boot.append('window.__KC_COMMITS_COMPRESSED__=' + json.dumps(compressed) + ';')
            boot.append('window.__KC_COMMITS_COMPRESSION__=' + json.dumps('zlib') + ';')
        else:
            boot.append('window.__KC_COMMITS__=' + commits_json + ';')
    inline_data = '<script>' + ''.join(boot) + '</script>'

    out = (tpl
           .replace('__TITLE__', f'{title} {VERSION}')
           .replace('__CSS__',   css)
           .replace('__JS__',    js)
           .replace('__BODY__',  body)
           .replace('__COMMITS_DATA__', inline_data))

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(out)
