"""Tests for lib.profile_rules -- active_profile_names, compile_rules_for_config,
load_profile_rules, _merged_patterns.

v13.0.0 (E.2, E.8):
  E.2 -- added test: load_profile_rules() recompiles when a rule file is modified
         (stale cache based on content hash, not timestamp).
  E.8 -- added test: _compute_schema_hash() only hashes the loaded rule files,
         not the entire rules directory tree.
"""
import json
import os
import time

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


# -- active_profile_names ------------------------------------------------------
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


# -- _merged_patterns ----------------------------------------------------------
def test_merged_patterns_empty():
    assert _merged_patterns(None) == {}
    assert _merged_patterns({}) == {}


def test_merged_patterns_returns_merged_dict():
    pdata = {'merged': {'keywords_whitelist': ['usb']}}
    assert _merged_patterns(pdata) == {'keywords_whitelist': ['usb']}


# -- compile_rules_for_config --------------------------------------------------
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


# -- load_profile_rules --------------------------------------------------------
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


# == E.2: stale cache detection via content hash ===============================

def test_load_profile_rules_recompiles_when_rule_file_changes(tmp_path):
    """E.2: load_profile_rules() must detect a stale cache when a rule file
    body is modified, even if the file mtime has not changed.

    The test writes an initial rule, calls load_profile_rules() to prime the
    cache, then modifies the rule file content, then calls load_profile_rules()
    again.  The second call must return the updated patterns (i.e. it
    recompiled rather than reading the stale cache).
    """
    pd = tmp_path / 'profiles'; pd.mkdir()
    rd = tmp_path / 'rules';    rd.mkdir()
    (tmp_path / 'cache').mkdir()
    _write_rule(rd, 'r1', ['original-keyword'])
    _write_profile(pd, 'sec', ['r1'])
    cfg = _cfg(tmp_path, {'sec': 100}, pd, rd)

    # Prime the cache
    result1 = load_profile_rules(cfg)
    kw1 = result1['sec']['merged'].get('keywords_whitelist', [])
    kw1_strs = [p if isinstance(p, str) else p.pattern for p in kw1]
    assert any('original-keyword' in k for k in kw1_strs), \
        'original-keyword not found in first load: %r' % kw1_strs

    # Overwrite rule file with new content
    rule_file = os.path.join(str(rd), 'r1', 'keywords_whitelist.txt')
    with open(rule_file, 'w') as f:
        f.write('replaced-keyword\n')

    # Second load must detect the change and recompile
    result2 = load_profile_rules(cfg)
    kw2 = result2['sec']['merged'].get('keywords_whitelist', [])
    kw2_strs = [p if isinstance(p, str) else p.pattern for p in kw2]
    assert any('replaced-keyword' in k for k in kw2_strs), (
        'E.2: load_profile_rules() did not recompile after rule file content '
        'changed. Got: %r' % kw2_strs
    )
    assert not any('original-keyword' in k for k in kw2_strs), (
        'E.2: stale original-keyword still present after rule file change. '
        'Got: %r' % kw2_strs
    )


# == E.8: hash only covers loaded files =======================================

def test_schema_hash_does_not_include_unloaded_files(tmp_path):
    """E.8: adding a rule file that is NOT referenced by any active profile
    must NOT invalidate the compiled cache.

    If E.8 is correctly implemented, the hash only covers the profile JSON
    and rule body files actually loaded for the active profiles.  An
    irrelevant extra file should not change the hash and therefore should not
    trigger a recompile.
    """
    pd = tmp_path / 'profiles'; pd.mkdir()
    rd = tmp_path / 'rules';    rd.mkdir()
    (tmp_path / 'cache').mkdir()
    _write_rule(rd, 'r1', ['relevant-keyword'])
    _write_profile(pd, 'sec', ['r1'])
    cfg = _cfg(tmp_path, {'sec': 100}, pd, rd)

    # Prime the cache
    result1 = load_profile_rules(cfg)
    assert 'sec' in result1

    # Record the compiled_rules.json mtime to detect recompilation
    from lib.manifest import CACHE_FILES
    cache_file = os.path.join(str(tmp_path / 'cache'), CACHE_FILES['compiled_rules'])
    mtime_before = os.path.getmtime(cache_file) if os.path.exists(cache_file) else None

    # Add an unrelated rule file that no active profile references
    _write_rule(rd, 'r_unused', ['irrelevant-keyword'])

    # Second load: should still use cached result
    result2 = load_profile_rules(cfg)
    assert 'sec' in result2

    if mtime_before is not None and os.path.exists(cache_file):
        mtime_after = os.path.getmtime(cache_file)
        assert mtime_after == mtime_before, (
            'E.8: compiled_rules.json was rewritten after adding an unreferenced '
            'rule file, suggesting the hash covers more files than it should.'
        )


# -- fallback to builtin rules dir ---------------------------------------------
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
