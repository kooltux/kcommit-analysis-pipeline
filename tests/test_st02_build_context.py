"""Tests for lib.stages.st02_build_context — _read_lines, _scan_build_dir, run().

v13.0.3 (J):
  J  -- run() reads kernel.arch and kernel.srctree from config and passes
        them to load_kernel_config_symbols().  Tests added:
          test_run_arch_in_config_sets_env()
          test_run_srctree_in_config_sets_env()
          test_run_arch_printed_in_summary()
"""
import json, os
import pytest

from lib.stages.st02_build_context import (
    _read_lines, _scan_build_dir, run, _KBUILD_PLACEHOLDER_NAMES,
)
from lib.manifest import CACHE_FILES


# ── _read_lines ────────────────────────────────────────────────────────────
def test_read_lines_basic(tmp_path):
    p = tmp_path / 'build.log'
    p.write_text('line1\nline2\nline3\n')
    assert _read_lines(str(p)) == ['line1', 'line2', 'line3']


def test_read_lines_strips_trailing_newline(tmp_path):
    p = tmp_path / 'f.txt'
    p.write_text('hello\n')
    assert _read_lines(str(p)) == ['hello']


def test_read_lines_missing_file():
    assert _read_lines('/no/such/file.log') == []


def test_read_lines_none():
    assert _read_lines(None) == []


def test_read_lines_empty_file(tmp_path):
    p = tmp_path / 'empty.log'
    p.write_text('')
    assert _read_lines(str(p)) == []


# ── _scan_build_dir ───────────────────────────────────────────────────────────
def test_scan_build_dir_finds_objects(tmp_path):
    d = tmp_path / 'build' / 'drivers' / 'usb'
    d.mkdir(parents=True)
    (d / 'hub.o').write_text('')
    (d / 'xhci.ko').write_text('')
    result = _scan_build_dir(str(tmp_path / 'build'))
    assert any('hub.o' in p for p in result)
    assert any('xhci.ko' in p for p in result)


def test_scan_build_dir_ignores_non_objects(tmp_path):
    d = tmp_path / 'build'
    d.mkdir()
    (d / 'README').write_text('')
    (d / 'vmlinux').write_text('')
    result = _scan_build_dir(str(d))
    assert result == []


def test_scan_build_dir_missing():
    assert _scan_build_dir('/no/such/build') == []


def test_scan_build_dir_none():
    assert _scan_build_dir(None) == []


def test_scan_build_dir_sorted(tmp_path):
    d = tmp_path / 'build'
    d.mkdir()
    (d / 'z.o').write_text('')
    (d / 'a.o').write_text('')
    result = _scan_build_dir(str(d))
    assert result == sorted(result)


# ── A: built-in.o / built-in.a exclusion (kbuild placeholder aggregators) ────

def test_scan_build_dir_excludes_builtin_o(tmp_path):
    """built-in.o is a kbuild directory aggregator and must NOT appear in results."""
    d = tmp_path / 'build' / 'drivers' / 'gpu' / 'drm'
    d.mkdir(parents=True)
    (d / 'built-in.o').write_text('')
    (d / 'drm_drv.o').write_text('')
    result = _scan_build_dir(str(tmp_path / 'build'))
    names = [os.path.basename(p) for p in result]
    assert 'built-in.o' not in names, 'built-in.o must be excluded (kbuild placeholder)'
    assert 'drm_drv.o' in names, 'real object files must still be included'


def test_scan_build_dir_excludes_builtin_a(tmp_path):
    """built-in.a (newer kbuild format) is also a placeholder and must be excluded."""
    d = tmp_path / 'build' / 'net' / 'core'
    d.mkdir(parents=True)
    (d / 'built-in.a').write_text('')
    (d / 'skbuff.o').write_text('')
    result = _scan_build_dir(str(tmp_path / 'build'))
    names = [os.path.basename(p) for p in result]
    assert 'built-in.a' not in names
    assert 'skbuff.o' in names


def test_scan_build_dir_excludes_builtin_o_at_root(tmp_path):
    """Exclusion applies at every directory depth, including the build root."""
    bd = tmp_path / 'build'
    bd.mkdir()
    (bd / 'built-in.o').write_text('')
    (bd / 'init.o').write_text('')
    result = _scan_build_dir(str(bd))
    names = [os.path.basename(p) for p in result]
    assert 'built-in.o' not in names
    assert 'init.o' in names


def test_scan_build_dir_only_builtin_returns_empty(tmp_path):
    """A build dir containing only placeholder aggregators yields no artifacts."""
    d = tmp_path / 'build' / 'drivers' / 'usb'
    d.mkdir(parents=True)
    (d / 'built-in.o').write_text('')
    result = _scan_build_dir(str(tmp_path / 'build'))
    assert result == []


def test_kbuild_placeholder_names_constant_contains_expected():
    """_KBUILD_PLACEHOLDER_NAMES must cover both the .o and .a aggregator forms."""
    assert 'built-in.o' in _KBUILD_PLACEHOLDER_NAMES
    assert 'built-in.a' in _KBUILD_PLACEHOLDER_NAMES


# ── run() helpers ─────────────────────────────────────────────────────────────
def _make_cfg(tmp_path, kconfig=None, source_dir=None, build_dir=None,
             build_log=None, yocto_log=None, arch=None, srctree=None):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache, exist_ok=True)
    return cache, {
        'kernel': {
            'source_dir':        str(source_dir) if source_dir else None,
            'kernel_config':     str(kconfig)   if kconfig    else None,
            'build_dir':         str(build_dir) if build_dir  else None,
            'kernel_build_log':  str(build_log) if build_log  else None,
            'yocto_build_log':   str(yocto_log) if yocto_log  else None,
            'arch':              arch,
            'srctree':           srctree,
        }
    }


# ── run() basic tests ──────────────────────────────────────────────────────────
def test_run_minimal_no_paths(tmp_path):
    """run() with no kernel files produces a valid but empty build_context."""
    cache, cfg = _make_cfg(tmp_path)
    ctx, c2p = run(cfg, cache)
    assert isinstance(ctx, dict)
    assert 'kernel_config' in ctx
    assert 'build_artifacts' in ctx
    assert isinstance(c2p, dict)


def test_run_writes_build_context_json(tmp_path):
    cache, cfg = _make_cfg(tmp_path)
    run(cfg, cache)
    path = os.path.join(cache, CACHE_FILES['build_context'])
    assert os.path.exists(path)
    data = json.load(open(path))
    assert 'kernel_config' in data


def test_run_writes_kbuild_map_json(tmp_path):
    cache, cfg = _make_cfg(tmp_path)
    run(cfg, cache)
    path = os.path.join(cache, CACHE_FILES['kbuild_map'])
    assert os.path.exists(path)


def test_run_with_kconfig(tmp_path):
    kc = tmp_path / '.config'
    kc.write_text('CONFIG_USB=y\nCONFIG_NET=m\n')
    cache, cfg = _make_cfg(tmp_path, kconfig=kc)
    ctx, _ = run(cfg, cache)
    assert 'CONFIG_USB=y' in ctx['kernel_config']


def test_run_with_build_log(tmp_path):
    log = tmp_path / 'build.log'
    log.write_text('  CC drivers/usb/hub.o\n  LD vmlinux\n')
    cache, cfg = _make_cfg(tmp_path, build_log=log)
    ctx, _ = run(cfg, cache)
    assert len(ctx['kernel_build_log']) == 2


def test_run_with_yocto_log(tmp_path):
    log = tmp_path / 'yocto.log'
    log.write_text('NOTE: recipe: linux-yocto\n')
    cache, cfg = _make_cfg(tmp_path, yocto_log=log)
    ctx, _ = run(cfg, cache)
    assert 'NOTE: recipe: linux-yocto' in ctx['yocto_build_log']


def test_run_with_build_dir(tmp_path):
    bd = tmp_path / 'build'
    (bd / 'drivers').mkdir(parents=True)
    (bd / 'drivers' / 'hub.o').write_text('')
    cache, cfg = _make_cfg(tmp_path, build_dir=bd)
    ctx, _ = run(cfg, cache)
    assert any('hub.o' in p for p in ctx['build_artifacts'])


def test_run_nonexistent_kconfig_ignored(tmp_path):
    """A kconfig path that does not exist is silently ignored."""
    cache, cfg = _make_cfg(tmp_path, kconfig=tmp_path / 'missing.config')
    ctx, _ = run(cfg, cache)
    assert ctx['kernel_config'] == []


def test_run_with_kbuild_source_tree(tmp_path):
    src = tmp_path / 'linux'
    d = src / 'drivers' / 'usb'
    d.mkdir(parents=True)
    (d / 'Makefile').write_text('obj-$(CONFIG_USB) += hub.o\n')
    cache, cfg = _make_cfg(tmp_path, source_dir=src)
    ctx, c2p = run(cfg, cache)
    assert 'CONFIG_USB' in c2p
    assert len(ctx['kbuild_files']) == 1


def test_run_builtin_o_excluded_from_build_artifacts(tmp_path):
    """run() must not include built-in.o in build_artifacts in the cached context."""
    bd = tmp_path / 'build'
    drm = bd / 'drivers' / 'gpu' / 'drm'
    drm.mkdir(parents=True)
    (drm / 'built-in.o').write_text('')
    (drm / 'drm_drv.o').write_text('')
    cache, cfg = _make_cfg(tmp_path, build_dir=bd)
    ctx, _ = run(cfg, cache)
    basenames = [os.path.basename(p) for p in ctx['build_artifacts']]
    assert 'built-in.o' not in basenames
    assert 'drm_drv.o' in basenames
    # Verify the JSON on disk is also clean
    data = json.load(open(os.path.join(cache, CACHE_FILES['build_context'])))
    disk_basenames = [os.path.basename(p) for p in data['build_artifacts']]
    assert 'built-in.o' not in disk_basenames


# ── v13.0.3 (J): arch / srctree propagation from config to env ────────────────

def test_run_arch_in_config_sets_env(tmp_path, monkeypatch):
    """J: kernel.arch in config → SRCARCH/ARCH set in env before kconfiglib call."""
    monkeypatch.delenv('SRCARCH', raising=False)
    monkeypatch.delenv('ARCH', raising=False)
    kc = tmp_path / '.config'
    kc.write_text('CONFIG_ARM=y\n')
    cache, cfg = _make_cfg(tmp_path, kconfig=kc, arch='arm')
    run(cfg, cache)
    assert os.environ.get('SRCARCH') == 'arm'
    assert os.environ.get('ARCH') == 'arm'


def test_run_srctree_in_config_sets_env(tmp_path, monkeypatch):
    """J: kernel.srctree in config → srctree env var set."""
    monkeypatch.delenv('srctree', raising=False)
    kc = tmp_path / '.config'
    kc.write_text('CONFIG_USB=y\n')
    explicit = str(tmp_path / 'my_srctree')
    cache, cfg = _make_cfg(tmp_path, kconfig=kc, arch='arm64', srctree=explicit)
    run(cfg, cache)
    assert os.environ.get('srctree') == explicit


def test_run_arch_not_set_no_env_change(tmp_path, monkeypatch):
    """J: When kernel.arch is absent, SRCARCH/ARCH are not injected."""
    monkeypatch.delenv('SRCARCH', raising=False)
    monkeypatch.delenv('ARCH', raising=False)
    kc = tmp_path / '.config'
    kc.write_text('CONFIG_USB=y\n')
    cache, cfg = _make_cfg(tmp_path, kconfig=kc)  # no arch
    run(cfg, cache)
    assert 'SRCARCH' not in os.environ
    assert 'ARCH' not in os.environ


def test_run_arch_printed_in_summary(tmp_path, capsys):
    """J: run() prints the arch value in the build context summary."""
    kc = tmp_path / '.config'
    kc.write_text('CONFIG_USB=y\n')
    cache, cfg = _make_cfg(tmp_path, kconfig=kc, arch='arm')
    run(cfg, cache)
    captured = capsys.readouterr()
    assert 'arm' in captured.out


def test_run_no_arch_prints_hint(tmp_path, capsys):
    """J: When arch is not set, summary line mentions the hint to set it."""
    cache, cfg = _make_cfg(tmp_path)
    run(cfg, cache)
    captured = capsys.readouterr()
    assert 'kernel.arch' in captured.out
