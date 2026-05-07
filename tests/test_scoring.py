"""Tests for lib.scoring — extract_commit_meta, score_commit."""
import os

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
    """Build a minimal profile_rules dict matching compile_rules_for_config output."""
    return {
        'networking': {
            'rules': {
                'net_generic': {
                    'keywords_whitelist': ['net:', 'skb'],
                    'weight': 10,
                }
            },
            'merged': {
                'keywords_whitelist': ['net:', 'skb'],
                'keywords_blacklist': [],
                'commit_whitelist':   [],
                'commit_blacklist':   [],
                'path_whitelist':     [],
                'path_blacklist':     [],
            },
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


# ── fmt helpers (E.3) ────────────────────────────────────────────────────────
from lib.scoring import fmt_profiles, fmt_evidence


def test_fmt_profiles_empty():
    assert fmt_profiles({}) == ''


def test_fmt_profiles_single():
    assert fmt_profiles({'matched_profiles': ['security_fixes']}) == 'security_fixes'


def test_fmt_profiles_multi():
    result = fmt_profiles({'matched_profiles': ['security_fixes', 'performance']})
    assert result == 'security_fixes; performance'


def test_fmt_evidence_empty():
    assert fmt_evidence({}) == ''


def test_fmt_evidence_values():
    c = {'product_evidence': ['kconfig:CONFIG_USB', 'path:drivers/usb']}
    assert fmt_evidence(c) == 'kconfig:CONFIG_USB; path:drivers/usb'


# ── _collect_product_evidence ─────────────────────────────────────────────────
from lib.scoring import _collect_product_evidence


def _pm(**kw):
    base = {
        'config_to_paths':          {},
        'enabled_configs':          [],
        'config_dirs':              [],
        'built_artifacts_from_dir': [],
        'built_objects_from_log':   [],
    }
    base.update(kw)
    return base


def test_evidence_config_map_hit():
    c = _commit(files=['drivers/usb/core/hub.c'])
    pm = _pm(config_to_paths={'CONFIG_USB': ['drivers/usb/core/hub.c']})
    ev = _collect_product_evidence(c, pm)
    assert any('config_map' in e for e in ev)


def test_evidence_config_map_miss():
    c = _commit(files=['mm/slab.c'])
    pm = _pm(config_to_paths={'CONFIG_USB': ['drivers/usb/core/hub.c']})
    ev = _collect_product_evidence(c, pm)
    assert not any('config_map' in e for e in ev)


def test_evidence_artifact_hit():
    # scoring.py: base = basename(tp) → 'hub.c'; matches if base in artifact entry
    c = _commit(files=['drivers/usb/core/hub.c'])
    c['touched_paths_guess'] = ['drivers/usb/core/hub.c']
    pm = _pm(built_artifacts_from_dir=['drivers/usb/core/hub.c'])  # 'hub.c' in 'hub.c'
    ev = _collect_product_evidence(c, pm)
    assert any('artifact' in e for e in ev)


def test_evidence_build_log_hit():
    # scoring.py: base = basename(tp) → 'hub.c'; matches if base in log line
    c = _commit(files=['drivers/usb/core/hub.c'])
    c['touched_paths_guess'] = ['drivers/usb/core/hub.c']
    pm = _pm(built_objects_from_log=['CC drivers/usb/core/hub.c'])  # 'hub.c' in line
    ev = _collect_product_evidence(c, pm)
    assert any('build_log' in e for e in ev)


def test_evidence_config_text_hit():
    # scoring.py line 130: sym[7:].lower() in full_lower → 'usb' in subject/body
    c = _commit(subject='Fix CONFIG_USB driver crash', body='usb stack overflow')
    c['touched_paths_guess'] = []
    pm = _pm(enabled_configs=['CONFIG_USB'])   # no =y suffix; sym[7:] = 'USB'
    ev = _collect_product_evidence(c, pm)
    assert any('config_text' in e for e in ev)


def test_evidence_none_product_map():
    c = _commit(subject='net: fix skb')
    ev = _collect_product_evidence(c, None)
    assert ev == []


# ── meta-multiplier bonuses (extract_commit_meta flags) ──────────────────────
def test_extract_meta_no_flags():
    c = _commit(subject='treewide: fix typos')
    m = extract_commit_meta(c)
    assert m['has_cve'] is False
    assert m['is_fix'] is False
    assert m['has_stable_cc'] is False
    assert m['has_syzbot'] is False


def test_extract_meta_multiple_flags():
    c = _commit(
        subject='Fix CVE-2024-99999',
        body='Fixes: aabbccdd1234 ("some bug")\nCc: stable@vger.kernel.org',
    )
    m = extract_commit_meta(c)
    assert m['has_cve'] is True
    assert m['is_fix'] is True
    assert m['has_stable_cc'] is True
