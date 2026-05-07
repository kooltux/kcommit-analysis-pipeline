"""Stage 03: Build product map from config, logs, artifacts, and Kbuild metadata.

Stage 03 of the kcommit pipeline (absorbed into lib/stages in v9.13).
"""
import os
import sys

from lib.config import load_json, save_json
from lib.history_map import build_history_config_map, _set_gitshow_cache_dir
from lib.parse_kconfig import scan_makefile_config_map
from lib.pipeline_runtime import update_stage_progress
from lib.manifest import CACHE_FILES, NSTAGES


def _derive_config_dirs(config_to_paths):
    dirs = set()
    for paths in (config_to_paths or {}).values():
        for p in paths:
            d = os.path.dirname(p)
            if d:
                dirs.add(d.rstrip('/') + '/')
    return sorted(dirs)


def _extract_log_objects(lines):
    objs = set()
    for line in (lines or []):
        for tok in line.split():
            if tok.endswith('.o') or tok.endswith('.ko'):
                objs.add(os.path.basename(tok))
    return sorted(objs)


def run(cfg, cache):
    ctx = load_json(os.path.join(cache, CACHE_FILES['build_context']), default={}) or {}
    source_dir = (cfg.get('kernel', {}) or {}).get('source_dir')

    # 1. Static config-to-paths map (prefer stage 02 cached result)
    cached_map_path = os.path.join(cache, CACHE_FILES['kbuild_map'])
    if os.path.exists(cached_map_path):
        base_map = load_json(cached_map_path, default={}) or {}
        print('  reusing kbuild_static_map from stage 02 (%d symbols)' % len(base_map))
    elif source_dir and os.path.isdir(source_dir):
        print('  kbuild_static_map not found — scanning tree ...')
        base_map = scan_makefile_config_map(source_dir)
    else:
        base_map = {}

    update_stage_progress(3, NSTAGES, 0.20, 'base map ready',
                          n_done=len(base_map), n_total=len(base_map))

    # Wire on-disk git-show cache
    _set_gitshow_cache_dir(cache)

    # 2. History-based config map
    history_info    = None
    config_to_paths = base_map

    if source_dir and os.path.isdir(source_dir) and base_map:
        def _hist_progress(done, total):
            update_stage_progress(3, NSTAGES, 0.20 + 0.70 * done / max(total, 1),
                                  'history map', n_done=done, n_total=total)
        try:
            history_info    = build_history_config_map(
                cfg, base_map, progress_callback=_hist_progress)
            config_to_paths = history_info.get('config_to_paths', base_map)
        except Exception as e:
            print('\n  warning: history config mapping disabled: %s' % e)
            config_to_paths = base_map
            history_info    = {'mode': 'error', 'error': str(e)}
    elif source_dir and os.path.isdir(source_dir) and not base_map:
        print('  skipping history map: base kbuild map is empty')

    sys.stderr.write('\n'); sys.stderr.flush()

    # 3. Assemble product map
    product_map = {
        'enabled_configs':          ctx.get('kernel_config', []),
        'built_objects_from_log':   _extract_log_objects(
                                        ctx.get('kernel_build_log', []) +
                                        ctx.get('yocto_build_log', [])),
        'built_artifacts_from_dir': ctx.get('build_artifacts', []),
        'kbuild_files':             ctx.get('kbuild_files', []),
        'dts_roots':                ctx.get('dts_roots', []),
        'config_to_paths':          config_to_paths,
        'config_dirs':              _derive_config_dirs(config_to_paths),
    }
    if history_info:
        product_map['history_info'] = {
            'mode':           history_info.get('mode'),
            'snapshot_count': len(history_info.get('snapshots', [])),
        }

    save_json(os.path.join(cache, CACHE_FILES['product_map']), product_map)
    print('  product map built: %d config symbols, %d config dirs'
          % (len(config_to_paths), len(product_map['config_dirs'])))
    return product_map
