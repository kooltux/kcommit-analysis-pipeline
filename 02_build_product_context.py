#!/usr/bin/env python3
"""Stage 02: Build product context (config, logs, artifacts, Kbuild map, history).

Merges former stages 02 (collect_build_context) and 03 (build_product_map).
Outputs: cache/build_context.json, cache/kbuild_static_map.json, cache/product_map.json
"""
import os
import sys

from lib.io_utils import ensure_dir, save_json
from lib.kbuild import load_kernel_config_symbols
from lib.parse_kconfig import parse_kernel_config, scan_kbuild_tree
from lib.history_map import build_history_config_map
from lib.pipeline_runtime import stage_main, update_stage_progress


def _read_lines(path):
    if not path or not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        return [line.rstrip() for line in f]


def _scan_build_dir(build_dir):
    objects = []
    if not build_dir or not os.path.isdir(build_dir):
        return objects
    for root, _, files in os.walk(build_dir):
        for name in files:
            if name.endswith('.o') or name.endswith('.ko'):
                objects.append(
                    os.path.relpath(os.path.join(root, name), build_dir))
    return sorted(objects)


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


@stage_main('build_product_context', 1, 5)
def main(cfg, work):
    cache      = os.path.join(work, 'cache')
    ensure_dir(cache)

    inputs     = cfg.get('inputs', {}) or {}
    source_dir = (cfg.get('kernel', {}) or {}).get('source_dir')

    kconfig_path = inputs.get('kernel_config')
    if kconfig_path and not os.path.isfile(kconfig_path):
        kconfig_path = None

    build_dir = inputs.get('build_dir')
    if build_dir and not os.path.isdir(build_dir):
        build_dir = None

    # ── 1. Gather build context (formerly stage 02) ───────────────────────
    update_stage_progress(1, 5, 0.10, 'loading kernel config')
    kernel_config = load_kernel_config_symbols(kconfig_path, source_dir)

    update_stage_progress(1, 5, 0.20, 'parsing .config')
    kernel_config_parsed = parse_kernel_config(kconfig_path)

    update_stage_progress(1, 5, 0.30, 'reading build logs')
    kernel_build_log = _read_lines(inputs.get('kernel_build_log'))
    yocto_build_log  = _read_lines(inputs.get('yocto_build_log'))

    update_stage_progress(1, 5, 0.40, 'scanning build dir')
    build_artifacts = _scan_build_dir(build_dir)

    update_stage_progress(1, 5, 0.50, 'walking kbuild tree')
    if source_dir and os.path.isdir(source_dir):
        static_config_map, kbuild_files = scan_kbuild_tree(source_dir)
    else:
        static_config_map, kbuild_files = {}, []

    save_json(os.path.join(cache, 'kbuild_static_map.json'), static_config_map)

    ctx = {
        'kernel_config':        kernel_config,
        'kernel_config_parsed': kernel_config_parsed,
        'kernel_build_log':     kernel_build_log,
        'yocto_build_log':      yocto_build_log,
        'dts_roots':            inputs.get('dts_roots', []),
        'build_dir':            build_dir,
        'build_artifacts':      build_artifacts,
        'kbuild_files':         kbuild_files,
    }
    save_json(os.path.join(cache, 'build_context.json'), ctx)

    # ── 2. Build history-based product map (formerly stage 03) ───────────
    history_info    = None
    config_to_paths = static_config_map

    if source_dir and os.path.isdir(source_dir):
        def _hist_progress(done, total):
            frac = done / max(total, 1)
            update_stage_progress(1, 5, 0.60 + 0.30 * frac,
                                  'history map',
                                  n_done=done, n_total=total)
        try:
            history_info    = build_history_config_map(
                cfg, static_config_map, progress_callback=_hist_progress)
            config_to_paths = history_info.get('config_to_paths', static_config_map)
        except Exception as e:
            print('\n  warning: history config mapping disabled: %s' % e)
            config_to_paths = static_config_map
            history_info    = {'mode': 'error', 'error': str(e)}

    product_map = {
        'enabled_configs':          kernel_config,
        'built_objects_from_log':   _extract_log_objects(kernel_build_log + yocto_build_log),
        'built_artifacts_from_dir': build_artifacts,
        'kbuild_files':             kbuild_files,
        'dts_roots':                inputs.get('dts_roots', []),
        'config_to_paths':          config_to_paths,
        'config_dirs':              _derive_config_dirs(config_to_paths),
    }
    if history_info:
        product_map['history_info'] = {
            'mode':           history_info.get('mode'),
            'snapshot_count': len(history_info.get('snapshots', [])),
        }

    save_json(os.path.join(cache, 'product_map.json'), product_map)

    sys.stdout.write('\n')
    sys.stdout.flush()

    print('  product context captured: %d symbols, %d dirs'
          % (len(config_to_paths), len(product_map['config_dirs'])))
    
    return {
        'build_artifact_count': len(build_artifacts),
        'kbuild_file_count':    len(kbuild_files),
        'enabled_config_count': len(kernel_config),
        'config_symbol_count':  len(config_to_paths),
        'config_dir_count':     len(product_map['config_dirs']),
    }


if __name__ == '__main__':
    main()
