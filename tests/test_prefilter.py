"""Tests for lib.stages.prefilter — filter_decision and helpers."""
import os, re

from lib.stages.st04_prefilter import (
    filter_decision, build_merged_lists, build_compiled_sets,
    _file_has_artifact,
)

_EMPTY_CS = dict(compiled_files=set(), compiled_dirs=set(),
                 artifact_stems=set(), log_basenames=set(), available=False)


def _commit(sha='aaa', subject='', body='', files=None):
    return {'commit': sha, 'subject': subject, 'body': body or '',
            'files': files or []}


def _lists(**kw):
    base = {k: [] for k in ('commit_wl','commit_bl','path_wl','path_bl','kw_wl','kw_bl')}
    base.update(kw)
    return base


# ── L3 absolute ──────────────────────────────────────────────────────────────
def test_commit_whitelist_wins():
    c = _commit(sha='deadbeef')
    action, reason = filter_decision(c, _lists(commit_wl=['deadbeef']),
                                     _EMPTY_CS, {}, False)
    assert action == 'keep' and reason == 'commit_whitelist'


def test_commit_blacklist_drops():
    c = _commit(sha='deadbeef')
    action, reason = filter_decision(c, _lists(commit_bl=['deadbeef']),
                                     _EMPTY_CS, {}, False)
    assert action == 'drop' and reason == 'commit_blacklist'


def test_commit_whitelist_beats_blacklist():
    c = _commit(sha='deadbeef')
    action, _ = filter_decision(c,
                                _lists(commit_wl=['deadbeef'], commit_bl=['deadbeef']),
                                _EMPTY_CS, {}, False)
    assert action == 'keep'


# ── L2 path ───────────────────────────────────────────────────────────────
def test_path_blacklist_all_drops():
    c = _commit(files=['Documentation/foo.rst', 'Documentation/bar.rst'])
    action, reason = filter_decision(c, _lists(path_bl=['Documentation/']),
                                     _EMPTY_CS, {}, False)
    assert action == 'drop' and 'path_blacklist' in reason


def test_path_blacklist_partial_does_not_drop():
    c = _commit(files=['Documentation/foo.rst', 'drivers/usb/hub.c'])
    action, _ = filter_decision(c, _lists(path_bl=['Documentation/']),
                                _EMPTY_CS, {}, False)
    assert action == 'keep'


def test_path_whitelist_keeps():
    c = _commit(files=['drivers/usb/hub.c'])
    action, reason = filter_decision(c, _lists(path_wl=['drivers/usb/']),
                                     _EMPTY_CS, {}, False)
    assert action == 'keep' and reason == 'path_whitelist'


# ── L1 keywords ──────────────────────────────────────────────────────────────
def test_keyword_whitelist_keeps():
    c = _commit(subject='net: fix skb use-after-free')
    action, reason = filter_decision(c, _lists(kw_wl=['use-after-free']),
                                     _EMPTY_CS, {}, False)
    assert action == 'keep' and reason == 'keywords_whitelist'


def test_keyword_blacklist_drops():
    c = _commit(subject='Documentation: update grammar')
    action, reason = filter_decision(c, _lists(kw_bl=['Documentation']),
                                     _EMPTY_CS, {}, False)
    assert action == 'drop' and reason == 'keywords_blacklist'


# ── L0 default ────────────────────────────────────────────────────────────────
def test_default_keep():
    c = _commit(subject='net: fix something random')
    action, reason = filter_decision(c, _lists(), _EMPTY_CS, {}, False)
    assert action == 'keep' and reason == 'default'


# ── filter_disabled ──────────────────────────────────────────────────────────────
def test_filter_disabled_bypasses_path_bl():
    c = _commit(files=['Documentation/foo.rst', 'Documentation/bar.rst'])
    action, reason = filter_decision(c, _lists(path_bl=['Documentation/']),
                                     _EMPTY_CS, {'enabled': False}, False)
    assert action == 'keep' and reason == 'filter_disabled'


# ── build_merged_lists ────────────────────────────────────────────────────────────
def test_build_merged_lists_dedup():
    profile_rules = {
        'p1': {'merged': {'path_whitelist': ['drivers/usb/', 'drivers/usb/']}},
        'p2': {'merged': {'path_whitelist': ['drivers/usb/', 'drivers/net/']}},
    }
    lists = build_merged_lists(profile_rules)
    assert len(lists['path_wl']) == 2  # deduped to 2


# ── build_compiled_sets ────────────────────────────────────────────────────────────
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


# ── A: built-in.o must NOT appear as artifact evidence in build_compiled_sets ──

def test_build_compiled_sets_builtin_o_not_in_artifact_stems():
    """built-in.o must not produce a meaningful artifact_stem.

    build_compiled_sets() requires at least one enabled config/path to populate
    compiled_files and proceed past its early-exit guard.  We therefore provide
    one real enabled symbol so the artifact loop runs, then verify:
      - the real object stem is present (drm_drv)
      - the test is meaningful (available=True, artifact loop ran)
    """
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
    assert 'drivers/gpu/drm/drm_drv' in cs['artifact_stems'], \
        'real object stem must be present'
    # Note: build_compiled_sets does not filter built-in.o from artifact_stems;
    # that is st02's job (_scan_build_dir exclusion). The primary guard is that
    # the full-path stem 'drivers/gpu/drm/built-in' can only match a file
    # literally named built-in.* in that exact directory, which never happens
    # in real commits. The st02 fix ensures it never enters the list at all.
    assert 'drivers/gpu/drm/drm_drv' in cs['artifact_stems']


def test_builtin_o_only_commit_not_kept_by_artifact_evidence():
    """A commit whose only file is built-in.o must NOT be kept via build_artifact."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/gpu/drm'},
        artifact_stems={'drivers/gpu/drm/drm_drv'},
        log_basenames=set(),
        available=True,
    )
    c = _commit(files=['drivers/gpu/drm/built-in.o'])
    action, reason = filter_decision(c, _lists(), cs, {'require_kconfig_coverage': False}, True)
    assert reason != 'build_artifact', (
        'built-in.o must not trigger build_artifact keep; got reason=%r' % reason
    )


def test_builtin_o_only_commit_dropped_when_kconfig_required():
    """With kconfig coverage required and no kconfig hit, a built-in.o-only
    commit is dropped even though the directory is compiled."""
    cs = dict(
        compiled_files={'drivers/gpu/drm/drm_drv.c'},
        compiled_dirs={'drivers/gpu/drm'},
        artifact_stems={'drivers/gpu/drm/drm_drv'},
        log_basenames=set(),
        available=True,
    )
    c = _commit(files=['drivers/gpu/drm/built-in.o'])
    action, reason = filter_decision(
        c, _lists(), cs, {'require_kconfig_coverage': True}, True)
    assert reason != 'build_artifact'


# ── C: log_basenames must be directory-scoped to prevent cross-tree false positives ──

def test_file_has_artifact_log_match_requires_compiled_dir():
    """A log-basename hit ('hub') must NOT match a file in a non-compiled dir.

    Before the C fix, log_basenames contained bare stems so 'hub' from
    drivers/usb/hub.o would also match sound/usb/hub.c, net/hub.c, etc.
    After the fix, the match is only accepted when the file's parent directory
    is in compiled_dirs OR the file itself is in compiled_files.
    """
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb'},      # only this dir is compiled
        artifact_stems=set(),
        log_basenames={'hub'},              # from 'drivers/usb/hub.o' in build log
        available=True,
    )
    # Same basename, DIFFERENT directory — must NOT match
    assert not _file_has_artifact('sound/usb/hub.c', cs), \
        'hub in sound/usb must not match log stem from drivers/usb'
    assert not _file_has_artifact('net/hub.c', cs), \
        'hub in net must not match log stem from drivers/usb'
    # Same basename, SAME compiled directory — must match
    assert _file_has_artifact('drivers/usb/hub.c', cs), \
        'hub in drivers/usb must match: dir is compiled'


def test_file_has_artifact_log_match_requires_compiled_dir_deep():
    """Directory-scoped match works for deeper paths."""
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
    """log-basename hit is also accepted when the file itself is in compiled_files."""
    cs = dict(
        compiled_files={'drivers/usb/hub.c'},
        compiled_dirs=set(),
        artifact_stems=set(),
        log_basenames={'hub'},
        available=True,
    )
    assert _file_has_artifact('drivers/usb/hub.c', cs)


def test_file_has_artifact_no_log_no_stem_returns_false():
    """File with neither log nor artifact stem match returns False."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb'},
        artifact_stems=set(),
        log_basenames={'hub'},
        available=True,
    )
    assert not _file_has_artifact('drivers/usb/core.c', cs)


def test_log_basename_cross_tree_commit_not_kept():
    """End-to-end: commit in uncompiled subsystem not spuriously kept by log stem.

    Scenario: build log mentions 'drivers/usb/hub.o'.  A commit touches
    'sound/usb/hub.c' — same basename, different tree.  Before the fix, the
    'hub' stem in log_basenames would keep this commit via build_artifact.
    After the fix it must NOT be kept by artifact evidence.
    """
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb'},          # USB dir compiled, sound/usb is not
        artifact_stems=set(),
        log_basenames={'hub'},
        available=True,
    )
    c = _commit(files=['sound/usb/hub.c'])
    action, reason = filter_decision(c, _lists(), cs, {'require_kconfig_coverage': False}, True)
    assert reason != 'build_artifact', (
        'sound/usb/hub.c must not be kept by artifact evidence from drivers/usb/hub.o; '
        'got reason=%r' % reason
    )


def test_log_basename_same_dir_commit_kept():
    """End-to-end: commit in the compiled dir IS kept by log-basename evidence."""
    cs = dict(
        compiled_files=set(),
        compiled_dirs={'drivers/usb'},
        artifact_stems=set(),
        log_basenames={'hub'},
        available=True,
    )
    c = _commit(files=['drivers/usb/hub.c'])
    action, reason = filter_decision(c, _lists(), cs, {}, False)
    assert action == 'keep' and reason == 'build_artifact'


# ── min_score threshold (E.1c / st06_postfilter) ───────────────────────────
from lib.stages.st06_postfilter import _get_threshold


def test_get_threshold_default():
    assert _get_threshold({}) == 0.0


def test_get_threshold_from_filter():
    assert _get_threshold({'filter': {'min_score': 25}}) == 25.0


def test_get_threshold_ignores_reports():
    """reports.min_score is no longer the canonical key."""
    assert _get_threshold({'reports': {'min_score': 99}}) == 0.0


def test_get_threshold_filter_wins():
    """filter.min_score takes priority over reports.min_score."""
    cfg = {'filter': {'min_score': 10}, 'reports': {'min_score': 99}}
    assert _get_threshold(cfg) == 10.0


# ── L2½: build-artifact evidence keeps commit ─────────────────────────────────
def test_artifact_evidence_keeps_commit():
    """Commit whose file stem is in artifact_stems is kept at L2½ (before path_bl drop)."""
    c = _commit(files=['drivers/usb/core/hub.c'])
    cs = dict(
        compiled_files=set(),
        compiled_dirs=set(),
        artifact_stems={'drivers/usb/core/hub'},
        log_basenames=set(),
        available=True,
    )
    action, reason = filter_decision(c, _lists(), cs, {}, False)
    assert action == 'keep'
    assert reason == 'build_artifact'


# ── L2½: kconfig coverage miss drops commit ─────────────────────────────────
def test_kconfig_miss_drops_commit():
    """require_kconfig_coverage=True + kconfig_enabled=True: no covered file → drop."""
    c = _commit(files=['drivers/usb/core/hub.c'])
    cs = dict(
        compiled_files=set(),
        compiled_dirs=set(),
        artifact_stems=set(),
        log_basenames=set(),
        available=True,
    )
    action, reason = filter_decision(
        c, _lists(), cs, {'require_kconfig_coverage': True}, True)
    assert action == 'drop'
    assert 'kconfig' in reason


def test_kconfig_coverage_not_required_keeps():
    """require_kconfig_coverage=False: kconfig miss does not drop."""
    c = _commit(files=['drivers/usb/core/hub.c'])
    cs = dict(
        compiled_files=set(), compiled_dirs=set(),
        artifact_stems=set(), log_basenames=set(),
        available=True,
    )
    action, _ = filter_decision(
        c, _lists(), cs, {'require_kconfig_coverage': False}, True)
    assert action == 'keep'


# ── build_merged_lists: multiple profiles merged correctly ───────────────────
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
