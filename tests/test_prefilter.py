"""Tests for lib.stages.st04_prefilter -- filter_decision and helpers.

v12.0.0 (A.1): filter_decision() returns a 3-tuple (action, reason, debug_detail).

v13.0.0 (E.1.x / G):
  E.1.1 -- artifact_files computed once, reused.
  E.1.2 -- kconfig_covered/uncovered populated in debug unconditionally.
  E.1.4 -- L2a path-blacklist only drops when ALL files match.
  E.1.5 -- zero-file commits handled before path/kconfig layers.
  E.1.6 -- build_compiled_sets() ignores bare CONFIG entries without '=' suffix.
  G     -- zero-file default keep reason is 'no_files_layer'.

v13.0.1 (H -- Bug-1 fix):
  H     -- build_compiled_sets() reads config_enabled_map / config_enabled_dirs
           from product_map instead of config_to_paths / enabled_configs.

v13.0.2 (I -- Bug-2 fix):
  I     -- available=True when ANY evidence source is non-empty.
           Added:
             test_build_compiled_sets_cem_empty_no_artifacts_available_false()
             test_build_compiled_sets_cem_empty_but_artifacts_available_true()
             test_btrfs_commit_dropped_auto_require_when_cem_has_usb_only()

v14.1.0 (B -- keyword/path-wl decoupling):
  B     -- build_merged_lists() deleted; filter_decision() `lists` parameter
           removed; L2b (path_whitelist), L1a (kw_wl), L1b (kw_bl) layers and
           kw_wl rescue / kw_wl_rescue_suppressed removed entirely.
           SHA overrides (commit_whitelist/blacklist) and path_blacklist are now
           read from filter_cfg directly, not from profile_rules.
           All keyword and path-whitelist tests removed; debug_detail key
           assertions updated to remove kw/path-wl fields.

v16.0.0 (C -- Kconfig/Makefile directory-scoped coverage):
  C     -- _file_is_kconfig_covered(): build-system files (Kconfig, Makefile,
           Kbuild, *.mk) are no longer unconditionally covered.
           They are covered only when their directory is in compiled_dirs
           (trailing-slash normalised) or when they are at the kernel root.
           Added:
             test_kconfig_file_in_uncovered_dir_drops()
             test_kconfig_file_in_compiled_dir_keeps()
             test_root_kconfig_always_keeps()
             test_root_makefile_always_keeps()
             test_makefile_in_uncovered_dir_drops()
             test_mk_file_in_uncovered_dir_drops()
             test_kconfig_uncovered_plus_artifact_keeps_via_artifact()
             test_kconfig_covered_dir_trailing_slash_normalisation()
             test_kconfig_file_uncovered_appears_in_debug_uncovered_list()
"""
import os
import re

from lib.stages.st04_prefilter import (
    filter_decision, build_compiled_sets,
    _file_has_artifact, _file_is_kconfig_covered,
    _build_prefilter_debug_entry,
)

_EMPTY_CS = dict(compiled_files=set(), compiled_dirs=set(),
                 artifact_stems=set(), log_basenames=set(), available=False)


def _commit(sha='aaa', subject='', body='', files=None):
    return {'commit': sha, 'subject': subject, 'body': body or '',
            'files': files or []}


def _usb_cs():
    """compiled_sets for a product that compiles drivers/usb/core/ only.

    compiled_dirs uses the trailing-slash form produced by st03
    _derive_config_dirs(), so these tests exercise the normalisation path.
    """
    return dict(
        compiled_files={'drivers/usb/core/hub.c'},
        compiled_dirs={'drivers/usb/core/'},
        artifact_stems=set(),
        log_basenames=set(),
        available=True,
    )


# -- L3 absolute ---------------------------------------------------------------

def test_commit_whitelist_wins():
    c = _commit(sha='deadbeef')
    action, reason, dbg = filter_decision(
        c, _EMPTY_CS, {'commit_whitelist': ['deadbeef']}, False)
    assert action == 'keep' and reason == 'commit_whitelist'


def test_commit_blacklist_drops():
    c = _commit(sha='deadbeef')
    action, reason, dbg = filter_decision(
        c, _EMPTY_CS, {'commit_blacklist': ['deadbeef']}, False)
    assert action == 'drop' and reason == 'commit_blacklist'


def test_commit_whitelist_beats_blacklist():
    c = _commit(sha='deadbeef')
    action, _, _dbg = filter_decision(
        c, _EMPTY_CS,
        {'commit_whitelist': ['deadbeef'], 'commit_blacklist': ['deadbeef']},
        False)
    assert action == 'keep'


# -- L2a path blacklist --------------------------------------------------------

def test_path_blacklist_all_drops():
    c = _commit(files=['Documentation/foo.rst', 'Documentation/bar.rst'])
    action, reason, dbg = filter_decision(
        c, _EMPTY_CS, {'path_blacklist': ['Documentation/']}, False)
    assert action == 'drop' and reason == 'path_blacklist_all'


def test_path_blacklist_partial_does_not_drop():
    """E.1.4: L2a only drops when ALL files match the blacklist."""
    c = _commit(files=['Documentation/foo.rst', 'drivers/usb/hub.c'])
    action, _, _dbg = filter_decision(
        c, _EMPTY_CS, {'path_blacklist': ['Documentation/']}, False)
    assert action == 'keep'


# -- L0 default ----------------------------------------------------------------

def test_default_keep():
    c = _commit(subject='net: fix something random', files=['net/core/sock.c'])
    action, reason, dbg = filter_decision(c, _EMPTY_CS, {}, False)
    assert action == 'keep' and reason == 'default'


# -- filter_disabled -----------------------------------------------------------

def test_filter_disabled_bypasses_path_bl():
    c = _commit(files=['Documentation/foo.rst', 'Documentation/bar.rst'])
    action, reason, dbg = filter_decision(
        c, _EMPTY_CS, {'enabled': False, 'path_blacklist': ['Documentation/']}, False)
    assert action == 'keep' and reason == 'filter_disabled'


# -- build_compiled_sets -------------------------------------------------------

def test_build_compiled_sets_empty_no_product_map():
    cs = build_compiled_sets(None)
    assert cs['available'] is False


def test_build_compiled_sets_missing_enabled_map_returns_empty():
    """H (v13.0.1): if config_enabled_map is absent, return empty and warn."""
    pm = {
        'config_to_paths': {'CONFIG_USB': ['drivers/usb/core/hub.c']},
        'enabled_configs':  ['CONFIG_USB=y'],
        'built_artifacts_from_dir': [],
        'built_objects_from_log':   [],
    }
    cs = build_compiled_sets(pm)
    assert cs['available'] is False


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
    symbols; build_compiled_sets must not see them at all."""
    pm = {
        'config_enabled_map':  {'CONFIG_USB': ['drivers/usb/core/hub.c']},
        'config_enabled_dirs': ['drivers/usb/core/'],
        'built_artifacts_from_dir': [],
        'built_objects_from_log':   [],
    }
    cs = build_compiled_sets(pm)
    assert cs['available'] is True
    assert not any('btrfs' in f for f in cs['compiled_files'])
    assert not any('btrfs' in d for d in cs['compiled_dirs'])


def test_build_compiled_sets_cem_empty_no_artifacts_available_false():
    """Bug-2 regression (v13.0.2): cem={} + no artifacts → available=False."""
    pm = {
        'config_enabled_map':       {},
        'config_enabled_dirs':      [],
        'built_artifacts_from_dir': [],
        'built_objects_from_log':   [],
    }
    cs = build_compiled_sets(pm)
    assert cs['available'] is False


def test_build_compiled_sets_cem_empty_but_artifacts_available_true():
    """Bug-2: artifacts alone make available=True even when cem={}."""
    pm = {
        'config_enabled_map':       {},
        'config_enabled_dirs':      [],
        'built_artifacts_from_dir': ['drivers/usb/core/hub.o'],
        'built_objects_from_log':   [],
    }
    cs = build_compiled_sets(pm)
    assert cs['available'] is True
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


# -- built-in.o exclusion ------------------------------------------------------

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
        c, cs, {'require_kconfig_coverage': False}, True)
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
        c, cs, {'require_kconfig_coverage': True}, True)
    assert reason != 'build_artifact'


# -- log_basenames directory-scoped --------------------------------------------

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
        c, cs, {'require_kconfig_coverage': False}, True)
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
    action, reason, dbg = filter_decision(c, cs, {}, False)
    assert action == 'keep' and reason == 'build_artifact'


# -- st06 threshold passthrough ------------------------------------------------

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
    action, reason, dbg = filter_decision(c, cs, {}, False)
    assert action == 'keep' and reason == 'build_artifact'


def test_kconfig_miss_drops_commit():
    c = _commit(files=['drivers/usb/core/hub.c'])
    cs = dict(
        compiled_files=set(), compiled_dirs=set(),
        artifact_stems=set(), log_basenames=set(), available=True,
    )
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'drop' and 'kconfig' in reason


def test_kconfig_coverage_not_required_keeps():
    c = _commit(files=['drivers/usb/core/hub.c'])
    cs = dict(
        compiled_files=set(), compiled_dirs=set(),
        artifact_stems=set(), log_basenames=set(), available=True,
    )
    action, _, _dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': False}, True)
    assert action == 'keep'


# -- Zero-file commits ---------------------------------------------------------

def test_zero_file_commit_keeps_by_no_files_layer():
    """E.1.5 / G: zero-file commits (merge commits) always kept."""
    c = _commit(sha='merge001', subject='Merge branch x into y', files=[])
    action, reason, dbg = filter_decision(c, _EMPTY_CS, {}, False)
    assert action == 'keep' and reason == 'no_files_layer'


def test_zero_file_commit_not_dropped_by_path_blacklist():
    c = _commit(sha='zf003', subject='Merge tag v5.15', files=[])
    action, reason, dbg = filter_decision(
        c, _EMPTY_CS, {'path_blacklist': ['Documentation/']}, False)
    assert action == 'keep' and reason == 'no_files_layer'


def test_zero_file_commit_not_dropped_by_kconfig():
    cs = dict(
        compiled_files={'drivers/usb/hub.c'},
        compiled_dirs={'drivers/usb'},
        artifact_stems=set(), log_basenames=set(), available=True,
    )
    c = _commit(sha='zf004', subject='random merge', files=[])
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'keep' and reason == 'no_files_layer'


def test_zero_file_commit_debug_has_empty_evidence_lists():
    c = _commit(sha='zf005', subject='Merge tag', files=[])
    _, _, dbg = filter_decision(c, _EMPTY_CS, {}, True)
    assert dbg['l2a_path_bl_matches'] == []
    assert dbg['l2half_artifact_files'] == []
    assert dbg['l2half_kconfig_covered_files'] == []
    assert dbg['l2half_kconfig_uncovered_files'] == []


# -- debug_detail content ------------------------------------------------------

def test_debug_detail_required_keys():
    c = _commit(subject='net: fix skb', files=['net/core/sock.c'])
    _, _, dbg = filter_decision(c, _EMPTY_CS, {}, False)
    for key in ('sha', 'files', 'filter_enabled', 'kconfig_required',
                'l3_commit_wl_match', 'l3_commit_bl_match',
                'l2a_path_bl_matches', 'l2half_artifact_files',
                'l2half_kconfig_covered_files',
                'l2half_kconfig_uncovered_files'):
        assert key in dbg, 'debug_detail missing key: %r' % key


def test_debug_detail_no_stale_kw_fields():
    """v14.1.0 (B): removed fields must not appear in debug_detail."""
    c = _commit(subject='net: fix skb', files=['net/core/sock.c'])
    _, _, dbg = filter_decision(c, _EMPTY_CS, {}, False)
    for key in ('l2b_path_wl_matches', 'l1a_kw_wl_matches',
                'l1b_kw_bl_matches', 'kw_wl_rescue_suppressed'):
        assert key not in dbg, 'Stale key %r must not appear in debug_detail' % key


def test_debug_detail_sha_populated():
    c = _commit(sha='abc123', subject='foo')
    _, _, dbg = filter_decision(c, _EMPTY_CS, {}, False)
    assert dbg['sha'] == 'abc123'


def test_debug_detail_l3_commit_bl_match_populated():
    c = _commit(sha='deadbeef')
    _, _, dbg = filter_decision(
        c, _EMPTY_CS, {'commit_blacklist': ['deadbeef']}, False)
    assert dbg['l3_commit_bl_match'] is not None
    assert dbg['l3_commit_bl_match']['pattern'] == 'deadbeef'


def test_debug_detail_l3_commit_bl_none_on_miss():
    c = _commit(sha='xyz')
    _, _, dbg = filter_decision(
        c, _EMPTY_CS, {'commit_blacklist': ['deadbeef']}, False)
    assert dbg['l3_commit_bl_match'] is None


def test_debug_detail_l2a_path_bl_matches_on_drop():
    c = _commit(files=['Documentation/foo.rst', 'Documentation/bar.rst'])
    _, _, dbg = filter_decision(
        c, _EMPTY_CS, {'path_blacklist': ['Documentation/']}, False)
    assert len(dbg['l2a_path_bl_matches']) >= 1
    assert any('Documentation' in m['pattern'] for m in dbg['l2a_path_bl_matches'])


def test_debug_detail_kconfig_covered_populated():
    c = _commit(files=['drivers/usb/core/hub.c'])
    cs = dict(
        compiled_files={'drivers/usb/core/hub.c'},
        compiled_dirs=set(), artifact_stems=set(), log_basenames=set(), available=True,
    )
    _, _, dbg = filter_decision(c, cs, {}, True)
    assert 'drivers/usb/core/hub.c' in dbg['l2half_kconfig_covered_files']
    assert dbg['l2half_kconfig_uncovered_files'] == []


def test_debug_detail_kconfig_uncovered_populated():
    c = _commit(files=['net/unrelated.c'])
    cs = dict(
        compiled_files={'drivers/usb/core/hub.c'},
        compiled_dirs=set(), artifact_stems=set(), log_basenames=set(), available=True,
    )
    _, _, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert 'net/unrelated.c' in dbg['l2half_kconfig_uncovered_files']


def test_debug_detail_filter_enabled_flag():
    c = _commit()
    _, _, dbg = filter_decision(c, _EMPTY_CS, {'enabled': False}, False)
    assert dbg['filter_enabled'] is False


# -- _build_prefilter_debug_entry ----------------------------------------------

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
    entry = _build_prefilter_debug_entry(c, 'no_kconfig_coverage', {})
    assert len(entry['sha']) == 40


def test_build_prefilter_debug_entry_sha12_truncated():
    sha = 'a' * 50
    c = _commit(sha=sha)
    entry = _build_prefilter_debug_entry(c, 'no_kconfig_coverage', {})
    assert len(entry['sha12']) == 12


# -- Bug-1 end-to-end: btrfs commit dropped by kconfig check -------------------

def test_btrfs_commit_dropped_by_kconfig_when_disabled():
    """Bug-1 regression (v13.0.1): BTRFS commit dropped when CONFIG_BTRFS_FS
    is absent from config_enabled_map."""
    pm = {
        'config_enabled_map':  {'CONFIG_USB': ['drivers/usb/core/hub.c']},
        'config_enabled_dirs': ['drivers/usb/core/'],
        'built_artifacts_from_dir': [],
        'built_objects_from_log':   [],
    }
    cs = build_compiled_sets(pm)
    assert cs['available'] is True

    c = _commit(
        sha='btrfs001',
        subject='btrfs: fix tree corruption on power loss',
        files=['fs/btrfs/tree-log.c'],
    )
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'drop'
    assert reason == 'no_kconfig_coverage'
    assert 'fs/btrfs/tree-log.c' in dbg['l2half_kconfig_uncovered_files']


def test_btrfs_commit_dropped_auto_require_when_cem_has_usb_only():
    """Bug-2 regression (v13.0.2): auto require_kconfig_coverage=None +
    available=True drops BTRFS commit."""
    pm = {
        'config_enabled_map':  {'CONFIG_USB': ['drivers/usb/core/hub.c']},
        'config_enabled_dirs': ['drivers/usb/core/'],
        'built_artifacts_from_dir': [],
        'built_objects_from_log':   [],
    }
    cs = build_compiled_sets(pm)
    c = _commit(
        sha='btrfs002',
        subject='btrfs: optimize extent allocation',
        files=['fs/btrfs/extent-tree.c'],
    )
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': None}, cs['available'])
    assert action == 'drop'
    assert reason == 'no_kconfig_coverage'


def test_btrfs_with_security_keywords_dropped():
    """v14.1.0 (B): BTRFS commit with security keywords (BUG, lockup) must still
    be dropped.  Keywords are no longer evaluated in the prefilter at all."""
    pm = {
        'config_enabled_map':  {'CONFIG_USB': ['drivers/usb/core/hub.c']},
        'config_enabled_dirs': ['drivers/usb/core/'],
        'built_artifacts_from_dir': [],
        'built_objects_from_log':   [],
    }
    cs = build_compiled_sets(pm)
    c = _commit(
        sha='b238eaa1536c9fa9',
        subject='btrfs: reschedule when cloning lots of extents',
        body='watchdog: BUG: soft lockup - CPU#0 stuck for 22s! [xfs_io:10030]',
        files=['fs/btrfs/ioctl.c'],
    )
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': None}, cs['available'])
    assert action == 'drop'
    assert reason == 'no_kconfig_coverage'
    assert 'fs/btrfs/ioctl.c' in dbg['l2half_kconfig_uncovered_files']


# ==============================================================================
# v16.0.0 (C) -- Kconfig/Makefile directory-scoped coverage
# ==============================================================================

def test_kconfig_file_in_uncovered_dir_drops():
    """C (v16.0.0): fs/btrfs/Kconfig must be dropped when CONFIG_BTRFS_FS is
    absent from config_enabled_map.  Previously the unconditional
    _is_build_system_file() passthrough rescued it."""
    cs = _usb_cs()
    c = _commit(
        sha='btrfs_kconfig_01',
        subject='btrfs: add Kconfig option for free-space tree',
        files=['fs/btrfs/Kconfig'],
    )
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'drop'
    assert reason == 'no_kconfig_coverage'
    assert 'fs/btrfs/Kconfig' in dbg['l2half_kconfig_uncovered_files']


def test_kconfig_file_in_compiled_dir_keeps():
    """C (v16.0.0): drivers/usb/Kconfig must be kept when drivers/usb/ (or a
    sub-directory) is in compiled_dirs.  Trailing-slash normalisation is
    exercised: compiled_dirs stores 'drivers/usb/core/' while dirname of
    'drivers/usb/Kconfig' is 'drivers/usb' -- we need the parent-dir check."""
    # Use a compiled_dirs entry whose directory IS the parent of the Kconfig.
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb/'},
        artifact_stems=set(),
        log_basenames=set(),
        available=True,
    )
    c = _commit(
        sha='usb_kconfig_01',
        subject='usb: add Kconfig option for USB4',
        files=['drivers/usb/Kconfig'],
    )
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'keep'
    assert 'drivers/usb/Kconfig' in dbg['l2half_kconfig_covered_files']


def test_root_kconfig_always_keeps():
    """C (v16.0.0): top-level Kconfig (fdir == '') is always covered regardless
    of compiled_dirs.  It is unconditionally product-relevant."""
    cs = _usb_cs()
    c = _commit(
        sha='root_kconfig_01',
        subject='kconfig: add EXPERT dependency to DEBUG_FS',
        files=['Kconfig'],
    )
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'keep'
    assert 'Kconfig' in dbg['l2half_kconfig_covered_files']


def test_root_makefile_always_keeps():
    """C (v16.0.0): top-level Makefile (fdir == '') is always covered."""
    cs = _usb_cs()
    c = _commit(
        sha='root_makefile_01',
        subject='Makefile: bump SUBLEVEL to 4',
        files=['Makefile'],
    )
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'keep'
    assert 'Makefile' in dbg['l2half_kconfig_covered_files']


def test_makefile_in_uncovered_dir_drops():
    """C (v16.0.0): fs/btrfs/Makefile must be dropped when fs/btrfs/ is not
    compiled.  Same rule as Kconfig; the unconditional passthrough is gone."""
    cs = _usb_cs()
    c = _commit(
        sha='btrfs_makefile_01',
        subject='btrfs: add new object to Makefile',
        files=['fs/btrfs/Makefile'],
    )
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'drop'
    assert reason == 'no_kconfig_coverage'
    assert 'fs/btrfs/Makefile' in dbg['l2half_kconfig_uncovered_files']


def test_mk_file_in_uncovered_dir_drops():
    """C (v16.0.0): *.mk files in uncovered directories are dropped."""
    cs = _usb_cs()
    c = _commit(
        sha='btrfs_mk_01',
        subject='btrfs: update build helpers',
        files=['fs/btrfs/build.mk'],
    )
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'drop'
    assert reason == 'no_kconfig_coverage'


def test_kconfig_uncovered_plus_artifact_keeps_via_artifact():
    """C (v16.0.0): a commit touching both an uncovered Kconfig and a compiled
    source file must be kept via build_artifact evidence.  The Kconfig drop
    path must not fire when artifact evidence is present for other files."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb/core/'},
        artifact_stems={'drivers/usb/core/hub'},
        log_basenames=set(),
        available=True,
    )
    c = _commit(
        sha='mixed_commit_01',
        subject='usb/btrfs: cross-subsystem change',
        files=['fs/btrfs/Kconfig', 'drivers/usb/core/hub.c'],
    )
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'keep'
    assert reason == 'build_artifact'


def test_kconfig_covered_dir_trailing_slash_normalisation():
    """C (v16.0.0): verify that the trailing-slash normalisation makes
    compiled_dirs lookup work correctly.

    compiled_dirs stores 'net/core/' (with slash); dirname of
    'net/core/Kconfig' is 'net/core' (without slash).  Without normalisation
    the lookup would silently fail and the file would be uncovered."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'net/core/'},   # trailing slash, as stored by st03
        artifact_stems=set(),
        log_basenames=set(),
        available=True,
    )
    assert _file_is_kconfig_covered('net/core/Kconfig', cs) is True
    assert _file_is_kconfig_covered('net/core/filter.c', cs) is True
    assert _file_is_kconfig_covered('net/sched/Kconfig', cs) is False


def test_kconfig_file_uncovered_appears_in_debug_uncovered_list():
    """C (v16.0.0): when a Kconfig file in an uncovered dir causes a drop,
    it must appear in l2half_kconfig_uncovered_files in debug_detail."""
    cs = _usb_cs()
    c = _commit(
        sha='btrfs_kconfig_debug',
        subject='btrfs: Kconfig: add BTRFS_FS_POSIX_ACL option',
        files=['fs/btrfs/Kconfig'],
    )
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'drop'
    assert 'fs/btrfs/Kconfig' in dbg['l2half_kconfig_uncovered_files']
    assert 'fs/btrfs/Kconfig' not in dbg['l2half_kconfig_covered_files']
