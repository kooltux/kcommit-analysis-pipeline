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

v16.0.1 (D -- artifact trailing-slash normalisation):
  D     -- _file_has_artifact(): trailing-slash normalisation applied to
           compiled_dirs lookup (same fix as C applied to _file_is_kconfig_covered).
           Existing compiled_dirs test fixtures corrected from no-slash form
           (e.g. {'drivers/usb'}) to the real st03 trailing-slash form
           (e.g. {'drivers/usb/'}) so they exercise the actual normalisation
           path rather than masking the bug.
           Fixed fixtures:
             test_file_has_artifact_log_match_requires_compiled_dir
             test_file_has_artifact_log_match_requires_compiled_dir_deep
             test_log_basename_cross_tree_commit_not_kept
             test_log_basename_same_dir_commit_kept
             test_builtin_o_only_commit_not_kept_by_artifact_evidence
             test_builtin_o_only_commit_dropped_when_kconfig_required
           Added:
             test_file_has_artifact_log_trailing_slash_normalisation()
             test_file_has_artifact_log_root_file_not_rescued_by_dir()
             test_file_has_artifact_log_sibling_dir_not_rescued()

v16.1.0 (F -- file-type-aware L2half):
  F     -- New helpers _file_is_header(), _file_is_source(),
           _has_real_artifact_evidence(), _dir_has_artifact_coverage().
           New keep reason 'kconfig_coverage' for header/build-meta keeps.
           New debug field 'l2half_has_real_artifacts'.

           Behavioural changes exercised by new tests:

           1. Header-only commits: always evaluated via kconfig regardless of
              artifact availability.  Previously fell through to L0 default.
              Added:
                test_header_only_commit_keeps_via_kconfig_when_covered()
                test_header_only_commit_drops_when_not_covered()
                test_header_only_commit_keeps_regardless_of_artifact_availability()
                test_header_only_no_require_keeps_by_default()

           2. Build-meta path-prefix artifact fallback: a Kconfig/Makefile
              whose directory is a prefix of a compiled artifact path is kept
              via build_artifact.  Added:
                test_build_meta_parent_dir_kept_via_artifact_prefix()
                test_build_meta_unrelated_dir_dropped_when_require()
                test_build_meta_prefix_fallback_no_artifacts_drops()
                test_root_build_meta_always_kept_dir_has_artifact_coverage()

           3. 'kconfig_coverage' reason emitted for header/build-meta keeps.
              Added:
                test_reason_kconfig_coverage_for_covered_header()
                test_reason_kconfig_coverage_for_covered_build_meta()

           4. 'l2half_has_real_artifacts' debug field.
              Added:
                test_debug_has_real_artifacts_true_when_stems_present()
                test_debug_has_real_artifacts_false_when_no_artifacts()
                test_debug_required_keys_includes_has_real_artifacts()

           5. Source file behaviour with real artifacts present.
              Added:
                test_source_not_in_artifact_drops_when_real_artifacts_present()
                test_source_in_artifact_keeps_when_real_artifacts_present()
                test_source_no_real_artifacts_falls_back_to_kconfig()
"""
import os
import re

from lib.stages.st04_prefilter import (
    filter_decision, build_compiled_sets,
    _file_has_artifact, _file_is_kconfig_covered,
    _file_is_header, _file_is_source,
    _has_real_artifact_evidence, _dir_has_artifact_coverage,
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


def _usb_cs_with_artifacts():
    """compiled_sets for a product with real artifact evidence."""
    return dict(
        compiled_files={'drivers/usb/core/hub.c'},
        compiled_dirs={'drivers/usb/core/'},
        artifact_stems={'drivers/usb/core/hub'},
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
    """Bug-2 regression (v13.0.2): cem={} + no artifacts -> available=False."""
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
    """D (v16.0.1): fixture corrected to use trailing-slash compiled_dirs."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/gpu/drm/'},   # trailing slash -- real st03 form
        artifact_stems={'drivers/gpu/drm/drm_drv'},
        log_basenames=set(),
        available=True,
    )
    c = _commit(files=['drivers/gpu/drm/built-in.o'])
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': False}, True)
    assert reason != 'build_artifact'


def test_builtin_o_only_commit_dropped_when_kconfig_required():
    """D (v16.0.1): fixture corrected to use trailing-slash compiled_dirs."""
    cs = dict(
        compiled_files={'drivers/gpu/drm/drm_drv.c'},
        compiled_dirs={'drivers/gpu/drm/'},   # trailing slash -- real st03 form
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
    """D (v16.0.1): compiled_dirs uses trailing-slash form (real st03 output)."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb/'},   # trailing slash
        artifact_stems=set(),
        log_basenames={'hub'},
        available=True,
    )
    assert not _file_has_artifact('sound/usb/hub.c', cs)
    assert not _file_has_artifact('net/hub.c', cs)
    assert _file_has_artifact('drivers/usb/hub.c', cs)


def test_file_has_artifact_log_match_requires_compiled_dir_deep():
    """D (v16.0.1): compiled_dirs uses trailing-slash form (real st03 output)."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/net/ethernet/intel/'},   # trailing slash
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
    """D (v16.0.1): compiled_dirs uses trailing-slash form."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb/'},   # trailing slash
        artifact_stems=set(),
        log_basenames={'hub'},
        available=True,
    )
    assert not _file_has_artifact('drivers/usb/core.c', cs)


def test_log_basename_cross_tree_commit_not_kept():
    """D (v16.0.1): compiled_dirs uses trailing-slash form."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb/'},   # trailing slash
        artifact_stems=set(),
        log_basenames={'hub'},
        available=True,
    )
    c = _commit(files=['sound/usb/hub.c'])
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': False}, True)
    assert reason != 'build_artifact'


def test_log_basename_same_dir_commit_kept():
    """D (v16.0.1): compiled_dirs uses trailing-slash form."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb/'},   # trailing slash
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
        compiled_dirs={'drivers/usb/'},
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
                'l2a_path_bl_matches',
                'l2half_has_real_artifacts',
                'l2half_artifact_files',
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
    """C (v16.0.0): drivers/usb/Kconfig must be kept when drivers/usb/ is in
    compiled_dirs.  Reason must be kconfig_coverage (F: v16.1.0)."""
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
    assert reason == 'kconfig_coverage'
    assert 'drivers/usb/Kconfig' in dbg['l2half_kconfig_covered_files']


def test_root_kconfig_always_keeps():
    """C (v16.0.0): top-level Kconfig (fdir == '') is always covered.
    Reason must be kconfig_coverage (F: v16.1.0)."""
    cs = _usb_cs()
    c = _commit(
        sha='root_kconfig_01',
        subject='kconfig: add EXPERT dependency to DEBUG_FS',
        files=['Kconfig'],
    )
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'keep'
    assert reason == 'kconfig_coverage'
    assert 'Kconfig' in dbg['l2half_kconfig_covered_files']


def test_root_makefile_always_keeps():
    """C (v16.0.0): top-level Makefile (fdir == '') is always covered.
    Reason must be kconfig_coverage (F: v16.1.0)."""
    cs = _usb_cs()
    c = _commit(
        sha='root_makefile_01',
        subject='Makefile: bump SUBLEVEL to 4',
        files=['Makefile'],
    )
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'keep'
    assert reason == 'kconfig_coverage'
    assert 'Makefile' in dbg['l2half_kconfig_covered_files']


def test_makefile_in_uncovered_dir_drops():
    """C (v16.0.0): fs/btrfs/Makefile must be dropped when fs/btrfs/ is not
    compiled."""
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
    source file must be kept via build_artifact evidence."""
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
    compiled_dirs lookup work correctly."""
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


# ==============================================================================
# v16.0.1 (D) -- artifact trailing-slash normalisation
# ==============================================================================

def test_file_has_artifact_log_trailing_slash_normalisation():
    """D (v16.0.1): verify that the trailing-slash normalisation in
    _file_has_artifact() makes compiled_dirs lookup reliable."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb/core/'},   # trailing slash -- real st03 form
        artifact_stems=set(),
        log_basenames={'hub'},
        available=True,
    )
    assert _file_has_artifact('drivers/usb/core/hub.c', cs) is True
    assert _file_has_artifact('sound/usb/hub.c', cs) is False
    assert _file_has_artifact('drivers/usb/hub.c', cs) is False


def test_file_has_artifact_log_root_file_not_rescued_by_dir():
    """D (v16.0.1): a file at the kernel root (fdir == '') must NOT be rescued
    by the compiled_dirs check."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb/core/'},
        artifact_stems=set(),
        log_basenames={'Makefile'},
        available=True,
    )
    assert _file_has_artifact('Makefile', cs) is False


def test_file_has_artifact_log_sibling_dir_not_rescued():
    """D (v16.0.1): a file in a sibling directory is not rescued by a
    log-basename hit from a different directory."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb/core/'},   # core/ only, not host/
        artifact_stems=set(),
        log_basenames={'xhci'},
        available=True,
    )
    assert _file_has_artifact('drivers/usb/host/xhci.c', cs) is False
    assert _file_has_artifact('drivers/usb/core/xhci.c', cs) is True


# ==============================================================================
# v16.1.0 (F) -- file-type-aware L2half
# ==============================================================================

# -- Helper unit tests ---------------------------------------------------------

def test_file_is_header_dot_h():
    assert _file_is_header('include/linux/usb.h') is True

def test_file_is_header_dot_hpp():
    assert _file_is_header('drivers/foo/bar.hpp') is True

def test_file_is_header_dot_c_is_not_header():
    assert _file_is_header('drivers/usb/hub.c') is False

def test_file_is_header_makefile_is_not_header():
    assert _file_is_header('drivers/usb/Makefile') is False

def test_file_is_source_dot_c():
    assert _file_is_source('drivers/usb/hub.c') is True

def test_file_is_source_dot_S():
    assert _file_is_source('arch/arm/entry.S') is True

def test_file_is_source_dot_h_is_not_source():
    assert _file_is_source('include/linux/usb.h') is False

def test_file_is_source_makefile_is_not_source():
    assert _file_is_source('drivers/usb/Makefile') is False


def test_has_real_artifact_evidence_stems():
    cs = dict(artifact_stems={'drivers/usb/hub'}, log_basenames=set())
    assert _has_real_artifact_evidence(cs) is True

def test_has_real_artifact_evidence_log_basenames():
    cs = dict(artifact_stems=set(), log_basenames={'hub'})
    assert _has_real_artifact_evidence(cs) is True

def test_has_real_artifact_evidence_empty():
    cs = dict(artifact_stems=set(), log_basenames=set())
    assert _has_real_artifact_evidence(cs) is False


def test_dir_has_artifact_coverage_exact_dir_match():
    cs = dict(
        compiled_dirs={'drivers/usb/core/'},
        artifact_stems={'drivers/usb/core/hub'},
    )
    assert _dir_has_artifact_coverage('drivers/usb/core/Makefile', cs) is True

def test_dir_has_artifact_coverage_prefix_match():
    """F: parent dir is a prefix of an artifact stem path."""
    cs = dict(
        compiled_dirs=set(),
        artifact_stems={'drivers/usb/core/hub'},
    )
    # drivers/usb/Kconfig: fdir=drivers/usb, fdir_slash=drivers/usb/
    # artifact stem drivers/usb/core/hub starts with drivers/usb/
    assert _dir_has_artifact_coverage('drivers/usb/Kconfig', cs) is True

def test_dir_has_artifact_coverage_no_match():
    cs = dict(
        compiled_dirs={'drivers/usb/core/'},
        artifact_stems={'drivers/usb/core/hub'},
    )
    assert _dir_has_artifact_coverage('fs/btrfs/Kconfig', cs) is False

def test_dir_has_artifact_coverage_root():
    """F: root-level files always return True."""
    cs = dict(compiled_dirs=set(), artifact_stems=set())
    assert _dir_has_artifact_coverage('Kconfig', cs) is True
    assert _dir_has_artifact_coverage('Makefile', cs) is True


# -- Header-only commits -------------------------------------------------------

def test_header_only_commit_keeps_via_kconfig_when_covered():
    """F (v16.1.0): a commit that only touches a header in a compiled dir must
    be kept via kconfig_coverage.  Previously it fell through to L0 default
    because _file_has_artifact() always returns False for .h files."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb/core/'},
        artifact_stems={'drivers/usb/core/hub'},   # real artifacts present
        log_basenames=set(),
        available=True,
    )
    c = _commit(
        sha='hdr_01',
        subject='usb: add ioctl constants to hub.h',
        files=['drivers/usb/core/hub.h'],
    )
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'keep'
    assert reason == 'kconfig_coverage'


def test_header_only_commit_drops_when_not_covered():
    """F (v16.1.0): a commit that only touches a header in an uncovered dir
    must be dropped regardless of artifact availability."""
    cs = _usb_cs_with_artifacts()   # USB compiled, btrfs not
    c = _commit(
        sha='hdr_02',
        subject='btrfs: extend on-disk format header',
        files=['fs/btrfs/ctree.h'],
    )
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'drop'
    assert reason == 'no_kconfig_coverage'
    assert 'fs/btrfs/ctree.h' in dbg['l2half_kconfig_uncovered_files']


def test_header_only_commit_keeps_regardless_of_artifact_availability():
    """F (v16.1.0): header evaluation uses kconfig regardless of whether real
    artifacts are present.  With or without artifact_stems, a covered header
    commit is kept via kconfig_coverage."""
    # Without real artifacts
    cs_no_art = dict(
        compiled_files=set(),
        compiled_dirs={'include/linux/'},
        artifact_stems=set(),
        log_basenames=set(),
        available=True,
    )
    c = _commit(
        sha='hdr_03',
        subject='linux/list.h: add list_for_each_entry_from_reverse',
        files=['include/linux/list.h'],
    )
    action, reason, _ = filter_decision(
        c, cs_no_art, {'require_kconfig_coverage': True}, True)
    assert action == 'keep' and reason == 'kconfig_coverage'

    # With real artifacts -- same result
    cs_with_art = dict(
        compiled_files=set(),
        compiled_dirs={'include/linux/'},
        artifact_stems={'drivers/usb/core/hub'},
        log_basenames=set(),
        available=True,
    )
    action2, reason2, _ = filter_decision(
        c, cs_with_art, {'require_kconfig_coverage': True}, True)
    assert action2 == 'keep' and reason2 == 'kconfig_coverage'


def test_header_only_no_require_keeps_by_default():
    """F (v16.1.0): when require is inactive, a header-only commit in an
    uncovered dir is neutral and falls through to L0 default keep."""
    cs = _usb_cs_with_artifacts()
    c = _commit(
        sha='hdr_04',
        subject='btrfs: extend ctree.h',
        files=['fs/btrfs/ctree.h'],
    )
    action, reason, _ = filter_decision(
        c, cs, {'require_kconfig_coverage': False}, True)
    assert action == 'keep'
    # reason may be 'default' or another keep -- just must not be a drop


# -- Build-meta path-prefix artifact fallback ----------------------------------

def test_build_meta_parent_dir_kept_via_artifact_prefix():
    """F (v16.1.0): drivers/usb/Kconfig must be kept via build_artifact when
    drivers/usb/core/hub is in artifact_stems (prefix match).
    The Kconfig file's dir (drivers/usb/) is a prefix of the artifact path."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb/core/'},
        artifact_stems={'drivers/usb/core/hub'},
        log_basenames=set(),
        available=True,
    )
    c = _commit(
        sha='usb_parent_kconfig',
        subject='usb: add Kconfig option for USB4 tunnelling',
        files=['drivers/usb/Kconfig'],
    )
    action, reason, dbg = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'keep'
    assert reason == 'build_artifact'


def test_build_meta_unrelated_dir_dropped_when_require():
    """F (v16.1.0): a Makefile in an entirely unrelated dir (no artifact prefix
    match) must be dropped when require is active."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb/core/'},
        artifact_stems={'drivers/usb/core/hub'},
        log_basenames=set(),
        available=True,
    )
    c = _commit(
        sha='btrfs_makefile_02',
        subject='btrfs: add new helper to Makefile',
        files=['fs/btrfs/Makefile'],
    )
    action, reason, _ = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'drop'
    assert reason == 'no_kconfig_coverage'


def test_build_meta_prefix_fallback_no_artifacts_drops():
    """F (v16.1.0): without real artifacts the path-prefix fallback is inactive;
    an uncovered Makefile must be dropped when require is active."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb/core/'},
        artifact_stems=set(),          # no real artifacts
        log_basenames=set(),
        available=True,
    )
    c = _commit(
        sha='usb_parent_makefile_no_art',
        subject='usb: tweak top-level Makefile',
        files=['drivers/usb/Makefile'],
    )
    # drivers/usb/ is NOT in compiled_dirs (only core/ is), and there are no
    # real artifacts, so the prefix fallback must not fire.
    action, reason, _ = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'drop'
    assert reason == 'no_kconfig_coverage'


def test_root_build_meta_always_kept_dir_has_artifact_coverage():
    """F (v16.1.0): _dir_has_artifact_coverage returns True for root files;
    root Makefile/Kconfig kept via kconfig_coverage through
    _file_is_kconfig_covered() root exception (fdir=='')."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb/core/'},
        artifact_stems={'drivers/usb/core/hub'},
        log_basenames=set(),
        available=True,
    )
    c = _commit(
        sha='root_kconfig_02',
        subject='Kconfig: add new top-level option',
        files=['Kconfig'],
    )
    action, reason, _ = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'keep'
    # Root Kconfig covered by _file_is_kconfig_covered root exception
    assert reason == 'kconfig_coverage'


# -- 'kconfig_coverage' reason -------------------------------------------------

def test_reason_kconfig_coverage_for_covered_header():
    """F (v16.1.0): reason must be 'kconfig_coverage' for a header in a
    compiled directory."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'net/core/'},
        artifact_stems={'net/core/sock'},
        log_basenames=set(),
        available=True,
    )
    c = _commit(
        sha='hdr_reason_01',
        subject='net: add skb helper to skbuff.h',
        files=['net/core/skbuff.h'],
    )
    _, reason, _ = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert reason == 'kconfig_coverage'


def test_reason_kconfig_coverage_for_covered_build_meta():
    """F (v16.1.0): reason must be 'kconfig_coverage' for a Makefile whose
    directory is in compiled_dirs."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'net/core/'},
        artifact_stems={'net/core/sock'},
        log_basenames=set(),
        available=True,
    )
    c = _commit(
        sha='makefile_reason_01',
        subject='net/core: add object to Makefile',
        files=['net/core/Makefile'],
    )
    _, reason, _ = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert reason == 'kconfig_coverage'


# -- l2half_has_real_artifacts debug field -------------------------------------

def test_debug_has_real_artifacts_true_when_stems_present():
    """F (v16.1.0): l2half_has_real_artifacts must be True when artifact_stems
    is non-empty."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb/core/'},
        artifact_stems={'drivers/usb/core/hub'},
        log_basenames=set(),
        available=True,
    )
    c = _commit(files=['drivers/usb/core/hub.c'])
    _, _, dbg = filter_decision(c, cs, {}, True)
    assert dbg['l2half_has_real_artifacts'] is True


def test_debug_has_real_artifacts_false_when_no_artifacts():
    """F (v16.1.0): l2half_has_real_artifacts must be False when neither
    artifact_stems nor log_basenames are non-empty."""
    cs = _usb_cs()   # compiled_files + compiled_dirs but no artifact_stems
    c = _commit(files=['drivers/usb/core/hub.c'])
    _, _, dbg = filter_decision(c, cs, {}, True)
    assert dbg['l2half_has_real_artifacts'] is False


def test_debug_required_keys_includes_has_real_artifacts():
    """F (v16.1.0): l2half_has_real_artifacts must always appear in debug_detail."""
    c = _commit(subject='net: fix skb', files=['net/core/sock.c'])
    _, _, dbg = filter_decision(c, _EMPTY_CS, {}, False)
    assert 'l2half_has_real_artifacts' in dbg


# -- Source file behaviour with real artifacts ---------------------------------

def test_source_not_in_artifact_drops_when_real_artifacts_present():
    """F (v16.1.0): when real artifact evidence is present, a source file that
    is NOT in artifact_stems must be dropped (not rescued by kconfig coverage)."""
    cs = dict(
        compiled_files={'drivers/usb/core/hub.c'},  # kconfig covers hub.c
        compiled_dirs={'drivers/usb/core/'},
        artifact_stems={'drivers/usb/core/hub'},     # only hub is built
        log_basenames=set(),
        available=True,
    )
    # different.c is in the compiled dir (kconfig covered) but NOT in artifacts
    c = _commit(
        sha='src_no_art_01',
        subject='usb: add new helper',
        files=['drivers/usb/core/different.c'],
    )
    action, reason, _ = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'drop'
    assert reason == 'no_kconfig_coverage'


def test_source_in_artifact_keeps_when_real_artifacts_present():
    """F (v16.1.0): a source file that IS in artifact_stems is kept even when
    kconfig coverage check would also pass."""
    cs = _usb_cs_with_artifacts()
    c = _commit(
        sha='src_art_01',
        subject='usb: fix hub enumeration',
        files=['drivers/usb/core/hub.c'],
    )
    action, reason, _ = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'keep'
    assert reason == 'build_artifact'


def test_source_no_real_artifacts_falls_back_to_kconfig():
    """F (v16.1.0): when no real artifacts exist, a source file in a compiled
    dir is kept via kconfig_coverage (not dropped due to missing artifact)."""
    cs = _usb_cs()   # compiled_files + compiled_dirs, artifact_stems=empty
    c = _commit(
        sha='src_kconfig_01',
        subject='usb: fix hub locking',
        files=['drivers/usb/core/hub.c'],
    )
    action, reason, _ = filter_decision(
        c, cs, {'require_kconfig_coverage': True}, True)
    assert action == 'keep'
    assert reason == 'kconfig_coverage'
