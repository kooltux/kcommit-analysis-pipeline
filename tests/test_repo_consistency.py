from pathlib import Path


def test_example_config_uses_profile_language():
    txt = Path('configs/example-arm-embedded-full.json').read_text()
    assert 'profiles' in txt
    assert 'active' in txt
    assert 'networking' in txt or 'performance' in txt or 'security_fixes' in txt


def test_readme_mentions_rule_trace_json_not_csv_trace_column():
    txt = Path('README.md').read_text()
    assert 'rule_trace.json' in txt
    assert 'CSV adds a trace-summary column' not in txt


def test_scoring_module_has_single_header_and_helper():
    txt = Path('lib/scoring.py').read_text()
    assert txt.count('def order_commit_details(') == 1
    assert txt.count('"""Commit scoring helpers for kcommit-analysis-pipeline.') == 1
