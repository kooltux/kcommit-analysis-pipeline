"""Extra tests for lib.scoring — product evidence, meta extraction, formatting."""
import pytest

from lib.scoring import (
    score_commit, extract_commit_meta,
    fmt_profiles, fmt_evidence,
    precompile_rules,
)
from lib.stages.st05_score import score_all


def _commit(sha='abc', subject='net: fix skb', body='', files=None):
    return {
        'commit': sha, 'subject': subject, 'body': body or '',
        'author_name': 'Dev', 'author_time': 0,
        'files': files or ['drivers/net/core.c'],
        'meta': {}, 'touched_paths_guess': [],
    }


def _profile_rules(kw_wl=None, kw_bl=None, path_wl=None, path_bl=None,
                   commit_wl=None, commit_bl=None, weight=20):
    return {
        'networking': {
            'description': '',
            'rules': {
                'net_kw': {
                    'keywords_whitelist': kw_wl or ['net:', 'skb'],
                    'keywords_blacklist': kw_bl or [],
                    'path_whitelist':     path_wl or [],
                    'path_blacklist':     path_bl or [],
                    'commit_whitelist':   commit_wl or [],
                    'commit_blacklist':   commit_bl or [],
                    'weight': weight,
                }
            },
            'merged': {
                'keywords_whitelist': kw_wl or ['net:', 'skb'],
                'keywords_blacklist': kw_bl or [],
                'path_whitelist':     path_wl or [],
                'path_blacklist':     path_bl or [],
                'commit_whitelist':   commit_wl or [],
                'commit_blacklist':   commit_bl or [],
            },
        }
    }


# ── extract_commit_meta ───────────────────────────────────────────────────────
def test_meta_fixes_tag():
    m = extract_commit_meta({'subject': 'fix: null deref', 'body': 'Fixes: abc123'})
    assert m['is_fix'] is True


def test_meta_cve():
    m = extract_commit_meta({'subject': 'CVE-2024-1234 fix', 'body': ''})
    assert m['has_cve'] is True


def test_meta_syzbot():
    m = extract_commit_meta({'subject': 'mm: fix', 'body': 'Reported-by: syzbot+abc@google.com'})
    assert m['has_syzbot'] is True


def test_meta_stable_cc():
    m = extract_commit_meta({'subject': 'fix', 'body': 'Cc: stable@vger.kernel.org'})
    assert m['has_stable_cc'] is True


def test_meta_plain_commit():
    m = extract_commit_meta({'subject': 'mm: add new page', 'body': ''})
    assert m == {'is_fix': False, 'has_cve': False,
                 'has_syzbot': False, 'has_stable_cc': False}


def test_meta_none_fields():
    m = extract_commit_meta({'subject': None, 'body': None})
    assert isinstance(m, dict)


# ── score_commit — hit/miss/blacklist paths ───────────────────────────────────
def test_score_commit_keyword_hit():
    c = _commit(subject='net: fix skb leak')
    pr = _profile_rules()
    r = score_commit(c, {}, pr)
    assert r['score'] > 0
    assert 'networking' in r['matched_profiles']


def test_score_commit_keyword_miss():
    c = _commit(subject='mm: fix page fault')
    pr = _profile_rules()
    r = score_commit(c, {}, pr)
    assert 'networking' not in r['matched_profiles']


def test_score_commit_path_whitelist_hit():
    c = _commit(subject='fix: something', files=['drivers/net/core.c'])
    pr = _profile_rules(kw_wl=[], path_wl=['drivers/net/'])
    r = score_commit(c, {}, pr)
    assert r['score'] > 0


def test_score_commit_keyword_blacklist_suppresses():
    c = _commit(subject='net: fix skb')
    pr = _profile_rules(kw_bl=['net:'])
    r = score_commit(c, {}, pr)
    assert r['scoring']['profiles']['networking'] == 0


def test_score_commit_commit_whitelist():
    c = _commit(sha='deadbeef')
    pr = _profile_rules(kw_wl=[], commit_wl=['deadbeef'])
    r = score_commit(c, {}, pr)
    assert 'networking' in r['matched_profiles']


def test_score_commit_commit_blacklist():
    c = _commit(sha='badsha')
    pr = _profile_rules(commit_bl=['badsha'])
    r = score_commit(c, {}, pr)
    assert r['scoring']['profiles']['networking'] == 0


def test_score_commit_body_keyword_hit():
    c = _commit(subject='mm: fix', body='This fixes a skb leak in the net stack')
    pr = _profile_rules()
    r = score_commit(c, {}, pr)
    assert r['score'] > 0


def test_score_commit_no_profiles():
    c = _commit()
    r = score_commit(c, {}, {})
    assert r['score'] == 0
    assert r['matched_profiles'] == []


def test_score_commit_capped_at_100_per_profile():
    """Multiple heavy rules can't push a single profile above 100."""
    rules = {f'r{i}': {'keywords_whitelist': ['net:'], 'keywords_blacklist': [],
                        'path_whitelist': [], 'path_blacklist': [],
                        'commit_whitelist': [], 'commit_blacklist': [],
                        'weight': 60} for i in range(5)}
    pr = {'networking': {'description': '', 'rules': rules,
                  'merged': {'keywords_whitelist': ['net:'], 'keywords_blacklist': [],
                              'path_whitelist': [], 'path_blacklist': [],
                              'commit_whitelist': [], 'commit_blacklist': []}}}
    precompile_rules(pr)
    r = score_commit(_commit(subject='net: big fix'), {}, pr)
    assert r['scoring']['profiles']['networking'] <= 100


def test_score_commit_product_evidence_config_map():
    c = _commit(files=['drivers/usb/hub.c'])
    pm = {'config_to_paths': {'CONFIG_USB': ['drivers/usb/hub.c']},
          'enabled_configs': ['CONFIG_USB'],
          'config_dirs': [], 'built_objects_from_log': [],
          'built_artifacts_from_dir': []}
    r = score_commit(c, pm, {})
    assert any('config_map:CONFIG_USB' in e for e in r['product_evidence'])


def test_score_commit_meta_stored():
    c = _commit(subject='CVE-2024-9999 fix')
    r = score_commit(c, {}, {})
    assert r['meta'].get('has_cve') is True


# ── fmt_profiles / fmt_evidence ───────────────────────────────────────────────
def test_fmt_profiles_multiple():
    c = {'matched_profiles': ['networking', 'security_fixes']}
    assert fmt_profiles(c) == 'networking; security_fixes'


def test_fmt_profiles_empty():
    assert fmt_profiles({'matched_profiles': []}) == ''


def test_fmt_profiles_missing_key():
    assert fmt_profiles({}) == ''


def test_fmt_evidence_multiple():
    c = {'product_evidence': ['config_map:CONFIG_USB', 'build_log:hub']}
    result = fmt_evidence(c)
    assert 'config_map:CONFIG_USB' in result


def test_fmt_evidence_empty():
    assert fmt_evidence({'product_evidence': []}) == ''
