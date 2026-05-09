import json
import os
import zipfile

from lib.stages import st07_report


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)


def _cfg(tmp_path):
    return {
        'paths': {'templates_dir': None},
        'reports': {'outputs': ['csv', 'xlsx', 'ods'], 'top_n': 0},
        'profiles': {'active': {'p': 100}},
        '_meta': {'config_dir': str(tmp_path)},
    }


def _commit():
    return {
        'commit': 'abcdef1234567890', 'subject': 'usb fix', 'author_name': 'Alice', 'author_time': 1700000000,
        'body': 'details', 'files': ['drivers/usb/core.c'], 'score': 42, 'matched_profiles': ['p'],
        'product_evidence': ['config_map:CONFIG_USB'],
        'scoring': {'profiles': {'p': 42}, 'trace': {'profiles': {'p': {'multiplier': 1.0, 'merged_matches': {'keywords_whitelist': [], 'keywords_blacklist': [], 'path_whitelist': [], 'path_blacklist': [], 'commit_whitelist': [], 'commit_blacklist': []}, 'blocked': False, 'block_reason': '', 'rules': {'usb_rule': {'weight': 42, 'matched': True, 'matched_level': 'matched', 'score': 42, 'matches': {'keywords_whitelist': [{'pattern': 'usb*', 'value': 'usb fix'}], 'path_whitelist': [{'pattern': 'drivers/usb/*', 'value': 'drivers/usb/core.c'}], 'commit_whitelist': []}}}, 'raw_rule_total': 42, 'raw_rule_total_capped': 42, 'final_score': 42}}}}
    }


def test_stage07_writes_rule_trace_json_csv_and_summary_workbooks(tmp_path, monkeypatch):
    cache = tmp_path / 'cache'
    out = tmp_path / 'out'
    cache.mkdir(); out.mkdir()
    _write(str(cache / 'relevant_commits.json'), [_commit()])
    _write(str(cache / 'filtered_commits.json'), [])
    _write(str(cache / 'postfilter_dropped_commits.json'), [])
    monkeypatch.setattr('lib.profile_rules.load_profile_rules', lambda cfg: {'p': {'description': 'Profile p'}})
    st07_report.run(_cfg(tmp_path), str(cache), str(out))
    rule_trace = json.load(open(out / 'rule_trace.json'))
    assert rule_trace['header'][0] == 'sha'
    assert any(r[2] == 'usb_rule' for r in rule_trace['rows'])
    csv_txt = open(out / 'relevant_commits.csv', encoding='utf-8').read()
    assert 'usb fix' in csv_txt
    with zipfile.ZipFile(out / 'summary.xlsx') as zf:
        workbook = zf.read('xl/workbook.xml').decode('utf-8')
    assert 'Rule Trace' in workbook
