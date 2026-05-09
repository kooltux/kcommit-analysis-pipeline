"""Tests for lib.parse_kconfig — parse_kernel_config, scan_kbuild_tree."""
import os

from lib.parse_kconfig import (
    parse_kernel_config,
    scan_kbuild_tree,
    scan_makefile_config_map,
    scan_kbuild_makefiles_list,
)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)


# ── parse_kernel_config ───────────────────────────────────────────────────────
def test_parse_enabled_y(tmp_path):
    p = tmp_path / '.config'
    p.write_text('CONFIG_USB=y\nCONFIG_NET=m\n')
    r = parse_kernel_config(str(p))
    assert r['enabled']['CONFIG_USB'] == 'y'
    assert r['enabled']['CONFIG_NET'] == 'm'


def test_parse_not_set(tmp_path):
    p = tmp_path / '.config'
    p.write_text('# CONFIG_BLUETOOTH is not set\n')
    r = parse_kernel_config(str(p))
    assert 'CONFIG_BLUETOOTH' in r['disabled']
    assert 'CONFIG_BLUETOOTH' not in r['enabled']


def test_parse_comments_ignored(tmp_path):
    p = tmp_path / '.config'
    p.write_text('# This is a comment\nCONFIG_USB=y\n')
    r = parse_kernel_config(str(p))
    assert 'CONFIG_USB' in r['enabled']


def test_parse_arbitrary_value(tmp_path):
    p = tmp_path / '.config'
    p.write_text('CONFIG_LOG_BUF_SHIFT=17\n')
    r = parse_kernel_config(str(p))
    assert r['enabled']['CONFIG_LOG_BUF_SHIFT'] == '17'


def test_parse_empty_file(tmp_path):
    p = tmp_path / '.config'
    p.write_text('')
    r = parse_kernel_config(str(p))
    assert r['enabled'] == {}
    assert r['disabled'] == []


def test_parse_missing_file():
    r = parse_kernel_config('/does/not/exist/.config')
    assert r['enabled'] == {}
    assert r['disabled'] == []


def test_parse_none_path():
    r = parse_kernel_config(None)
    assert r['enabled'] == {}


def test_parse_disabled_sorted(tmp_path):
    p = tmp_path / '.config'
    p.write_text('# CONFIG_Z is not set\n# CONFIG_A is not set\n')
    r = parse_kernel_config(str(p))
    assert r['disabled'] == sorted(r['disabled'])


# ── scan_kbuild_tree ──────────────────────────────────────────────────────────
def _make_kernel_tree(root):
    """Create a minimal fake kernel source tree with Makefiles."""
    usb = root / 'drivers' / 'usb' / 'core'
    usb.mkdir(parents=True)
    (usb / 'Makefile').write_text(
        'obj-$(CONFIG_USB) += hub.o urb.o\n'
        'obj-$(CONFIG_USB_XHCI_HCD) += xhci.o\n'
    )
    net = root / 'drivers' / 'net'
    net.mkdir(parents=True)
    (net / 'Makefile').write_text('obj-$(CONFIG_NET) += core.o\n')
    # Non-Makefile file — should be ignored
    (root / 'drivers' / 'README').write_text('ignore me')
    return root


def test_scan_kbuild_tree_finds_makefiles(tmp_path):
    _make_kernel_tree(tmp_path)
    _, kbuild = scan_kbuild_tree(str(tmp_path))
    names = [os.path.basename(p) for p in kbuild]
    assert names.count('Makefile') == 2


def test_scan_kbuild_tree_config_to_paths(tmp_path):
    _make_kernel_tree(tmp_path)
    c2p, _ = scan_kbuild_tree(str(tmp_path))
    assert 'CONFIG_USB' in c2p
    paths = c2p['CONFIG_USB']
    assert any('hub.c' in p for p in paths)
    assert any('urb.c' in p for p in paths)


def test_scan_kbuild_tree_missing_dir():
    c2p, kbuild = scan_kbuild_tree('/does/not/exist')
    assert c2p == {}
    assert kbuild == []


def test_scan_kbuild_tree_none_dir():
    c2p, kbuild = scan_kbuild_tree(None)
    assert c2p == {}
    assert kbuild == []


def test_scan_kbuild_tree_multiple_objects(tmp_path):
    d = tmp_path / 'sound' / 'core'
    d.mkdir(parents=True)
    (d / 'Makefile').write_text('obj-$(CONFIG_SOUND) += pcm.o init.o info.o\n')
    c2p, _ = scan_kbuild_tree(str(tmp_path))
    assert len(c2p['CONFIG_SOUND']) == 3


def test_scan_makefile_config_map_wrapper(tmp_path):
    _make_kernel_tree(tmp_path)
    result = scan_makefile_config_map(str(tmp_path))
    assert isinstance(result, dict)
    assert 'CONFIG_USB' in result


def test_scan_kbuild_makefiles_list_wrapper(tmp_path):
    _make_kernel_tree(tmp_path)
    result = scan_kbuild_makefiles_list(str(tmp_path))
    assert isinstance(result, list)
    assert len(result) == 2


def test_scan_kbuild_tree_kbuild_file(tmp_path):
    """Files named 'Kbuild' (not 'Makefile') are also collected."""
    d = tmp_path / 'arch' / 'arm'
    d.mkdir(parents=True)
    (d / 'Kbuild').write_text('obj-$(CONFIG_ARM) += setup.o\n')
    _, kbuild = scan_kbuild_tree(str(tmp_path))
    assert any('Kbuild' in p for p in kbuild)
