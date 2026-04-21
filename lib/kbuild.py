# Shared helpers for kernel config and Kbuild-style parsing.
from __future__ import print_function
import os

try:
    import kconfiglib
except Exception:
    kconfiglib = None


def load_kernel_config_symbols(config_path):
    # Parse a .config file and return enabled CONFIG symbols.
    symbols = []
    if not config_path or not os.path.isfile(config_path):
        return symbols
    if kconfiglib is not None:
        # Kconfiglib is the preferred parser for kernel configuration data.
        with open(config_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if line.startswith('CONFIG_') and '=y' in line or '=m' in line:
                    symbols.append(line)
        return symbols
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
