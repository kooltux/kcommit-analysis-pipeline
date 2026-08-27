"""HTML report generator for kcommit-analysis-pipeline.

Generates self-contained HTML reports with a 3-pane horizontally-resizable
layout:
  Left pane   — pipeline run stats + profiles (collapsible, JS-rendered)
  Middle pane — commit table with typed per-column filters (JS-rendered)
  Right pane  — commit detail panel (opens on SHA click, JS-rendered)

All UI content is data-driven: the generator serialises window.__KC_UI__
(meta, columns, rows, sidebar) into the __COMMITS_DATA__ placeholder; the
browser-side JS reads that object and renders everything.

JS assembly (v18.1.0):
  The browser-side JavaScript is no longer shipped as a pre-built
  configs/html/summary.js artifact.  Instead, _assemble_js() concatenates
  all configs/html/js/summary_*.js modules at report-generation time (sorted
  by filename, which encodes the correct load order via numeric prefixes).
  The concatenated body is wrapped in an IIFE:
    (function(){'use strict'; <modules> })();
  This means summary.js must NOT be committed to the repository; the js/
  modules are the single source of truth.

Changes:
  v15.0.0 — Full data-driven rewrite.  Python no longer builds body HTML;
             window.__KC_UI__ replaces all previous __BODY__ / __COMMITS__
             globals.  Template is a static shell (no __BODY__ marker).
           — Per-profile score columns: each row now carries score_<profile>
             keys; JS expands these into individual table columns.
  v16.6.0 — Left-pane enhancements:
           — Tooltips on every stat label (ⓘ icon, click to toggle on
             mobile, hover on desktop).
           — Score distribution section: histogram + min/max/avg/median.
             Data comes from run_stats stage_05_scoring.score_distribution
             and per-profile score_max/score_min/score_avg already
             computed by _build_stage05() in run_stats.py.
  v16.9.0 — Context section added at the top of the left pane.
           — Exposes kernel.rev_old, kernel.rev_new (commit range),
             build_dir/kernel_build_log/yocto_build_log/dts_roots/
             kernel_config presence as yes/no artifact flags.
           — avg/median bug fixed: _sidebar_payload() now accepts an
             optional run_stats_data kwarg (the full pipeline_run_stats
             dict) and reads stage_05_scoring top-level fields from it;
             falls back to the legacy report_stats path.
           — "evaluation" / "Parameters" section removed from the
             sidebar payload; it is no longer rendered in the left pane.
  v16.14.0 — Unified two-tab HTML report.
           — generate_html_report() accepts a new optional kwarg
             filtered_commits (list of pre- + postfilter dropped commits).
             When supplied, window.__KC_UI__ gains:
               tabs             — [{id, label, count}, ...]
               filtered_columns — slim column definitions (rank, sha12,
                                  subject, author, date, filter_stage,
                                  reason) — no score/profile columns
               filtered_rows    — one slim row dict per filtered commit
               filtered_store   — sha12 → slim commit dict (metadata +
                                  prefilter_debug only; scoring stripped)
             The JS tab switcher reads these keys and renders the filtered
             tab with a purpose-built detail panel.
           — is_filtered parameter and _FILTERED_EXTRA tuple removed;
             tab logic in the JS replaces them.
           — _FILTERED_COLUMNS constant defines the filtered tab columns.
           — _filtered_commit_row() builds slim row dicts; filter_stage
             is derived from presence of prefilter_debug on the commit.
           — _filtered_commit_store_entry() strips scoring fields from
             the commit dict stored in filtered_store.
  v18.1.0 — JS assembly at runtime.
           — configs/html/summary.js removed from the repository.
           — _assemble_js(templates_dir) reads configs/html/js/summary_*.js
             modules in sorted order and wraps them in an IIFE.
           — generate_html_report() calls _assemble_js() instead of
             _get_template('summary.js', ...).
"""
import json
import os
import time

from lib.manifest    import VERSION
from lib.scoring     import order_commit_details
from lib.spreadsheet import COMMIT_COLS

# When there are more commits than this threshold, the full commit detail
# store is NOT inlined (window.__KC_COMMITS__ stays empty).  The JS falls
# back to lazy-loading from sidecar shard files via DROOT.  Row metadata
# (compact per-commit summary for the virtual-scroll table) is always
# inlined inside window.__KC_UI__.rows regardless.
MAX_EMBEDDED_COMMITS = 2000


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


def _assemble_js(templates_dir):
    """Concatenate js/summary_*.js modules (sorted) into one IIFE bundle.

    Modules in configs/html/js/ are named with numeric prefixes
    (summary_01_globals.js … summary_12_bootstrap.js) that encode the
    correct concatenation order.  The resulting bundle is wrapped in a
    strict-mode IIFE so all top-level declarations remain local to the
    report's script tag.

    Returns an empty string if the js/ directory does not exist or
    contains no .js files (graceful degradation for tests that supply
    a minimal template directory without the full js/ tree).
    """
    js_dir = os.path.join(templates_dir, 'js')
    try:
        files = sorted(f for f in os.listdir(js_dir) if f.endswith('.js'))
    except OSError:
        return ''
    parts = []
    for fname in files:
        path = os.path.join(js_dir, fname)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                parts.append(f.read())
        except OSError:
            pass
    if not parts:
        return ''
    body = '\n'.join(parts)
    return "(function(){'use strict';\n" + body + "\n})();"


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


def _extract_author_org(email):
    """Extract organization domain from author email address.
    
    Returns the domain part after '@' if email is valid, otherwise empty string.
    """
    if not email:
        return ''
    parts = str(email).rsplit('@', 1)
    if len(parts) == 2:
        return parts[1]
    return ''


# ---------------------------------------------------------------------------
# Column definitions — relevant tab
# ---------------------------------------------------------------------------

# Base columns — profile_scores is removed; JS inserts per-profile columns
# dynamically after the "score" column using score_<profile> row keys.
#
# Each entry is (key, label, type[, hidden]).  hidden=True columns are still
# emitted as row data (so their values remain available for search, future
# views and detail rendering) but are dropped from the *visible* table by the
# browser-side JS (they behave like invisible columns).  files/lines/hunks are
# hidden by default to keep the table narrow; the same numbers are surfaced in
# the commit-detail Overview tab and in the spreadsheet exports (COMMIT_COLS).
_COMMIT_COLUMNS = [
    ('rank',          '#',              'number'),
    ('sha12',         'SHA',            'string'),
    ('subject',       'Subject',        'string'),
    ('author_org',    'ORG',            'string'),
    ('date',          'Date',           'date'),
    # Pick priority is the primary triage indicator (higher = more relevant & easier)
    ('pick_priority', 'Pick\nPriority', 'number'),
    # Score (normalized 0-100) — bounded, colour-comparable signal.
    # The raw score is hidden below.
    ('score_norm',    'Score',          'number'),
    # Backport complexity — higher = harder to backport.
    ('backport_cx',   'Complexity',     'number'),
    ('profiles',      'Profiles',       'select'),
    # Hidden columns: raw data kept for search/export but not shown in table.
    ('score',         'Score (raw)',    'number',  True),
    ('files',         'Files Changed',  'number',  True),
    ('lines',         'Lines Changed',  'number',  True),
    ('hunks',         'Hunks',          'number',  True),
]

# Default table sort: highest pick_priority first (look at the best
# relevant + easy-to-backport commits first).
_DEFAULT_SORT = {'key': 'pick_priority', 'dir': -1}


def _columns_def(profile_names):
    """Return JS column-definition list for the relevant-commits tab.

    Columns flagged hidden in _COMMIT_COLUMNS carry ``hidden: True`` so the
    browser-side JS can keep their row values while dropping them from the
    visible table (invisible columns).
    """
    cols = []
    for spec in _COMMIT_COLUMNS:
        k, l, t = spec[0], spec[1], spec[2]
        hidden = len(spec) > 3 and bool(spec[3])
        col = {'key': k, 'label': l, 'type': t}
        if hidden:
            col['hidden'] = True
        cols.append(col)
    for col in cols:
        if col['key'] == 'profiles' and profile_names:
            col['options'] = sorted(profile_names)
    return cols


def _commit_row(i, c, all_profiles=None):
    """Serialize one relevant commit to a flat dict for the JS rows array.

    Per-profile scores are stored as ``score_<profile>`` keys so that the
    browser-side JS can render one column per profile without any extra
    server-side column enumeration.
    """
    sha   = (c.get('commit') or '')
    sha12 = sha[:12]
    profs = c.get('matched_profiles') or []
    stats = c.get('stats') or {}

    row = {
        'rank':     i,
        'sha12':    sha12,
        'sha':      sha,
        'subject':  c.get('subject') or '',
        'author_org': _extract_author_org(c.get('author_email', '')),
        'date':     _fmt_date(c.get('author_time')),
        'score':    c.get('score', 0) or 0,
        'score_norm': c.get('score_norm', 0) or 0,
        'files':    stats.get('files_changed', 0) or 0,
        'lines':    stats.get('lines_changed', 0) or 0,
        'hunks':    stats.get('hunks', 0) or 0,
        'backport_cx':   c.get('backport_complexity', 0) or 0,
        'pick_priority': c.get('pick_priority', 0) or 0,
        'profiles': profs,
    }

    # Per-profile scores — emit 0 for profiles not matched by this commit
    prof_scores = (((c.get('scoring') or {}).get('profiles')) or {})
    for p in (all_profiles or []):
        row[f'score_{p}'] = float(prof_scores.get(p) or 0)

    return row


# ---------------------------------------------------------------------------
# Column definitions — filtered tab (v16.14.0)
# ---------------------------------------------------------------------------

# Slim column set for the filtered tab.  Intentionally omits score, profiles,
# and all score_<profile> keys — those fields are meaningless for commits that
# were dropped before (or immediately after) the scoring stage.
_FILTERED_COLUMNS = [
    ('rank',         'Rank',         'number'),
    ('sha12',        'SHA',          'string'),
    ('subject',      'Subject',      'string'),
    ('author_org',   'Author Organization', 'string'),
    ('date',         'Date',         'date'),
    ('filter_stage', 'Filter stage', 'select'),
    ('reason',       'Drop reason',  'string'),
]

_FILTERED_STAGE_OPTIONS = ['prefilter', 'postfilter']


def _filtered_columns_def():
    """Return JS column-definition list for the filtered-commits tab."""
    cols = [{'key': k, 'label': l, 'type': t} for k, l, t in _FILTERED_COLUMNS]
    for col in cols:
        if col['key'] == 'filter_stage':
            col['options'] = _FILTERED_STAGE_OPTIONS
    return cols


def _filtered_commit_row(i, c):
    """Serialize one filtered commit to a slim flat dict.

    filter_stage is derived from the presence of prefilter_debug on the
    commit: commits carrying that key were dropped by the prefilter stage
    (st04); all others were dropped by the postfilter (st06).

    drop_reason is read from prefilter_debug.drop_reason when available,
    falling back to the legacy _filter_reason field written by st06.
    """
    sha   = (c.get('commit') or '')
    sha12 = sha[:12]

    pf_debug = c.get('prefilter_debug') or {}
    if pf_debug:
        filter_stage = 'prefilter'
        reason = (pf_debug.get('drop_reason')
                  or pf_debug.get('reason')
                  or c.get('_filter_reason', ''))
    else:
        filter_stage = 'postfilter'
        reason = c.get('_filter_reason', '')

    return {
        'rank':         i,
        'sha12':        sha12,
        'sha':          sha,
        'subject':      c.get('subject') or '',
        'author_org':   _extract_author_org(c.get('author_email', '')),
        'date':         _fmt_date(c.get('author_time')),
        'filter_stage': filter_stage,
        'reason':       reason,
    }


# Scoring-related keys stripped from the filtered_store entries so that
# the detail panel cannot accidentally render irrelevant scoring data.
_SCORING_KEYS = frozenset({
    'scoring', 'score', 'matched_profiles', 'product_evidence',
    'coverage', '_rank', '_filter_reason',
})


def _filtered_commit_store_entry(c):
    """Return a slim commit dict suitable for filtered_store.

    Retains: commit identity fields, commit message metadata, files list,
    and prefilter_debug.  Strips all scoring-related keys.
    """
    return {k: v for k, v in c.items() if k not in _SCORING_KEYS}


# ---------------------------------------------------------------------------
# Context payload helpers
# ---------------------------------------------------------------------------

def _bool_flag(value):
    """Return 'yes' / 'no' / None depending on whether value is a truthy path/bool."""
    if value is None:
        return None
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, (list, tuple)):
        return 'yes' if value else 'no'
    s = str(value).strip()
    return 'yes' if s else None


def _build_context(cfg, report_stats):
    """Build the context dict surfaced at the top of the left pane (v16.9.0).

    Exposes:
      rev_old / rev_new  — the analyzed commit range from kernel config
      rev_range          — combined 'rev_old..rev_new' string
      git_range          — from evaluation block (may differ if overridden)
      kernel_version     — kernel version string if available
      artifacts          — dict of artifact-type → 'yes'/'no'
      profiles           — comma-separated list of active profiles
      title              — report title
    """
    kernel  = (cfg.get('kernel')  or {}) if isinstance(cfg, dict) else {}
    reports = (cfg.get('reports') or {}) if isinstance(cfg, dict) else {}
    profs   = (cfg.get('profiles') or {}).get('active', {}) if isinstance(cfg, dict) else {}

    rev_old = kernel.get('rev_old') or ''
    rev_new = kernel.get('rev_new') or ''
    rev_range = f'{rev_old}..{rev_new}' if rev_old and rev_new else (rev_old or rev_new or '')

    # Evaluation block may carry a git_range computed from git.base_rev/head_rev
    eval_info  = (report_stats or {}).get('evaluation') or {}
    git_range  = eval_info.get('git_range') or rev_range or ''
    kernel_ver = kernel.get('kernel_version') or eval_info.get('kernel_revision') or ''

    artifacts = {}
    if _bool_flag(kernel.get('build_dir')):
        artifacts['build_dir'] = _bool_flag(kernel.get('build_dir'))
    if _bool_flag(kernel.get('kernel_build_log')):
        artifacts['kernel_build_log'] = _bool_flag(kernel.get('kernel_build_log'))
    if _bool_flag(kernel.get('yocto_build_log')):
        artifacts['yocto_build_log'] = _bool_flag(kernel.get('yocto_build_log'))
    if _bool_flag(kernel.get('kernel_config')):
        artifacts['kernel_config'] = _bool_flag(kernel.get('kernel_config'))
    if _bool_flag(kernel.get('dts_roots')):
        artifacts['dts_roots'] = _bool_flag(kernel.get('dts_roots'))

    active_profiles = sorted(profs.keys()) if isinstance(profs, dict) else []

    return {
        'rev_old':        rev_old or None,
        'rev_new':        rev_new or None,
        'rev_range':      rev_range or None,
        'git_range':      git_range or None,
        'kernel_version': kernel_ver or None,
        'artifacts':      artifacts,
        'profiles':       active_profiles,
        'title':          reports.get('title') or None,
    }


# ---------------------------------------------------------------------------
# Sidebar payload
# ---------------------------------------------------------------------------

def _sidebar_payload(report_stats, profile_summary, run_stats_data=None):
    """Build the sidebar dict consumed by the JS left-pane renderer.

    v16.9.0 changes:
      - run_stats_data: the full pipeline_run_stats dict (written by
        build_run_stats() at the end of stage 07).  When provided, the
        stage_05_scoring top-level fields (score_max, score_min, score_avg,
        score_median, score_distribution) are read from it directly, fixing
        the avg/median = 0 bug that occurred when only report_stats was
        available (which does not carry stage_05_scoring).
      - 'evaluation' key removed from the returned dict; the JS Parameters
        section is gone.
    """
    rs  = report_stats or {}
    ps  = profile_summary or {}

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
    zero_prof   = rs.get('commits_matched_zero_profiles')

    ann = {}
    for k in ('total_commits', 'is_fix', 'is_fix_and_kept',
              'has_cve', 'has_cve_and_kept',
              'has_syzbot', 'has_syzbot_and_kept',
              'has_stable_cc', 'has_stable_cc_and_kept'):
        if rs.get(k) is not None:
            ann[k] = rs[k]

    # v16.9.0: prefer run_stats_data (full pipeline_run_stats) for the
    # stage_05_scoring block — it contains the correct global avg/median.
    # Fall back to the legacy rs.get('stage_05_scoring') path for backwards
    # compatibility when run_stats_data is not passed.
    rsd = run_stats_data or {}
    st05_full = rsd.get('stage_05_scoring') or rs.get('stage_05_scoring') or {}
    st05_profiles_full = st05_full.get('profiles') or {}

    profiles_sidebar = {}
    for pname, pd in sorted(ps.items()):
        full = st05_profiles_full.get(pname) or {}
        profiles_sidebar[pname] = {
            'commits_scored': pd.get('commit_count', pd.get('count', 0)),
            'score_avg':      round(float(pd.get('avg_score', 0) or 0), 1),
            'score_max':      int(full.get('score_max', 0) or 0),
            'score_min':      int(full.get('score_min', 0) or 0),
            'score_distribution': full.get('score_distribution') or [],
        }

    # v16.9.0: global score distribution and stats — now correctly read from
    # the top-level of stage_05_scoring (populated by run_stats._build_stage05
    # since v16.8.0).  When run_stats_data is supplied these fields are always
    # present and non-zero.
    score_dist = (st05_full.get('score_distribution') or {}).get('items') or []

    st05_glob = {
        'score_max':    int(st05_full.get('score_max', score_hi or 0) or 0),
        'score_min':    int(st05_full.get('score_min', score_lo or 0) or 0),
        'score_avg':    round(float(st05_full.get('score_avg', 0) or 0), 1),
        'score_median': round(float(st05_full.get('score_median', 0) or 0), 1),
        'distribution': score_dist,
    }

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
        'score_stats':           st05_glob,
    }

    stage_06 = {
        'threshold':         threshold,
        'kept':              pf2_kept,
        'dropped':           pf2_drop,
        'top_score':         score_hi,
        'bottom_kept_score': score_lo,
    }

    sidebar = {
        'funnel':   funnel,
        'stage_05': {k: v for k, v in stage_05.items() if v is not None},
        'stage_06': {k: v for k, v in stage_06.items() if v is not None},
        'annotations': ann,
        # 'evaluation' intentionally omitted in v16.9.0 — the Parameters
        # section has been replaced by the Context block rendered separately.
    }

    drop_reasons = rs.get('st04_drop_reasons')
    if drop_reasons:
        sidebar['stage_04'] = {'drop_reasons': drop_reasons}

    dropped_subs = rs.get('st04_dropped_subsystems')
    if dropped_subs:
        sidebar.setdefault('stage_04', {})['dropped_subsystems'] = dropped_subs

    return sidebar


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------

def generate_html_report(commits, profile_summary, report_stats, output_path,
                         title='kcommit-analysis-pipeline',
                         filtered_commits=None,
                         templates_dir=None,
                         detail_mode='embedded', commit_index_path=None,
                         commit_detail_root=None, embed_compression='none',
                         metadata_path=None, cfg=None, run_stats_data=None):
    """Write a unified HTML report to *output_path*.

    When *filtered_commits* is supplied (non-empty list), the report renders
    a two-tab UI:
      Tab 1 — Relevant Commits  (existing 3-pane layout, all columns)
      Tab 2 — Filtered Commits  (slim columns: rank, sha, subject, author,
                                  date, filter_stage, drop reason; no scoring
                                  data; purpose-built detail panel)

    When *filtered_commits* is None or empty, the report is identical to
    the pre-v16.14.0 single-tab layout (zero regression).

    New kwargs (v16.9.0):
      cfg            -- full pipeline config dict; used to build the Context
                        block (kernel.rev_old/rev_new, artifact flags, etc.).
      run_stats_data -- full pipeline_run_stats dict returned/written by
                        build_run_stats(); provides correct global score_avg
                        and score_median for the Score Distribution block.

    New kwargs (v16.14.0):
      filtered_commits -- list of pre- + postfilter dropped commit dicts.
                          When provided, adds tabs/filtered_columns/
                          filtered_rows/filtered_store to window.__KC_UI__.

    v18.1.0 — JS is assembled at runtime from configs/html/js/summary_*.js
    modules via _assemble_js(); configs/html/summary.js is no longer used.
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
    js  = _assemble_js(templates_dir)

    generated = time.strftime('%Y-%m-%d %H:%M')
    commits   = commits or []
    filtered  = filtered_commits or []

    # ── Profile name universe (relevant tab only) ─────────────────────────
    all_profile_names = sorted({
        p
        for c in commits
        for p in (c.get('matched_profiles') or [])
    })

    # ── Column definitions ────────────────────────────────────────────────
    cols = _columns_def(all_profile_names)

    # ── Row data (relevant tab) ───────────────────────────────────────────
    rows = [
        _commit_row(i, c, all_profile_names)
        for i, c in enumerate(commits, 1)
    ]

    # ── Embed full commit detail — relevant tab (embedded mode) ───────────
    commit_store = {}
    if detail_mode == 'embedded' and len(commits) <= MAX_EMBEDDED_COMMITS:
        for c in commits:
            sha   = (c.get('commit') or '')
            sha12 = sha[:12]
            detail = order_commit_details(c)
            if sha12: commit_store[sha12] = detail

    # ── Filtered tab data (v16.14.0) ──────────────────────────────────────
    tabs             = None
    filtered_cols    = None
    filtered_rows    = None
    filtered_store   = None

    if filtered:
        tabs = [
            {'id': 'relevant', 'label': 'Relevant Commits', 'count': len(commits)},
            {'id': 'filtered', 'label': 'Filtered Commits',  'count': len(filtered)},
        ]
        filtered_cols  = _filtered_columns_def()
        filtered_rows  = [
            _filtered_commit_row(i, c)
            for i, c in enumerate(filtered, 1)
        ]
        # Slim store: sha12 → metadata + prefilter_debug, no scoring keys
        filtered_store = {}
        if len(filtered) <= MAX_EMBEDDED_COMMITS:
            for c in filtered:
                sha   = (c.get('commit') or '')
                sha12 = sha[:12]
                entry = _filtered_commit_store_entry(c)
                if sha12: filtered_store[sha12] = entry

    # ── Meta ──────────────────────────────────────────────────────────────
    rs        = report_stats or {}
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

    # ── Context block (v16.9.0) ───────────────────────────────────────────
    context = _build_context(cfg or {}, report_stats)

    # ── KC_UI payload ─────────────────────────────────────────────────────
    kc_ui = {
        'meta':        meta,
        'context':     context,
        'columns':     cols,
        'default_sort': dict(_DEFAULT_SORT),
        'rows':        rows,
        'sidebar':     _sidebar_payload(report_stats, profile_summary,
                                        run_stats_data=run_stats_data),
        'detail_root': commit_detail_root or '',
    }

    # Tabs payload — only present when filtered commits were supplied
    if tabs is not None:
        kc_ui['tabs']              = tabs
        kc_ui['filtered_columns']  = filtered_cols
        kc_ui['filtered_rows']     = filtered_rows

    ui_json    = json.dumps(kc_ui,            default=str, separators=(',', ':'))
    store_json = json.dumps(commit_store,     default=str, separators=(',', ':'))

    boot_parts = [
        f'window.__KC_UI__={ui_json};',
        f'window.__KC_COMMITS__={store_json};',
    ]

    # Filtered store serialised separately to keep the main KC_UI payload
    # lean and allow the JS to load it lazily on first tab switch.
    if filtered_store is not None:
        fstore_json = json.dumps(filtered_store, default=str, separators=(',', ':'))
        boot_parts.append(f'window.__KC_FILTERED_COMMITS__={fstore_json};')

    if commit_detail_root:
        boot_parts.append(
            'window.__KC_COMMIT_DETAIL_ROOT__=' +
            json.dumps(commit_detail_root) + ';')
    if detail_mode == 'sidecar' and metadata_path:
        boot_parts.append(
            'window.KCOMMIT_REPORT_METADATA_URL=' +
            json.dumps(metadata_path) + ';')

    inline_data = '<script>' + ''.join(boot_parts) + '</script>'
    subtitle    = meta['subtitle']

    out = (tpl
           .replace('__TITLE__',        _esc(title))
           .replace('__SUBTITLE__',     _esc(subtitle))
           .replace('__CSS__',          css)
           .replace('__JS__',           js)
           .replace('__COMMITS_DATA__', inline_data))

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(out)
