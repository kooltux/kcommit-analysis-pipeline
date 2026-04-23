#!/usr/bin/env python3
"""Stage 03: Build product map from config, logs, artifacts, and Kbuild metadata.

v7.18 changes vs v7.17:
  - Loads cache/kbuild_static_map.json written by stage 02 so that the
    Makefile/Kbuild tree does NOT need to be walked a second time.  Falls back
    to scan_makefile_config_map() only when that cache file is absent.
  - Passes progress_callback into build_history_config_map() so the parallel
    git-show calls report live progress via update_stage_progress.
  - Python 3.6 compatible.
"""
from __future__ import print_function
import argparse
import os
import sys

from lib.config import load_config
from lib.io_utils import ensure_dir, load_json, save_json
from lib.parse_kconfig import scan_makefile_config_map
from lib.history_map import build_history_config_map
from lib.validation import validate_inputs
from lib.pipeline_runtime import (
    start_stage, finish_stage, fail_stage, update_stage_progress
)


def _derive_config_dirs(config_to_paths):
    dirs = set()
    for paths in (config_to_paths or {}).values():
        for p in paths:
            d = os.path.dirname(p)
            if d:
                dirs.add(d.rstrip('/') + '/')
    return sorted(dirs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    args = ap.parse_args()

    cfg        = load_config(args.config)
    work       = cfg.get('project', {}).get('work_dir', './work')
    state_path = os.path.join(work, 'pipeline_state.json')
    started    = start_stage(state_path, 'build_product_map', 4, 7)

    try:
        problems, notices = validate_inputs(cfg)
        for note in notices:
            print('  NOTICE:', note)
        if problems:
            for p in problems:
                print('  ERROR:', p)
            fail_stage(state_path, 'build_product_map', started,
                       error_msg='; '.join(problems))
            raise SystemExit(2)

        cache = os.path.join(work, 'cache')
        ensure_dir(cache)

        ctx        = load_json(os.path.join(cache, 'build_context.json'),
                               default={}) or {}
        source_dir = (cfg.get('kernel', {}) or {}).get('source_dir')

        # ── 1. Static config-to-paths map ────────────────────────────────────
        # Prefer the map already computed (and cached) by stage 02.
        cached_map_path = os.path.join(cache, 'kbuild_static_map.json')
        if os.path.exists(cached_map_path):
            base_map = load_json(cached_map_path, default={}) or {}
            print('  reusing kbuild_static_map.json from stage 02 '
                  '(%d symbols)' % len(base_map))
        elif source_dir and os.path.isdir(source_dir):
            print('  kbuild_static_map.json not found – scanning tree ...')
            base_map = scan_makefile_config_map(source_dir)
        else:
            base_map = {}

        update_stage_progress(4, 7, 0.20, 'base map ready',
                              n_done=len(base_map), n_total=len(base_map))

        # ── 2. History-based config map (parallel git show) ──────────────────
        history_info    = None
        config_to_paths = base_map

        if source_dir and os.path.isdir(source_dir):
            def _hist_progress(done, total):
                frac = done / max(total, 1)
                update_stage_progress(4, 7, 0.20 + 0.70 * frac,
                                      'history map',
                                      n_done=done, n_total=total)
            try:
                history_info    = build_history_config_map(
                    cfg, base_map, progress_callback=_hist_progress)
                config_to_paths = history_info.get('config_to_paths', base_map)
            except Exception as e:
                print('\n  warning: history config mapping disabled: %s' % e)
                config_to_paths = base_map
                history_info    = {'mode': 'error', 'error': str(e)}

        sys.stdout.write('\n')
        sys.stdout.flush()

        # ── 3. Assemble product map ───────────────────────────────────────────
        def _extract_log_objects(lines):
            objs = set()
            for line in (lines or []):
                for tok in line.split():
                    if tok.endswith('.o') or tok.endswith('.ko'):
                        objs.add(os.path.basename(tok))
            return sorted(objs)

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

        save_json(os.path.join(cache, 'product_map.json'), product_map)

        print('  product map built: %d config symbols, %d config dirs'
              % (len(config_to_paths), len(product_map['config_dirs'])))
        finish_stage(state_path, 'build_product_map', started, status='ok',
                     extra={
                         'log_object_count':    len(product_map['built_objects_from_log']),
                         'artifact_count':      len(product_map['built_artifacts_from_dir']),
                         'config_symbol_count': len(config_to_paths),
                         'config_dir_count':    len(product_map['config_dirs']),
                     })

    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        fail_stage(state_path, 'build_product_map', started, error_msg=str(exc))
        raise


if __name__ == '__main__':
    main()
