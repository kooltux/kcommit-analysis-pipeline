"""Kernel config and Kbuild-style parsing helpers.

v7.18 changes vs v7.17:
  - scan_kbuild_makefiles() now delegates to parse_kconfig.scan_kbuild_tree()
    instead of performing its own os.walk so that stage 02 callers that need
    both the Makefile list and the config_to_paths mapping only traverse the
    source tree once.
  - Python 3.6 compatible.
"""
import os

from lib.parse_kconfig import scan_kbuild_tree

try:
    import kconfiglib
except Exception:
    kconfiglib = None


def load_kernel_config_symbols(config_path, source_dir=None):
    """Parse a .config file and return enabled CONFIG_* symbols.

    Prefers Kconfiglib when available and a kernel source directory is given.
    Falls back to a lightweight line-based parser otherwise.
    """
    symbols = []
    if not config_path or not os.path.isfile(config_path):
        return symbols

    if kconfiglib is not None and source_dir:
        kconfig_path = os.path.join(source_dir, 'Kconfig')
        try:
            if os.path.isfile(kconfig_path):
                conf = kconfiglib.Kconfig(kconfig_path)
                conf.load_config(config_path)
                for sym in conf.unique_defined_syms:
                    if sym.str_value in ('y', 'm'):
                        symbols.append('CONFIG_%s=%s' % (sym.name, sym.str_value))
                return symbols
        except Exception:
            pass

    with open(config_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if line.startswith('CONFIG_') and ('=y' in line or '=m' in line):
                symbols.append(line)
    return symbols


def scan_kbuild_makefiles(source_dir):
    """Return sorted list of absolute Makefile/Kbuild paths.

    Delegates to scan_kbuild_tree() to avoid a redundant os.walk when
    scan_kbuild_tree() results are reused by the caller.
    """
    _, kbuild_files = scan_kbuild_tree(source_dir)
    return kbuild_files
