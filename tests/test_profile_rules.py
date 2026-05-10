"""Tests for lib.profile_rules — active_profile_names, compile_rules_for_config,
load_profile_rules, _merged_patterns."""
import json
import os

from lib.profile_rules import (
    active_profile_names,
    compile_rules_for_config,
    load_profile_rules,
    _merged_patterns,
)


def _write_profile(profiles_dir, name, rules_refs):
    """Write a minimal profile JSON file referencing rule folder names."""
    data = {'rules': {r: {'weight': 10} for r in rules_refs}}
    p = os.path.join(str(profiles_dir), name + '.json')
    with open(p, 'w') as f:
        json.dump(data, f)


def _write_rule(rules_dir, name, patterns):
    """Create a rule subdirectory with a keywords_whitelist.txt file."""
    rdir = os.path.join(str(rules_dir), name)
    os.makedirs(rdir, exist_ok=True)
    with open(os.path.join(rdir, 'keywords_whitelist.txt'), 'w') as f:
        f.write('\n'.join(patterns))


def _cfg(tmp_path, active, profiles_dir, rules_dir):
    return {
        'paths': {
            'work_dir':      str(tmp_path),
            'cache_dir':     str(tmp_path / 'cache'),
            'profiles_dirs': [str(profiles_dir)],
            'rules_dirs':    [str(rules_dir)],
        },
        'profiles': {'active': active},
        'kernel':   {'source_dir': '/linux', 'rev_old': 'v6.8', 'rev_new': 'HEAD'},
    }


# ── active_profile_names ──────────────────────────────────────────────────────
def test_active_profile_names_dict():
    cfg = {'profiles': {'active': {'security_fixes': 100, 'networking': 80}}}
    names = active_profile_names(cfg)
    assert set(names) == {'security_fixes', 'networking'}


def test_active_profile_names_list():
    cfg = {'profiles': {'active': ['security_fixes', 'networking']}}
    names = active_profile_names(cfg)
    assert set(names) == {'security_fixes', 'networking'}


def test_active_profile_names_empty():
    cfg = {'profiles': {'active': {}}}
    assert active_profile_names(cfg) == []


def test_active_profile_names_missing():
    cfg = {}
    assert active_profile_names(cfg) == []


# ── _merged_patterns ──────────────────────────────────────────────────────────
def test_merged_patterns_empty():
    assert _merged_patterns(None) == {}
    assert _merged_patterns({}) == {}


def test_merged_patterns_returns_merged_dict():
    pdata = {'merged': {'keywords_whitelist': ['usb']}}
    assert _merged_patterns(pdata) == {'keywords_whitelist': ['usb']}


# ── compile_rules_for_config ──────────────────────────────────────────────────
def test_compile_rules_basic(tmp_path):
    pd = tmp_path / 'profiles'; pd.mkdir()
    rd = tmp_path / 'rules';    rd.mkdir()
    (tmp_path / 'cache').mkdir()
    _write_rule(rd, 'net_rule', ['net:', 'skb'])
    _write_profile(pd, 'networking', ['net_rule'])

    cfg = _cfg(tmp_path, {'networking': 100}, pd, rd)
    result = compile_rules_for_config(cfg, str(tmp_path))

    assert 'networking' in result
    assert 'net_rule' in result['networking']['rules']
    kw = result['networking']['merged'].get('keywords_whitelist', [])
    kw_strs = [p if isinstance(p, str) else p.pattern for p in kw]
    assert any('net' in k for k in kw_strs)


def test_compile_rules_no_active_raises(tmp_path):
    import pytest
    pd = tmp_path / 'profiles'; pd.mkdir()
    rd = tmp_path / 'rules';    rd.mkdir()
    cfg = _cfg(tmp_path, {}, pd, rd)
    with pytest.raises(RuntimeError, match='no active profiles'):
        compile_rules_for_config(cfg, str(tmp_path))


def test_compile_rules_missing_profile_raises(tmp_path):
    import pytest
    pd = tmp_path / 'profiles'; pd.mkdir()
    rd = tmp_path / 'rules';    rd.mkdir()
    cfg = _cfg(tmp_path, {'ghost_profile': 10}, pd, rd)
    with pytest.raises(RuntimeError):
        compile_rules_for_config(cfg, str(tmp_path))


def test_compile_rules_merged_union(tmp_path):
    """merged.keywords_whitelist is the union of patterns across all rules."""
    pd = tmp_path / 'profiles'; pd.mkdir()
    rd = tmp_path / 'rules';    rd.mkdir()
    (tmp_path / 'cache').mkdir()
    _write_rule(rd, 'rule_a', ['usb'])
    _write_rule(rd, 'rule_b', ['bluetooth'])
    _write_profile(pd, 'wireless', ['rule_a', 'rule_b'])
    cfg = _cfg(tmp_path, {'wireless': 100}, pd, rd)
    result = compile_rules_for_config(cfg, str(tmp_path))
    kw = result['wireless']['merged']['keywords_whitelist']
    kw_strs = [p if isinstance(p, str) else p.pattern for p in kw]
    assert any('usb' in k for k in kw_strs)
    assert any('bluetooth' in k for k in kw_strs)


# ── load_profile_rules ────────────────────────────────────────────────────────
def test_load_profile_rules_uses_compiled_cache(tmp_path):
    """load_profile_rules compiles and writes cache; second call reads it."""
    pd = tmp_path / 'profiles'; pd.mkdir()
    rd = tmp_path / 'rules';    rd.mkdir()
    (tmp_path / 'cache').mkdir()
    _write_rule(rd, 'r1', ['cve'])
    _write_profile(pd, 'security_fixes', ['r1'])
    cfg = _cfg(tmp_path, {'security_fixes': 100}, pd, rd)

    result1 = load_profile_rules(cfg)
    assert 'security_fixes' in result1

    result2 = load_profile_rules(cfg)
    assert 'security_fixes' in result2


def test_compile_rules_falls_back_to_builtin_rule_dirs(tmp_path):
    """D.1: external configs may reference shipped shared rules without copying
    them into the external rules tree."""
    pd = tmp_path / 'profiles'; pd.mkdir()
    rd = tmp_path / 'rules';    rd.mkdir()
    (tmp_path / 'cache').mkdir()
    _write_profile(pd, 'performance', ['generic'])
    cfg = _cfg(tmp_path, {'performance': 100}, pd, rd)
    result = compile_rules_for_config(cfg, str(tmp_path))
    assert 'performance' in result
    assert 'generic' in result['performance']['rules']


def test_compile_rules_prefers_external_rule_dir_before_builtin(tmp_path):
    """D.1: if a custom rules tree defines the same rule name, it wins."""
    pd = tmp_path / 'profiles'; pd.mkdir()
    rd = tmp_path / 'rules';    rd.mkdir()
    (tmp_path / 'cache').mkdir()
    _write_rule(rd, 'generic', ['artemis-only-keyword'])
    _write_profile(pd, 'performance', ['generic'])
    cfg = _cfg(tmp_path, {'performance': 100}, pd, rd)
    result = compile_rules_for_config(cfg, str(tmp_path))
    kw = result['performance']['merged'].get('keywords_whitelist', [])
    kw_strs = [p if isinstance(p, str) else p.pattern for p in kw]
    assert any('artemis-only-keyword' in k for k in kw_strs)



def test_compile_rules_accepts_singular_paths_rules_dir_alias(tmp_path):
    profiles = tmp_path / 'profiles'
    rules = tmp_path / 'rules'
    profiles.mkdir(); rules.mkdir()
    _write_profile(profiles, 'myprof', {'r1': 100})
    _write_rule(rules, 'r1', {'keyword.txt': ['foo']})
    cfg = {
        'profiles': {'active': {'myprof': 100}},
        'paths': {
            'profiles_dir': str(profiles),
            'rules_dir': str(rules),
        },
        '_meta': {'config_dir': str(tmp_path)},
    }
    out = compile_rules_for_config(cfg, cache_dir=str(tmp_path / 'cache'))
    assert 'myprof' in out
    assert 'r1' in out['myprof']['rules']


def test_compile_rules_accepts_singular_paths_profiles_dir_alias(tmp_path):
    profiles = tmp_path / 'profiles'
    rules = tmp_path / 'rules'
    profiles.mkdir(); rules.mkdir()
    _write_profile(profiles, 'myprof', {'r1': 100})
    _write_rule(rules, 'r1', {'keyword.txt': ['foo']})
    cfg = {
        'profiles': {'active': {'myprof': 100}},
        'paths': {
            'profiles_dir': str(profiles),
            'rules_dirs': [str(rules)],
        },
        '_meta': {'config_dir': str(tmp_path)},
    }
    out = compile_rules_for_config(cfg, cache_dir=str(tmp_path / 'cache'))
    assert 'myprof' in out
    assert 'r1' in out['myprof']['rules']



def test_compile_rules_builtin_profile_uses_builtin_rule_dirs(tmp_path):
    cfg = {
        'profiles': {'active': {'performance': 100}},
        'paths': {
            'profiles_dirs': [str(tmp_path / 'profiles')],
            'rules_dirs': [str(tmp_path / 'rules')],
        },
        '_meta': {'config_dir': str(tmp_path)},
    }
    (tmp_path / 'profiles').mkdir()
    (tmp_path / 'rules').mkdir()
    out = compile_rules_for_config(cfg, cache_dir=str(tmp_path / 'cache'))
    assert 'performance' in out
    assert 'generic' in out['performance']['rules']


def test_compile_rules_external_profile_can_use_builtin_rule_fallback(tmp_path):
    profiles = tmp_path / 'profiles'
    rules = tmp_path / 'rules'
    profiles.mkdir(); rules.mkdir()
    _write_profile(profiles, 'performance', {'generic': 10, 'performance_general': 70})
    cfg = {
        'profiles': {'active': {'performance': 100}},
        'paths': {
            'profiles_dirs': [str(profiles)],
            'rules_dirs': [str(rules)],
        },
        '_meta': {'config_dir': str(tmp_path)},
    }
    out = compile_rules_for_config(cfg, cache_dir=str(tmp_path / 'cache'))
    assert 'performance' in out
    assert 'generic' in out['performance']['rules']
    assert 'performance_general' in out['performance']['rules']



def test_compile_rules_builtin_rule_alias_artemis_generic_falls_back_to_generic(tmp_path):
    profiles = tmp_path / 'profiles'
    rules = tmp_path / 'rules'
    profiles.mkdir(); rules.mkdir()
    _write_profile(profiles, 'performance', {'artemis_generic': 10})
    cfg = {
        'profiles': {'active': {'performance': 100}},
        'paths': {
            'profiles_dirs': [str(profiles)],
            'rules_dirs': [str(rules)],
        },
        '_meta': {'config_dir': str(tmp_path)},
    }
    out = compile_rules_for_config(cfg, cache_dir=str(tmp_path / 'cache'))
    assert 'performance' in out
    assert 'artemis_generic' in out['performance']['rules']
    assert out['performance']['rules']['artemis_generic']['weight'] == 10


def test_compile_rules_prefers_external_artemis_rule_over_builtin_alias(tmp_path):
    profiles = tmp_path / 'profiles'
    rules = tmp_path / 'rules'
    profiles.mkdir(); rules.mkdir()
    _write_profile(profiles, 'performance', {'artemis_generic': 10})
    _write_rule(rules, 'artemis_generic', ['external-artemis-keyword'])
    cfg = {
        'profiles': {'active': {'performance': 100}},
        'paths': {
            'profiles_dirs': [str(profiles)],
            'rules_dirs': [str(rules)],
        },
        '_meta': {'config_dir': str(tmp_path)},
    }
    out = compile_rules_for_config(cfg, cache_dir=str(tmp_path / 'cache'))
    assert 'artemis_generic' in out['performance']['rules']
    pats = out['performance']['rules']['artemis_generic'].get('keywords_whitelist', [])
    assert any('external-artemis-keyword' in p for p in pats)
