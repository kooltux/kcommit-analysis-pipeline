"""Tests for lib.html_report — template handling and HTML output (v15)."""
import json
import os

from lib.html_report import generate_html_report


def _tpl_dir(tmp_path):
    """Minimal template dir for isolated tests (no __BODY__ marker)."""
    tpl_dir = tmp_path / 'tpl'
    tpl_dir.mkdir()
    (tpl_dir / 'report.html').write_text(
        '<html><head><title>__TITLE__</title><style>__CSS__</style>'
        '__COMMITS_DATA__</head><body>'
        '<span id="kc-subtitle">__SUBTITLE__</span>'
        '<script>__JS__</script></body></html>'
    )
    (tpl_dir / 'summary.css').write_text('.seed{}')
    (tpl_dir / 'summary.js').write_text('/* test js */')
    return tpl_dir


def _kc_ui(txt):
    """Extract and parse window.__KC_UI__ from rendered HTML."""
    marker = 'window.__KC_UI__='
    idx = txt.index(marker) + len(marker)
    obj, _ = json.JSONDecoder().raw_decode(txt, idx)
    return obj


# ---------------------------------------------------------------------------
# Basic generation
# ---------------------------------------------------------------------------

def test_generate_html_report_writes_file(tmp_path):
    tpl_dir = _tpl_dir(tmp_path)
    out = tmp_path / 'report.html'
    generate_html_report([], {}, {}, str(out), templates_dir=str(tpl_dir))
    assert out.exists()


def test_generate_html_report_raises_on_missing_template(tmp_path):
    """RuntimeError when the template file does not exist at all."""
    tpl_dir = tmp_path / 'empty_tpl'
    tpl_dir.mkdir()
    (tpl_dir / 'summary.css').write_text('')
    (tpl_dir / 'summary.js').write_text('')
    out = tmp_path / 'report.html'
    import pytest
    with pytest.raises(RuntimeError):
        generate_html_report([], {}, {}, str(out), templates_dir=str(tpl_dir))


def test_html_report_embeds_commit_map(tmp_path):
    tpl_dir = _tpl_dir(tmp_path)
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'abc123456789' + 'f' * 28, 'subject': 'subj', 'body': 'body',
        'author_name': 'A', 'author_time': 1700000000,
        'score': 10, 'matched_profiles': ['p'], 'product_evidence': []
    }]
    generate_html_report(commits, {}, {}, str(out), templates_dir=str(tpl_dir))
    txt = out.read_text()
    assert 'window.__KC_COMMITS__' in txt
    assert 'abc123456789' in txt


def test_html_report_embeds_kc_ui_payload(tmp_path):
    """window.__KC_UI__ must be present and parseable."""
    tpl_dir = _tpl_dir(tmp_path)
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'abc123456789' + 'f' * 28, 'subject': 'subj', 'body': 'body',
        'author_name': 'A', 'author_time': 1700000000,
        'score': 10, 'matched_profiles': ['p'], 'product_evidence': []
    }]
    generate_html_report(commits, {}, {}, str(out), templates_dir=str(tpl_dir))
    ui = _kc_ui(out.read_text())
    assert 'meta' in ui
    assert 'columns' in ui
    assert 'rows' in ui
    assert 'sidebar' in ui
    assert len(ui['rows']) == 1
    assert ui['rows'][0]['sha12'] == 'abc123456789'
    assert ui['rows'][0]['score'] == 10


def test_html_detail_assets_include_js(tmp_path):
    tpl_dir = _tpl_dir(tmp_path)
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'abc123456789' + 'f' * 28, 'subject': 'subj', 'body': 'line1\n\tline2',
        'author_name': 'A', 'author_time': 1700000000,
        'score': 42, 'matched_profiles': ['p'], 'product_evidence': ['config_map:CONFIG_USB'],
        'scoring': {'profiles': {'p': 42}, 'trace': {'profiles': {'p': {
            'multiplier': 1.0, 'blocked': False, 'block_reason': '', 'rules': {},
            'raw_rule_total': 42, 'raw_rule_total_capped': 42, 'final_score': 42
        }}}}
    }]
    generate_html_report(commits, {}, {}, str(out), templates_dir=str(tpl_dir))
    txt = out.read_text()
    assert '/* test js */' in txt
    assert 'window.__KC_COMMITS__' in txt
    # body text should be JSON-escaped inside the KC_UI payload
    assert 'line1\n\tline2' not in txt
    assert 'line1\\n\\tline2' in txt


# ---------------------------------------------------------------------------
# Columns and row data
# ---------------------------------------------------------------------------

def test_html_filtered_table_includes_reason_column(tmp_path):
    tpl_dir = _tpl_dir(tmp_path)
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'abc123456789' + 'f' * 28, 'subject': 'subj', 'body': '',
        'author_name': 'A', 'author_time': 1700000000,
        'score': 0, 'matched_profiles': [], 'product_evidence': [],
        '_filter_reason': 'path_blacklist'
    }]
    generate_html_report(commits, {}, {}, str(out), templates_dir=str(tpl_dir), is_filtered=True)
    ui = _kc_ui(out.read_text())
    col_keys = [c['key'] for c in ui['columns']]
    assert 'reason' in col_keys
    assert ui['rows'][0]['reason'] == 'path_blacklist'


def test_html_report_includes_profile_scores_column(tmp_path):
    """Per-profile scores are emitted as score_<profile> row keys.

    The old combined 'profile_scores' string column was replaced by
    individual score_<profile> numeric keys on each row (one per profile
    in the report universe).  The JS expands these into separate columns.
    """
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'a' * 40, 'subject': 'usb fix', 'author_name': 'Alice',
        'author_time': 1710000000, 'score': 42,
        'matched_profiles': ['security_fixes'], 'product_evidence': [],
        'scoring': {'profiles': {'security_fixes': 42, 'performance': 5}}
    }]
    generate_html_report(commits, {}, {}, str(out))
    ui      = _kc_ui(out.read_text())
    col_keys = [c['key'] for c in ui['columns']]
    row      = ui['rows'][0]

    # Old combined column must no longer exist
    assert 'profile_scores' not in col_keys

    # Per-profile score keys are present on the row
    # (only profiles that appear in matched_profiles are in the universe)
    assert 'score_security_fixes' in row
    assert row['score_security_fixes'] == 42.0

    # 'performance' is present in scoring.profiles but NOT in matched_profiles
    # for any commit, so it is NOT in the profile universe and must be absent.
    assert 'score_performance' not in row


def test_html_report_rows_contain_expected_fields(tmp_path):
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'deadbeef1234' + 'a' * 28, 'subject': 'net fix',
        'author_name': 'Bob', 'author_time': 1710000100,
        'score': 17, 'matched_profiles': ['network'], 'product_evidence': []
    }]
    generate_html_report(commits, {}, {}, str(out))
    row = _kc_ui(out.read_text())['rows'][0]
    assert row['sha12'] == 'deadbeef1234'
    assert row['subject'] == 'net fix'
    assert row['author'] == 'Bob'
    assert row['score'] == 17
    assert row['profiles'] == ['network']


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

def test_html_report_meta_contains_version_and_title(tmp_path):
    out = tmp_path / 'report.html'
    generate_html_report([], {}, {}, str(out), title='My Report')
    meta = _kc_ui(out.read_text())['meta']
    assert meta['title'] == 'My Report'
    assert 'version' in meta
    assert 'generated_at' in meta


def test_html_report_subtitle_substituted_in_template(tmp_path):
    tpl_dir = _tpl_dir(tmp_path)
    out = tmp_path / 'report.html'
    commits = [{'commit': 'a' * 40, 'subject': 's', 'author_name': 'x',
                'author_time': 1, 'score': 1, 'matched_profiles': []}]
    generate_html_report(commits, {}, {}, str(out), templates_dir=str(tpl_dir))
    txt = out.read_text()
    assert '1 commit' in txt


# ---------------------------------------------------------------------------
# Sidebar payload
# ---------------------------------------------------------------------------

def test_html_report_sidebar_has_funnel_counts(tmp_path):
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'a' * 40, 'subject': 'net fix', 'author_name': 'Dev',
        'author_time': 1710000000, 'score': 55,
        'matched_profiles': ['security'], 'product_evidence': ['CONFIG_USB'],
        'scoring': {'profiles': {'security': 55}},
    }]
    rs = {
        'st01_collected': 5000,
        'st04_prefilter_kept': 3200,
        'st04_prefilter_dropped': 1800,
        'st05_total_scored': 3200,
        'st06_threshold': 10.0,
        'st06_postfilter_dropped': 120,
        'total_scored_commits': 1,
        'score_highest': 55.0,
        'score_lowest': 55.0,
        'score_avg': 55.0,
        'commits_matched_zero_profiles': 0,
        'commits_with_product_evidence': 1,
    }
    generate_html_report(
        commits,
        {'security': {'commit_count': 1, 'total_score': 55, 'avg_score': 55}},
        rs, str(out))
    sb = _kc_ui(out.read_text())['sidebar']
    funnel = sb['funnel']
    assert funnel['collected'] == 5000
    assert funnel['prefilter_kept'] == 3200
    assert funnel['prefilter_dropped'] == 1800
    assert funnel['scored'] == 3200
    assert sb['stage_06']['threshold'] == 10.0
    assert sb['stage_05']['profiles']['security']['commits_scored'] == 1


def test_html_report_sidebar_handles_missing_stage_counts(tmp_path):
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'b' * 40, 'subject': 'fix', 'author_name': 'Dev',
        'author_time': 1710000000, 'score': 30,
        'matched_profiles': [], 'product_evidence': [],
    }]
    generate_html_report(commits, {}, {}, str(out))
    sb = _kc_ui(out.read_text())['sidebar']
    assert 'funnel' in sb
    # No crash even when all stage counts are absent
    assert sb['funnel']['collected'] is None


def test_html_report_sidebar_includes_evaluation_config(tmp_path):
    out = tmp_path / 'report.html'
    rs = {
        'evaluation': {
            'git_range':        'abc..def',
            'kernel_revision':  'v6.1',
            'profiles':         'security,network',
            'top_n':            100,
        },
        'total_scored_commits': 0,
    }
    generate_html_report([], {}, rs, str(out))
    sb = _kc_ui(out.read_text())['sidebar']
    ev = sb['evaluation']
    assert ev.get('git_range') == 'abc..def'
    assert ev.get('kernel_revision') == 'v6.1'


# ---------------------------------------------------------------------------
# Detail / sidecar modes
# ---------------------------------------------------------------------------

def test_html_report_uses_metadata_sidecar(tmp_path):
    out = tmp_path / 'report.html'
    generate_html_report(
        [{'commit': 'a' * 40, 'subject': 'subj', 'author_name': 'dev',
          'author_time': 1, 'score': 7, 'matched_profiles': ['p'],
          'product_evidence': ['x']}],
        {'p': {'commit_count': 1}},
        {'relevant_commit_count': 1},
        str(out),
        detail_mode='sidecar',
        commit_index_path='./relevant_commits.table.json',
        commit_detail_root='./commits',
        metadata_path='./report_metadata.json')
    txt = out.read_text()
    assert 'KCOMMIT_REPORT_METADATA_URL' in txt
    # In sidecar mode, commit store is NOT embedded
    assert '"a" * 40' not in txt


def test_html_report_detail_root_in_kc_ui(tmp_path):
    out = tmp_path / 'report.html'
    generate_html_report(
        [], {}, {}, str(out), commit_detail_root='./commits')
    ui = _kc_ui(out.read_text())
    assert ui['detail_root'] == './commits'


# ---------------------------------------------------------------------------
# Compression
# ---------------------------------------------------------------------------

def test_html_report_embeds_fallback_commit_map_when_compressed(tmp_path):
    """embed_compression is accepted without error; __KC_UI__ and commit data
    are always present regardless of the compression setting."""
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'abc123456789deadbeef' + 'f' * 20, 'subject': 'subj',
        'body': 'body', 'author_name': 'A', 'author_time': 1700000000,
        'score': 10, 'matched_profiles': ['p'], 'product_evidence': []
    }]
    generate_html_report(commits, {}, {}, str(out), embed_compression='zlib')
    txt = out.read_text(encoding='utf-8')
    assert 'window.__KC_UI__' in txt
    assert 'abc123456789' in txt


# ---------------------------------------------------------------------------
# Template-level checks (real assets)
# ---------------------------------------------------------------------------

def test_html_report_includes_theme_toggle_button(tmp_path):
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'a' * 40, 'subject': 'usb fix', 'author_name': 'Alice',
        'author_time': 1710000000, 'score': 42,
        'matched_profiles': ['mini_security'], 'product_evidence': []
    }]
    generate_html_report(commits, {}, {}, str(out))
    txt = out.read_text(encoding='utf-8')
    assert 'kc-theme-btn' in txt


def test_html_report_has_three_pane_layout(tmp_path):
    """The rendered report must contain the three pane landmark IDs."""
    out = tmp_path / 'report.html'
    generate_html_report([], {}, {}, str(out))
    txt = out.read_text(encoding='utf-8')
    assert 'kc-pane-left'  in txt
    assert 'kc-pane-mid'   in txt
    assert 'kc-pane-right' in txt


def test_html_detail_pane_has_tabs(tmp_path):
    """Detail pane must have Overview, Scoring, Files, Raw JSON tabs."""
    out = tmp_path / 'report.html'
    generate_html_report([], {}, {}, str(out))
    txt = out.read_text(encoding='utf-8')
    assert 'Overview'  in txt
    assert 'Scoring'   in txt
    assert 'Files'     in txt
    assert 'Raw JSON'  in txt
    assert 'kc-tab'    in txt


def test_html_report_kc_ui_rows_have_sha_and_subject(tmp_path):
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'abc123456789' + 'f' * 28, 'subject': 'usb fix',
        'author_name': 'Dev', 'author_time': 1700000000,
        'score': 87, 'matched_profiles': ['security_fixes'],
        'product_evidence': ['config_map:CONFIG_USB'],
        'scoring': {
            'profiles': {'security_fixes': 87},
            'trace': {'profiles': {'security_fixes': {
                'multiplier': 1.0, 'final_score': 87, 'raw_rule_total': 87,
                'raw_rule_total_capped': 87, 'blocked': False,
                'rules': {
                    'security_memory': {
                        'weight': 80, 'matched': True, 'score': 80,
                        'matches': {'keywords_whitelist': [
                            {'pattern': 'use-after-free', 'value': 'Fix use-after-free'}
                        ]}
                    }
                }
            }}}
        },
        'files': ['drivers/usb/core.c']
    }]
    generate_html_report(commits, {}, {}, str(out))
    ui  = _kc_ui(out.read_text())
    row = ui['rows'][0]
    assert row['sha12']   == 'abc123456789'
    assert row['subject'] == 'usb fix'
    assert row['score']   == 87
    # Full commit detail available in __KC_COMMITS__ for JS panel
    txt = out.read_text()
    assert 'window.__KC_COMMITS__' in txt
    assert 'use-after-free' in txt


def test_html_report_kc_ui_contains_profile_in_columns(tmp_path):
    """Profiles column must carry select options when profiles exist."""
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'a' * 40, 'subject': 'fix', 'author_name': 'x',
        'author_time': 1, 'score': 50,
        'matched_profiles': ['security', 'network'], 'product_evidence': []
    }]
    generate_html_report(commits, {}, {}, str(out))
    ui = _kc_ui(out.read_text())
    prof_col = next(c for c in ui['columns'] if c['key'] == 'profiles')
    assert 'options' in prof_col
    assert 'security' in prof_col['options']
    assert 'network'  in prof_col['options']


# ---------------------------------------------------------------------------
# CSS asset checks (real summary.css)
# ---------------------------------------------------------------------------

def test_summary_css_has_theme_override_blocks():
    css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            'configs', 'html', 'summary.css')
    with open(css_path, encoding='utf-8') as f:
        css = f.read()
    assert '[data-theme="dark"]'  in css
    assert 'kc-theme-btn'         in css


def test_summary_css_has_three_pane_layout_classes():
    css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            'configs', 'html', 'summary.css')
    with open(css_path, encoding='utf-8') as f:
        css = f.read()
    assert '.kc-pane-left'  in css
    assert '.kc-pane-right' in css
    assert '.kc-pane-mid'   in css
    assert '.kc-handle'     in css
    assert '.kc-collapse-btn' in css


def test_summary_css_has_score_pills():
    css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            'configs', 'html', 'summary.css')
    with open(css_path, encoding='utf-8') as f:
        css = f.read()
    assert '.kc-score-pill' in css
    assert '.kc-hi'  in css
    assert '.kc-mid' in css
    assert '.kc-low' in css


def test_summary_css_detail_pane_is_scrollable():
    css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            'configs', 'html', 'summary.css')
    with open(css_path, encoding='utf-8') as f:
        css = f.read()
    assert '.kc-detail-body' in css
    assert 'overflow-y: auto' in css


# ---------------------------------------------------------------------------
# JS asset checks (real summary.js)
# ---------------------------------------------------------------------------

def test_summary_js_reads_kc_ui_global():
    """JS must read window.__KC_UI__ as its data source."""
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert 'window.__KC_UI__' in js


def test_summary_js_has_theme_toggle_logic():
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert 'kc-theme-btn'         in js
    assert "setAttribute('data-theme'" in js or 'applyTheme'  in js
    assert 'prefers-color-scheme'  in js


def test_summary_js_has_filter_and_sort_logic():
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert 'applyFilters'   in js
    assert 'applySort'      in js
    assert 'scheduleFilter' in js


def test_summary_js_has_detail_panel_logic():
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert 'openDetail'    in js
    assert 'fetchCommit'   in js
    assert 'populateDetail' in js


def test_summary_js_has_csv_export():
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert 'kc-export-csv' in js or 'exportBtn' in js
    assert 'text/csv'       in js


def test_summary_js_has_collapse_and_resize():
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert 'kc-collapsed'  in js
    assert 'mousedown'     in js
    assert 'mousemove'     in js


def test_summary_js_has_keyboard_navigation():
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert 'ArrowDown' in js
    assert 'ArrowUp'   in js
    assert 'Escape'    in js


def test_summary_js_live_count_update():
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert 'liveCount' in js
    assert 'Showing'   in js


def test_summary_js_sidebar_renderer_present():
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert 'kc-left-body'   in js
    assert 'kc-funnel-bar'  in js or 'funnel' in js


def test_summary_js_has_scoring_trace_renderer():
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert 'renderProfileTrace' in js
    assert 'kc-trace-table'     in js


def test_summary_js_has_per_profile_score_columns():
    """JS must expand per-profile score_<profile> keys into table columns."""
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert 'score_' in js          # key prefix used for per-profile columns
    assert 'PROFILE_NAMES' in js   # profile name universe computed at startup
    assert '_profile' in js        # column marker used in rowHtml()
