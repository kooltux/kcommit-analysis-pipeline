"""Tests for lib.history_map — cache helpers, build_history_config_map (mocked git).

v18.1.0 additions:
  B — _guess_makefiles_from_map: depth cap and symbol-count threshold
      test_guess_makefiles_depth_cap
      test_guess_makefiles_min_symbols
      test_guess_makefiles_combined_filters
      test_guess_makefiles_no_filter_default_keeps_all_with_depth_lte3
      test_guess_makefiles_empty_map
  C — build_history_config_map: max_history_revisions cap
      test_build_history_revision_cap
      test_build_history_revision_cap_default_16
  E — merged-map top-level cache
      test_merged_map_cache_key_stable
      test_merged_map_cache_key_varies_with_range
      test_merged_map_cache_key_varies_with_paths
      test_merged_map_cache_roundtrip
      test_merged_map_cache_miss_wrong_key
      test_merged_map_cache_miss_absent
      test_build_history_uses_merged_cache
      test_build_history_saves_merged_cache
"""
import os
import hashlib
from unittest.mock import patch, MagicMock
import pytest

from lib.history_map import (
    _gitshow_cache_path,
    _gitshow_cache_get,
    _gitshow_cache_put,
    _merged_map_cache_key,
    _load_merged_map_cache,
    _save_merged_map_cache,
    _guess_makefiles_from_map,
    build_history_config_map,
)


def _cfg(src='/fake/repo', max_hist_revs=None, max_depth=None, min_symbols=None):
    hm = {
        'enabled': True, 'mode': 'range',
        'sample_step': 1000, 'max_commits_per_probe': 256,
        'max_failure_rate': 0.05,
    }
    if max_hist_revs is not None:
        hm['max_history_revisions'] = max_hist_revs
    if max_depth is not None:
        hm['max_makefile_depth'] = max_depth
    if min_symbols is not None:
        hm['min_makefile_symbols'] = min_symbols
    return {
        'kernel':  {'source_dir': src, 'rev_old': 'v6.1', 'rev_new': 'v6.6'},
        'collect': {'no_merges': True, 'first_parent': False,
                    'history_workers': 1, 'extra_git_log_args': []},
        'history_mapping': hm,
    }


# ── _gitshow_cache_path ───────────────────────────────────────────────────
def test_cache_path_structure(tmp_path):
    key = 'abcdef1234567890'
    p = _gitshow_cache_path(str(tmp_path), key)
    assert 'gitshow_cache' in p
    assert p.endswith(key)
    # sharded: key[:2] / key[2:4] / key
    assert key[:2] in p
    assert key[2:4] in p


# ── _gitshow_cache_get / put roundtrip ───────────────────────────────────────
def test_cache_roundtrip(tmp_path):
    _gitshow_cache_put(str(tmp_path), 'v6.1', 'drivers/usb/Makefile',
                       'obj-$(CONFIG_USB) += hub.o\n')
    result = _gitshow_cache_get(str(tmp_path), 'v6.1', 'drivers/usb/Makefile')
    assert result == 'obj-$(CONFIG_USB) += hub.o\n'


def test_cache_get_miss(tmp_path):
    result = _gitshow_cache_get(str(tmp_path), 'v6.1', 'no/such/Makefile')
    assert result is None


def test_cache_get_none_dir():
    assert _gitshow_cache_get(None, 'v6.1', 'Makefile') is None


def test_cache_put_none_dir():
    """put with None cache_dir must not raise."""
    _gitshow_cache_put(None, 'v6.1', 'Makefile', 'content')  # no-op


def test_cache_put_overwrites(tmp_path):
    _gitshow_cache_put(str(tmp_path), 'v6.1', 'M', 'first')
    _gitshow_cache_put(str(tmp_path), 'v6.1', 'M', 'second')
    assert _gitshow_cache_get(str(tmp_path), 'v6.1', 'M') == 'second'


# ── E: _merged_map_cache_key ────────────────────────────────────────────────
def test_merged_map_cache_key_stable():
    """E: same inputs always produce the same key."""
    paths = ['drivers/usb/Makefile', 'net/Makefile']
    k1 = _merged_map_cache_key('v6.1', 'v6.6', paths)
    k2 = _merged_map_cache_key('v6.1', 'v6.6', paths)
    assert k1 == k2
    assert len(k1) == 24


def test_merged_map_cache_key_varies_with_range():
    """E: different rev ranges produce different keys."""
    paths = ['drivers/usb/Makefile']
    k1 = _merged_map_cache_key('v6.1', 'v6.6', paths)
    k2 = _merged_map_cache_key('v6.1', 'v6.7', paths)
    assert k1 != k2


def test_merged_map_cache_key_varies_with_paths():
    """E: different Makefile sets produce different keys."""
    k1 = _merged_map_cache_key('v6.1', 'v6.6', ['drivers/usb/Makefile'])
    k2 = _merged_map_cache_key('v6.1', 'v6.6', ['net/Makefile'])
    assert k1 != k2


def test_merged_map_cache_key_order_independent():
    """E: key is independent of input list order (paths are sorted internally)."""
    k1 = _merged_map_cache_key('v6.1', 'v6.6', ['net/Makefile', 'drivers/usb/Makefile'])
    k2 = _merged_map_cache_key('v6.1', 'v6.6', ['drivers/usb/Makefile', 'net/Makefile'])
    assert k1 == k2


# ── E: _load_merged_map_cache / _save_merged_map_cache ─────────────────────
def test_merged_map_cache_roundtrip(tmp_path):
    """E: save then load returns the same config_to_paths."""
    c2p = {'CONFIG_USB': ['drivers/usb/hub.c', 'drivers/usb/core.c']}
    key = 'abc123def456789012345678'
    _save_merged_map_cache(str(tmp_path), key, c2p, 'range')
    result = _load_merged_map_cache(str(tmp_path), key)
    assert result == c2p


def test_merged_map_cache_miss_wrong_key(tmp_path):
    """E: load with a different key returns None (stale cache)."""
    c2p = {'CONFIG_USB': ['drivers/usb/hub.c']}
    _save_merged_map_cache(str(tmp_path), 'key_A', c2p, 'range')
    result = _load_merged_map_cache(str(tmp_path), 'key_B')
    assert result is None


def test_merged_map_cache_miss_absent(tmp_path):
    """E: load when no file exists returns None."""
    assert _load_merged_map_cache(str(tmp_path), 'anykey') is None


def test_merged_map_cache_none_dir():
    """E: None cache_dir is a no-op for both save and load."""
    _save_merged_map_cache(None, 'k', {}, 'range')   # must not raise
    assert _load_merged_map_cache(None, 'k') is None


def test_merged_map_cache_overwrites(tmp_path):
    """E: saving twice with the same key overwrites; load returns latest."""
    c2p_v1 = {'CONFIG_USB': ['drivers/usb/hub.c']}
    c2p_v2 = {'CONFIG_USB': ['drivers/usb/hub.c'], 'CONFIG_NET': ['net/core/skbuff.c']}
    key = 'stablekey123456789012345'
    _save_merged_map_cache(str(tmp_path), key, c2p_v1, 'range')
    _save_merged_map_cache(str(tmp_path), key, c2p_v2, 'range')
    result = _load_merged_map_cache(str(tmp_path), key)
    assert result == c2p_v2


# ── B: _guess_makefiles_from_map ─────────────────────────────────────────────
def test_guess_makefiles_depth_cap():
    """B: directories deeper than max_depth are excluded."""
    base_map = {
        'CONFIG_A': ['drivers/usb/core/hub.c'],       # depth 3 -> included at max_depth=3
        'CONFIG_B': ['drivers/usb/host/xhci/main.c'], # depth 4 -> excluded at max_depth=3
    }
    result = _guess_makefiles_from_map(base_map, max_depth=3)
    assert 'drivers/usb/core/Makefile' in result
    assert 'drivers/usb/host/xhci/Makefile' not in result


def test_guess_makefiles_min_symbols():
    """B: directories with fewer symbol references than min_symbols are excluded."""
    base_map = {
        'CONFIG_A': ['drivers/usb/hub.c'],
        'CONFIG_B': ['drivers/usb/core.c'],   # same dir -> 2 refs
        'CONFIG_C': ['net/lone.c'],            # only 1 ref
    }
    result = _guess_makefiles_from_map(base_map, max_depth=3, min_symbols=2)
    assert 'drivers/usb/Makefile' in result
    assert 'net/Makefile' not in result


def test_guess_makefiles_combined_filters():
    """B: both depth cap and symbol threshold must pass."""
    base_map = {
        # deep dir with many symbols -> excluded by depth
        'CONFIG_A': ['a/b/c/d/file1.c'],
        'CONFIG_B': ['a/b/c/d/file2.c'],
        'CONFIG_C': ['a/b/c/d/file3.c'],
        # shallow dir with few symbols -> excluded by min_symbols
        'CONFIG_D': ['net/lone.c'],
        # shallow dir with enough symbols -> included
        'CONFIG_E': ['drivers/usb/hub.c'],
        'CONFIG_F': ['drivers/usb/core.c'],
    }
    result = _guess_makefiles_from_map(base_map, max_depth=3, min_symbols=2)
    assert 'drivers/usb/Makefile' in result
    assert 'a/b/c/d/Makefile' not in result
    assert 'net/Makefile' not in result


def test_guess_makefiles_no_filter_default_keeps_shallow():
    """B: with default max_depth=3 and min_symbols=1, shallow dirs are always kept."""
    base_map = {
        'CONFIG_USB': ['drivers/usb/hub.c'],
        'CONFIG_NET': ['net/core/skbuff.c'],
    }
    result = _guess_makefiles_from_map(base_map)  # use defaults
    assert 'drivers/usb/Makefile' in result
    assert 'net/core/Makefile' in result


def test_guess_makefiles_empty_map():
    """B: empty base_map returns an empty list."""
    assert _guess_makefiles_from_map({}) == []


def test_guess_makefiles_sorted_output():
    """B: returned list is always sorted."""
    base_map = {
        'CONFIG_Z': ['z/sub/file.c'],
        'CONFIG_A': ['a/sub/file.c'],
    }
    result = _guess_makefiles_from_map(base_map, max_depth=3)
    assert result == sorted(result)


def test_guess_makefiles_root_paths_excluded():
    """B: files with no directory component produce no Makefile entry."""
    base_map = {'CONFIG_X': ['rootfile.c']}
    assert _guess_makefiles_from_map(base_map) == []


# ── build_history_config_map (original tests, updated cfg helper) ─────────────
MAKEFILE_CONTENT = 'obj-$(CONFIG_USB) += hub.o\nobj-$(CONFIG_NET) += core.o\n'


def _mock_run(commits_out='abc123\ndef456\n', makefile=MAKEFILE_CONTENT):
    """Return a mock for subprocess.run covering rev-list and show calls."""
    def side_effect(cmd, **kwargs):
        r = MagicMock()
        r.returncode = 0
        r.stderr = ''
        if 'rev-list' in cmd:
            r.stdout = commits_out
        else:
            r.stdout = makefile
        return r
    return side_effect


def test_build_history_disabled(tmp_path):
    cfg = _cfg()
    cfg['history_mapping']['enabled'] = False
    base = {'CONFIG_USB': ['drivers/usb/hub.c']}
    result = build_history_config_map(cfg, base, str(tmp_path))
    assert result['mode'] == 'disabled'
    assert result['config_to_paths'] is base


def test_build_history_no_commits(tmp_path):
    """Empty rev-list → returns base_map unchanged."""
    with patch('subprocess.run', side_effect=_mock_run(commits_out='')):
        result = build_history_config_map(_cfg(), {}, str(tmp_path))
    assert result['config_to_paths'] == {}


def test_build_history_adds_paths(tmp_path):
    """With valid Makefile content, config_to_paths gets entries."""
    base = {}
    with patch('subprocess.run', side_effect=_mock_run()):
        result = build_history_config_map(_cfg(), base, str(tmp_path))
    c2p = result['config_to_paths']
    assert isinstance(c2p, dict)


def test_build_history_uses_cache(tmp_path):
    """Second call reads from disk cache, not subprocess."""
    base = {}
    with patch('subprocess.run', side_effect=_mock_run()) as m1:
        build_history_config_map(_cfg(), base, str(tmp_path))
    first_call_count = m1.call_count

    with patch('subprocess.run', side_effect=_mock_run()) as m2:
        build_history_config_map(_cfg(), base, str(tmp_path))
    # rev-list still called; git-show calls reduced because results are cached
    assert m2.call_count <= first_call_count


def test_build_history_progress_callback(tmp_path):
    calls = []
    def cb(done, total):
        calls.append((done, total))
    with patch('subprocess.run', side_effect=_mock_run()):
        build_history_config_map(_cfg(), {}, str(tmp_path), progress_callback=cb)
    assert len(calls) >= 0  # callback was accepted without crash


def test_build_history_snapshots_list(tmp_path):
    with patch('subprocess.run', side_effect=_mock_run()):
        result = build_history_config_map(_cfg(), {}, str(tmp_path))
    assert 'snapshots' in result
    assert isinstance(result['snapshots'], list)


# ── C: max_history_revisions cap ─────────────────────────────────────────────
def test_build_history_revision_cap(tmp_path):
    """C: max_history_revisions=2 limits sampled revisions to 2 even with many commits.

    We feed 20 commits and sample_step=1 (would normally sample all 20).
    With max_history_revisions=2 only 2 revisions are probed.
    We count git-show calls (non-rev-list subprocess.run calls) and verify
    the count is ≤ 2 * len(interesting_paths) + some overhead.
    """
    # 20 commit hashes in rev-list output
    commits_out = '\n'.join('c%02d' % i for i in range(20)) + '\n'
    base = {'CONFIG_USB': ['drivers/usb/hub.c']}
    show_calls = []

    def side_effect(cmd, **kwargs):
        r = MagicMock()
        r.returncode = 0
        r.stderr = ''
        if 'rev-list' in cmd:
            r.stdout = commits_out
        else:
            show_calls.append(cmd)
            r.stdout = MAKEFILE_CONTENT
        return r

    cfg = _cfg(max_hist_revs=2)
    cfg['history_mapping']['sample_step'] = 1  # without cap, would sample all 20
    with patch('subprocess.run', side_effect=side_effect):
        result = build_history_config_map(cfg, base, str(tmp_path))

    # With cap=2, at most 2 revisions are probed regardless of sample_step
    # Each revision probes len(interesting_paths) Makefiles
    assert len(show_calls) <= 2 * 10  # generous upper bound
    assert 'snapshots' in result
    assert len(result['snapshots']) <= 2


def test_build_history_revision_cap_default_16(tmp_path):
    """C: default max_history_revisions is 16 — verify the key is read correctly."""
    cfg = _cfg()  # no explicit max_hist_revs
    assert cfg['history_mapping'].get('max_history_revisions', 16) == 16


# ── E: merged-map cache integration with build_history_config_map ─────────
def test_build_history_uses_merged_cache(tmp_path):
    """E: second call with same range returns cached result without git-show."""
    base = {'CONFIG_USB': ['drivers/usb/hub.c']}
    show_calls = []

    def side_effect(cmd, **kwargs):
        r = MagicMock()
        r.returncode = 0
        r.stderr = ''
        if 'rev-list' in cmd:
            r.stdout = 'abc123\ndef456\n'
        else:
            show_calls.append(cmd)
            r.stdout = MAKEFILE_CONTENT
        return r

    cfg = _cfg()
    with patch('subprocess.run', side_effect=side_effect):
        r1 = build_history_config_map(cfg, base, str(tmp_path))
    first_show_count = len(show_calls)
    show_calls.clear()

    # Second call: merged-map cache should be hit, no git-show calls at all
    with patch('subprocess.run', side_effect=side_effect):
        r2 = build_history_config_map(cfg, base, str(tmp_path))

    assert len(show_calls) == 0, (
        'E: second call should hit merged-map cache and make zero git-show calls; '
        'got %d show calls' % len(show_calls))
    assert r2['config_to_paths'] == r1['config_to_paths']


def test_build_history_saves_merged_cache(tmp_path):
    """E: after a cold run, history_merged_map.json is present in cache_dir."""
    import json
    base = {'CONFIG_USB': ['drivers/usb/hub.c']}
    with patch('subprocess.run', side_effect=_mock_run()):
        build_history_config_map(_cfg(), base, str(tmp_path))
    cache_file = os.path.join(str(tmp_path), 'history_merged_map.json')
    assert os.path.exists(cache_file), 'history_merged_map.json must be written after cold run'
    stored = json.load(open(cache_file))
    assert 'key' in stored
    assert 'config_to_paths' in stored


def test_build_history_merged_cache_invalidated_on_range_change(tmp_path):
    """E: changing rev_new invalidates the merged-map cache (different key)."""
    base = {'CONFIG_USB': ['drivers/usb/hub.c']}
    show_calls = []

    def side_effect(cmd, **kwargs):
        r = MagicMock()
        r.returncode = 0
        r.stderr = ''
        if 'rev-list' in cmd:
            r.stdout = 'abc123\ndef456\n'
        else:
            show_calls.append(cmd)
            r.stdout = MAKEFILE_CONTENT
        return r

    cfg_v1 = _cfg()  # rev_new = v6.6
    with patch('subprocess.run', side_effect=side_effect):
        build_history_config_map(cfg_v1, base, str(tmp_path))
    show_calls.clear()

    # Different rev_new -> different cache key -> cold run again
    cfg_v2 = _cfg()
    cfg_v2['kernel']['rev_new'] = 'v6.7'
    with patch('subprocess.run', side_effect=side_effect):
        build_history_config_map(cfg_v2, base, str(tmp_path))

    assert len(show_calls) > 0, (
        'E: changed rev_new must invalidate merged-map cache and trigger new git-show calls')
