"""Kernel config and Kbuild-style parsing helpers.

v7.18 changes:
  - scan_kbuild_makefiles() delegates to parse_kconfig.scan_kbuild_tree()
    instead of performing its own os.walk.
  - Python 3.6 compatible.

v12.0.2 changes:
  - KBUILD_PLACEHOLDER_NAMES exported here as the single authoritative
    definition, shared by st02 (_scan_build_dir) and st03 (_extract_log_objects).

v13.0.0 changes (E.9):
  - Removed redundant 'import os as _os' inside infer_touched_paths();
    the module-level 'import os' is used throughout.

v13.0.2 changes (Bug-2 fix):
  - load_kernel_config_symbols(): emits a logging.warning when kconfiglib is
    not installed so that the fallback line-based parser is used.  The
    fallback is functional but less accurate than kconfiglib for complex
    Kconfig expressions; users should install kconfiglib for best results.
  - load_kernel_config_symbols(): emits a logging.warning when config_path
    is None or does not exist, so the caller can distinguish "no .config
    provided" from an empty but valid .config file.
"""
import functools as _functools
import logging
import os

from lib.parse_kconfig import scan_kbuild_tree

try:
    import kconfiglib
except Exception:
    kconfiglib = None
    logging.warning(
        'kconfiglib not installed — load_kernel_config_symbols() will use the '
        'built-in fallback line parser.  This parser handles simple "CONFIG_X=y/m" '
        'lines but may miss symbols that require full Kconfig expression evaluation. '
        'Install kconfiglib for best results: pip install kconfiglib')


# Kbuild directory-aggregator basenames that must never enter the product map
# as build-artifact evidence.  These are synthetic intermediate linker inputs
# produced automatically by kbuild to merge directory-level objects for upward
# linking; they have no 1-to-1 correspondence with any source file.
#
# Used by:
#   lib/stages/st02_build_context._scan_build_dir()    -- filesystem scan
#   lib/stages/st03_product_map._extract_log_objects() -- build-log scan
KBUILD_PLACEHOLDER_NAMES = frozenset({
    'built-in.o',
    'built-in.a',
})


def load_kernel_config_symbols(config_path, source_dir=None):
    """Parse a .config file and return enabled CONFIG_* symbols.

    Returns a list of 'CONFIG_X=y' / 'CONFIG_X=m' strings for every symbol
    that is enabled in the given .config file.

    Prefers kconfiglib when available and a kernel source directory is given,
    as it evaluates full Kconfig expressions.  Falls back to a lightweight
    line-based parser otherwise (handles simple =y / =m lines).

    Emits logging.warning when:
      - config_path is None or does not exist (caller should know .config is absent)
      - kconfiglib is not available (fallback parser in use — see module warning)

    Returns [] when config_path is absent; callers must treat [] as
    "no .config provided" and keep kconfig filtering disabled.
    """
    symbols = []
    if not config_path:
        logging.warning(
            'load_kernel_config_symbols: no kernel_config path configured — '
            'kconfig symbol filtering will be disabled for this run. '
            'Set kernel.kernel_config in your pipeline config for better '
            'product-scope filtering.')
        return symbols
    if not os.path.isfile(config_path):
        logging.warning(
            'load_kernel_config_symbols: kernel_config path does not exist: %s — '
            'kconfig symbol filtering will be disabled for this run.',
            config_path)
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
        except Exception as exc:
            logging.warning(
                'load_kernel_config_symbols: kconfiglib failed (%s) — '
                'falling back to line-based parser.', exc)

    # Fallback: lightweight line-based parser.
    # Handles lines of the form CONFIG_X=y or CONFIG_X=m.
    # Does not evaluate Kconfig expressions or handle select/depends chains.
    with open(config_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line.startswith('CONFIG_') or '=' not in line:
                continue
            sym, _, val = line.partition('=')
            if val.strip() in ('y', 'm'):
                symbols.append('%s=%s' % (sym, val.strip()))
    return symbols


def scan_kbuild_makefiles(source_dir):
    """Return sorted list of absolute Makefile/Kbuild paths.

    Delegates to scan_kbuild_tree() to avoid a redundant os.walk when
    scan_kbuild_tree() results are reused by the caller.
    """
    _, kbuild_files = scan_kbuild_tree(source_dir)
    return kbuild_files


# ── Subsystem path inference (moved from lib/scoring.py in v9.12) ────────────

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

    E.9 (v13.0.0): removed inner 'import os as _os'; uses module-level os.
    """
    if not cfg:
        return []
    paths = cfg.get('paths', {}) or {}
    scoring_dir = paths.get('scoring_dir') or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'configs', 'scoring')
    hints_path = os.path.join(scoring_dir, 'subsystem_path_hints.json')
    if not os.path.exists(hints_path):
        return []
    hints = _load_hints_from_path(os.path.abspath(hints_path))
    low = (subject or '').lower()
    result = []
    for keyword, kpaths in hints.items():
        if keyword.lower() in low:
            result.extend(kpaths if isinstance(kpaths, list) else [str(kpaths)])
    return sorted(set(result))
