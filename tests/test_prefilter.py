"""Tests for lib.stages.prefilter — filter_decision and helpers."""
import os, re

from lib.stages.st04_prefilter import (
    filter_decision, build_merged_lists, build_compiled_sets,
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


# ── L2 path ──────────────────────────────────────────────────────────────────
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


# ── L0 default ───────────────────────────────────────────────────────────────
def test_default_keep():
    c = _commit(subject='net: fix something random')
    action, reason = filter_decision(c, _lists(), _EMPTY_CS, {}, False)
    assert action == 'keep' and reason == 'default'


# ── filter_disabled ──────────────────────────────────────────────────────────
def test_filter_disabled_bypasses_path_bl():
    c = _commit(files=['Documentation/foo.rst', 'Documentation/bar.rst'])
    action, reason = filter_decision(c, _lists(path_bl=['Documentation/']),
                                     _EMPTY_CS, {'enabled': False}, False)
    assert action == 'keep' and reason == 'filter_disabled'


# ── build_merged_lists ───────────────────────────────────────────────────────
def test_build_merged_lists_dedup():
    profile_rules = {
        'p1': {'merged': {'path_whitelist': ['drivers/usb/', 'drivers/usb/']}},
        'p2': {'merged': {'path_whitelist': ['drivers/usb/', 'drivers/net/']}},
    }
    lists = build_merged_lists(profile_rules)
    assert len(lists['path_wl']) == 2  # deduped to 2


# ── build_compiled_sets ──────────────────────────────────────────────────────
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


# ── min_score threshold (E.1c / st06_postfilter) ─────────────────────────────
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
        artifact_stems={'drivers/usb/core/hub'},   # stem matches hub.c
        log_basenames=set(),
        available=True,
    )
    # No path_wl, no path_bl all-files-drop — falls through to L2½ artifact check
    action, reason = filter_decision(c, _lists(), cs, {}, False)
    assert action == 'keep'
    assert reason == 'build_artifact'


# ── L2½: kconfig coverage miss drops commit ───────────────────────────────────
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
    # 4th arg = filter_cfg, 5th = kconfig_enabled
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
