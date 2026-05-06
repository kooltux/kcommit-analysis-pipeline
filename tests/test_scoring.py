"""Tests for lib.scoring — extract_commit_meta, score_commit."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.scoring import extract_commit_meta, score_commit, precompile_rules


def _commit(subject='', body='', files=None):
    return {'commit': 'abc123', 'subject': subject, 'body': body or '',
            'files': files or []}


def test_extract_meta_cve():
    c = _commit(subject='Fix CVE-2024-12345 in usb core')
    m = extract_commit_meta(c)
    assert m['has_cve'] is True
    assert m['is_fix'] is False


def test_extract_meta_fixes_tag():
    c = _commit(body='Fixes: 1234567890ab ("mm: slab: wrong ref")')
    m = extract_commit_meta(c)
    assert m['is_fix'] is True


def test_extract_meta_stable_cc():
    c = _commit(body='Cc: stable@vger.kernel.org')
    m = extract_commit_meta(c)
    assert m['has_stable_cc'] is True


def test_extract_meta_syzbot():
    c = _commit(body='Reported-by: syzbot+abc@syzkaller.appspotmail.com')
    m = extract_commit_meta(c)
    assert m['has_syzbot'] is True


def test_score_no_rules_zero():
    c = _commit(subject='net: fix skb leak')
    s = score_commit(c, {}, {})
    assert s['score'] == 0
    assert s['matched_profiles'] == []


def _net_rules():
    # score_commit reads rdata['keywords_whitelist'] and rdata['path_whitelist']
    return {
        'networking': {
            'rules': {
                'net_generic': {
                    'keywords_whitelist': ['net:', 'skb'],
                    'weight': 10,
                }
            },
            'merged': {'keywords_whitelist': [], 'keywords_blacklist': [],
                       'commit_whitelist': [], 'commit_blacklist': [],
                       'path_whitelist': [], 'path_blacklist': []},
        }
    }


def test_score_rule_hit():
    profile_rules = _net_rules()
    precompile_rules(profile_rules)
    c = _commit(subject='net: fix skb memory leak')
    s = score_commit(c, {}, profile_rules)
    assert s['score'] > 0
    assert 'networking' in s['matched_profiles']


def test_score_rule_miss():
    profile_rules = _net_rules()
    precompile_rules(profile_rules)
    c = _commit(subject='mm: fix page ref counting')
    s = score_commit(c, {}, profile_rules)
    assert 'networking' not in s['matched_profiles']
