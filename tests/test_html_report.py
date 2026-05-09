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
