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


# ── Subsystem path inference (moved from lib/scoring.py in v9.12) ─────────────

import functools as _functools

@_functools.lru_cache(maxsize=8)
def _load_hints_from_path(hints_path):
    """Load subsystem_path_hints.json (cached by path)."""
    try:
        import json as _json
        with open(hints_path, encoding='utf-8') as _f:
            return _json.load(_f)
    except Exception:
        return {}


def infer_touched_paths(subject, cfg=None):
    """Guess relevant kernel path prefixes from a commit subject line.

    Uses configs/scoring/subsystem_path_hints.json.
    Returns a sorted, deduplicated list of path prefix strings.
    """
    import os as _os
    if not cfg:
        return []
    meta     = cfg.get('_meta', {}) or {}
    vars_    = meta.get('vars', {}) or {}
    tooldir  = (vars_.get('TOOLDIR')
                or _os.environ.get('TOOLDIR')
                or _os.path.abspath(_os.path.join(meta.get('config_dir', '.'), '..')))
    hints_path = _os.path.join(tooldir, 'configs', 'scoring', 'subsystem_path_hints.json')
    if not _os.path.exists(hints_path):
        return []
    hints = _load_hints_from_path(_os.path.abspath(hints_path))
    low   = (subject or '').lower()
    result = []
    for keyword, paths in hints.items():
        if keyword.lower() in low:
            result.extend(paths if isinstance(paths, list) else [str(paths)])
    return sorted(set(result))
