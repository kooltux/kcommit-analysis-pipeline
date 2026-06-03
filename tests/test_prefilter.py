"""Tests for lib.stages.st04_prefilter — filter_decision and helpers.

v12.0.0 (A.1): filter_decision() now returns a 3-tuple
  (action, reason, debug_detail)
All callers updated; new test block covers debug_detail content.
"""
import os
import re

from lib.stages.st04_prefilter import (
    filter_decision, build_merged_lists, build_compiled_sets,
    _file_has_artifact, _build_prefilter_debug_entry,
)

_EMPTY_CS = dict(compiled_files=set(), compiled_dirs=set(),
                 artifact_stems=set(), log_basenames=set(), available=False)


def _commit(sha='aaa', subject='', body='', files=None):
    return {'commit': sha, 'subject': subject, 'body': body or '',
            'files': files or []}


def _lists(**kw):
    base = {k: [] for k in ('commit_wl', 'commit_bl', 'path_wl', 'path_bl', 'kw_wl', 'kw_bl')}
    base.update(kw)
    return base


# ── L3 absolute ──────────────────────────────────────────────────────────────
def test_commit_whitelist_wins():
    c = _commit(sha='deadbeef')
    action, reason, dbg = filter_decision(c, _lists(commit_wl=['deadbeef']),
                                          _EMPTY_CS, {}, False)
    assert action == 'keep' and reason == 'commit_whitelist'


def test_commit_blacklist_drops():
    c = _commit(sha='deadbeef')
    action, reason, dbg = filter_decision(c, _lists(commit_bl=['deadbeef']),
                                          _EMPTY_CS, {}, False)
    assert action == 'drop' and reason == 'commit_blacklist'


def test_commit_whitelist_beats_blacklist():
    c = _commit(sha='deadbeef')
    action, _, _dbg = filter_decision(
        c, _lists(commit_wl=['deadbeef'], commit_bl=['deadbeef']),
        _EMPTY_CS, {}, False)
    assert action == 'keep'


# ── L2 path ──────────────────────────────────────────────────────────────────
def test_path_blacklist_all_drops():
    c = _commit(files=['Documentation/foo.rst', 'Documentation/bar.rst'])
    action, reason, dbg = filter_decision(c, _lists(path_bl=['Documentation/']),
                                          _EMPTY_CS, {}, False)
    assert action == 'drop' and 'path_blacklist' in reason


def test_path_blacklist_partial_does_not_drop():
    c = _commit(files=['Documentation/foo.rst', 'drivers/usb/hub.c'])
    action, _, _dbg = filter_decision(c, _lists(path_bl=['Documentation/']),
                                      _EMPTY_CS, {}, False)
    assert action == 'keep'


def test_path_whitelist_keeps():
    c = _commit(files=['drivers/usb/hub.c'])
    action, reason, dbg = filter_decision(c, _lists(path_wl=['drivers/usb/']),
                                          _EMPTY_CS, {}, False)
    assert action == 'keep' and reason == 'path_whitelist'


# ── L1 keywords ──────────────────────────────────────────────────────────────
def test_keyword_whitelist_keeps():
    c = _commit(subject='net: fix skb use-after-free')
    action, reason, dbg = filter_decision(c, _lists(kw_wl=['use-after-free']),
                                          _EMPTY_CS, {}, False)
    assert action == 'keep' and reason == 'keywords_whitelist'


def test_keyword_blacklist_drops():
    c = _commit(subject='Documentation: update grammar')
    action, reason, dbg = filter_decision(c, _lists(kw_bl=['Documentation']),
                                          _EMPTY_CS, {}, False)
    assert action == 'drop' and reason == 'keywords_blacklist'


# ── L0 default ────────────────────────────────────────────────────────────────
def test_default_keep():
    c = _commit(subject='net: fix something random')
    action, reason, dbg = filter_decision(c, _lists(), _EMPTY_CS, {}, False)
    assert action == 'keep' and reason == 'default'


# ── filter_disabled ───────────────────────────────────────────────────────────
def test_filter_disabled_bypasses_path_bl():
    c = _commit(files=['Documentation/foo.rst', 'Documentation/bar.rst'])
    action, reason, dbg = filter_decision(c, _lists(path_bl=['Documentation/']),
                                          _EMPTY_CS, {'enabled': False}, False)
    assert action == 'keep' and reason == 'filter_disabled'


# ── build_merged_lists ────────────────────────────────────────────────────────
def test_build_merged_lists_dedup():
    profile_rules = {
        'p1': {'merged': {'path_whitelist': ['drivers/usb/', 'drivers/usb/']}},
        'p2': {'merged': {'path_whitelist': ['drivers/usb/', 'drivers/net/']}},
    }
    lists = build_merged_lists(profile_rules)
    assert len(lists['path_wl']) == 2  # deduped to 2


# ── build_compiled_sets ───────────────────────────────────────────────────────
def test_build_compiled_sets_empty_no_product_map():
    cs = build_compiled_sets(None)
    assert cs['available'] is False


def test_build_compiled_sets_with_data():
    pm = {
        'config_to_paths': {'CONFIG_USB': ['drivers/usb/core/hub.c']},
        'enabled_configs':  ['CONFIG_USB=y'],
        'built_artifacts_from_dir': ['drivers/usb/core/hub.o'],
        'built_objects_from_log':   [],
    }
    cs = build_compiled_sets(pm)
    assert cs['available'] is True
    assert 'drivers/usb/core/hub.c' in cs['compiled_files']
    assert 'drivers/usb/core' in cs['compiled_dirs']
    assert 'drivers/usb/core/hub' in cs['artifact_stems']


# ── A: built-in.o ────────────────────────────────────────────────────────────
def test_build_compiled_sets_builtin_o_not_in_artifact_stems():
    pm = {
        'config_to_paths': {'CONFIG_DRM': ['drivers/gpu/drm/drm_drv.c']},
        'enabled_configs':  ['CONFIG_DRM=y'],
        'built_artifacts_from_dir': [
            'drivers/gpu/drm/built-in.o',
            'drivers/gpu/drm/drm_drv.o',
        ],
        'built_objects_from_log': [],
    }
    cs = build_compiled_sets(pm)
    assert cs['available'] is True
    assert 'drivers/gpu/drm/drm_drv' in cs['artifact_stems']


def test_builtin_o_only_commit_not_kept_by_artifact_evidence():
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/gpu/drm'},
        artifact_stems={'drivers/gpu/drm/drm_drv'},
        log_basenames=set(),
        available=True,
    )
    c = _commit(files=['drivers/gpu/drm/built-in.o'])
    action, reason, dbg = filter_decision(
        c, _lists(), cs, {'require_kconfig_coverage': False}, True)
    assert reason != 'build_artifact', (
        'built-in.o must not trigger build_artifact keep; got reason=%r' % reason
    )


def test_builtin_o_only_commit_dropped_when_kconfig_required():
    cs = dict(
        compiled_files={'drivers/gpu/drm/drm_drv.c'},
        compiled_dirs={'drivers/gpu/drm'},
        artifact_stems={'drivers/gpu/drm/drm_drv'},
        log_basenames=set(),
        available=True,
    )
    c = _commit(files=['drivers/gpu/drm/built-in.o'])
    action, reason, dbg = filter_decision(
        c, _lists(), cs, {'require_kconfig_coverage': True}, True)
    assert reason != 'build_artifact'


# ── C: log_basenames directory-scoped ────────────────────────────────────────
def test_file_has_artifact_log_match_requires_compiled_dir():
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb'},
        artifact_stems=set(),
        log_basenames={'hub'},
        available=True,
    )
    assert not _file_has_artifact('sound/usb/hub.c', cs)
    assert not _file_has_artifact('net/hub.c', cs)
    assert _file_has_artifact('drivers/usb/hub.c', cs)


def test_file_has_artifact_log_match_requires_compiled_dir_deep():
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/net/ethernet/intel'},
        artifact_stems=set(),
        log_basenames={'e1000e'},
        available=True,
    )
    assert _file_has_artifact('drivers/net/ethernet/intel/e1000e.c', cs)
    assert not _file_has_artifact('drivers/net/ethernet/broadcom/e1000e.c', cs)


def test_file_has_artifact_log_match_via_compiled_files():
    cs = dict(
        compiled_files={'drivers/usb/hub.c'},
        compiled_dirs=set(),
        artifact_stems=set(),
        log_basenames={'hub'},
        available=True,
    )
    assert _file_has_artifact('drivers/usb/hub.c', cs)


def test_file_has_artifact_no_log_no_stem_returns_false():
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb'},
        artifact_stems=set(),
        log_basenames={'hub'},
        available=True,
    )
    assert not _file_has_artifact('drivers/usb/core.c', cs)


def test_log_basename_cross_tree_commit_not_kept():
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb'},
        artifact_stems=set(),
        log_basenames={'hub'},
        available=True,
    )
    c = _commit(files=['sound/usb/hub.c'])
    action, reason, dbg = filter_decision(
        c, _lists(), cs, {'require_kconfig_coverage': False}, True)
    assert reason != 'build_artifact', (
        'sound/usb/hub.c must not be kept by artifact evidence from drivers/usb/hub.o; '
        'got reason=%r' % reason
    )


def test_log_basename_same_dir_commit_kept():
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb'},
        artifact_stems=set(),
        log_basenames={'hub'},
        available=True,
    )
    c = _commit(files=['drivers/usb/hub.c'])
    action, reason, dbg = filter_decision(c, _lists(), cs, {}, False)
    assert action == 'keep' and reason == 'build_artifact'


# ── min_score threshold (E.1c / st06_postfilter) ─────────────────────────────
from lib.stages.st06_postfilter import _get_threshold


def test_get_threshold_default():
    assert _get_threshold({}) == 0.0


def test_get_threshold_from_filter():
    assert _get_threshold({'filter': {'min_score': 25}}) == 25.0


def test_get_threshold_ignores_reports():
    assert _get_threshold({'reports': {'min_score': 99}}) == 0.0


def test_get_threshold_filter_wins():
    cfg = {'filter': {'min_score': 10}, 'reports': {'min_score': 99}}
    assert _get_threshold(cfg) == 10.0


# ── L2½: artifact / kconfig evidence ────────────────────────────────────────
def test_artifact_evidence_keeps_commit():
    c = _commit(files=['drivers/usb/core/hub.c'])
    cs = dict(
        compiled_files=set(),
        compiled_dirs=set(),
        artifact_stems={'drivers/usb/core/hub'},
        log_basenames=set(),
        available=True,
    )
    action, reason, dbg = filter_decision(c, _lists(), cs, {}, False)
    assert action == 'keep'
    assert reason == 'build_artifact'


def test_kconfig_miss_drops_commit():
    c = _commit(files=['drivers/usb/core/hub.c'])
    cs = dict(
        compiled_files=set(), compiled_dirs=set(),
        artifact_stems=set(), log_basenames=set(), available=True,
    )
    action, reason, dbg = filter_decision(
        c, _lists(), cs, {'require_kconfig_coverage': True}, True)
    assert action == 'drop'
    assert 'kconfig' in reason


def test_kconfig_coverage_not_required_keeps():
    c = _commit(files=['drivers/usb/core/hub.c'])
    cs = dict(
        compiled_files=set(), compiled_dirs=set(),
        artifact_stems=set(), log_basenames=set(), available=True,
    )
    action, _, _dbg = filter_decision(
        c, _lists(), cs, {'require_kconfig_coverage': False}, True)
    assert action == 'keep'


# ── build_merged_lists: multiple profiles merged correctly ────────────────────
def test_build_merged_lists_multiple_profiles():
    profile_rules = {
        'net':  {'merged': {'path_whitelist': ['drivers/net/'], 'path_blacklist': [],
                            'keywords_whitelist': [], 'keywords_blacklist': [],
                            'commit_whitelist': [], 'commit_blacklist': []}},
        'usb':  {'merged': {'path_whitelist': ['drivers/usb/'], 'path_blacklist': [],
                            'keywords_whitelist': [], 'keywords_blacklist': [],
                            'commit_whitelist': [], 'commit_blacklist': []}},
    }
    lists = build_merged_lists(profile_rules)
    assert 'drivers/net/' in lists['path_wl']
    assert 'drivers/usb/' in lists['path_wl']


# ══ A.1: debug_detail content tests ══════════════════════════════════════════════════════

def test_debug_detail_is_dict_with_required_keys():
    """filter_decision() always returns a dict with the documented keys."""
    c = _commit(subject='net: fix skb')
    _, _, dbg = filter_decision(c, _lists(), _EMPTY_CS, {}, False)
    for key in ('sha', 'files', 'l3_commit_wl_match', 'l3_commit_bl_match',
                'l2a_path_bl_matches', 'l2b_path_wl_matches',
                'l2half_artifact_files',
                'l2half_kconfig_covered_files', 'l2half_kconfig_uncovered_files',
                'l1a_kw_wl_matches', 'l1b_kw_bl_matches',
                'filter_enabled', 'kconfig_required'):
        assert key in dbg, f'debug_detail missing key: {key!r}'


def test_debug_detail_sha_populated():
    c = _commit(sha='abc123', subject='foo')
    _, _, dbg = filter_decision(c, _lists(), _EMPTY_CS, {}, False)
    assert dbg['sha'] == 'abc123'


def test_debug_detail_l3_commit_bl_match_populated():
    c = _commit(sha='deadbeef')
    _, _, dbg = filter_decision(c, _lists(commit_bl=['deadbeef']), _EMPTY_CS, {}, False)
    assert dbg['l3_commit_bl_match'] is not None
    assert dbg['l3_commit_bl_match']['pattern'] == 'deadbeef'
    assert dbg['l3_commit_bl_match']['value'] == 'deadbeef'


def test_debug_detail_l3_commit_bl_none_on_miss():
    c = _commit(sha='xyz')
    _, _, dbg = filter_decision(c, _lists(commit_bl=['deadbeef']), _EMPTY_CS, {}, False)
    assert dbg['l3_commit_bl_match'] is None


def test_debug_detail_l2a_path_bl_matches_on_drop():
    c = _commit(files=['Documentation/foo.rst', 'Documentation/bar.rst'])
    _, _, dbg = filter_decision(c, _lists(path_bl=['Documentation/']), _EMPTY_CS, {}, False)
    assert len(dbg['l2a_path_bl_matches']) >= 1
    patterns = [m['pattern'] for m in dbg['l2a_path_bl_matches']]
    assert any('Documentation' in p for p in patterns)


def test_debug_detail_l2b_path_wl_matches_on_keep():
    c = _commit(files=['drivers/usb/hub.c'])
    _, _, dbg = filter_decision(c, _lists(path_wl=['drivers/usb/']), _EMPTY_CS, {}, False)
    assert len(dbg['l2b_path_wl_matches']) >= 1
    patterns = [m['pattern'] for m in dbg['l2b_path_wl_matches']]
    assert any('drivers/usb' in p for p in patterns)


def test_debug_detail_l1a_kw_wl_matches_on_keyword_keep():
    c = _commit(subject='net: fix skb use-after-free')
    _, _, dbg = filter_decision(c, _lists(kw_wl=['use-after-free']), _EMPTY_CS, {}, False)
    assert len(dbg['l1a_kw_wl_matches']) >= 1
    assert any('use-after-free' in m['pattern'] for m in dbg['l1a_kw_wl_matches'])


def test_debug_detail_l1b_kw_bl_matches_on_keyword_drop():
    c = _commit(subject='Documentation: update grammar')
    _, _, dbg = filter_decision(c, _lists(kw_bl=['Documentation']), _EMPTY_CS, {}, False)
    assert len(dbg['l1b_kw_bl_matches']) >= 1


def test_debug_detail_kconfig_covered_populated():
    c = _commit(files=['drivers/usb/core/hub.c'])
    cs = dict(
        compiled_files={'drivers/usb/core/hub.c'},
        compiled_dirs=set(), artifact_stems=set(), log_basenames=set(), available=True,
    )
    _, _, dbg = filter_decision(c, _lists(), cs, {}, True)
    assert 'drivers/usb/core/hub.c' in dbg['l2half_kconfig_covered_files']
    assert dbg['l2half_kconfig_uncovered_files'] == []


def test_debug_detail_kconfig_uncovered_populated():
    c = _commit(files=['net/unrelated.c'])
    cs = dict(
        compiled_files={'drivers/usb/core/hub.c'},
        compiled_dirs=set(), artifact_stems=set(), log_basenames=set(), available=True,
    )
    _, _, dbg = filter_decision(
        c, _lists(), cs, {'require_kconfig_coverage': True}, True)
    assert 'net/unrelated.c' in dbg['l2half_kconfig_uncovered_files']


def test_debug_detail_filter_enabled_flag():
    c = _commit()
    _, _, dbg = filter_decision(c, _lists(), _EMPTY_CS, {'enabled': False}, False)
    assert dbg['filter_enabled'] is False


# ══ A.1: _build_prefilter_debug_entry ═════════════════════════════════════════════════════

def test_build_prefilter_debug_entry_structure():
    c = _commit(sha='abc123', subject='treewide: cleanup', files=['mm/slab.c'])
    c['author_name'] = 'Alice'
    dbg = {'sha': 'abc123', 'filter_enabled': True}
    entry = _build_prefilter_debug_entry(c, 'path_blacklist_all', dbg)
    assert entry['sha12'] == 'abc123'
    assert entry['drop_reason'] == 'path_blacklist_all'
    assert entry['subject'] == 'treewide: cleanup'
    assert entry['author'] == 'Alice'
    assert 'mm/slab.c' in entry['files']
    assert entry['debug'] is dbg


def test_build_prefilter_debug_entry_sha_truncated():
    sha = 'a' * 50  # longer than 40
    c = _commit(sha=sha)
    entry = _build_prefilter_debug_entry(c, 'keywords_blacklist', {})
    assert len(entry['sha']) == 40


def test_build_prefilter_debug_entry_sha12_truncated():
    sha = 'a' * 50
    c = _commit(sha=sha)
    entry = _build_prefilter_debug_entry(c, 'keywords_blacklist', {})
    assert len(entry['sha12']) == 12
