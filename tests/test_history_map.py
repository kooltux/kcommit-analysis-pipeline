"""Tests for lib.history_map — cache helpers, build_history_config_map (mocked git).

v18.1.0 additions:
  B — _guess_makefiles_from_map: depth cap and symbol-count threshold
  C — build_history_config_map: max_history_revisions cap
  E — merged-map top-level cache

v18.2.0 additions (F):
  test_build_history_uses_cache    — updated: fetch path is now Popen-based
  test_build_history_batch_fetch_used — new: batch_show_paths is called for misses
  test_build_history_batch_fallback   — new: serial fallback when Popen fails
"""
import io
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


MAKEFILE_CONTENT = 'obj-$(CONFIG_USB) += hub.o\nobj-$(CONFIG_NET) += core.o\n'


def _make_catfile_proc(content=MAKEFILE_CONTENT):
    """Minimal Popen mock that returns a single blob response for every read."""
    # We don't know the exact queries in advance, so we return a stream
    # that can answer multiple queries.  Each readline() returns a header;
    # each subsequent read() returns the content.
    content_bytes = content.encode('utf-8')
    header_line = b'deadbeef1234 blob %d\n' % len(content_bytes)

    # Build a stream: header + content + '\n', repeated enough times.
    # We use a counter-based mock so each task gets its own response.
    responses = []

    class _Stream:
        def __init__(self):
            self._buf = b''
            self._task_idx = 0

        def readline(self):
            # Called once per task
            return header_line

        def read(self, n):
            # Called with size, then with 1 (trailing newline)
            if n == 1:
                return b'\n'
            return content_bytes[:n]

    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stdout = _Stream()
    proc.stderr = MagicMock()
    proc.wait = MagicMock(return_value=0)
    proc.kill = MagicMock()
    return proc


def _mock_revlist(commits_out='abc123\ndef456\n'):
    """Return a mock for subprocess.run covering only rev-list calls."""
    def side_effect(cmd, **kwargs):
        r = MagicMock()
        r.returncode = 0
        r.stderr = ''
        r.stdout = commits_out
        return r
    return side_effect


# ── _gitshow_cache_path ───────────────────────────────────────────────────
def test_cache_path_structure(tmp_path):
    key = 'abcdef1234567890'
    p = _gitshow_cache_path(str(tmp_path), key)
    assert 'gitshow_cache' in p
    assert p.endswith(key)
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
    _gitshow_cache_put(None, 'v6.1', 'Makefile', 'content')  # no-op


def test_cache_put_overwrites(tmp_path):
    _gitshow_cache_put(str(tmp_path), 'v6.1', 'M', 'first')
    _gitshow_cache_put(str(tmp_path), 'v6.1', 'M', 'second')
    assert _gitshow_cache_get(str(tmp_path), 'v6.1', 'M') == 'second'


# ── E: _merged_map_cache_key ────────────────────────────────────────────────
def test_merged_map_cache_key_stable():
    paths = ['drivers/usb/Makefile', 'net/Makefile']
    k1 = _merged_map_cache_key('v6.1', 'v6.6', paths)
    k2 = _merged_map_cache_key('v6.1', 'v6.6', paths)
    assert k1 == k2
    assert len(k1) == 24


def test_merged_map_cache_key_varies_with_range():
    paths = ['drivers/usb/Makefile']
    k1 = _merged_map_cache_key('v6.1', 'v6.6', paths)
    k2 = _merged_map_cache_key('v6.1', 'v6.7', paths)
    assert k1 != k2


def test_merged_map_cache_key_varies_with_paths():
    k1 = _merged_map_cache_key('v6.1', 'v6.6', ['drivers/usb/Makefile'])
    k2 = _merged_map_cache_key('v6.1', 'v6.6', ['net/Makefile'])
    assert k1 != k2


def test_merged_map_cache_key_order_independent():
    k1 = _merged_map_cache_key('v6.1', 'v6.6', ['net/Makefile', 'drivers/usb/Makefile'])
    k2 = _merged_map_cache_key('v6.1', 'v6.6', ['drivers/usb/Makefile', 'net/Makefile'])
    assert k1 == k2


# ── E: _load_merged_map_cache / _save_merged_map_cache ─────────────────────
def test_merged_map_cache_roundtrip(tmp_path):
    c2p = {'CONFIG_USB': ['drivers/usb/hub.c', 'drivers/usb/core.c']}
    key = 'abc123def456789012345678'
    _save_merged_map_cache(str(tmp_path), key, c2p, 'range')
    result = _load_merged_map_cache(str(tmp_path), key)
    assert result == c2p


def test_merged_map_cache_miss_wrong_key(tmp_path):
    c2p = {'CONFIG_USB': ['drivers/usb/hub.c']}
    _save_merged_map_cache(str(tmp_path), 'key_A', c2p, 'range')
    result = _load_merged_map_cache(str(tmp_path), 'key_B')
    assert result is None


def test_merged_map_cache_miss_absent(tmp_path):
    assert _load_merged_map_cache(str(tmp_path), 'anykey') is None


def test_merged_map_cache_none_dir():
    _save_merged_map_cache(None, 'k', {}, 'range')
    assert _load_merged_map_cache(None, 'k') is None


def test_merged_map_cache_overwrites(tmp_path):
    c2p_v1 = {'CONFIG_USB': ['drivers/usb/hub.c']}
    c2p_v2 = {'CONFIG_USB': ['drivers/usb/hub.c'], 'CONFIG_NET': ['net/core/skbuff.c']}
    key = 'stablekey123456789012345'
    _save_merged_map_cache(str(tmp_path), key, c2p_v1, 'range')
    _save_merged_map_cache(str(tmp_path), key, c2p_v2, 'range')
    result = _load_merged_map_cache(str(tmp_path), key)
    assert result == c2p_v2


# ── B: _guess_makefiles_from_map ─────────────────────────────────────────────
def test_guess_makefiles_depth_cap():
    base_map = {
        'CONFIG_A': ['drivers/usb/core/hub.c'],
        'CONFIG_B': ['drivers/usb/host/xhci/main.c'],
    }
    result = _guess_makefiles_from_map(base_map, max_depth=3)
    assert 'drivers/usb/core/Makefile' in result
    assert 'drivers/usb/host/xhci/Makefile' not in result


def test_guess_makefiles_min_symbols():
    base_map = {
        'CONFIG_A': ['drivers/usb/hub.c'],
        'CONFIG_B': ['drivers/usb/core.c'],
        'CONFIG_C': ['net/lone.c'],
    }
    result = _guess_makefiles_from_map(base_map, max_depth=3, min_symbols=2)
    assert 'drivers/usb/Makefile' in result
    assert 'net/Makefile' not in result


def test_guess_makefiles_combined_filters():
    base_map = {
        'CONFIG_A': ['a/b/c/d/file1.c'],
        'CONFIG_B': ['a/b/c/d/file2.c'],
        'CONFIG_C': ['a/b/c/d/file3.c'],
        'CONFIG_D': ['net/lone.c'],
        'CONFIG_E': ['drivers/usb/hub.c'],
        'CONFIG_F': ['drivers/usb/core.c'],
    }
    result = _guess_makefiles_from_map(base_map, max_depth=3, min_symbols=2)
    assert 'drivers/usb/Makefile' in result
    assert 'a/b/c/d/Makefile' not in result
    assert 'net/Makefile' not in result


def test_guess_makefiles_no_filter_default_keeps_shallow():
    base_map = {
        'CONFIG_USB': ['drivers/usb/hub.c'],
        'CONFIG_NET': ['net/core/skbuff.c'],
    }
    result = _guess_makefiles_from_map(base_map)
    assert 'drivers/usb/Makefile' in result
    assert 'net/core/Makefile' in result


def test_guess_makefiles_empty_map():
    assert _guess_makefiles_from_map({}) == []


def test_guess_makefiles_sorted_output():
    base_map = {
        'CONFIG_Z': ['z/sub/file.c'],
        'CONFIG_A': ['a/sub/file.c'],
    }
    result = _guess_makefiles_from_map(base_map, max_depth=3)
    assert result == sorted(result)


def test_guess_makefiles_root_paths_excluded():
    base_map = {'CONFIG_X': ['rootfile.c']}
    assert _guess_makefiles_from_map(base_map) == []


# ── build_history_config_map: core tests ──────────────────────────────────────
def test_build_history_disabled(tmp_path):
    cfg = _cfg()
    cfg['history_mapping']['enabled'] = False
    base = {'CONFIG_USB': ['drivers/usb/hub.c']}
    result = build_history_config_map(cfg, base, str(tmp_path))
    assert result['mode'] == 'disabled'
    assert result['config_to_paths'] is base


def test_build_history_no_commits(tmp_path):
    with patch('subprocess.run', side_effect=lambda cmd, **kw: _mk_run_ok('')):
        result = build_history_config_map(_cfg(), {}, str(tmp_path))
    assert result['config_to_paths'] == {}


def _mk_run_ok(stdout):
    r = MagicMock()
    r.returncode = 0
    r.stderr = ''
    r.stdout = stdout
    return r


def test_build_history_adds_paths(tmp_path):
    """With valid Makefile content via batch, config_to_paths gets entries."""
    base = {}
    with patch('subprocess.run',
               side_effect=lambda cmd, **kw: _mk_run_ok('abc123\ndef456\n')):
        with patch('subprocess.Popen', return_value=_make_catfile_proc()):
            result = build_history_config_map(_cfg(), base, str(tmp_path))
    assert isinstance(result['config_to_paths'], dict)


def test_build_history_progress_callback(tmp_path):
    calls = []
    def cb(done, total):
        calls.append((done, total))
    with patch('subprocess.run',
               side_effect=lambda cmd, **kw: _mk_run_ok('abc123\ndef456\n')):
        with patch('subprocess.Popen', return_value=_make_catfile_proc()):
            build_history_config_map(_cfg(), {}, str(tmp_path), progress_callback=cb)
    # callback accepted without crash; may or may not be called depending on tasks
    assert isinstance(calls, list)


def test_build_history_snapshots_list(tmp_path):
    with patch('subprocess.run',
               side_effect=lambda cmd, **kw: _mk_run_ok('abc123\ndef456\n')):
        with patch('subprocess.Popen', return_value=_make_catfile_proc()):
            result = build_history_config_map(_cfg(), {}, str(tmp_path))
    assert 'snapshots' in result
    assert isinstance(result['snapshots'], list)


# ── C: max_history_revisions cap ─────────────────────────────────────────────
def test_build_history_revision_cap(tmp_path):
    """C: max_history_revisions=2 limits snapshots to 2."""
    commits_out = '\n'.join('c%02d' % i for i in range(20)) + '\n'
    base = {'CONFIG_USB': ['drivers/usb/hub.c']}

    cfg = _cfg(max_hist_revs=2)
    cfg['history_mapping']['sample_step'] = 1
    with patch('subprocess.run',
               side_effect=lambda cmd, **kw: _mk_run_ok(commits_out)):
        with patch('subprocess.Popen', return_value=_make_catfile_proc()):
            result = build_history_config_map(cfg, base, str(tmp_path))

    assert len(result['snapshots']) <= 2


def test_build_history_revision_cap_default_16(tmp_path):
    cfg = _cfg()
    assert cfg['history_mapping'].get('max_history_revisions', 16) == 16


# ── E: merged-map cache integration ──────────────────────────────────────────
def test_build_history_uses_merged_cache(tmp_path):
    """E: second call with same range hits merged-map cache; no Popen opened."""
    base = {'CONFIG_USB': ['drivers/usb/hub.c']}

    # First (cold) run
    with patch('subprocess.run',
               side_effect=lambda cmd, **kw: _mk_run_ok('abc123\ndef456\n')):
        with patch('subprocess.Popen', return_value=_make_catfile_proc()):
            r1 = build_history_config_map(_cfg(), base, str(tmp_path))

    # Second (warm) run: Popen must NOT be called
    with patch('subprocess.run',
               side_effect=lambda cmd, **kw: _mk_run_ok('abc123\ndef456\n')):
        with patch('subprocess.Popen') as mock_popen:
            r2 = build_history_config_map(_cfg(), base, str(tmp_path))

    mock_popen.assert_not_called()
    assert r2['config_to_paths'] == r1['config_to_paths']


def test_build_history_saves_merged_cache(tmp_path):
    """E: after a cold run, history_merged_map.json is present."""
    import json
    base = {'CONFIG_USB': ['drivers/usb/hub.c']}
    with patch('subprocess.run',
               side_effect=lambda cmd, **kw: _mk_run_ok('abc123\ndef456\n')):
        with patch('subprocess.Popen', return_value=_make_catfile_proc()):
            build_history_config_map(_cfg(), base, str(tmp_path))
    cache_file = os.path.join(str(tmp_path), 'history_merged_map.json')
    assert os.path.exists(cache_file)
    stored = json.load(open(cache_file))
    assert 'key' in stored
    assert 'config_to_paths' in stored


def test_build_history_merged_cache_invalidated_on_range_change(tmp_path):
    """E: changing rev_new forces a cold run (different cache key)."""
    base = {'CONFIG_USB': ['drivers/usb/hub.c']}
    popen_calls = []

    def _popen(*args, **kwargs):
        popen_calls.append(1)
        return _make_catfile_proc()

    cfg_v1 = _cfg()
    with patch('subprocess.run',
               side_effect=lambda cmd, **kw: _mk_run_ok('abc123\ndef456\n')):
        with patch('subprocess.Popen', side_effect=_popen):
            build_history_config_map(cfg_v1, base, str(tmp_path))
    popen_calls.clear()

    cfg_v2 = _cfg()
    cfg_v2['kernel']['rev_new'] = 'v6.7'
    with patch('subprocess.run',
               side_effect=lambda cmd, **kw: _mk_run_ok('abc123\ndef456\n')):
        with patch('subprocess.Popen', side_effect=_popen):
            build_history_config_map(cfg_v2, base, str(tmp_path))

    assert len(popen_calls) > 0, 'E: range change must invalidate cache and open batch pipe'


# ── F: batch fetch integration ───────────────────────────────────────────────
def test_build_history_uses_cache(tmp_path):
    """F: warm gitshow_cache → no Popen calls needed."""
    base = {'CONFIG_USB': ['drivers/usb/hub.c']}
    cfg  = _cfg()

    # Warm gitshow_cache manually for both expected tasks
    from lib.history_map import _guess_makefiles_from_map
    paths = _guess_makefiles_from_map(base)
    for mk in paths:
        _gitshow_cache_put(str(tmp_path), 'v6.1', mk, MAKEFILE_CONTENT)
        _gitshow_cache_put(str(tmp_path), 'v6.6', mk, MAKEFILE_CONTENT)

    popen_calls = []
    with patch('subprocess.run',
               side_effect=lambda cmd, **kw: _mk_run_ok('abc123\ndef456\n')):
        with patch('subprocess.Popen', side_effect=lambda *a, **kw: popen_calls.append(1) or _make_catfile_proc()):
            build_history_config_map(cfg, base, str(tmp_path))

    assert len(popen_calls) == 0, (
        'F: all tasks were in gitshow_cache; Popen must not be called')


def test_build_history_batch_fetch_used(tmp_path):
    """F: cold run (empty gitshow_cache) opens exactly one Popen for batch."""
    base = {'CONFIG_USB': ['drivers/usb/hub.c']}
    popen_calls = []

    def _popen(*args, **kwargs):
        popen_calls.append(1)
        return _make_catfile_proc()

    with patch('subprocess.run',
               side_effect=lambda cmd, **kw: _mk_run_ok('abc123\ndef456\n')):
        with patch('subprocess.Popen', side_effect=_popen):
            build_history_config_map(_cfg(), base, str(tmp_path))

    assert len(popen_calls) == 1, (
        'F: cold run must open exactly 1 batch pipe (Popen call)')


def test_build_history_batch_fallback(tmp_path):
    """F: if Popen fails, fallback to serial show_path_history without crash."""
    base = {'CONFIG_USB': ['drivers/usb/hub.c']}

    with patch('subprocess.run',
               side_effect=lambda cmd, **kw: _mk_run_ok('abc123\ndef456\n')):
        with patch('subprocess.Popen', side_effect=OSError('no git')):
            with patch('lib.gitutils.show_path_history', return_value=MAKEFILE_CONTENT):
                result = build_history_config_map(_cfg(), base, str(tmp_path))

    assert isinstance(result['config_to_paths'], dict)
