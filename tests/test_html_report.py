"""Tests for lib.html_report — template handling and HTML output."""
import os

from lib.html_report import generate_html_report


def _tpl_dir(tmp_path):
    tpl_dir = tmp_path / 'tpl'
    tpl_dir.mkdir()
    (tpl_dir / 'report.html').write_text('<html><head><title>__TITLE__</title><style>__CSS__</style>__COMMITS_DATA__</head><body>__BODY__<script>__JS__</script></body></html>')
    (tpl_dir / 'summary.css').write_text('.seed{}')
    (tpl_dir / 'summary.js').write_text('function renderDetail(c){}')
    (tpl_dir / 'logo.svg').write_text('<svg></svg>')
    return tpl_dir


def test_generate_html_report_writes_file(tmp_path):
    tpl_dir = _tpl_dir(tmp_path)
    out = tmp_path / 'report.html'
    generate_html_report([], {}, {}, str(out), templates_dir=str(tpl_dir))
    assert out.exists()


def test_generate_html_report_requires_body_marker(tmp_path):
    tpl_dir = tmp_path / 'tpl'
    tpl_dir.mkdir()
    (tpl_dir / 'report.html').write_text('<html></html>')
    (tpl_dir / 'summary.css').write_text('')
    (tpl_dir / 'summary.js').write_text('')
    (tpl_dir / 'logo.svg').write_text('')
    out = tmp_path / 'report.html'
    import pytest
    with pytest.raises(RuntimeError):
        generate_html_report([], {}, {}, str(out), templates_dir=str(tpl_dir))


def test_html_report_embeds_commit_map(tmp_path):
    tpl_dir = _tpl_dir(tmp_path)
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'abc123456789', 'subject': 'subj', 'body': 'body',
        'author_name': 'A', 'author_time': 1700000000,
        'score': 10, 'matched_profiles': ['p'], 'product_evidence': []
    }]
    generate_html_report(commits, {}, {}, str(out), templates_dir=str(tpl_dir))
    txt = out.read_text()
    assert 'window.__KC_COMMITS__' in txt
    assert 'abc123456789' in txt


def test_html_detail_assets_include_split_pane_and_analysis_classes(tmp_path):
    tpl_dir = _tpl_dir(tmp_path)
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'abc123456789', 'subject': 'subj', 'body': 'line1\n\tline2',
        'author_name': 'A', 'author_time': 1700000000,
        'score': 42, 'matched_profiles': ['p'], 'product_evidence': ['config_map:CONFIG_USB'],
        'scoring': {'profiles': {'p': 42}, 'trace': {'profiles': {'p': {'multiplier': 1.0, 'merged_matches': {'keywords_whitelist': [], 'keywords_blacklist': [], 'path_whitelist': [], 'path_blacklist': [], 'commit_whitelist': [], 'commit_blacklist': []}, 'blocked': False, 'block_reason': '', 'rules': {}, 'raw_rule_total': 42, 'raw_rule_total_capped': 42, 'final_score': 42}}}}
    }]
    generate_html_report(commits, {}, {}, str(out), templates_dir=str(tpl_dir))
    txt = out.read_text()
    assert 'function renderDetail(c){}' in txt
    assert 'window.__KC_COMMITS__' in txt
    assert 'line1\n\tline2' not in txt  # JSON-escaped inside embedded data
    assert 'line1\\n\\tline2' in txt


def test_html_filtered_table_includes_reason_column(tmp_path):
    tpl_dir = _tpl_dir(tmp_path)
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'abc123456789', 'subject': 'subj', 'body': '', 'author_name': 'A', 'author_time': 1700000000,
        'score': 0, 'matched_profiles': [], 'product_evidence': [], '_filter_reason': 'path_blacklist'
    }]
    generate_html_report(commits, {}, {}, str(out), templates_dir=str(tpl_dir), is_filtered=True)
    txt = out.read_text()
    assert 'Filter reason' in txt
    assert 'path_blacklist' in txt


def test_html_report_includes_profile_scores_column(tmp_path):
    from lib.html_report import generate_html_report
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'a'*40, 'subject': 'usb fix', 'author_name': 'Alice', 'author_time': 1710000000,
        'score': 42, 'matched_profiles': ['security_fixes'], 'product_evidence': [],
        'scoring': {'profiles': {'security_fixes': 42, 'performance': 5}}
    }]
    generate_html_report(commits, {}, {}, str(out))
    txt = out.read_text(encoding='utf-8')
    assert 'Profile Scores' in txt
    assert 'performance:5' in txt
    assert 'security_fixes:42' in txt


def test_summary_js_openpanel_uses_async_loadcommitstore():
    """G.2: openPanel must resolve commit data via loadCommitStore().then()
    so that compressed and sidecar detail modes always populate the pane."""
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert 'loadCommitStore().then' in js, \
        "openPanel must use loadCommitStore().then() for async commit resolution"
    # The synchronous map lookup must NOT appear in openPanel any more
    open_panel_start = js.index('function openPanel')
    open_panel_end   = js.index('\n  }', open_panel_start) + 4
    open_panel_body  = js[open_panel_start:open_panel_end]
    assert 'window.__KC_COMMITS__' not in open_panel_body, \
        "openPanel must not access window.__KC_COMMITS__ directly (use loadCommitStore)"


def test_html_report_includes_live_filtered_counter_and_csv_button(tmp_path):
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'a'*40, 'subject': 'usb fix', 'author_name': 'Alice', 'author_time': 1710000000,
        'score': 42, 'matched_profiles': ['mini_security'], 'product_evidence': []
    }, {
        'commit': 'b'*40, 'subject': 'net fix', 'author_name': 'Bob', 'author_time': 1710000100,
        'score': 17, 'matched_profiles': ['mini_network'], 'product_evidence': []
    }]
    generate_html_report(commits, {}, {}, str(out))
    txt = out.read_text(encoding='utf-8')
    assert 'kc-live-count' in txt
    assert 'Showing 2 of 2 commits' in txt
    assert 'kc-export-filtered-csv' in txt
    assert 'Export filtered CSV' in txt


def test_summary_js_updates_live_count_and_exports_visible_rows():
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert 'updateLiveCount(visible)' in js
    assert "Showing ' + visible + ' of ' + rows.length + ' commits" in js
    assert "querySelector('.kc-export-filtered-csv')" in js
    assert 'tbody tr:not(.hidden)' in js


def test_summary_js_has_firefox_safe_download_and_zlib_fallback():
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert 'function triggerDownload(blob, filename)' in js
    assert "dispatchEvent(new MouseEvent('click'" in js
    assert "type:'text/csv;charset=utf-8'" in js
    assert 'window.__KC_COMMITS_FALLBACK__' in js
    assert 'decodeEmbeddedCommitStore()' in js


def test_html_report_embeds_fallback_commit_map_when_compressed(tmp_path):
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'abc123456789deadbeef', 'subject': 'subj', 'body': 'body',
        'author_name': 'A', 'author_time': 1700000000,
        'score': 10, 'matched_profiles': ['p'], 'product_evidence': []
    }]
    generate_html_report(commits, {}, {}, str(out), embed_compression='zlib')
    txt = out.read_text(encoding='utf-8')
    assert 'window.__KC_COMMITS_COMPRESSED__' in txt
    assert 'window.__KC_COMMITS_FALLBACK__' in txt
    assert 'abc123456789' in txt


def test_summary_js_has_detail_pane_fallbacks_for_firefox():
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert "openPanel(a.getAttribute('data-sha')" in js
    assert 'stopImmediatePropagation' in js
    assert 'return false;' in js
    assert '.catch(function(err)' in js
    assert 'Unable to load commit details:' in js


def test_html_report_includes_theme_toggle_button(tmp_path):
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'a'*40, 'subject': 'usb fix', 'author_name': 'Alice',
        'author_time': 1710000000, 'score': 42,
        'matched_profiles': ['mini_security'], 'product_evidence': []
    }]
    generate_html_report(commits, {}, {}, str(out))
    txt = out.read_text(encoding='utf-8')
    assert 'kc-theme-toggle' in txt
    assert 'kc-theme-btn' in txt
    assert 'data-theme' in txt


def test_summary_js_has_theme_toggle_logic():
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert 'kc-theme-toggle' in js
    assert "setAttribute('data-theme'" in js
    assert 'prefers-color-scheme' in js
    assert "SUN" in js and "MOON" in js


def test_summary_css_has_theme_override_blocks():
    css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            'configs', 'html', 'summary.css')
    with open(css_path, encoding='utf-8') as f:
        css = f.read()
    assert '[data-theme="dark"]' in css
    assert '[data-theme="light"]' in css
    assert 'kc-theme-btn' in css
