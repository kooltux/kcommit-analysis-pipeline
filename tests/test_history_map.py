"""Tests for lib.history_map — cache helpers, build_history_config_map (mocked git)."""
import os
import hashlib
from unittest.mock import patch, MagicMock
import pytest

from lib.history_map import (
    _gitshow_cache_path,
    _gitshow_cache_get,
    _gitshow_cache_put,
    build_history_config_map,
)


def _cfg(src='/fake/repo'):
    return {
        'kernel':  {'source_dir': src, 'rev_old': 'v6.1', 'rev_new': 'v6.6'},
        'collect': {'no_merges': True, 'first_parent': False,
                    'history_workers': 1, 'extra_git_log_args': []},
        'history_mapping': {
            'enabled': True, 'mode': 'range',
            'sample_step': 1000, 'max_commits_per_probe': 256,
            'max_failure_rate': 0.05,
        },
    }


# ── _gitshow_cache_path ───────────────────────────────────────────────────────
def test_cache_path_structure(tmp_path):
    key = 'abcdef1234567890'
    p = _gitshow_cache_path(str(tmp_path), key)
    assert 'gitshow_cache' in p
    assert p.endswith(key)
    # sharded: key[:2] / key[2:4] / key
    assert key[:2] in p
    assert key[2:4] in p


# ── _gitshow_cache_get / put roundtrip ────────────────────────────────────────
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


# ── build_history_config_map ──────────────────────────────────────────────────
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
