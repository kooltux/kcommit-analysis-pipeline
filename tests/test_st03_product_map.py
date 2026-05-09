"""Tests for lib.stages.st03_product_map — _derive_config_dirs,
_extract_log_objects, run() (with mocked history_map)."""
import json, os
from unittest.mock import patch
import pytest

from lib.stages.st03_product_map import _derive_config_dirs, _extract_log_objects, run
from lib.manifest import CACHE_FILES


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f)


# ── _derive_config_dirs ───────────────────────────────────────────────────────
def test_derive_config_dirs_basic():
    c2p = {'CONFIG_USB': ['drivers/usb/hub.c', 'drivers/usb/core.c']}
    dirs = _derive_config_dirs(c2p)
    assert 'drivers/usb/' in dirs


def test_derive_config_dirs_nested():
    c2p = {'CONFIG_NET': ['net/core/skbuff.c', 'net/ipv4/tcp.c']}
    dirs = _derive_config_dirs(c2p)
    assert any('net/' in d for d in dirs)


def test_derive_config_dirs_empty():
    assert _derive_config_dirs({}) == []


def test_derive_config_dirs_none():
    assert _derive_config_dirs(None) == []


def test_derive_config_dirs_sorted():
    c2p = {'CONFIG_Z': ['z/file.c'], 'CONFIG_A': ['a/file.c']}
    dirs = _derive_config_dirs(c2p)
    assert dirs == sorted(dirs)


def test_derive_config_dirs_no_dirname():
    """Paths with no directory component should be skipped."""
    c2p = {'CONFIG_X': ['rootfile.c']}
    dirs = _derive_config_dirs(c2p)
    assert dirs == []


# ── _extract_log_objects ──────────────────────────────────────────────────────
def test_extract_log_objects_basic():
    lines = ['  CC      drivers/net/core.o', '  LD      vmlinux']
    objs = _extract_log_objects(lines)
    assert any('core.o' in o for o in objs)


def test_extract_log_objects_ko():
    lines = ['  LD      drivers/usb/host/xhci-hcd.ko']
    objs = _extract_log_objects(lines)
    assert any('xhci-hcd.ko' in o for o in objs)


def test_extract_log_objects_none():
    assert _extract_log_objects(None) == []


def test_extract_log_objects_empty():
    assert _extract_log_objects([]) == []


def test_extract_log_objects_no_objects():
    lines = ['NOTE: recipe: linux-yocto', 'NOTE: starting bitbake']
    assert _extract_log_objects(lines) == []


def test_extract_log_objects_sorted():
    lines = ['z.o hub.o', 'a.ko']
    objs = _extract_log_objects(lines)
    assert objs == sorted(objs)


# ── run() ─────────────────────────────────────────────────────────────────────
def _build_context(kernel_config=None, build_log=None, artifacts=None,
                   kbuild_files=None):
    return {
        'kernel_config':        kernel_config or ['CONFIG_USB=y'],
        'kernel_config_parsed': {'enabled': {'CONFIG_USB': 'y'}, 'disabled': []},
        'kernel_build_log':     build_log or ['  CC drivers/usb/hub.o'],
        'yocto_build_log':      [],
        'build_artifacts':      artifacts or ['drivers/usb/hub.o'],
        'kbuild_files':         kbuild_files or [],
        'dts_roots':            [],
        'build_dir':            None,
    }


def _setup(tmp_path, ctx=None, kbuild_map=None, source_dir=None):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    _write(os.path.join(cache, CACHE_FILES['build_context']),
           ctx or _build_context())
    if kbuild_map is not None:
        _write(os.path.join(cache, CACHE_FILES['kbuild_map']), kbuild_map)
    cfg = {
        'kernel': {'source_dir': str(source_dir) if source_dir else None,
                   'rev_old': 'v6.1', 'rev_new': 'v6.6'},
        'paths': {'work_dir': str(tmp_path), 'cache_dir': cache},
        'collect': {},
        'history_mapping': {'enabled': False},
    }
    return cache, cfg


def test_run_writes_product_map(tmp_path):
    cache, cfg = _setup(tmp_path)
    run(cfg, cache)
    path = os.path.join(cache, CACHE_FILES['product_map'])
    assert os.path.exists(path)
    data = json.load(open(path))
    assert 'config_to_paths' in data
    assert 'enabled_configs' in data


def test_run_uses_kbuild_map_cache(tmp_path):
    c2p = {'CONFIG_USB': ['drivers/usb/hub.c']}
    cache, cfg = _setup(tmp_path, kbuild_map=c2p)
    pm = run(cfg, cache)
    assert 'CONFIG_USB' in pm['config_to_paths']


def test_run_no_kbuild_map_no_source_dir(tmp_path):
    """Without kbuild_map and without source_dir, config_to_paths is empty."""
    cache, cfg = _setup(tmp_path)  # no kbuild_map file written
    pm = run(cfg, cache)
    assert pm['config_to_paths'] == {}


def test_run_extracts_log_objects(tmp_path):
    ctx = _build_context(build_log=['  CC drivers/net/core.o'])
    cache, cfg = _setup(tmp_path, ctx=ctx)
    pm = run(cfg, cache)
    assert any('core.o' in o for o in pm['built_objects_from_log'])


def test_run_enabled_configs(tmp_path):
    ctx = _build_context(kernel_config=['CONFIG_USB=y', 'CONFIG_NET=m'])
    cache, cfg = _setup(tmp_path, ctx=ctx)
    pm = run(cfg, cache)
    assert 'CONFIG_USB=y' in pm['enabled_configs']


def test_run_config_dirs_derived(tmp_path):
    c2p = {'CONFIG_USB': ['drivers/usb/hub.c']}
    cache, cfg = _setup(tmp_path, kbuild_map=c2p)
    pm = run(cfg, cache)
    assert 'drivers/usb/' in pm['config_dirs']


def test_run_history_disabled(tmp_path):
    """When history_mapping.enabled=False, product_map has no history_info."""
    cache, cfg = _setup(tmp_path)
    pm = run(cfg, cache)
    assert 'history_info' not in pm


def test_run_history_map_error_graceful(tmp_path, monkeypatch):
    """A RuntimeError from build_history_config_map is caught gracefully."""
    c2p = {'CONFIG_USB': ['drivers/usb/hub.c']}
    src = tmp_path / 'linux'
    src.mkdir()
    cache, cfg = _setup(tmp_path, kbuild_map=c2p, source_dir=src)
    cfg['history_mapping'] = {'enabled': True}

    with patch('lib.stages.st03_product_map.build_history_config_map',
               side_effect=RuntimeError('git not available')):
        pm = run(cfg, cache)
    assert pm['history_info']['mode'] == 'error'
