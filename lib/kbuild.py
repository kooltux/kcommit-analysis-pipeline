# Shared helpers for kernel config and Kbuild-style parsing.
from __future__ import print_function
import os

try:
    import kconfiglib
except Exception:
    kconfiglib = None


def load_kernel_config_symbols(config_path, source_dir=None):
    """Parse a .config file and return enabled CONFIG symbols.

    When Kconfiglib is available and a kernel source directory is provided,
    prefer it as the backend so we get a canonical view of enabled symbols.
    Falls back to a lightweight line-based parser otherwise.
    """
    symbols = []
    if not config_path or not os.path.isfile(config_path):
        return symbols

    # Preferred path: use Kconfiglib if available and we know where the
    # top-level Kconfig lives.
    if kconfiglib is not None and source_dir:
        kconfig_path = os.path.join(source_dir, 'Kconfig')
        try:
            if os.path.isfile(kconfig_path):
                conf = kconfiglib.Kconfig(kconfig_path)
                # Read values from the specified .config instead of the
                # default .config in the source tree.
                conf.load_config(config_path)
                for sym in conf.unique_defined_syms:
                    if sym.str_value in ('y', 'm'):
                        symbols.append('CONFIG_%s=%s' % (sym.name, sym.str_value))
                return symbols
        except Exception:
            # Fall through to the simple parser if anything goes wrong.
            pass

    # Fallback: simple textual parsing of the .config content.
    with open(config_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if line.startswith('CONFIG_') and ('=y' in line or '=m' in line):
                symbols.append(line)
    return symbols


def scan_kbuild_makefiles(source_dir):
    # Collect Makefile/Kbuild paths so later stages can inspect build structure.
    found = []
    if not source_dir or not os.path.isdir(source_dir):
        return found
    for root, _, files in os.walk(source_dir):
        for name in files:
            if name in ('Makefile', 'Kbuild'):
                found.append(os.path.join(root, name))
    return sorted(found)
