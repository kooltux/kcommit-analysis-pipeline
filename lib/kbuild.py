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

v13.0.3 changes (J):
  - load_kernel_config_symbols(): accepts arch and srctree keyword arguments.
    When arch is supplied, SRCARCH and ARCH are set in the process environment
    (via os.environ.setdefault) before kconfiglib is invoked, so that
    kconfiglib can resolve 'source "arch/$SRCARCH/Kconfig"' references.
    srctree defaults to source_dir when not explicitly given.
    Both variables are set with setdefault so that values already present in
    the environment (e.g. from a build system) are always respected.
    After the kconfiglib call the env vars are NOT unset; they are harmless
    for the rest of the process and unsetting them could break sub-processes.

v16.0.2 changes (E.1):
  - _ARCH_CONFIG_MAP: lookup table mapping CONFIG_<ARCH>=y markers to
    (arch, srcarch) pairs for all mainstream Linux architectures.  More-specific
    entries appear before less-specific ones (X86_64 before X86, PPC64 before
    PPC, SPARC64 before SPARC) so the first match is always the most precise.
  - detect_arch_from_dotconfig(config_path): new public helper that reads a
    .config file and returns (arch, srcarch) by scanning for the first
    CONFIG_<ARCH>=y line that matches _ARCH_CONFIG_MAP.  Returns (None, None)
    when the file is absent, unreadable, or contains no recognised arch symbol.
    arch    -- value for the ARCH env var  (e.g. 'arm64', 'x86_64')
    srcarch -- value for the SRCARCH env var (differs from arch only for the
               x86 family: CONFIG_X86_64=y -> arch='x86_64', srcarch='x86')
  - load_kernel_config_symbols(): new srcarch keyword argument.  When given,
    SRCARCH env var is set to srcarch rather than arch (relevant for x86 where
    ARCH=x86_64 but SRCARCH=x86).  Defaults to arch when srcarch is None,
    preserving the previous behaviour for all other architectures.
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


# ── Architecture detection (v16.0.2 / E.1) ───────────────────────────────────

# Mapping from CONFIG_<suffix>=y marker to (ARCH, SRCARCH) env var values.
# Rules:
#  - More-specific entries MUST appear before less-specific ones so the first
#    match is always the most precise (e.g. X86_64 before X86).
#  - ARCH is the user-facing architecture name passed to the kernel build.
#  - SRCARCH is the directory name under arch/ used by the kernel Makefile;
#    for the x86 family both CONFIG_X86_64 and CONFIG_X86 map to srcarch='x86'.
_ARCH_CONFIG_MAP = [
    # (config_symbol_suffix,  ARCH,          SRCARCH)
    ('ARM64',                 'arm64',        'arm64'),
    ('ARM',                   'arm',          'arm'),
    ('X86_64',                'x86_64',       'x86'),
    ('X86',                   'x86',          'x86'),
    ('RISCV',                 'riscv',        'riscv'),
    ('MIPS',                  'mips',         'mips'),
    ('PPC64',                 'powerpc',      'powerpc'),
    ('PPC',                   'powerpc',      'powerpc'),
    ('S390',                  's390',         's390'),
    ('SPARC64',               'sparc',        'sparc'),
    ('SPARC',                 'sparc',        'sparc'),
    ('ALPHA',                 'alpha',        'alpha'),
    ('IA64',                  'ia64',         'ia64'),
    ('M68K',                  'm68k',         'm68k'),
    ('MICROBLAZE',            'microblaze',   'microblaze'),
    ('NIOS2',                 'nios2',        'nios2'),
    ('OPENRISC',              'openrisc',     'openrisc'),
    ('PARISC',                'parisc',       'parisc'),
    ('SH',                    'sh',           'sh'),
    ('UML',                   'um',           'um'),
    ('XTENSA',                'xtensa',       'xtensa'),
    ('CSKY',                  'csky',         'csky'),
    ('HEXAGON',               'hexagon',      'hexagon'),
    ('LOONGARCH',             'loongarch',    'loongarch'),
    ('ARC',                   'arc',          'arc'),
    ('NDS32',                 'nds32',        'nds32'),
]


def detect_arch_from_dotconfig(config_path):
    """Detect the target architecture from a kernel .config file.

    Scans config_path for ``CONFIG_<ARCH>=y`` markers defined in
    ``_ARCH_CONFIG_MAP`` and returns the first match as a ``(arch, srcarch)``
    tuple, where:

    * ``arch``    -- value for the ``ARCH`` env var (e.g. ``'arm64'``,
                     ``'x86_64'``).  This is what the kernel ``make ARCH=``
                     argument expects.
    * ``srcarch`` -- value for the ``SRCARCH`` env var.  For most
                     architectures this is identical to ``arch``.  For the x86
                     family ``SRCARCH`` is always ``'x86'`` regardless of
                     whether the config is 32- or 64-bit
                     (``CONFIG_X86_64=y`` → ``arch='x86_64'``,
                     ``srcarch='x86'``).

    Returns ``(None, None)`` when:
    * ``config_path`` is ``None`` or the file does not exist / is unreadable.
    * The file contains no ``CONFIG_<ARCH>=y`` line matching the table.

    The caller is responsible for logging a warning when ``(None, None)`` is
    returned and architecture detection is required.
    """
    if not config_path or not os.path.isfile(config_path):
        return None, None
    # Build a fast O(1) lookup from the ordered table.
    # The table order is only relevant for the list; the dict gives direct lookup.
    lookup = {'CONFIG_' + sym: (arch, srcarch)
              for sym, arch, srcarch in _ARCH_CONFIG_MAP}
    try:
        with open(config_path, 'r', encoding='utf-8', errors='replace') as fh:
            for line in fh:
                line = line.strip()
                if not line.startswith('CONFIG_') or not line.endswith('=y'):
                    continue
                sym = line[:-2]  # strip trailing '=y'
                if sym in lookup:
                    return lookup[sym]
    except OSError:
        pass
    return None, None


def load_kernel_config_symbols(config_path, source_dir=None, arch=None,
                               srcarch=None, srctree=None):
    """Parse a .config file and return enabled CONFIG_* symbols.

    Returns a list of 'CONFIG_X=y' / 'CONFIG_X=m' strings for every symbol
    that is enabled in the given .config file.

    Prefers kconfiglib when available and a kernel source directory is given,
    as it evaluates full Kconfig expressions.  Falls back to a lightweight
    line-based parser otherwise (handles simple =y / =m lines).

    Parameters
    ----------
    config_path : str or None
        Path to the .config file.  Returns [] when None or missing.
    source_dir : str or None
        Kernel source root (used as kconfiglib Kconfig entry point).
    arch : str or None
        Target architecture name (e.g. 'arm', 'arm64', 'x86_64').  When given,
        ARCH is injected into the process environment via os.environ.setdefault
        so that kconfiglib can resolve arch-specific Kconfig includes.
        Values already in the environment are never overwritten.
    srcarch : str or None
        Value for the SRCARCH env var.  When None, defaults to arch (correct
        for all architectures except the x86 family where ARCH='x86_64' but
        SRCARCH='x86').  Use detect_arch_from_dotconfig() to obtain the correct
        (arch, srcarch) pair automatically.
    srctree : str or None
        Value to set for the 'srctree' env var expected by kconfiglib.
        Defaults to source_dir when not explicitly provided.

    Emits logging.warning when:
      - config_path is None or does not exist (caller should know .config is absent)
      - kconfiglib is not available (fallback parser in use — see module warning)
      - kconfiglib raises an exception (falls back to line parser)

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
        # v13.0.3 (J): inject arch / srctree env vars so kconfiglib can
        # resolve 'source "arch/$SRCARCH/Kconfig"' and similar includes.
        # setdefault is used so values already in the environment (e.g. from
        # a CI/build system) are always respected over config-file values.
        #
        # v16.0.2 (E.1): srcarch may differ from arch for the x86 family;
        # use srcarch for SRCARCH when explicitly provided, otherwise fall
        # back to arch (correct for all other architectures).
        _srctree = srctree or source_dir
        if _srctree:
            prev_srctree = os.environ.get('srctree')
            os.environ.setdefault('srctree', _srctree)
            if prev_srctree is None:
                logging.debug('load_kernel_config_symbols: set srctree=%s', _srctree)
        if arch:
            _srcarch = srcarch or arch
            os.environ.setdefault('SRCARCH', _srcarch)
            os.environ.setdefault('ARCH', arch)
            logging.debug(
                'load_kernel_config_symbols: SRCARCH=%s ARCH=%s (setdefault)',
                os.environ['SRCARCH'], os.environ['ARCH'])

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
