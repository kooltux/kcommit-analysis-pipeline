"""Tests for lib.stages.st02_build_context — _read_lines, _scan_build_dir, run()."""
import json, os
import pytest

from lib.stages.st02_build_context import _read_lines, _scan_build_dir, run
from lib.manifest import CACHE_FILES


# ── _read_lines ───────────────────────────────────────────────────────────────
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


# ── run() ─────────────────────────────────────────────────────────────────────
def _make_cfg(tmp_path, kconfig=None, source_dir=None, build_dir=None,
              build_log=None, yocto_log=None):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache, exist_ok=True)
    return cache, {
        'kernel': {
            'source_dir':        str(source_dir) if source_dir else None,
            'kernel_config':     str(kconfig)   if kconfig    else None,
            'build_dir':         str(build_dir) if build_dir  else None,
            'kernel_build_log':  str(build_log) if build_log  else None,
            'yocto_build_log':   str(yocto_log) if yocto_log  else None,
        }
    }


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
