"""Tests for lib.scoring — extract_commit_meta, score_commit.

v13.0.1: _pm() helper now includes config_enabled_map and config_enabled_dirs
so that _collect_product_evidence() reads from the correct field.
test_evidence_config_map_hit / test_evidence_config_map_miss updated accordingly.

vG: removed touched_paths_guess from commit fixtures (field no longer used by
_collect_product_evidence).  test_evidence_artifact_hit updated to match the
new T1 full-path-stem logic.  test_evidence_build_log_hit updated to use a
real object path and supply config_enabled_dirs so the T2 directory-scope guard
fires.  test_evidence_config_text_hit replaced by test_evidence_no_config_text_tag
to verify that the old config_text: noise source no longer fires.
"""
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


# -- fmt helpers (E.3) ---------------------------------------------------------
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


# -- _collect_product_evidence -------------------------------------------------
from lib.scoring import _collect_product_evidence


def _pm(**kw):
    """Build a minimal product_map for evidence tests.

    v13.0.1: includes config_enabled_map and config_enabled_dirs by default
    so _collect_product_evidence() reads from the correct (enabled-only) field.
    If a test passes config_enabled_map explicitly it overrides the default.
    """
    base = {
        'config_enabled_map':       {},
        'config_enabled_dirs':      [],
        'config_to_paths':          {},
        'enabled_configs':          [],
        'config_dirs':              [],
        'built_artifacts_from_dir': [],
        'built_objects_from_log':   [],
    }
    base.update(kw)
    return base


def test_evidence_config_map_hit():
    """v13.0.1: pass config_enabled_map (enabled symbols only)."""
    c = _commit(files=['drivers/usb/core/hub.c'])
    pm = _pm(config_enabled_map={'CONFIG_USB': ['drivers/usb/core/hub.c']})
    ev = _collect_product_evidence(c, pm)
    assert any('config_map' in e for e in ev)


def test_evidence_config_map_miss():
    """File not in config_enabled_map -> no config_map evidence."""
    c = _commit(files=['mm/slab.c'])
    pm = _pm(config_enabled_map={'CONFIG_USB': ['drivers/usb/core/hub.c']})
    ev = _collect_product_evidence(c, pm)
    assert not any('config_map' in e for e in ev)


def test_evidence_artifact_hit():
    """vG (T1): full-path stem match against built_artifacts_from_dir.
    touched_paths_guess is no longer used for evidence collection.
    """
    c = _commit(files=['drivers/usb/core/hub.c'])
    pm = _pm(built_artifacts_from_dir=['drivers/usb/core/hub.c'])
    ev = _collect_product_evidence(c, pm)
    assert any('artifact' in e for e in ev)


def test_evidence_build_log_hit():
    """vG (T2): basename-stem match scoped to compiled dirs.
    Log entry must be an object path (hub.o) so the basename stem extraction
    yields 'hub'.  config_enabled_dirs must include the file's parent directory
    so the directory-scope guard passes (same as st04 _file_has_artifact).
    """
    c = _commit(files=['drivers/usb/core/hub.c'])
    pm = _pm(
        config_enabled_dirs=['drivers/usb/core/'],
        built_objects_from_log=['drivers/usb/core/hub.o'],
    )
    ev = _collect_product_evidence(c, pm)
    assert any('build_log' in e for e in ev)


def test_evidence_no_config_text_tag():
    """vG: config_text: tags were removed.  The commit subject/body text no
    longer generates evidence; only actual commit files are evaluated.
    A commit that mentions 'CONFIG_USB' in its message but does not touch any
    USB source file must NOT receive a config_text evidence tag.
    """
    c = _commit(subject='Fix CONFIG_USB driver crash', body='usb stack overflow',
                files=['mm/slab.c'])
    pm = _pm(enabled_configs=['CONFIG_USB'])
    ev = _collect_product_evidence(c, pm)
    assert not any('config_text' in e for e in ev)


def test_evidence_none_product_map():
    c = _commit(subject='net: fix skb')
    ev = _collect_product_evidence(c, None)
    assert ev == []


# -- meta-multiplier bonuses (extract_commit_meta flags) -----------------------
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


def test_score_commit_includes_rule_trace_details():
    commit = {'commit': 'abc123', 'subject': 'usb fix', 'body': 'CVE-2026-1234',
              'files': ['drivers/usb/core.c']}
    product_map = {
        'config_enabled_map': {}, 'config_enabled_dirs': [],
        'config_to_paths': {}, 'enabled_configs': [],
        'config_dirs': [], 'built_objects_from_log': [],
        'built_artifacts_from_dir': [],
    }
    profile_rules = {
        'sec': {
            'merged': {
                'keywords_whitelist': ['CVE-*'], 'keywords_blacklist': [],
                'path_whitelist': ['drivers/usb/*'], 'path_blacklist': [],
                'commit_whitelist': [], 'commit_blacklist': [],
            },
            'rules': {
                'r1': {'weight': 30, 'keywords_whitelist': ['CVE-*'],
                       'path_whitelist': [], 'commit_whitelist': []},
                'r2': {'weight': 20, 'keywords_whitelist': [],
                       'path_whitelist': ['drivers/usb/*'], 'commit_whitelist': []},
            },
        }
    }
    out = score_commit(commit, product_map, profile_rules,
                       {'profiles': {'active': {'sec': 100}}})
    trace = out['scoring']['trace']['profiles']['sec']
    assert trace['raw_rule_total'] == 50
    assert trace['final_score'] == 50
    assert trace['rules']['r1']['matched'] is True
    assert trace['rules']['r1']['score']
