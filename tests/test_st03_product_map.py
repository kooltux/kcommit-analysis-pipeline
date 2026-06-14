"""Tests for lib.stages.st03_product_map.

Covers _derive_config_dirs, _extract_log_objects, _filter_to_enabled, run().

v13.0.1 changes:
  -- Added tests for _filter_to_enabled() (new function, Bug-1 fix).
  -- run() tests now assert config_enabled_map and config_enabled_dirs are
     present in product_map and contain only enabled symbols.
  -- test_run_config_dirs_derived updated to check config_enabled_dirs.
  -- Added test_run_disabled_symbol_excluded_from_enabled_map() as the
     primary regression test for Bug-1 (BTRFS-style scenario).
  -- _build_context(): changed `kernel_config or [default]` to
     `kernel_config if kernel_config is not None else [default]` so that
     an explicit empty list [] is preserved rather than silently replaced
     by the default ([] is falsy but semantically distinct from None).
  -- _setup(): when kbuild_map=None, explicitly removes any pre-existing
     kbuild_map.json from the cache dir so that "no kbuild map" is
     guaranteed even if tmp_path reuse or name collision left a stale file.

v16.3.0 (H.2 -- full-path stems for build-log objects):
  -- _extract_log_objects() now returns full-path stems (directory stripped
     of extension) instead of raw tokens with extension.  Bare-filename
     tokens (no directory) continue to be returned as-is including extension.
  -- Updated tests to assert on full-path stem form:
       test_extract_log_objects_basic
       test_extract_log_objects_ko
       test_extract_log_objects_excludes_builtin_o
       test_extract_log_objects_excludes_builtin_a
       test_extract_log_objects_builtin_mixed_with_real
       test_run_extracts_log_objects
       test_run_builtin_o_excluded_from_log_objects
       test_run_builtin_a_excluded_from_log_objects
"""
import json, os
from unittest.mock import patch
import pytest

from lib.stages.st03_product_map import (
    _derive_config_dirs, _extract_log_objects, _filter_to_enabled, run,
)
from lib.manifest import CACHE_FILES


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f)


# -- _derive_config_dirs -------------------------------------------------------

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


# -- _extract_log_objects ------------------------------------------------------
# H.2 (v16.3.0): _extract_log_objects() returns full-path stems for entries
# that have a directory component (extension stripped), and raw tokens for
# bare-filename entries.  Tests updated accordingly.

def test_extract_log_objects_basic():
    """H.2: full-path .o -> stem 'drivers/net/core' (no extension)."""
    lines = ['  CC      drivers/net/core.o', '  LD      vmlinux']
    objs = _extract_log_objects(lines)
    assert any('drivers/net/core' in o for o in objs)


def test_extract_log_objects_ko():
    """H.2: full-path .ko -> stem 'drivers/usb/host/xhci-hcd' (no extension)."""
    lines = ['  LD      drivers/usb/host/xhci-hcd.ko']
    objs = _extract_log_objects(lines)
    assert any('drivers/usb/host/xhci-hcd' in o for o in objs)


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


def test_extract_log_objects_excludes_builtin_o():
    """H.2: built-in.o excluded; drm_drv.o -> stem 'drivers/gpu/drm/drm_drv'."""
    lines = [
        '  LD      drivers/gpu/drm/built-in.o',
        '  CC      drivers/gpu/drm/drm_drv.o',
    ]
    objs = _extract_log_objects(lines)
    assert not any('built-in' in o for o in objs)
    assert 'drivers/gpu/drm/drm_drv' in objs


def test_extract_log_objects_excludes_builtin_a():
    """H.2: built-in.a excluded; skbuff.o -> stem 'net/core/skbuff'."""
    lines = [
        '  AR      net/core/built-in.a',
        '  CC      net/core/skbuff.o',
    ]
    objs = _extract_log_objects(lines)
    assert not any('built-in' in o for o in objs)
    assert 'net/core/skbuff' in objs


def test_extract_log_objects_builtin_only_returns_empty():
    lines = [
        '  LD      drivers/built-in.o',
        '  AR      net/built-in.a',
    ]
    assert _extract_log_objects(lines) == []


def test_extract_log_objects_builtin_mixed_with_real():
    """H.2: full-path stems returned for real objects, built-ins excluded."""
    lines = [
        '  LD      drivers/gpu/built-in.o',
        '  CC      drivers/gpu/drm/drm_mode.o',
        '  AR      drivers/net/built-in.a',
        '  CC      drivers/net/core/skbuff.o',
    ]
    objs = _extract_log_objects(lines)
    assert not any('built-in' in o for o in objs)
    assert 'drivers/gpu/drm/drm_mode' in objs
    assert 'drivers/net/core/skbuff' in objs


# -- _filter_to_enabled (v13.0.1 Bug-1) ----------------------------------------

def test_filter_to_enabled_keeps_y_and_m():
    """Symbols enabled with =y or =m are kept; all others are excluded."""
    c2p = {
        'CONFIG_USB':   ['drivers/usb/core.c'],
        'CONFIG_VLAN':  ['net/8021q/vlan.c'],
        'CONFIG_BTRFS': ['fs/btrfs/btrfs.c'],   # disabled
    }
    raw = ['CONFIG_USB=y', 'CONFIG_VLAN=m']      # CONFIG_BTRFS not listed
    result = _filter_to_enabled(c2p, raw)
    assert 'CONFIG_USB' in result
    assert 'CONFIG_VLAN' in result
    assert 'CONFIG_BTRFS' not in result


def test_filter_to_enabled_excludes_n():
    """=n is not a valid enabled value."""
    c2p = {'CONFIG_USB': ['drivers/usb/core.c']}
    raw = ['CONFIG_USB=n']
    result = _filter_to_enabled(c2p, raw)
    assert 'CONFIG_USB' not in result


def test_filter_to_enabled_excludes_string_values():
    """String-valued symbols (CONFIG_CMDLINE=\"...\") are not enabled object code."""
    c2p = {'CONFIG_CMDLINE': ['init/main.c']}
    raw = ['CONFIG_CMDLINE="console=ttyMSM0"']
    result = _filter_to_enabled(c2p, raw)
    assert 'CONFIG_CMDLINE' not in result


def test_filter_to_enabled_excludes_bare_symbol():
    """Bare symbol without '=' is ignored."""
    c2p = {'CONFIG_USB': ['drivers/usb/core.c']}
    raw = ['CONFIG_USB']
    result = _filter_to_enabled(c2p, raw)
    assert 'CONFIG_USB' not in result


def test_filter_to_enabled_empty_inputs():
    assert _filter_to_enabled({}, []) == {}
    assert _filter_to_enabled({}, ['CONFIG_USB=y']) == {}
    assert _filter_to_enabled({'CONFIG_USB': ['drivers/usb/core.c']}, []) == {}


def test_filter_to_enabled_preserves_paths():
    """Source paths in enabled symbols are preserved exactly."""
    c2p = {'CONFIG_USB': ['drivers/usb/core.c', 'drivers/usb/hub.c']}
    raw = ['CONFIG_USB=y']
    result = _filter_to_enabled(c2p, raw)
    assert result['CONFIG_USB'] == ['drivers/usb/core.c', 'drivers/usb/hub.c']


def test_filter_to_enabled_symbol_in_raw_but_not_in_map():
    """Symbols enabled in .config but absent from Kbuild map are silently ignored."""
    c2p = {'CONFIG_USB': ['drivers/usb/core.c']}
    raw = ['CONFIG_USB=y', 'CONFIG_NONEXISTENT=y']
    result = _filter_to_enabled(c2p, raw)
    assert 'CONFIG_NONEXISTENT' not in result
    assert 'CONFIG_USB' in result


# -- run() helpers -------------------------------------------------------------

def _build_context(kernel_config=None, build_log=None, artifacts=None,
                   kbuild_files=None):
    """Build a minimal build_context dict for run() tests.

    Uses `is not None` checks instead of `or` so that an explicit empty list
    (e.g. kernel_config=[]) is preserved rather than silently replaced by the
    default value.  An empty list is semantically meaningful: it means
    "no symbols enabled", which is distinct from "caller did not specify".
    """
    return {
        'kernel_config':        kernel_config if kernel_config is not None else ['CONFIG_USB=y'],
        'kernel_config_parsed': {'enabled': {'CONFIG_USB': 'y'}, 'disabled': []},
        'kernel_build_log':     build_log if build_log is not None else ['  CC drivers/usb/hub.o'],
        'yocto_build_log':      [],
        'build_artifacts':      artifacts if artifacts is not None else ['drivers/usb/hub.o'],
        'kbuild_files':         kbuild_files if kbuild_files is not None else [],
        'dts_roots':            [],
        'build_dir':            None,
    }


def _setup(tmp_path, ctx=None, kbuild_map=None, source_dir=None):
    """Set up a temporary cache directory for a run() test.

    When kbuild_map=None (caller wants no pre-existing kbuild map), any
    kbuild_map.json that may already exist in the cache dir is explicitly
    removed.  This guards against stale files left by tmp_path name-collision
    or pytest worker reuse producing a false 'reusing kbuild_map' code path.
    """
    cache = str(tmp_path / 'cache')
    os.makedirs(cache, exist_ok=True)
    _write(os.path.join(cache, CACHE_FILES['build_context']),
           ctx or _build_context())
    if kbuild_map is not None:
        _write(os.path.join(cache, CACHE_FILES['kbuild_map']), kbuild_map)
    else:
        # Ensure no stale kbuild_map.json misleads run() into the
        # 'reusing kbuild_map from stage 02' branch.
        stale = os.path.join(cache, CACHE_FILES['kbuild_map'])
        if os.path.exists(stale):
            os.remove(stale)
    cfg = {
        'kernel': {'source_dir': str(source_dir) if source_dir else None,
                   'rev_old': 'v6.1', 'rev_new': 'v6.6'},
        'paths': {'work_dir': str(tmp_path), 'cache_dir': cache},
        'collect': {},
        'history_mapping': {'enabled': False},
    }
    return cache, cfg


# -- run() tests ---------------------------------------------------------------

def test_run_writes_product_map(tmp_path):
    cache, cfg = _setup(tmp_path)
    run(cfg, cache)
    path = os.path.join(cache, CACHE_FILES['product_map'])
    assert os.path.exists(path)
    data = json.load(open(path))
    assert 'config_to_paths' in data
    assert 'enabled_configs' in data
    # v13.0.1: new fields must be present
    assert 'config_enabled_map' in data
    assert 'config_enabled_dirs' in data


def test_run_uses_kbuild_map_cache(tmp_path):
    c2p = {'CONFIG_USB': ['drivers/usb/hub.c']}
    cache, cfg = _setup(tmp_path, kbuild_map=c2p)
    pm = run(cfg, cache)
    assert 'CONFIG_USB' in pm['config_to_paths']


def test_run_no_kbuild_map_no_source_dir(tmp_path):
    """Without kbuild_map and without source_dir, config_to_paths is empty."""
    cache, cfg = _setup(tmp_path)
    pm = run(cfg, cache)
    assert pm['config_to_paths'] == {}


def test_run_extracts_log_objects(tmp_path):
    """H.2 (v16.3.0): built_objects_from_log contains full-path stems."""
    ctx = _build_context(build_log=['  CC drivers/net/core.o'])
    cache, cfg = _setup(tmp_path, ctx=ctx)
    pm = run(cfg, cache)
    assert any('drivers/net/core' in o for o in pm['built_objects_from_log'])


def test_run_enabled_configs(tmp_path):
    ctx = _build_context(kernel_config=['CONFIG_USB=y', 'CONFIG_NET=m'])
    cache, cfg = _setup(tmp_path, ctx=ctx)
    pm = run(cfg, cache)
    assert 'CONFIG_USB=y' in pm['enabled_configs']


def test_run_config_dirs_derived(tmp_path):
    """config_dirs is still derived from the full config_to_paths (all symbols)."""
    c2p = {'CONFIG_USB': ['drivers/usb/hub.c']}
    cache, cfg = _setup(tmp_path, kbuild_map=c2p)
    pm = run(cfg, cache)
    assert 'drivers/usb/' in pm['config_dirs']


def test_run_config_enabled_dirs_derived(tmp_path):
    """config_enabled_dirs is derived from config_enabled_map (enabled symbols only)."""
    c2p = {
        'CONFIG_USB':   ['drivers/usb/hub.c'],
        'CONFIG_BTRFS': ['fs/btrfs/btrfs.c'],   # disabled
    }
    ctx = _build_context(kernel_config=['CONFIG_USB=y'])   # CONFIG_BTRFS not enabled
    cache, cfg = _setup(tmp_path, ctx=ctx, kbuild_map=c2p)
    pm = run(cfg, cache)
    assert 'drivers/usb/' in pm['config_enabled_dirs']
    assert not any('btrfs' in d for d in pm['config_enabled_dirs'])


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


def test_run_builtin_o_excluded_from_log_objects(tmp_path):
    """H.2 (v16.3.0): built-in.o excluded; drm_drv.o -> stem 'drivers/gpu/drm/drm_drv'."""
    ctx = _build_context(build_log=[
        '  LD      drivers/gpu/drm/built-in.o',
        '  CC      drivers/gpu/drm/drm_drv.o',
    ])
    cache, cfg = _setup(tmp_path, ctx=ctx)
    pm = run(cfg, cache)
    assert not any('built-in' in o for o in pm['built_objects_from_log'])
    assert 'drivers/gpu/drm/drm_drv' in pm['built_objects_from_log']


def test_run_builtin_a_excluded_from_log_objects(tmp_path):
    """H.2 (v16.3.0): built-in.a excluded; skbuff.o -> stem 'net/core/skbuff'."""
    ctx = _build_context(build_log=[
        '  AR      net/core/built-in.a',
        '  CC      net/core/skbuff.o',
    ])
    cache, cfg = _setup(tmp_path, ctx=ctx)
    pm = run(cfg, cache)
    assert not any('built-in' in o for o in pm['built_objects_from_log'])
    assert 'net/core/skbuff' in pm['built_objects_from_log']


# -- Bug-1 regression: disabled symbol excluded from config_enabled_map --------

def test_run_disabled_symbol_excluded_from_enabled_map(tmp_path):
    """Bug-1 regression (v13.0.1): CONFIG_BTRFS_FS is in the Kbuild tree
    (config_to_paths) but disabled in .config.  It must not appear in
    config_enabled_map, so st04 build_compiled_sets() will not include
    fs/btrfs/ in compiled_dirs, and commits touching only fs/btrfs/
    will be dropped with no_kconfig_coverage.
    """
    c2p = {
        'CONFIG_USB':      ['drivers/usb/hub.c'],
        'CONFIG_BTRFS_FS': ['fs/btrfs/btrfs.c'],   # in Kbuild tree but disabled
    }
    ctx = _build_context(kernel_config=['CONFIG_USB=y'])   # CONFIG_BTRFS_FS absent
    cache, cfg = _setup(tmp_path, ctx=ctx, kbuild_map=c2p)
    pm = run(cfg, cache)

    # Full Kbuild map still contains both symbols (for diagnostics)
    assert 'CONFIG_BTRFS_FS' in pm['config_to_paths']

    # Enabled map must only contain CONFIG_USB
    assert 'CONFIG_BTRFS_FS' not in pm['config_enabled_map'], (
        'CONFIG_BTRFS_FS is disabled in .config and must not appear in '
        'config_enabled_map; got keys: %r' % list(pm['config_enabled_map'].keys())
    )
    assert 'CONFIG_USB' in pm['config_enabled_map']

    # config_enabled_dirs must not include fs/btrfs/
    assert not any('btrfs' in d for d in pm['config_enabled_dirs']), (
        'fs/btrfs/ must not appear in config_enabled_dirs; '
        'got: %r' % pm['config_enabled_dirs']
    )
    assert 'drivers/usb/' in pm['config_enabled_dirs']


def test_run_config_enabled_map_empty_when_no_kbuild_data(tmp_path):
    """When config_to_paths is empty, config_enabled_map is also empty."""
    ctx = _build_context(kernel_config=['CONFIG_USB=y'])
    cache, cfg = _setup(tmp_path, ctx=ctx)   # no kbuild_map: _setup removes stale file
    pm = run(cfg, cache)
    assert pm['config_enabled_map'] == {}
    assert pm['config_enabled_dirs'] == []


def test_run_config_enabled_map_empty_when_no_enabled_configs(tmp_path):
    """When enabled_configs is empty, config_enabled_map is empty.

    Uses kernel_config=[] (explicit empty list, not None) to simulate a
    .config file that is present but has no enabled symbols.  The _build_context()
    helper preserves [] explicitly (is-not-None check) to avoid the old
    `[] or default` pitfall.
    """
    c2p = {'CONFIG_USB': ['drivers/usb/hub.c']}
    ctx = _build_context(kernel_config=[])   # explicit empty: no symbols enabled
    cache, cfg = _setup(tmp_path, ctx=ctx, kbuild_map=c2p)
    pm = run(cfg, cache)
    assert pm['config_enabled_map'] == {}
