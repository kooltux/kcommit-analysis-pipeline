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
    assert 'makeSunPaths' in js or 'SUN' in js


def test_summary_css_has_theme_override_blocks():
    css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            'configs', 'html', 'summary.css')
    with open(css_path, encoding='utf-8') as f:
        css = f.read()
    assert '[data-theme="dark"]' in css
    assert '[data-theme="light"]' in css
    assert 'kc-theme-btn' in css


def test_html_report_includes_filter_busy_overlay(tmp_path):
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'a'*40, 'subject': 'usb fix', 'author_name': 'Alice',
        'author_time': 1710000000, 'score': 42,
        'matched_profiles': ['mini_security'], 'product_evidence': []
    }]
    generate_html_report(commits, {}, {}, str(out))
    txt = out.read_text(encoding='utf-8')
    assert 'kc-table-busy' in txt
    assert 'Filtering commits…' in txt
    assert 'aria-busy="false"' in txt


def test_summary_js_has_filter_busy_scheduler():
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert 'function setBusy(isBusy)' in js
    assert 'requestAnimationFrame(function()' in js
    assert 'setTimeout(function()' in js
    assert "tableWrap.setAttribute('aria-busy'" in js
    assert "busyEl.classList.toggle('visible'" in js


def test_summary_css_has_filter_busy_overlay_styles():
    css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            'configs', 'html', 'summary.css')
    with open(css_path, encoding='utf-8') as f:
        css = f.read()
    assert '.kc-table-busy' in css
    assert '@keyframes kc-spin' in css
    assert '.kc-table-busy.visible' in css


def test_summary_css_has_color_mix_fallback_for_busy_overlay():
    css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            'configs', 'html', 'summary.css')
    with open(css_path, encoding='utf-8') as f:
        css = f.read()
    assert 'background: rgba(246,248,250,.82);' in css
    assert '@supports (background: color-mix(in srgb, black 50%, transparent))' in css
    assert '[data-theme="dark"] .kc-table-busy' in css


def test_summary_js_has_firefox_download_click_fallback():
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert "typeof MouseEvent === 'function'" in js
    assert "else if (typeof a.click === 'function')" in js
    assert 'catch (err)' in js


def test_summary_js_uses_precomputed_row_data_for_filters():
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert 'var rowData = rows.map(function(row)' in js
    assert 'var vals = distinctVals(rowData, ci);' in js
    assert 'rowData.forEach(function(entry)' in js
    assert "var hay = entry._haystack || (entry._haystack = entry.cells.join(' ').toLowerCase());" in js
    assert "entry.row.classList.toggle('hidden', !show);" in js


def test_summary_js_theme_toggle_uses_dom_api():
    """Theme toggle must not use innerHTML for SVG (breaks in Firefox)."""
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'configs', 'html', 'summary.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    theme_start = js.find('/* \u2500\u2500 Theme toggle')
    theme_end   = js.find('/* \u2500\u2500 Bootstrap', theme_start)
    theme_block = js[theme_start:theme_end]
    assert 'createElementNS' in theme_block, "SVG must be built with createElementNS in Firefox-safe way"
    assert "innerHTML" not in theme_block, "innerHTML for SVG is broken in Firefox; use createElementNS"
    assert "SVG_NS = 'http://www.w3.org/2000/svg'" in theme_block
    assert "e.preventDefault" in theme_block


def test_html_report_sidebar_has_pipeline_hierarchy(tmp_path):
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'a'*40, 'subject': 'net fix', 'author_name': 'Dev',
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
    generate_html_report(commits, {'security': {'commit_count': 1, 'total_score': 55, 'avg_score': 55}}, rs, str(out))
    txt = out.read_text(encoding='utf-8')
    assert 'kc-stage-block' in txt
    assert 'Pipeline Run' in txt
    assert 'Collection' in txt
    assert 'Pre-filter' in txt
    assert 'Scoring' in txt
    assert 'Post-filter' in txt
    assert '5,000' in txt
    assert '3,200' in txt
    assert '1,800' in txt
    assert 'Score highest' in txt


def test_html_report_sidebar_handles_missing_stage_counts(tmp_path):
    out = tmp_path / 'report.html'
    commits = [{
        'commit': 'b'*40, 'subject': 'fix', 'author_name': 'Dev',
        'author_time': 1710000000, 'score': 30,
        'matched_profiles': [], 'product_evidence': [],
    }]
    generate_html_report(commits, {}, {}, str(out))
    txt = out.read_text(encoding='utf-8')
    assert 'kc-stage-block' in txt
    assert 'Pipeline Run' in txt
    assert 'Collection' in txt


def test_html_report_uses_metadata_sidecar_and_hides_product_evidence(tmp_path):
    from lib.html_report import generate_html_report
    out = tmp_path / 'report.html'
    generate_html_report([{'commit': 'a'*40, 'subject': 'subj', 'author_name': 'dev', 'author_time': 1, 'score': 7, 'matched_profiles': ['p'], 'product_evidence': ['x']}], {'p': {'commit_count': 1}}, {'relevant_commit_count': 1}, str(out), detail_mode='sidecar', commit_index_path='./relevant_commits.table.json', commit_detail_root='./commits', metadata_path='./report_metadata.json')
    s = out.read_text()
    assert 'KCOMMIT_REPORT_METADATA_URL' in s
    assert 'evaluation-details' in s
    assert '<th>Product evidence</th>' not in s
    assert '<h4>Product evidence</h4>' not in s
    assert '<h4>Evidence</h4>' in s
