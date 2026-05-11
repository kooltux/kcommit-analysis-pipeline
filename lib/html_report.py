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
        + '<button class="kc-theme-btn" id="kc-theme-toggle" aria-label="Toggle light/dark theme" title="Toggle theme"><svg viewBox="0 0 24 24" aria-hidden="true" id="kc-theme-icon"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>Theme</button>'
        '</header>'
    )

    # ── Sidebar ───────────────────────────────────────────────────────────
    def _srow(label, value, cls=''):
        cls_attr = f' class="{cls}"' if cls else ''
        return (
            f'<div class="kc-stat-row{cls_attr}">'
            f'<span class="kc-stat-label">{label}</span>'
            f'<span class="kc-stat-value">{value}</span>'
            f'</div>'
        )

    def _stage_block(icon, title, rows_html, stage_id=''):
        id_attr = f' id="sidebar-{stage_id}"' if stage_id else ''
        return (
            f'<div class="kc-stage-block"{id_attr}>'
            f'<div class="kc-stage-header"><span class="kc-stage-icon">{icon}</span>'
            f'<span class="kc-stage-title">{title}</span></div>'
            + rows_html
            + '</div>'
        )

    def _fmt_n(v, fallback='—'):
        try:
            n = int(v)
            return f'{n:,}'
        except (TypeError, ValueError):
            return fallback if v is None else str(v)

    def _fmt_score(v, fallback='—'):
        try:
            return f'{float(v):g}'
        except (TypeError, ValueError):
            return fallback if v is None else str(v)

    # Stage 01 – Collection
    collected   = rs.get('st01_collected')
    collect_cfg = cfg.get('collect', {}) if 'cfg' in dir() else {}
    pf_kept     = rs.get('st04_prefilter_kept')
    pf_drop     = rs.get('st04_prefilter_dropped')
    sc_total    = rs.get('st05_total_scored')
    threshold   = rs.get('st06_threshold', rs.get('min_score_threshold'))
    pf2_drop    = rs.get('st06_postfilter_dropped')
    rep_total   = rs.get('total_scored_commits', len(commits))
    top_n_val   = rs.get('top_n')
    score_hi    = rs.get('score_highest')
    score_lo    = rs.get('score_lowest')
    score_avg   = rs.get('score_avg')
    zero_prof   = rs.get('commits_matched_zero_profiles')
    prod_evid   = rs.get('commits_with_product_evidence')

    stage_collection = _stage_block('①', 'Collection',
        _srow('Total commits',    _fmt_n(collected) if collected is not None else _fmt_n(rep_total)),
        stage_id='collect')

    stage_prefilter = _stage_block('②', 'Pre-filter',
        (_srow('Kept',    _fmt_n(pf_kept))    if pf_kept    is not None else '')
      + (_srow('Dropped', _fmt_n(pf_drop), 'dim') if pf_drop   is not None else ''),
        stage_id='prefilter')

    stage_scoring = _stage_block('③', 'Scoring',
        (_srow('Scored',    _fmt_n(sc_total))  if sc_total is not None else _srow('Scored', _fmt_n(rep_total)))
      + (_srow('Profiles',  str(n_profs)))
      + (_srow('Coverage',  cov_pct)),
        stage_id='scoring')

    thr_label = f'Threshold ({_fmt_score(threshold)})' if threshold else 'Threshold'
    stage_postfilter = _stage_block('④', 'Post-filter',
        _srow(thr_label,   _fmt_score(threshold) if threshold else 'none')
      + (_srow('Dropped',  _fmt_n(pf2_drop), 'dim') if pf2_drop is not None else ''),
        stage_id='postfilter')

    top_n_note = f' (top {top_n_val:,})' if top_n_val else ''
    stage_report = _stage_block('⑤', f'Report{top_n_note}',
        _srow('Commits',       _fmt_n(rep_total))
      + (_srow('Score highest', _fmt_score(score_hi))   if score_hi  is not None else '')
      + (_srow('Score lowest',  _fmt_score(score_lo))   if score_lo  is not None else '')
      + (_srow('Score avg',     _fmt_score(score_avg))  if score_avg is not None else '')
      + (_srow('No-profile',   _fmt_n(zero_prof), 'dim')  if zero_prof is not None else '')
      + (_srow('With evidence', _fmt_n(prod_evid))        if prod_evid is not None else ''),
        stage_id='report')

    sidebar_stats = (
        '<div class="kc-sidebar-section kc-pipeline-stats"><h3>Pipeline Run</h3>'
        + stage_collection
        + stage_prefilter
        + stage_scoring
        + stage_postfilter
        + stage_report
        + '</div>'
    )

    prof_items = []
    for pname, pd in sorted((profile_summary or {}).items(),
                             key=lambda x: -x[1].get('total_score', 0)):
        cnt     = pd.get('commit_count', pd.get('count', 0))
        avg_sc  = pd.get('avg_score', 0)
        prof_items.append(
            f'<li><span class="pname">{pname}</span>'
            f'<span class="pbadge">{cnt}</span>'
            f'<span class="pavg" title="avg score">⌀{avg_sc:.0f}</span></li>'
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
        + '<span class="kc-live-count" aria-live="polite">'
        + 'Showing ' + str(len(commits)) + ' of ' + str(len(commits)) + ' commits'
        + '</span>'
        '<button type="button" class="kc-clear-filters">Clear all</button>'
        '<button type="button" class="kc-export-filtered-csv">↓ Export filtered CSV</button>'
        '</div>'
        '<div class="kc-table-wrap" aria-busy="false">'
        + '<div class="kc-table-busy" aria-hidden="true"><div class="spinner"></div><div class="label">Filtering commits…</div></div>'
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
            boot.append('window.__KC_COMMITS_FALLBACK__=' + commits_json + ';')
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
