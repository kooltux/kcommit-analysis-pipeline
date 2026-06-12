"""HTML report generator for kcommit-analysis-pipeline.

Generates self-contained HTML reports with a 3-pane horizontally-resizable
layout:
  Left pane   — pipeline run stats + profiles (collapsible, JS-rendered)
  Middle pane — commit table with typed per-column filters (JS-rendered)
  Right pane  — commit detail panel (opens on SHA click, JS-rendered)

All UI content is data-driven: the generator serialises window.__KC_UI__
(meta, columns, rows, sidebar) into the __COMMITS_DATA__ placeholder; the
browser-side JS in summary.js reads that object and renders everything.

Changes:
  v15.0.0 — Full data-driven rewrite.  Python no longer builds body HTML;
             window.__KC_UI__ replaces all previous __BODY__ / __COMMITS__
             globals.  Template is a static shell (no __BODY__ marker).
"""
import json
import os
import time

from lib.manifest    import VERSION
from lib.scoring     import order_commit_details
from lib.spreadsheet import COMMIT_COLS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _esc(text):
    return (str(text or '')
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))


def _get_template(name, templates_dir, default=''):
    path = os.path.join(templates_dir, name)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return default


def _fmt_date(ts):
    """Unix timestamp → 'YYYY-MM-DD HH:MM' string (UTC)."""
    if not ts:
        return ''
    try:
        import datetime as _dt
        return _dt.datetime.fromtimestamp(
            int(ts), tz=_dt.timezone.utc).strftime('%Y-%m-%d %H:%M')
    except (TypeError, ValueError):
        return str(ts)[:16]


def _profile_scores_text(commit):
    profiles = (((commit or {}).get('scoring') or {}).get('profiles') or {})
    return '; '.join(
        f'{p}:{float(profiles[p] or 0):g}'
        for p in sorted(profiles)
    )


# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------

# Ordered list of columns exposed to the JS table.
# Each entry: (key_in_row_dict, label, js_type)
# js_type is one of: 'string' | 'number' | 'date' | 'select'
_COMMIT_COLUMNS = [
    ('rank',           'Rank',           'number'),
    ('sha12',          'SHA',            'string'),
    ('subject',        'Subject',        'string'),
    ('author',         'Author',         'string'),
    ('date',           'Date',           'date'),
    ('score',          'Score',          'number'),
    ('profiles',       'Profiles',       'select'),
    ('profile_scores', 'Profile scores', 'string'),
]

_FILTERED_EXTRA = ('reason', 'Filter reason', 'string')


def _columns_def(is_filtered, profile_names):
    """Return JS column-definition list."""
    cols = [{'key': k, 'label': l, 'type': t} for k, l, t in _COMMIT_COLUMNS]
    # Populate select options for the Profiles column
    for col in cols:
        if col['key'] == 'profiles' and profile_names:
            col['options'] = sorted(profile_names)
    if is_filtered:
        k, l, t = _FILTERED_EXTRA
        cols.append({'key': k, 'label': l, 'type': t})
    return cols


def _commit_row(i, c, is_filtered=False):
    """Serialize one commit to a flat dict for the JS rows array."""
    sha    = (c.get('commit') or '')
    sha12  = sha[:12]
    profs  = c.get('matched_profiles') or []
    row = {
        'rank':           i,
        'sha12':          sha12,
        'sha':            sha,
        'subject':        c.get('subject') or '',
        'author':         c.get('author_name') or '',
        'date':           _fmt_date(c.get('author_time')),
        'score':          c.get('score', 0) or 0,
        'profiles':       profs,
        'profile_scores': _profile_scores_text(c),
    }
    if is_filtered:
        row['reason'] = c.get('_filter_reason', '')
    return row


# ---------------------------------------------------------------------------
# Sidebar payload
# ---------------------------------------------------------------------------

def _sidebar_payload(report_stats, profile_summary):
    """Build the sidebar dict consumed by the JS left-pane renderer."""
    rs  = report_stats or {}
    ps  = profile_summary or {}

    # Funnel numbers
    collected   = rs.get('st01_collected')
    pf_kept     = rs.get('st04_prefilter_kept')
    pf_drop     = rs.get('st04_prefilter_dropped')
    sc_total    = rs.get('st05_total_scored')
    threshold   = rs.get('st06_threshold', rs.get('min_score_threshold'))
    pf2_kept    = rs.get('st06_postfilter_kept')
    pf2_drop    = rs.get('st06_postfilter_dropped')
    rep_total   = rs.get('total_scored_commits', 0)
    score_hi    = rs.get('score_highest')
    score_lo    = rs.get('score_lowest')
    score_avg   = rs.get('score_avg')
    zero_prof   = rs.get('commits_matched_zero_profiles')
    prod_evid   = rs.get('commits_with_product_evidence')

    # Annotations (kernel-specific flags)
    ann = {}
    for k in ('total_commits', 'is_fix', 'is_fix_and_kept',
              'has_cve', 'has_cve_and_kept',
              'has_syzbot', 'has_syzbot_and_kept',
              'has_stable_cc', 'has_stable_cc_and_kept'):
        if rs.get(k) is not None:
            ann[k] = rs[k]

    # Per-profile scoring summary for sidebar list
    profiles_sidebar = {}
    for pname, pd in sorted(ps.items()):
        profiles_sidebar[pname] = {
            'commits_scored': pd.get('commit_count', pd.get('count', 0)),
            'score_avg':      round(float(pd.get('avg_score', 0) or 0), 1),
        }

    # Stage 04 / 05 / 06 breakdown (run_stats keys)
    def _maybe(v):
        return v if v is not None else None

    # Compute pass_rate
    try:
        pass_rate = round((rep_total / max(int(collected or 0), 1)) * 100, 1)
    except (TypeError, ZeroDivisionError):
        pass_rate = 0.0

    funnel = {
        'collected':           collected,
        'prefilter_kept':      pf_kept,
        'prefilter_dropped':   pf_drop,
        'scored':              sc_total,
        'postfilter_kept':     pf2_kept,
        'postfilter_dropped':  pf2_drop,
        'final_report':        rep_total,
        'pass_rate_pct':       pass_rate,
    }

    stage_05 = {
        'total_scored':          sc_total,
        'zero_score_commits':    zero_prof,
        'multi_profile_commits': rs.get('commits_multi_profile'),
        'profiles':              profiles_sidebar,
    }

    stage_06 = {
        'threshold':          threshold,
        'kept':               pf2_kept,
        'dropped':            pf2_drop,
        'top_score':          score_hi,
        'bottom_kept_score':  score_lo,
    }

    evaluation = rs.get('evaluation') or {}

    sidebar = {
        'funnel':     funnel,
        'stage_05':   {k: v for k, v in stage_05.items() if v is not None},
        'stage_06':   {k: v for k, v in stage_06.items() if v is not None},
        'annotations': ann,
        'evaluation':  evaluation,
    }

    # Drop-reasons detail from run_stats (stage 04)
    drop_reasons = rs.get('st04_drop_reasons')
    if drop_reasons:
        sidebar['stage_04'] = {'drop_reasons': drop_reasons}

    # Dropped subsystems
    dropped_subs = rs.get('st04_dropped_subsystems')
    if dropped_subs:
        sidebar.setdefault('stage_04', {})['dropped_subsystems'] = dropped_subs

    return sidebar


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------

def generate_html_report(commits, profile_summary, report_stats, output_path,
                         title='kcommit-analysis-pipeline',
                         is_filtered=False, templates_dir=None,
                         detail_mode='embedded', commit_index_path=None,
                         commit_detail_root=None, embed_compression='none',
                         metadata_path=None):
    """Write HTML report to *output_path*.

    The report is a self-contained HTML file.  All UI is rendered by
    browser-side JavaScript from the window.__KC_UI__ object serialised
    into the page at generation time.
    """
    if templates_dir is None:
        templates_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'configs', 'html')

    tpl = _get_template('report.html', templates_dir, '')
    if not tpl:
        raise RuntimeError(
            'HTML template missing: ' +
            os.path.join(templates_dir, 'report.html'))
    css = _get_template('summary.css', templates_dir)
    js  = _get_template('summary.js',  templates_dir)

    generated = time.strftime('%Y-%m-%d %H:%M:%S')
    commits   = commits or []

    # ── Column definitions ────────────────────────────────────────────────
    all_profile_names = set()
    for c in commits:
        all_profile_names.update(c.get('matched_profiles') or [])
    cols = _columns_def(is_filtered, all_profile_names)

    # ── Row data ──────────────────────────────────────────────────────────
    rows = [_commit_row(i, c, is_filtered) for i, c in enumerate(commits, 1)]

    # ── Embed full commit detail for sidecar / embedded modes ─────────────
    # In embedded mode we also keep order_commit_details per commit in STORE
    # so that the JS detail panel can look them up by sha12 or full sha.
    commit_store = {}
    if detail_mode == 'embedded':
        for c in commits:
            sha  = (c.get('commit') or '')
            sha12 = sha[:12]
            detail = order_commit_details(c)
            if sha12:
                commit_store[sha12] = detail
            if sha:
                commit_store[sha] = detail

    # ── Meta ──────────────────────────────────────────────────────────────
    rs      = report_stats or {}
    eval_info = rs.get('evaluation') or {}
    meta = {
        'version':      VERSION,
        'generated_at': generated,
        'title':        title,
        'subtitle':     f'{len(commits)} commit{"s" if len(commits) != 1 else ""}',
        'git_range':    eval_info.get('git_range') or rs.get('git_range'),
        'kernel_ver':   eval_info.get('kernel_revision'),
        'profiles':     eval_info.get('profiles'),
    }

    # ── KC_UI payload ─────────────────────────────────────────────────────
    kc_ui = {
        'meta':        meta,
        'columns':     cols,
        'rows':        rows,
        'sidebar':     _sidebar_payload(report_stats, profile_summary),
        'detail_root': commit_detail_root or '',
        'is_filtered': bool(is_filtered),
    }

    # ── Inline <script> block ─────────────────────────────────────────────
    ui_json    = json.dumps(kc_ui,         default=str, separators=(',', ':'))
    store_json = json.dumps(commit_store,  default=str, separators=(',', ':'))

    boot_parts = [
        f'window.__KC_UI__={ui_json};',
        f'window.__KC_COMMITS__={store_json};',
    ]
    if commit_detail_root:
        boot_parts.append(
            'window.__KC_COMMIT_DETAIL_ROOT__=' +
            json.dumps(commit_detail_root) + ';')
    if detail_mode == 'sidecar' and metadata_path:
        boot_parts.append(
            'window.KCOMMIT_REPORT_METADATA_URL=' +
            json.dumps(metadata_path) + ';')

    inline_data = '<script>' + ''.join(boot_parts) + '</script>'

    # ── Subtitle substitution (new placeholder in template) ───────────────
    subtitle = meta['subtitle']

    out = (tpl
           .replace('__TITLE__',        _esc(title))
           .replace('__SUBTITLE__',     _esc(subtitle))
           .replace('__CSS__',          css)
           .replace('__JS__',           js)
           .replace('__COMMITS_DATA__', inline_data))

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(out)
