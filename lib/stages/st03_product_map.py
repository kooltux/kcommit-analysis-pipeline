"""Stage 03: Build product map from config, logs, artifacts, and Kbuild metadata.

Stage 03 of the kcommit pipeline (absorbed into lib/stages in v9.13).

product_map fields
------------------
config_to_paths       -- full Kbuild universe: CONFIG_X -> [source paths] for ALL
                         symbols found in Makefiles, regardless of .config enablement.
                         Preserved for diagnostics (e.g. "why is this symbol missing
                         from the enabled map?").
config_dirs           -- directories derived from config_to_paths (all symbols).
config_enabled_map    -- config_to_paths filtered to symbols that are enabled (=y or =m)
                         in the product .config.  This is the authoritative source for
                         what the kernel build system would compile for this product.
                         Consumers that need product-scope file coverage must use this
                         field, not config_to_paths.
config_enabled_dirs   -- directories derived from config_enabled_map.  Equivalent to
                         the old runtime-computed compiled_dirs in build_compiled_sets(),
                         now materialised at stage 03 so all consumers share one
                         consistent view.
enabled_configs       -- flat list of 'CONFIG_X=y/m' strings from .config (Pass 1 of
                         load_kernel_config_symbols()).
built_objects_from_log  -- .o/.ko basenames extracted from kernel/yocto build logs.
built_artifacts_from_dir -- .o/.ko relative paths found by scanning build_dir.
kbuild_files          -- absolute paths of every Makefile/Kbuild in source_dir.
dts_roots             -- DTS root directories from config.

v13.0.1 changes (Bug-1 fix):
  -- Added config_enabled_map: config_to_paths intersected with enabled_configs.
     Previously config_to_paths contained ALL Kbuild symbols (enabled + disabled),
     causing st04 build_compiled_sets() and st05 _collect_product_evidence() to
     consider disabled symbols (e.g. CONFIG_BTRFS_FS) as part of the product.
  -- Added config_enabled_dirs: directories derived from config_enabled_map,
     replacing the runtime-derived compiled_dirs in build_compiled_sets().
  -- _derive_config_dirs() is now called for both maps; no logic change.
"""
import logging
import os

from lib.config import load_json, save_json
from lib.history_map import build_history_config_map
from lib.kbuild import KBUILD_PLACEHOLDER_NAMES
from lib.parse_kconfig import scan_makefile_config_map
from lib.pipeline_runtime import update_stage_progress, finish_progress_line
from lib.manifest import CACHE_FILES, NSTAGES


def _derive_config_dirs(config_map):
    """Return sorted list of unique parent directories from a config_to_paths-style map."""
    dirs = set()
    for paths in (config_map or {}).values():
        for p in paths:
            d = os.path.dirname(p)
            if d:
                dirs.add(d.rstrip('/') + '/')
    return sorted(dirs)


def _filter_to_enabled(config_map, enabled_configs_raw):
    """Return a copy of *config_map* restricted to symbols enabled in .config.

    *enabled_configs_raw* is the flat list produced by load_kernel_config_symbols():
    entries are 'CONFIG_X=y' or 'CONFIG_X=m' strings.
    Only symbols with value 'y' or 'm' are considered enabled; all others
    (including '=n', string values, hex values) are excluded.

    v13.0.1 (Bug-1): this filter was previously only performed at runtime inside
    st04 build_compiled_sets().  Moving it here ensures that config_enabled_map
    and config_enabled_dirs in product_map reflect only the product-compiled
    symbol set, making the product map self-consistent and accurate for all
    downstream consumers (st04 prefilter, st05 scoring/evidence).
    """
    enabled_syms = set()
    for s in (enabled_configs_raw or []):
        if '=' in s:
            sym, _, val = s.partition('=')
            if val.strip() in ('y', 'm'):
                enabled_syms.add(sym)
    filtered = {sym: paths for sym, paths in (config_map or {}).items()
                if sym in enabled_syms}
    logging.debug(
        'st03: config_enabled_map: %d enabled symbols (config_to_paths has %d total)',
        len(filtered), len(config_map or {}))
    return filtered


def _extract_log_objects(lines):
    """Extract compiled object basenames from build log lines.

    Kbuild directory-aggregator placeholders (``built-in.o``, ``built-in.a``)
    are excluded.  These are synthetic intermediate linker inputs produced
    automatically by kbuild with no 1-to-1 source-file correspondence; including
    them would add the stem ``built-in`` to ``log_basenames``, causing the
    stage-04 L2half artifact check to spuriously keep every commit whose filename
    starts with ``built-in``.
    """
    objs = set()
    for line in (lines or []):
        for tok in line.split():
            if tok.endswith('.o') or tok.endswith('.ko'):
                bn = os.path.basename(tok)
                if bn in KBUILD_PLACEHOLDER_NAMES:
                    continue
                objs.add(bn)
    return sorted(objs)


def run(cfg, cache):
    ctx = load_json(os.path.join(cache, CACHE_FILES['build_context']), default={}) or {}
    source_dir = (cfg.get('kernel', {}) or {}).get('source_dir')

    # 1. Static config-to-paths map (prefer stage 02 cached result)
    cached_map_path = os.path.join(cache, CACHE_FILES['kbuild_map'])
    if os.path.exists(cached_map_path):
        base_map = load_json(cached_map_path, default={}) or {}
        print('  reusing kbuild_map from stage 02 (%d symbols)' % len(base_map))
    elif source_dir and os.path.isdir(source_dir):
        print('  kbuild_map not found — scanning tree ...')
        base_map = scan_makefile_config_map(source_dir)
    else:
        base_map = {}

    update_stage_progress(3, NSTAGES, 0.20, 'base map ready',
                          n_done=len(base_map), n_total=len(base_map))

    # 2. History-based config map
    history_info    = None
    config_to_paths = base_map

    if source_dir and os.path.isdir(source_dir) and base_map:
        def _hist_progress(done, total):
            update_stage_progress(3, NSTAGES, 0.20 + 0.60 * done / max(total, 1),
                                  'history map', n_done=done, n_total=total)
        try:
            history_info    = build_history_config_map(
                cfg, base_map, cache, progress_callback=_hist_progress)
            config_to_paths = history_info.get('config_to_paths', base_map)
        except Exception as e:
            print('\n  warning: history config mapping disabled: %s' % e)
            config_to_paths = base_map
            history_info    = {'mode': 'error', 'error': str(e)}
    elif source_dir and os.path.isdir(source_dir) and not base_map:
        print('  skipping history map: base kbuild map is empty')

    # 3. Bug-1 fix: build config_enabled_map by intersecting config_to_paths
    #    with the enabled symbols from .config.  config_to_paths is preserved
    #    as-is for diagnostic use.
    update_stage_progress(3, NSTAGES, 0.82, 'filtering enabled symbols')
    enabled_configs_raw = ctx.get('kernel_config', [])
    config_enabled_map  = _filter_to_enabled(config_to_paths, enabled_configs_raw)
    config_enabled_dirs = _derive_config_dirs(config_enabled_map)

    finish_progress_line()

    # 4. Assemble product map
    product_map = {
        # --- Diagnostic / full-universe fields (all Kbuild symbols) ----------
        'config_to_paths':          config_to_paths,
        'config_dirs':              _derive_config_dirs(config_to_paths),
        # --- Product-scope fields (enabled symbols only) ---------------------
        'config_enabled_map':       config_enabled_map,
        'config_enabled_dirs':      config_enabled_dirs,
        # --- Other build evidence --------------------------------------------
        'enabled_configs':          enabled_configs_raw,
        'built_objects_from_log':   _extract_log_objects(
                                        ctx.get('kernel_build_log', []) +
                                        ctx.get('yocto_build_log', [])),
        'built_artifacts_from_dir': ctx.get('build_artifacts', []),
        'kbuild_files':             ctx.get('kbuild_files', []),
        'dts_roots':                ctx.get('dts_roots', []),
    }
    if history_info:
        product_map['history_info'] = {
            'mode':           history_info.get('mode'),
            'snapshot_count': len(history_info.get('snapshots', [])),
        }

    save_json(os.path.join(cache, CACHE_FILES['product_map']), product_map)
    print('  product map built:')
    print('    config_to_paths    : %d symbols (full Kbuild universe)' % len(config_to_paths))
    print('    config_enabled_map : %d symbols (enabled in .config)' % len(config_enabled_map))
    print('    config_enabled_dirs: %d directories' % len(config_enabled_dirs))
    return product_map
