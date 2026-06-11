"""Tests for lib.kbuild — load_kernel_config_symbols, scan_kbuild_makefiles,
infer_touched_paths.

v13.0.3 (J):
  J  -- load_kernel_config_symbols() accepts arch and srctree keyword args.
        SRCARCH/ARCH/srctree are injected into the process environment via
        os.environ.setdefault before kconfiglib is invoked.  Tests added:
          test_load_symbols_sets_srcarch_env()
          test_load_symbols_sets_srctree_from_source_dir()
          test_load_symbols_explicit_srctree_takes_precedence()
          test_load_symbols_setdefault_does_not_overwrite_existing_env()
"""
import os

from lib.kbuild import (
    load_kernel_config_symbols,
    scan_kbuild_makefiles,
    infer_touched_paths,
)


# ── load_kernel_config_symbols ────────────────────────────────────────────────
def test_load_symbols_y_and_m(tmp_path):
    p = tmp_path / '.config'
    p.write_text('CONFIG_USB=y\nCONFIG_NET=m\nCONFIG_BT=n\n')
    syms = load_kernel_config_symbols(str(p))
    assert 'CONFIG_USB=y' in syms
    assert 'CONFIG_NET=m' in syms
    assert not any('CONFIG_BT' in s for s in syms)


def test_load_symbols_missing_file():
    syms = load_kernel_config_symbols('/no/such/file')
    assert syms == []


def test_load_symbols_none_path():
    syms = load_kernel_config_symbols(None)
    assert syms == []


def test_load_symbols_empty_file(tmp_path):
    p = tmp_path / '.config'
    p.write_text('')
    syms = load_kernel_config_symbols(str(p))
    assert syms == []


def test_load_symbols_no_source_dir_fallback(tmp_path):
    """Without source_dir, uses the lightweight line parser."""
    p = tmp_path / '.config'
    p.write_text('CONFIG_SOUND=y\n# CONFIG_MIDI is not set\n')
    syms = load_kernel_config_symbols(str(p), source_dir=None)
    assert 'CONFIG_SOUND=y' in syms


def test_load_symbols_nonexistent_source_dir(tmp_path):
    """source_dir does not exist — falls back to line parser."""
    p = tmp_path / '.config'
    p.write_text('CONFIG_USB=y\n')
    syms = load_kernel_config_symbols(str(p), source_dir='/no/such/dir')
    assert 'CONFIG_USB=y' in syms


# ── v13.0.3 (J): arch / srctree env var injection ────────────────────────────

def test_load_symbols_sets_srcarch_env(tmp_path, monkeypatch):
    """J: When arch is supplied and SRCARCH/ARCH are not in env,
    load_kernel_config_symbols() injects them via setdefault.
    """
    monkeypatch.delenv('SRCARCH', raising=False)
    monkeypatch.delenv('ARCH', raising=False)
    p = tmp_path / '.config'
    p.write_text('CONFIG_USB=y\n')
    # No real Kconfig tree → falls back to line parser, but env vars are set.
    load_kernel_config_symbols(str(p), source_dir=str(tmp_path), arch='arm')
    assert os.environ.get('SRCARCH') == 'arm'
    assert os.environ.get('ARCH') == 'arm'


def test_load_symbols_sets_srctree_from_source_dir(tmp_path, monkeypatch):
    """J: When srctree is not given, it defaults to source_dir."""
    monkeypatch.delenv('srctree', raising=False)
    p = tmp_path / '.config'
    p.write_text('CONFIG_USB=y\n')
    load_kernel_config_symbols(str(p), source_dir=str(tmp_path), arch='arm64')
    assert os.environ.get('srctree') == str(tmp_path)


def test_load_symbols_explicit_srctree_takes_precedence(tmp_path, monkeypatch):
    """J: When srctree is given explicitly, it is used instead of source_dir."""
    monkeypatch.delenv('srctree', raising=False)
    p = tmp_path / '.config'
    p.write_text('CONFIG_USB=y\n')
    explicit_srctree = str(tmp_path / 'explicit')
    load_kernel_config_symbols(
        str(p), source_dir=str(tmp_path), arch='arm', srctree=explicit_srctree)
    assert os.environ.get('srctree') == explicit_srctree


def test_load_symbols_setdefault_does_not_overwrite_existing_env(tmp_path, monkeypatch):
    """J: setdefault must not overwrite env vars already set by the build system."""
    monkeypatch.setenv('SRCARCH', 'x86')
    monkeypatch.setenv('ARCH', 'x86')
    p = tmp_path / '.config'
    p.write_text('CONFIG_USB=y\n')
    load_kernel_config_symbols(str(p), source_dir=str(tmp_path), arch='arm')
    # Existing values must be preserved — setdefault does not overwrite.
    assert os.environ.get('SRCARCH') == 'x86'
    assert os.environ.get('ARCH') == 'x86'


def test_load_symbols_no_arch_no_env_change(tmp_path, monkeypatch):
    """J: When arch is not supplied, no env vars are touched."""
    monkeypatch.delenv('SRCARCH', raising=False)
    monkeypatch.delenv('ARCH', raising=False)
    p = tmp_path / '.config'
    p.write_text('CONFIG_USB=y\n')
    load_kernel_config_symbols(str(p), source_dir=str(tmp_path))
    # No arch → no env change.
    assert 'SRCARCH' not in os.environ
    assert 'ARCH' not in os.environ


def test_load_symbols_arch_still_parses_correctly(tmp_path, monkeypatch):
    """J: env var injection does not break the fallback line parser result."""
    monkeypatch.delenv('SRCARCH', raising=False)
    monkeypatch.delenv('srctree', raising=False)
    p = tmp_path / '.config'
    p.write_text('CONFIG_ARM=y\nCONFIG_NET=m\n')
    syms = load_kernel_config_symbols(
        str(p), source_dir=str(tmp_path), arch='arm')
    assert 'CONFIG_ARM=y' in syms
    assert 'CONFIG_NET=m' in syms


# ── scan_kbuild_makefiles ─────────────────────────────────────────────────────
def test_scan_kbuild_makefiles_returns_list(tmp_path):
    d = tmp_path / 'drivers' / 'usb'
    d.mkdir(parents=True)
    (d / 'Makefile').write_text('obj-$(CONFIG_USB) += hub.o\n')
    result = scan_kbuild_makefiles(str(tmp_path))
    assert isinstance(result, list)
    assert any('Makefile' in p for p in result)


def test_scan_kbuild_makefiles_missing_dir():
    result = scan_kbuild_makefiles('/does/not/exist')
    assert result == []


# ── infer_touched_paths ───────────────────────────────────────────────────────
def test_infer_touched_paths_no_cfg():
    result = infer_touched_paths('usb: fix hub reset', cfg=None)
    assert result == []


def test_infer_touched_paths_no_hints_file(tmp_path):
    """If hints file does not exist, returns empty list."""
    cfg = {'paths': {'scoring_dir': str(tmp_path)}}
    result = infer_touched_paths('usb: fix hub reset', cfg=cfg)
    assert result == []


def test_infer_touched_paths_with_hints(tmp_path):
    """If hints file exists and keyword matches, returns paths."""
    import json
    hints = {'usb': ['drivers/usb/', 'include/linux/usb.h']}
    hf = tmp_path / 'subsystem_path_hints.json'
    hf.write_text(json.dumps(hints))
    cfg = {'paths': {'scoring_dir': str(tmp_path)}}
    result = infer_touched_paths('usb: fix hub timeout', cfg=cfg)
    assert 'drivers/usb/' in result


def test_infer_touched_paths_no_match(tmp_path):
    import json
    hints = {'bluetooth': ['net/bluetooth/']}
    hf = tmp_path / 'subsystem_path_hints.json'
    hf.write_text(json.dumps(hints))
    cfg = {'paths': {'scoring_dir': str(tmp_path)}}
    result = infer_touched_paths('mm: fix page fault', cfg=cfg)
    assert result == []


def test_infer_touched_paths_deduped(tmp_path):
    import json
    hints = {'usb': ['drivers/usb/', 'drivers/usb/']}
    hf = tmp_path / 'subsystem_path_hints.json'
    hf.write_text(json.dumps(hints))
    cfg = {'paths': {'scoring_dir': str(tmp_path)}}
    result = infer_touched_paths('usb: fix', cfg=cfg)
    assert result == sorted(set(result))
