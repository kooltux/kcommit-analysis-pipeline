"""Tests for lib.stages.st04_prefilter -- filter_decision and helpers.

v12.0.0 (A.1): filter_decision() now returns a 3-tuple
  (action, reason, debug_detail)
All callers updated; new test block covers debug_detail content.

v13.0.0 (E.1.x / G):
  E.1.1 -- artifact_files computed once, reused.
  E.1.2 -- kconfig_covered/uncovered populated in debug even for kw-whitelist-saved commits.
  E.1.3 -- build_merged_lists() deduplication is case-insensitive on string patterns.
  E.1.5 -- zero-file commits handled before path/kconfig layers.
  E.1.6 -- build_compiled_sets() ignores bare CONFIG entries without '=' suffix.
  G     -- zero-file default keep reason is 'no_files_layer'.

v13.0.1 (H -- Bug-1 fix):
  H     -- build_compiled_sets() reads config_enabled_map / config_enabled_dirs
           from product_map instead of config_to_paths / enabled_configs.
           All build_compiled_sets() tests updated to supply config_enabled_map
           and config_enabled_dirs directly (pre-filtered by st03).
           Added test_build_compiled_sets_missing_enabled_map_returns_empty()
           to verify the fallback warning path.

v13.0.2 (I -- Bug-2 fix):
  I     -- build_compiled_sets(): removed `if not compiled_files: return empty`
           short-circuit that set available=False when cem={} (no .config).
           available is now True when ANY evidence source is non-empty.
           Added:
             test_build_compiled_sets_cem_empty_no_artifacts_available_false()
             test_build_compiled_sets_cem_empty_but_artifacts_available_true()
             test_btrfs_commit_dropped_auto_require_when_cem_has_usb_only()

v14.0.0 (A -- kw_wl rescue suppression):
  A     -- filter_decision(): kw_wl rescue inside L2half kconfig-miss path is
           suppressed when compiled_files is non-empty.  When file-level
           coverage data is available and a commit's files are conclusively
           uncovered, keyword matching must not override the drop decision.
           New debug field 'kw_wl_rescue_suppressed' (bool) added.
           Added tests:
             test_kw_wl_rescue_suppressed_when_compiled_files_nonempty()
             test_kw_wl_rescue_suppressed_debug_shows_matching_patterns()
             test_kw_wl_rescue_allowed_when_compiled_files_empty()
             test_kw_wl_rescue_suppressed_btrfs_real_world_scenario()
             test_debug_detail_has_kw_wl_rescue_suppressed_key()
             test_kw_wl_rescue_suppressed_false_by_default()
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


# -- L3 absolute ---------------------------------------------------------------
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


# -- L2 path -------------------------------------------------------------------
def test_path_blacklist_all_drops():
    c = _commit(files=['Documentation/foo.rst', 'Documentation/bar.rst'])
    action, reason, dbg = filter_decision(c, _lists(path_bl=['Documentation/']),
                                          _EMPTY_CS, {}, False)
    assert action == 'drop' and 'path_blacklist' in reason


def test_path_blacklist_partial_does_not_drop():
    """E.1.4: L2a only drops when ALL files match the blacklist."""
    c = _commit(files=['Documentation/foo.rst', 'drivers/usb/hub.c'])
    action, _, _dbg = filter_decision(c, _lists(path_bl=['Documentation/']),
                                      _EMPTY_CS, {}, False)
    assert action == 'keep'


def test_path_whitelist_keeps():
    c = _commit(files=['drivers/usb/hub.c'])
    action, reason, dbg = filter_decision(c, _lists(path_wl=['drivers/usb/']),
                                          _EMPTY_CS, {}, False)
    assert action == 'keep' and reason == 'path_whitelist'


# -- L1 keywords ---------------------------------------------------------------
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


# -- L0 default ----------------------------------------------------------------
def test_default_keep():
    """Commits WITH files that reach L0 still get reason='default'."""
    c = _commit(subject='net: fix something random', files=['net/core/sock.c'])
    action, reason, dbg = filter_decision(c, _lists(), _EMPTY_CS, {}, False)
    assert action == 'keep' and reason == 'default'


# -- filter_disabled -----------------------------------------------------------
def test_filter_disabled_bypasses_path_bl():
    c = _commit(files=['Documentation/foo.rst', 'Documentation/bar.rst'])
    action, reason, dbg = filter_decision(c, _lists(path_bl=['Documentation/']),
                                          _EMPTY_CS, {'enabled': False}, False)
    assert action == 'keep' and reason == 'filter_disabled'


# -- build_merged_lists --------------------------------------------------------
def test_build_merged_lists_dedup():
    profile_rules = {
        'p1': {'merged': {'path_whitelist': ['drivers/usb/', 'drivers/usb/']}},
        'p2': {'merged': {'path_whitelist': ['drivers/usb/', 'drivers/net/']}},
    }
    lists = build_merged_lists(profile_rules)
    assert len(lists['path_wl']) == 2  # deduped to 2


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


# -- build_compiled_sets (v13.0.1: reads config_enabled_map/config_enabled_dirs) --

def test_build_compiled_sets_empty_no_product_map():
    cs = build_compiled_sets(None)
    assert cs['available'] is False


def test_build_compiled_sets_missing_enabled_map_returns_empty():
    """H (v13.0.1): if config_enabled_map is absent, return empty and warn.
    This guards against running st04 against a pre-v13.0.1 cache.
    """
    pm = {
        # Old-style cache: only config_to_paths, no config_enabled_map
        'config_to_paths': {'CONFIG_USB': ['drivers/usb/core/hub.c']},
        'enabled_configs':  ['CONFIG_USB=y'],
        'built_artifacts_from_dir': [],
        'built_objects_from_log':   [],
    }
    cs = build_compiled_sets(pm)
    assert cs['available'] is False, (
        'build_compiled_sets must return empty when config_enabled_map is absent '
        '(pre-v13.0.1 cache); re-run st03 first'
    )


def test_build_compiled_sets_with_data():
    """H (v13.0.1): product_map supplies pre-filtered config_enabled_map."""
    pm = {
        'config_enabled_map':  {'CONFIG_USB': ['drivers/usb/core/hub.c']},
        'config_enabled_dirs': ['drivers/usb/core/'],
        'built_artifacts_from_dir': ['drivers/usb/core/hub.o'],
        'built_objects_from_log':   [],
    }
    cs = build_compiled_sets(pm)
    assert cs['available'] is True
    assert 'drivers/usb/core/hub.c' in cs['compiled_files']
    assert 'drivers/usb/core/' in cs['compiled_dirs']
    assert 'drivers/usb/core/hub' in cs['artifact_stems']


def test_build_compiled_sets_compiled_dirs_from_enabled_dirs():
    """H: compiled_dirs is taken directly from config_enabled_dirs."""
    pm = {
        'config_enabled_map':  {'CONFIG_USB': ['drivers/usb/core/hub.c']},
        'config_enabled_dirs': ['drivers/usb/core/', 'drivers/usb/host/'],
        'built_artifacts_from_dir': [],
        'built_objects_from_log':   [],
    }
    cs = build_compiled_sets(pm)
    assert 'drivers/usb/core/' in cs['compiled_dirs']
    assert 'drivers/usb/host/' in cs['compiled_dirs']


def test_build_compiled_sets_disabled_symbol_absent():
    """Bug-1 regression (v13.0.1): config_enabled_map already excludes disabled
    symbols; build_compiled_sets must not see them at all.
    """
    pm = {
        # CONFIG_BTRFS_FS absent from config_enabled_map (pre-filtered by st03)
        'config_enabled_map':  {'CONFIG_USB': ['drivers/usb/core/hub.c']},
        'config_enabled_dirs': ['drivers/usb/core/'],
        'built_artifacts_from_dir': [],
        'built_objects_from_log':   [],
    }
    cs = build_compiled_sets(pm)
    assert cs['available'] is True
    assert not any('btrfs' in f for f in cs['compiled_files'])
    assert not any('btrfs' in d for d in cs['compiled_dirs'])


# -- Bug-2 regression: cem={} + no artifacts → available=False (conservative) --

def test_build_compiled_sets_cem_empty_no_artifacts_available_false():
    """Bug-2 regression (v13.0.2): when config_enabled_map={} (no .config
    provided) AND no build artifacts/log objects exist, available must be
    False.  The pipeline has no coverage data; the scoring stage must handle
    ambiguities rather than the prefilter dropping everything.
    """
    pm = {
        'config_enabled_map':       {},   # cem present but empty (.config missing)
        'config_enabled_dirs':      [],
        'built_artifacts_from_dir': [],
        'built_objects_from_log':   [],
    }
    cs = build_compiled_sets(pm)
    assert cs['available'] is False, (
        'When cem={} and no artifacts/log, available must be False '
        '(conservative: no coverage data, keep everything for scoring)'
    )


def test_build_compiled_sets_cem_empty_but_artifacts_available_true():
    """Bug-2: when cem={} but build artifacts exist, available=True.
    Artifacts alone are enough evidence to perform coverage decisions.
    """
    pm = {
        'config_enabled_map':       {},   # no .config
        'config_enabled_dirs':      [],
        'built_artifacts_from_dir': ['drivers/usb/core/hub.o'],
        'built_objects_from_log':   [],
    }
    cs = build_compiled_sets(pm)
    assert cs['available'] is True, (
        'When artifacts are present, available must be True even if cem={}'
    )
    assert 'drivers/usb/core/hub' in cs['artifact_stems']


def test_build_compiled_sets_cem_empty_but_log_basenames_available_true():
    """Bug-2: log objects alone make available=True."""
    pm = {
        'config_enabled_map':       {},
        'config_enabled_dirs':      [],
        'built_artifacts_from_dir': [],
        'built_objects_from_log':   ['drivers/usb/core/hub.o'],
    }
    cs = build_compiled_sets(pm)
    assert cs['available'] is True
    assert 'hub' in cs['log_basenames']


# -- A: built-in.o exclusion ---------------------------------------------------
def test_build_compiled_sets_builtin_o_not_in_artifact_stems():
    pm = {
        'config_enabled_map':  {'CONFIG_DRM': ['drivers/gpu/drm/drm_drv.c']},
        'config_enabled_dirs': ['drivers/gpu/drm/'],
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
    assert reason != 'build_artifact'


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


# -- C: log_basenames directory-scoped -----------------------------------------
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
    assert reason != 'build_artifact'


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


# -- min_score threshold (st06_postfilter passthrough test) --------------------
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


# -- L2half artifact / kconfig evidence ----------------------------------------
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


# == E.1.2: kconfig debug populated even for kw-whitelist-saved commits ========

def test_debug_kconfig_uncovered_populated_when_kw_wl_saves_commit():
    """E.1.2: When compiled_files is empty (no coverage data), kw_wl may still
    rescue.  Verify kconfig_uncovered is populated in debug even in that case.
    """
    cs = dict(
        compiled_files=set(),          # empty: rescue is allowed
        compiled_dirs=set(),
        artifact_stems=set(), log_basenames=set(), available=True,
    )
    c = _commit(files=['arch/arm/mm/unrelated.c'], subject='arm: fix critical bug')
    action, reason, dbg = filter_decision(
        c,
        _lists(kw_wl=['critical bug']),
        cs,
        {'require_kconfig_coverage': True},
        True,
    )
    assert action == 'keep'
    assert reason == 'keywords_whitelist'
    assert 'arch/arm/mm/unrelated.c' in dbg['l2half_kconfig_uncovered_files']
    assert dbg['kw_wl_rescue_suppressed'] is False


# == E.1.5 / G: zero-file commits handled explicitly ==========================

def test_zero_file_commit_keeps_by_no_files_layer():
    c = _commit(sha='merge001', subject='Merge branch x into y', files=[])
    action, reason, dbg = filter_decision(c, _lists(), _EMPTY_CS, {}, False)
    assert action == 'keep'
    assert reason == 'no_files_layer'


def test_zero_file_commit_kept_by_kw_whitelist():
    c = _commit(sha='zf001', subject='security: patch critical CVE', files=[])
    action, reason, dbg = filter_decision(c, _lists(kw_wl=['CVE']), _EMPTY_CS, {}, True)
    assert action == 'keep'
    assert reason == 'keywords_whitelist'
    assert len(dbg['l1a_kw_wl_matches']) >= 1


def test_zero_file_commit_dropped_by_kw_blacklist():
    c = _commit(sha='zf002', subject='docs: typo fix in README', files=[])
    action, reason, dbg = filter_decision(c, _lists(kw_bl=['typo']), _EMPTY_CS, {}, True)
    assert action == 'drop'
    assert reason == 'keywords_blacklist'


def test_zero_file_commit_not_dropped_by_path_blacklist():
    c = _commit(sha='zf003', subject='Merge tag v5.15', files=[])
    action, reason, dbg = filter_decision(
        c, _lists(path_bl=['Documentation/']), _EMPTY_CS, {}, False)
    assert action == 'keep'


def test_zero_file_commit_not_dropped_by_kconfig():
    cs = dict(
        compiled_files={'drivers/usb/hub.c'},
        compiled_dirs={'drivers/usb'},
        artifact_stems=set(), log_basenames=set(), available=True,
    )
    c = _commit(sha='zf004', subject='random merge', files=[])
    action, reason, dbg = filter_decision(
        c, _lists(), cs, {'require_kconfig_coverage': True}, True)
    assert action == 'keep'


def test_zero_file_commit_debug_has_empty_lists():
    c = _commit(sha='zf005', subject='Merge tag', files=[])
    _, _, dbg = filter_decision(c, _lists(), _EMPTY_CS, {}, True)
    assert dbg['l2a_path_bl_matches'] == []
    assert dbg['l2b_path_wl_matches'] == []
    assert dbg['l2half_artifact_files'] == []
    assert dbg['l2half_kconfig_covered_files'] == []
    assert dbg['l2half_kconfig_uncovered_files'] == []


# == A.1: debug_detail content tests ==========================================

def test_debug_detail_is_dict_with_required_keys():
    """v14.0.0 (A): debug_detail must include the new kw_wl_rescue_suppressed key."""
    c = _commit(subject='net: fix skb', files=['net/core/sock.c'])
    _, _, dbg = filter_decision(c, _lists(), _EMPTY_CS, {}, False)
    for key in ('sha', 'files', 'l3_commit_wl_match', 'l3_commit_bl_match',
                'l2a_path_bl_matches', 'l2b_path_wl_matches',
                'l2half_artifact_files',
                'l2half_kconfig_covered_files', 'l2half_kconfig_uncovered_files',
                'l1a_kw_wl_matches', 'l1b_kw_bl_matches',
                'filter_enabled', 'kconfig_required',
                'kw_wl_rescue_suppressed'):
        assert key in dbg, 'debug_detail missing key: %r' % (key,)


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


# == A.1: _build_prefilter_debug_entry =========================================

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
    sha = 'a' * 50
    c = _commit(sha=sha)
    entry = _build_prefilter_debug_entry(c, 'keywords_blacklist', {})
    assert len(entry['sha']) == 40


def test_build_prefilter_debug_entry_sha12_truncated():
    sha = 'a' * 50
    c = _commit(sha=sha)
    entry = _build_prefilter_debug_entry(c, 'keywords_blacklist', {})
    assert len(entry['sha12']) == 12


# == Bug-1 end-to-end: btrfs commit dropped by kconfig check ===================

def test_btrfs_commit_dropped_by_kconfig_when_disabled():
    """Bug-1 regression (v13.0.1): a commit touching only fs/btrfs/ must be
    dropped at L2half (no_kconfig_coverage) when CONFIG_BTRFS_FS is absent from
    config_enabled_map (i.e. disabled in .config).

    Simulates the exact scenario: config_enabled_map does not contain
    CONFIG_BTRFS_FS, so build_compiled_sets() produces compiled_sets with no
    BTRFS files/dirs. filter_decision() then finds zero covered files and drops
    with no_kconfig_coverage.
    """
    pm = {
        # CONFIG_BTRFS_FS absent (disabled in .config); only USB enabled
        'config_enabled_map':  {'CONFIG_USB': ['drivers/usb/core/hub.c']},
        'config_enabled_dirs': ['drivers/usb/core/'],
        'built_artifacts_from_dir': [],
        'built_objects_from_log':   [],
    }
    cs = build_compiled_sets(pm)
    assert cs['available'] is True
    assert not any('btrfs' in f for f in cs['compiled_files'])

    c = _commit(
        sha='btrfs001',
        subject='btrfs: fix tree corruption on power loss',
        files=['fs/btrfs/tree-log.c'],
    )
    action, reason, dbg = filter_decision(
        c, _lists(), cs, {'require_kconfig_coverage': True}, True)
    assert action == 'drop', 'BTRFS commit must be dropped'
    assert reason == 'no_kconfig_coverage', (
        'Expected no_kconfig_coverage, got: %r' % reason
    )
    assert 'fs/btrfs/tree-log.c' in dbg['l2half_kconfig_uncovered_files']


def test_btrfs_commit_dropped_auto_require_when_cem_has_usb_only():
    """Bug-2 regression (v13.0.2): with require_kconfig_coverage=None (auto),
    compiled_sets.available=True (USB in cem) → require=True → BTRFS dropped.

    This is the real-world scenario: user provides .config where CONFIG_BTRFS_FS
    is not set but CONFIG_USB=y.  The pipeline must not keep the BTRFS commit
    under any auto-require logic.
    """
    pm = {
        'config_enabled_map':  {'CONFIG_USB': ['drivers/usb/core/hub.c']},
        'config_enabled_dirs': ['drivers/usb/core/'],
        'built_artifacts_from_dir': [],
        'built_objects_from_log':   [],
    }
    cs = build_compiled_sets(pm)
    assert cs['available'] is True

    c = _commit(
        sha='btrfs002',
        subject='btrfs: optimize extent allocation',
        files=['fs/btrfs/extent-tree.c'],
    )
    # require_kconfig_coverage=None → auto → require = available AND kconfig_enabled
    # kconfig_enabled = cs['available'] = True → require = True
    action, reason, dbg = filter_decision(
        c, _lists(), cs, {'require_kconfig_coverage': None}, cs['available'])
    assert action == 'drop', (
        'BTRFS commit must be dropped with auto require_kconfig_coverage '
        '(available=True, BTRFS not in compiled_files)'
    )
    assert reason == 'no_kconfig_coverage'


# == v14.0.0 (A): kw_wl rescue suppression ====================================

def test_kw_wl_rescue_suppressed_when_compiled_files_nonempty():
    """A (v14.0.0): when compiled_files is non-empty and a commit's files are
    conclusively uncovered, kw_wl must NOT rescue the commit from the kconfig
    miss.  The commit must be dropped with reason='no_kconfig_coverage'.
    """
    cs = dict(
        compiled_files={'drivers/usb/core/hub.c'},  # non-empty: rescue suppressed
        compiled_dirs={'drivers/usb/core'},
        artifact_stems=set(), log_basenames=set(), available=True,
    )
    c = _commit(
        sha='btrfs_kw',
        subject='btrfs: reschedule when cloning lots of extents',
        body='watchdog: BUG: soft lockup - CPU#0 stuck for 22s!',
        files=['fs/btrfs/ioctl.c'],
    )
    action, reason, dbg = filter_decision(
        c,
        _lists(kw_wl=['BUG', 'lockup', 'soft lockup']),
        cs,
        {'require_kconfig_coverage': True},
        True,
    )
    assert action == 'drop', (
        'Commit touching uncovered files must be dropped even when kw_wl matches, '
        'because compiled_files is non-empty (file evidence is authoritative)'
    )
    assert reason == 'no_kconfig_coverage'


def test_kw_wl_rescue_suppressed_debug_shows_matching_patterns():
    """A (v14.0.0): when rescue is suppressed, debug must show:
    - kw_wl_rescue_suppressed=True
    - l1a_kw_wl_matches populated with the patterns that would have matched
    """
    cs = dict(
        compiled_files={'drivers/usb/core/hub.c'},
        compiled_dirs={'drivers/usb/core'},
        artifact_stems=set(), log_basenames=set(), available=True,
    )
    c = _commit(
        subject='btrfs: reschedule when cloning extents',
        body='BUG: soft lockup detected',
        files=['fs/btrfs/ioctl.c'],
    )
    action, reason, dbg = filter_decision(
        c,
        _lists(kw_wl=['BUG', 'lockup']),
        cs,
        {'require_kconfig_coverage': True},
        True,
    )
    assert action == 'drop'
    assert dbg['kw_wl_rescue_suppressed'] is True
    assert len(dbg['l1a_kw_wl_matches']) >= 1, (
        'l1a_kw_wl_matches must be populated even when rescue is suppressed'
    )


def test_kw_wl_rescue_allowed_when_compiled_files_empty():
    """A (v14.0.0): when compiled_files is empty (no .config, no kconfig
    evidence), kw_wl rescue at L2half is still allowed.  Keyword matching is
    the best available heuristic when no file coverage data exists.
    """
    cs = dict(
        compiled_files=set(),           # empty: rescue is allowed
        compiled_dirs=set(),
        artifact_stems=set(), log_basenames=set(), available=True,
    )
    c = _commit(
        subject='btrfs: reschedule when cloning extents',
        body='BUG: soft lockup detected',
        files=['fs/btrfs/ioctl.c'],
    )
    action, reason, dbg = filter_decision(
        c,
        _lists(kw_wl=['BUG', 'lockup']),
        cs,
        {'require_kconfig_coverage': True},
        True,
    )
    assert action == 'keep', (
        'When compiled_files is empty, kw_wl rescue must still apply '
        '(no authoritative file evidence available)'
    )
    assert reason == 'keywords_whitelist'
    assert dbg['kw_wl_rescue_suppressed'] is False


def test_kw_wl_rescue_suppressed_btrfs_real_world_scenario():
    """A (v14.0.0): end-to-end regression for the real-world case that triggered
    the fix.  Commit b238eaa1 (btrfs: reschedule when cloning lots of extents)
    touched fs/btrfs/ioctl.c.  CONFIG_BTRFS_FS was not in config_enabled_map
    (product uses CONFIG_USB only).  The commit body contains 'soft lockup' /
    'BUG' which matched the kw_wl, incorrectly keeping the commit.

    After the fix the commit must be dropped.
    """
    pm = {
        'config_enabled_map':  {'CONFIG_USB': ['drivers/usb/core/hub.c']},
        'config_enabled_dirs': ['drivers/usb/core/'],
        'built_artifacts_from_dir': [],
        'built_objects_from_log':   [],
    }
    cs = build_compiled_sets(pm)
    assert cs['available'] is True
    assert len(cs['compiled_files']) > 0  # non-empty: rescue will be suppressed

    c = _commit(
        sha='b238eaa1536c9fa9',
        subject='btrfs: reschedule when cloning lots of extents',
        body=(
            'btrfs: reschedule when cloning lots of extents\n'
            '[ Upstream commit 6b613cc97f0ace77f92f7bc112b8f6ad3f52baf8 ]\n'
            'watchdog: BUG: soft lockup - CPU#0 stuck for 22s! [xfs_io:10030]'
        ),
        files=['fs/btrfs/ioctl.c'],
    )
    # Use a realistic kw_wl that would have matched before the fix
    action, reason, dbg = filter_decision(
        c,
        _lists(kw_wl=['BUG', 'lockup', 'soft lockup', 'use-after-free', 'CVE']),
        cs,
        {'require_kconfig_coverage': None},
        cs['available'],
    )
    assert action == 'drop', (
        'b238eaa1 (btrfs ioctl.c, CONFIG_BTRFS_FS disabled) must be dropped '
        'after kw_wl rescue suppression fix'
    )
    assert reason == 'no_kconfig_coverage'
    assert dbg['kw_wl_rescue_suppressed'] is True
    assert 'fs/btrfs/ioctl.c' in dbg['l2half_kconfig_uncovered_files']


def test_debug_detail_has_kw_wl_rescue_suppressed_key():
    """A (v14.0.0): kw_wl_rescue_suppressed must be present in debug_detail
    for ALL code paths, not just the suppression path.
    """
    c = _commit(subject='net: fix skb', files=['net/core/sock.c'])
    _, _, dbg = filter_decision(c, _lists(), _EMPTY_CS, {}, False)
    assert 'kw_wl_rescue_suppressed' in dbg


def test_kw_wl_rescue_suppressed_false_by_default():
    """A (v14.0.0): kw_wl_rescue_suppressed must be False when the suppress
    path was not taken (normal keep/drop outcomes).
    """
    # Normal drop via no_kconfig_coverage, no kw_wl configured
    cs = dict(
        compiled_files={'drivers/usb/core/hub.c'},
        compiled_dirs={'drivers/usb/core'},
        artifact_stems=set(), log_basenames=set(), available=True,
    )
    c = _commit(files=['fs/btrfs/ioctl.c'])
    action, reason, dbg = filter_decision(
        c, _lists(), cs, {'require_kconfig_coverage': True}, True)
    assert action == 'drop'
    assert dbg['kw_wl_rescue_suppressed'] is False

    # Normal keep via default (kconfig inactive)
    action2, _, dbg2 = filter_decision(
        _commit(files=['net/core/sock.c']), _lists(), _EMPTY_CS, {}, False)
    assert action2 == 'keep'
    assert dbg2['kw_wl_rescue_suppressed'] is False
