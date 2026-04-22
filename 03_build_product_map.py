#!/usr/bin/env python3
# Build a simple product map from captured config, logs, optional build artifacts, and Kbuild metadata.
from __future__ import print_function
import argparse
import os

from lib.config import load_config
from lib.io_utils import ensure_dir, load_json, save_json
from lib.parse_kconfig import scan_makefile_config_map
from lib.history_map import build_history_config_map
from lib.validation import validate_inputs
from lib.pipeline_runtime import start_stage, finish_stage


def _derive_config_dirs(config_to_paths):
    # Derive a set of directory prefixes from the config-to-paths mapping so
    # scoring can cheaply relate coarse path guesses to actual built sources.
    dirs = set()
    for paths in (config_to_paths or {}).values():
        for p in paths:
            d = os.path.dirname(p)
            if d:
                dirs.add(d.rstrip('/') + '/')
    return sorted(dirs)


def main():
    # Parse arguments, validate required inputs, and derive a product map for later scoring.
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    args = ap.parse_args()

    cfg = load_config(args.config)
    state_path = os.path.join(cfg.get('project', {}).get('work_dir', './work'), 'pipeline_state.json')
    started = start_stage(state_path, 'build_product_map', 3, 6)

    problems, notices = validate_inputs(cfg)
    for note in notices:
        print(note)
    if problems:
        for problem in problems:
            print(problem)
        raise SystemExit(2)

    work = cfg.get('project', {}).get('work_dir', './work')
    cache = os.path.join(work, 'cache')
    ensure_dir(cache)

    ctx = load_json(os.path.join(cache, 'build_context.json'), default={}) or {}

    # Build a config->paths map from Makefile/Kbuild content, and optionally
    # enrich it with history sampling if enabled via the configuration.
    source_dir = cfg.get('kernel', {}).get('source_dir')
    base_map = {}
    history_info = None
    if source_dir and os.path.isdir(source_dir):
        base_map = scan_makefile_config_map(source_dir)
        try:
            history_info = build_history_config_map(cfg, base_map)
            config_to_paths = history_info.get('config_to_paths', base_map)
        except Exception as e:
            print('warning: history-based config mapping disabled: %s' % e)
            config_to_paths = base_map
            history_info = {'mode': 'error', 'error': str(e)}
    else:
        config_to_paths = base_map

    config_dirs = _derive_config_dirs(config_to_paths)

    product_map = {
        'enabled_configs': ctx.get('kernel_config', []),
        'kernel_config_parsed': ctx.get('kernel_config_parsed', {}),
        'built_objects_from_log': [
            line.strip()
            for line in ctx.get('kernel_build_log', [])
            if '.o' in line or '.ko' in line
        ],
        'built_artifacts_from_dir': ctx.get('build_artifacts', []),
        'kbuild_files': ctx.get('kbuild_files', []),
        'dts_roots': ctx.get('dts_roots', []),
        'config_to_paths': config_to_paths,
        'config_dirs': config_dirs,
        'history_mapping': history_info,
    }

    save_json(os.path.join(cache, 'product_map.json'), product_map)
    print('product map built')
    finish_stage(
        state_path,
        'build_product_map',
        started,
        status='ok',
        extra={
            'enabled_config_count': len(product_map.get('enabled_configs', [])),
            'artifact_count': len(product_map.get('built_artifacts_from_dir', [])),
            'config_symbol_count': len(product_map.get('config_to_paths', {})),
        },
    )


if __name__ == '__main__':
    main()
