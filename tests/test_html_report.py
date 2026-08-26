"""Tests for lib.html_report — template handling and HTML output (v15)."""
import json
import os
import re

from lib.html_report import generate_html_report


def _tpl_dir(tmp_path):
    """Minimal template dir for isolated tests.

    Creates a js/ subdirectory with a single stub module so that
    _assemble_js() produces non-empty output without requiring the full
    configs/html/js/ tree.  The stub content ('/* test js */') is
    intentionally preserved so tests that assert on it still pass.
    """
    tpl_dir = tmp_path / 'tpl'
    tpl_dir.mkdir()
    (tpl_dir / 'report.html').write_text(
        '<html><head><title>__TITLE__</title><style>__CSS__</style>'
        '__COMMITS_DATA__</head><body>'
        '<span id="kc-subtitle">__SUBTITLE__</span>'
        '<script>__JS__</script></body></html>'
    )
    (tpl_dir / 'summary.css').write_text('.seed{}')
    js_dir = tpl_dir / 'js'
    js_dir.mkdir()
    (js_dir / 'summary_01_stub.js').write_text('/* test js */')
    return tpl_dir


def _kc_ui(txt):
    """Extract and parse window.__KC_UI__ from rendered HTML."""
    marker = 'window.__KC_UI__='
    idx = txt.index(marker) + len(marker)
    obj, _ = json.JSONDecoder().raw_decode(txt, idx)
    return obj


def _strip_comments(js):
    """Remove /* ... */ and // ... comment blocks from JS source."""
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.DOTALL)
    js = re.sub(r'//[^\n]*', '', js)
    return js


def _read_assembled_js():
    """Return the concatenated source of all configs/html/js/summary_*.js modules.

    Mirrors the runtime behaviour of _assemble_js() so that JS asset tests
    can verify the assembled output without depending on the removed
    configs/html/summary.js artifact.
    """
    js_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                          'configs', 'html', 'js')
    parts = []
    for fname in sorted(os.listdir(js_dir)):
        if fname.endswith('.js'):
            with open(os.path.join(js_dir, fname), encoding='utf-8') as f:
                parts.append(f.read())
    return '\n'.join(parts)


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
    # js/ dir present but empty — _assemble_js() returns '' gracefully
    (tpl_dir / 'js').mkdir()
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


def test_html_report_exposes_size_indicator_columns(tmp_path):
    """Relevant-tab columns and rows carry files/lines size indicators."""
    tpl_dir = _tpl_dir(tmp_path)
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'abc123456789' + 'f' * 28, 'subject': 'subj', 'body': 'body',
        'author_name': 'A', 'author_time': 1700000000,
        'score': 10, 'matched_profiles': ['p'], 'product_evidence': [],
        'stats': {'files_changed': 3, 'insertions': 20,
                  'deletions': 5, 'lines_changed': 25},
    }]
    generate_html_report(commits, {}, {}, str(out), templates_dir=str(tpl_dir))
    ui = _kc_ui(out.read_text())
    col_keys = [c['key'] for c in ui['columns']]
    assert 'files' in col_keys
    assert 'lines' in col_keys
    assert ui['rows'][0]['files'] == 3
    assert ui['rows'][0]['lines'] == 25
    # files/lines/hunks are emitted as hidden columns: their row values remain
    # available (above) but the browser-side JS drops them from the visible
    # table.  The server marks them hidden so the JS can filter them out.
    cols_by_key = {c['key']: c for c in ui['columns']}
    assert cols_by_key['files'].get('hidden') is True
    assert cols_by_key['lines'].get('hidden') is True


def test_html_report_size_indicators_default_zero_without_stats(tmp_path):
    tpl_dir = _tpl_dir(tmp_path)
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'abc123456789' + 'f' * 28, 'subject': 'subj', 'body': 'body',
        'author_name': 'A', 'author_time': 1700000000,
        'score': 10, 'matched_profiles': ['p'], 'product_evidence': [],
    }]
    generate_html_report(commits, {}, {}, str(out), templates_dir=str(tpl_dir))
    ui = _kc_ui(out.read_text())
    assert ui['rows'][0]['files'] == 0
    assert ui['rows'][0]['lines'] == 0


def test_html_report_exposes_hunks_and_backport_columns(tmp_path):
    """Hunks, Complexity and Pick Priority columns + row values.
    
    Complexity (formerly Backport Cx) is now heat-coloured directly in the cell
    via a 4-level (higher-worse) heat scheme. Pick Priority uses higher-better.
    """
    tpl_dir = _tpl_dir(tmp_path)
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'abc123456789' + 'f' * 28, 'subject': 'subj', 'body': 'body',
        'author_name': 'A', 'author_time': 1700000000,
        'score': 10, 'matched_profiles': ['p'], 'product_evidence': [],
        'stats': {'files_changed': 3, 'lines_changed': 25, 'hunks': 6},
        'backport_complexity': 42,
        'pick_priority': 77,
    }]
    generate_html_report(commits, {}, {}, str(out), templates_dir=str(tpl_dir))
    ui = _kc_ui(out.read_text())
    col_keys = [c['key'] for c in ui['columns']]
    assert 'hunks' in col_keys
    assert 'backport_cx' in col_keys
    assert 'pick_priority' in col_keys
    row = ui['rows'][0]
    assert row['hunks'] == 6
    assert row['backport_cx'] == 42
    assert row['pick_priority'] == 77
    # hunks is a hidden column: its row value is kept (searchable / exported)
    # but it is dropped from the visible table.  backport_cx and pick_priority
    # stay visible (and are heat-coloured).
    cols_by_key = {c['key']: c for c in ui['columns']}
    assert cols_by_key['hunks'].get('hidden') is True
    assert 'hidden' not in cols_by_key['backport_cx']
    assert 'hidden' not in cols_by_key['pick_priority']


def test_html_report_exposes_score_norm_column(tmp_path):
    """Score (score_norm) column and row value are present."""
    tpl_dir = _tpl_dir(tmp_path)
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'abc123456789' + 'f' * 28, 'subject': 'subj', 'body': 'body',
        'author_name': 'A', 'author_time': 1700000000,
        'score': 40, 'score_norm': 66, 'matched_profiles': ['p'],
        'product_evidence': [],
    }]
    generate_html_report(commits, {}, {}, str(out), templates_dir=str(tpl_dir))
    ui = _kc_ui(out.read_text())
    col_keys = [c['key'] for c in ui['columns']]
    assert 'score_norm' in col_keys
    assert ui['rows'][0]['score_norm'] == 66


def test_html_report_default_sort_is_pick_priority_desc(tmp_path):
    tpl_dir = _tpl_dir(tmp_path)
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'abc123456789' + 'f' * 28, 'subject': 'subj', 'body': 'body',
        'author_name': 'A', 'author_time': 1700000000,
        'score': 10, 'matched_profiles': ['p'], 'product_evidence': [],
    }]
    generate_html_report(commits, {}, {}, str(out), templates_dir=str(tpl_dir))
    ui = _kc_ui(out.read_text())
    assert ui['default_sort'] == {'key': 'pick_priority', 'dir': -1}


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
    """v16.14.0: filtered commits passed via filtered_commits= are exposed in
    __KC_UI__ as filtered_columns / filtered_rows.  The 'reason' key must
    appear in filtered_columns and each filtered row must carry it."""
    tpl_dir = _tpl_dir(tmp_path)
    out = tmp_path / 'report.html'
    filtered = [{
        'commit': 'abc123456789' + 'f' * 28, 'subject': 'subj', 'body': '',
        'author_name': 'A', 'author_time': 1700000000,
        'score': 0, 'matched_profiles': [], 'product_evidence': [],
        '_filter_reason': 'path_blacklist'
    }]
    generate_html_report([], {}, {}, str(out), templates_dir=str(tpl_dir),
                         filtered_commits=filtered)
    ui = _kc_ui(out.read_text())
    col_keys = [c['key'] for c in ui['filtered_columns']]
    assert 'reason' in col_keys
    assert ui['filtered_rows'][0]['reason'] == 'path_blacklist'


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


def test_html_report_sidebar_no_evaluation_key(tmp_path):
    """v16.9.0: 'evaluation' must no longer appear in the sidebar payload."""
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
    assert 'evaluation' not in sb


def test_html_report_context_block_present(tmp_path):
    """v16.9.0: UI.context must be present and contain expected fields."""
    out = tmp_path / 'report.html'
    cfg = {
        'kernel': {
            'rev_old': 'v6.1',
            'rev_new': 'v6.6',
            'build_dir': '/build',
            'kernel_build_log': '/build/build.log',
        },
        'profiles': {'active': {'security': 100, 'network': 80}},
    }
    generate_html_report([], {}, {}, str(out), cfg=cfg)
    ui  = _kc_ui(out.read_text())
    ctx = ui['context']
    assert ctx['rev_old']   == 'v6.1'
    assert ctx['rev_new']   == 'v6.6'
    assert ctx['rev_range'] == 'v6.1..v6.6'
    assert ctx['artifacts']['build_dir']        == 'yes'
    assert ctx['artifacts']['kernel_build_log'] == 'yes'
    assert set(ctx['profiles']) == {'security', 'network'}


def test_html_report_context_block_present_without_cfg(tmp_path):
    """UI.context is always present even when cfg is not supplied."""
    out = tmp_path / 'report.html'
    generate_html_report([], {}, {}, str(out))
    ui  = _kc_ui(out.read_text())
    assert 'context' in ui
    ctx = ui['context']
    assert ctx['rev_old']   is None
    assert ctx['rev_new']   is None
    assert ctx['rev_range'] is None
    assert ctx['artifacts'] == {}
    assert ctx['profiles']  == []


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
    out = tmp_path / 'report.html'
    generate_html_report([], {}, {}, str(out))
    txt = out.read_text(encoding='utf-8')
    assert 'kc-pane-left'  in txt
    assert 'kc-pane-mid'   in txt
    assert 'kc-pane-right' in txt


def test_html_detail_pane_has_tabs(tmp_path):
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
    txt = out.read_text()
    assert 'window.__KC_COMMITS__' in txt
    assert 'use-after-free' in txt


def test_html_report_kc_ui_contains_profile_in_columns(tmp_path):
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


def test_summary_css_has_heat_pills():
    """v18.5.0: Numeric columns use a unified 4-level heat-pill scheme.
    
    Complexity, Score and Pick Priority are rendered as heat-coloured pills
    (higher-better or higher-worse polarity) via .kc-heat-1..4 classes.
    """
    css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            'configs', 'html', 'summary.css')
    with open(css_path, encoding='utf-8') as f:
        css = f.read()
    assert '.kc-heat-pill' in css
    assert '.kc-heat-1'    in css
    assert '.kc-heat-2'    in css
    assert '.kc-heat-3'    in css
    assert '.kc-heat-4'    in css


def test_summary_css_has_profile_bullets():
    """v18.5.0: profile colour legend + table bullets."""
    css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            'configs', 'html', 'summary.css')
    with open(css_path, encoding='utf-8') as f:
        css = f.read()
    assert '.kc-prof-bullet'      in css
    assert '.kc-prof-bullets'     in css
    assert '.kc-prof-legend'      in css


# ---------------------------------------------------------------------------
# JS asset checks (real configs/html/js/ modules)
# ---------------------------------------------------------------------------

def test_summary_js_reads_kc_ui_global():
    js = _read_assembled_js()
    assert 'window.__KC_UI__' in js


def test_summary_js_has_theme_toggle_logic():
    js = _read_assembled_js()
    assert 'kc-theme-btn'         in js
    assert "setAttribute('data-theme'" in js or 'applyTheme'  in js
    assert 'prefers-color-scheme'  in js


def test_summary_js_has_filter_and_sort_logic():
    js = _read_assembled_js()
    assert 'applyFilters'   in js
    assert 'applySort'      in js
    assert 'scheduleFilter' in js


def test_summary_js_has_detail_panel_logic():
    js = _read_assembled_js()
    assert 'openDetail'    in js
    assert 'fetchCommit'   in js
    assert 'populateDetail' in js


def test_summary_js_has_csv_export():
    js = _read_assembled_js()
    assert 'kc-export-csv' in js or 'exportBtn' in js
    assert 'text/csv'       in js


def test_summary_js_has_collapse_and_resize():
    js = _read_assembled_js()
    assert 'kc-collapsed'  in js
    assert 'mousedown'     in js
    assert 'mousemove'     in js


def test_summary_js_has_keyboard_navigation():
    js = _read_assembled_js()
    assert 'ArrowDown' in js
    assert 'ArrowUp'   in js
    assert 'Escape'    in js


def test_summary_js_live_count_update():
    js = _read_assembled_js()
    assert 'liveCount' in js
    assert 'Showing'   in js


def test_summary_js_sidebar_renderer_present():
    js = _read_assembled_js()
    assert 'kc-left-body'   in js
    assert 'kc-funnel-bar'  in js or 'funnel' in js


def test_summary_js_has_scoring_trace_renderer():
    js = _read_assembled_js()
    assert 'renderProfileTrace' in js
    assert 'kc-trace-table'     in js


def test_summary_js_does_not_inject_per_profile_columns():
    """v18.5.0: the per-profile score_<profile> columns are no longer injected
    into the visible table.

    The breakdown is low-signal in the table (one column per profile) and is
    still available as score_<profile> row keys (searchable) and in the
    commit-detail "Scoring" tab.  The visible relevant-tab column set is just
    the server columns minus synthetic/hidden ones.
    """
    js   = _read_assembled_js()
    code = _strip_comments(js)
    # No dynamic score_<profile> column objects are built any more.
    assert 'score_${p}' not in code
    assert '_profile:' not in code
    assert 'PROFILE_NAMES' not in code
    # REL_COLS is a straight filter of BASE_COLS (no per-profile expansion).
    assert 'BASE_COLS.filter(' in code


def test_summary_js_has_heat_pill_helpers():
    """v18.5.0: heatLevel() and heatPill() replace cxPill() / tierPill() / cxTierClass().

    heatLevel(value, scale) → 1..4 (even quartiles of value/scale, clamped).
    heatPill(value, {scale, polarity}) → pill with .kc-heat-1..4; polarity:
    'higher-better' → level 1 (0-25%) → kc-heat-4 (red), level 4 (75-100%) → kc-heat-1 (green);
    'higher-worse' → level 1 (0-25%) → kc-heat-1 (green), level 4 (75-100%) → kc-heat-4 (red).
    """
    js   = _read_assembled_js()
    code = _strip_comments(js)
    assert 'function heatLevel' in code
    assert 'function heatPill' in code
    # Complexity uses heatPill with higher-worse polarity
    assert 'heatPill(v, {scale: 100, polarity: \'higher-worse\'})' in code


def test_summary_js_has_context_section():
    js = _read_assembled_js()
    assert 'UI.context' in js or 'CTX' in js
    assert 'Analysis Context' in js


def test_summary_js_has_profile_bullet_helpers():
    """v18.5.0: deterministic per-profile colour bullets, used both in the
    sidebar legend and the table 'Profiles' column."""
    js   = _read_assembled_js()
    code = _strip_comments(js)
    assert 'function profileHue'   in code
    assert 'function profileColor' in code
    assert 'function profileBullet' in code
    assert 'function profileBullets' in code
    # Table 'Profiles' column renders bullets, not text chips.
    assert 'profileBullets(' in code
    # Sidebar 'Scoring profiles' legend uses labelled bullets.
    assert 'profileBullet(p, true)' in code


def test_summary_js_overview_shows_backport_indicators():
    """v18.5.0: the detail Overview tab surfaces the size + backport
    indicators (files/lines/hunks/complexity/pick_priority).
    backport_tier was removed; Complexity is now heat-coloured directly."""
    js   = _read_assembled_js()
    code = _strip_comments(js)
    assert 'Files changed' in code
    assert 'Lines changed' in code
    assert 'Complexity' in code
    assert 'Pick Priority' in code


def test_summary_js_hidden_columns_dropped_from_visible_set():
    """v18.5.0: REL_COLS filters out server-flagged hidden columns so
    files/lines/hunks stay in ROW data but leave the visible table."""
    js   = _read_assembled_js()
    code = _strip_comments(js)
    assert '!c.hidden' in code


def test_assembled_js_parses_in_one_scope():
    """Regression: the real configs/html/js/ bundle must parse cleanly when
    concatenated into a single IIFE scope (the runtime layout).

    Per-file `node --check` is not enough — the modules share one function
    scope, so a duplicate top-level/function-scope `const`/`let` across (or
    within) modules is a runtime SyntaxError ("Identifier 'x' has already been
    declared") that only appears once assembled.  This guards that class of bug
    (e.g. the Overview-tab `files` collision fixed in v18.5.0).

    Skips gracefully when Node.js is not installed so CI without node still
    passes; developers with node get the check.
    """
    import shutil
    import subprocess
    import tempfile

    node = shutil.which('node')
    if not node:
        import pytest
        pytest.skip('node not available — cannot syntax-check assembled JS')

    from lib.html_report import _assemble_js
    tpl_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html')
    assembled = _assemble_js(tpl_dir)
    assert assembled.strip(), 'assembled JS is unexpectedly empty'

    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False,
                                     encoding='utf-8') as fh:
        fh.write(assembled)
        path = fh.name
    try:
        proc = subprocess.run([node, '--check', path],
                              capture_output=True, text=True)
    finally:
        os.unlink(path)
    # Skip if node itself has environment/library issues (e.g. GLIBCXX mismatch)
    stderr = proc.stderr or ''
    if proc.returncode != 0 and ('GLIBCXX' in stderr or 'libstdc++' in stderr):
        import pytest
        pytest.skip(f'Node.js library environment issue: {stderr.strip()}')
    assert proc.returncode == 0, (
        'assembled JS failed node --check (duplicate identifier or syntax '
        f'error):\n{stderr}'
    )


def test_summary_js_no_evaluation_config_section():
    js = _read_assembled_js()
    code = _strip_comments(js)
    assert 'Evaluation Config' not in code
    assert 'SB.evaluation'     not in code


def test_summary_js_buildhead_does_not_read_dom_into_colfilters():
    """v18.5.0: buildHead() must NOT contain a persist block that reads
    [data-filter-key] DOM elements back into colFilters.

    The old v18.4.1 persist block was identified by the local variable name
    'validKeys' (used only inside that block).  Its removal is verified by
    asserting 'validKeys' is absent from the assembled source.
    Note: 'colKeySet' (used in applyFilters) is intentionally present and
    is tested separately.
    """
    js = _read_assembled_js()
    code = _strip_comments(js)
    assert 'validKeys' not in code


def test_summary_js_applyfilters_guards_colfilters_write():
    """v18.5.0: applyFilters() must guard its colFilters write to the current
    COLS keyset only, preventing stale DOM elements from the departing tab
    from re-polluting colFilters after switchTab() has cleared it.
    """
    js = _read_assembled_js()
    code = _strip_comments(js)
    assert 'colKeySet' in code
    assert 'colKeySet.has(' in code


def test_summary_js_switchtab_resets_col_filters():
    """v18.4.0: switchTab() must reset colFilters and clear global search."""
    js = _read_assembled_js()
    code = _strip_comments(js)
    assert 'delete colFilters[k]' in code
    assert "globalSrch.value = ''" in code or 'globalSrch.value=""' in code


def test_summary_js_resetvirt_uses_sentinel():
    """v18.5.1: resetVirt() must set virtOffset = -1 (sentinel), not 0.

    The skip guard in virtRender() is:
      if (winStart === virtOffset && tbody.childElementCount === winEnd - winStart) return;

    After applyFilters() calls resetVirt() then virtRender(0), winStart is
    always 0 (scroll is at top).  If resetVirt() set virtOffset = 0, both
    guard conditions could be simultaneously satisfied when the viewport
    holds the same number of rows before and after the filter/sort —
    silently skipping the repaint and leaving stale rows on screen.

    Setting virtOffset = -1 guarantees winStart (>= 0) != virtOffset (-1),
    so the guard always fails on the first call after a reset.
    """
    js   = _read_assembled_js()
    code = _strip_comments(js)
    # resetVirt() must assign -1, not 0
    assert 'virtOffset = -1' in code
    # The initial declaration must also use -1 so the very first
    # virtRender() call after page load always paints.
    assert 'virtOffset    = -1' in code or 'virtOffset = -1' in code


def test_summary_js_resetvirt_does_not_assign_zero():
    """v18.5.1: virtOffset must never be reset to 0 — only to -1 (sentinel).

    Any assignment of virtOffset = 0 inside resetVirt() would re-introduce
    the silent skip-guard false-positive that this fix eliminates.
    """
    js   = _read_assembled_js()
    code = _strip_comments(js)
    # Confirm no 'virtOffset = 0' assignment exists anywhere in the source.
    # The only assignments should be: initial declaration (-1), sentinel
    # reset in resetVirt() (-1), and the live assignment in virtRender()
    # (virtOffset = winStart, which is always >= 0 and only set after a
    # successful paint — not on a skip path).
    import re as _re
    zero_assignments = _re.findall(r'virtOffset\s*=\s*0\b', code)
    assert zero_assignments == [], (
        f'Found unexpected virtOffset = 0 assignment(s): {zero_assignments}'
    )


# ---------------------------------------------------------------------------
# JS assembly checks
# ---------------------------------------------------------------------------

def test_assemble_js_wraps_in_iife(tmp_path):
    from lib.html_report import _assemble_js
    js_dir = tmp_path / 'js'
    js_dir.mkdir()
    (js_dir / 'summary_01_a.js').write_text('var x = 1;')
    (js_dir / 'summary_02_b.js').write_text('var y = 2;')
    result = _assemble_js(str(tmp_path))
    assert result.startswith("(function(){'use strict';")
    assert result.endswith('})();')
    assert 'var x = 1;' in result
    assert 'var y = 2;' in result


def test_assemble_js_sorted_order(tmp_path):
    from lib.html_report import _assemble_js
    js_dir = tmp_path / 'js'
    js_dir.mkdir()
    (js_dir / 'summary_02_b.js').write_text('/* B */')
    (js_dir / 'summary_01_a.js').write_text('/* A */')
    result = _assemble_js(str(tmp_path))
    assert result.index('/* A */') < result.index('/* B */')


def test_assemble_js_empty_dir_returns_empty(tmp_path):
    from lib.html_report import _assemble_js
    assert _assemble_js(str(tmp_path)) == ''
    (tmp_path / 'js').mkdir()
    assert _assemble_js(str(tmp_path)) == ''
