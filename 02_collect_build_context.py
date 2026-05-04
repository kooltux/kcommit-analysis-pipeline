#!/usr/bin/env python3
"""Stage 02: Gather kernel build context (.config, artifacts, logs, Kbuild).

v8.4 changes vs v8.3:
  - kernel_build_log, yocto_build_log, and dts_roots are now read from the
    kernel config section (kernel.kernel_build_log etc.) rather than the
    defunct inputs section. The inputs variable was never defined in this
    function — these three reads would have raised NameError at runtime.
"""

import json
import argparse
import os
import sys

from lib.config import load_config
from lib.config import save_json
from lib.kbuild import load_kernel_config_symbols
from lib.parse_kconfig import parse_kernel_config, scan_kbuild_tree
from lib.validation import validate_config_only as validate_inputs
from lib.pipeline_runtime import (
    start_stage, finish_stage, fail_stage, update_stage_progress
)


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--override', default=None, metavar='JSON',
                    help='Deep-merge JSON into config (forwarded from kcommit_pipeline)')
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.override:
        from kcommit_pipeline import apply_override
        apply_override(cfg, args.override)
    work       = cfg['paths']['work_dir']
    state_path = os.path.join(work, 'pipeline_state.json')
    started    = start_stage(state_path, 'collect_build_context', 2, 7)
    _t0_stage = __import__('time').time()
    print_stage_input('build context', cfg.get('kernel',{}).get('build_dir','(none)'))

    try:
        problems, notices = validate_inputs(cfg)
        for note in notices:
            print('  NOTICE:', note)
        if problems:
            for p in problems:
                print('  ERROR:', p)
            fail_stage(state_path, 'collect_build_context', started,
                       error_msg='; '.join(problems))
            raise SystemExit(2)

        cache      = os.path.join(work, 'cache')
        os.makedirs(cache, exist_ok=True)

        kernel     = cfg.get('kernel', {}) or {}
        source_dir = kernel.get('source_dir')

        kconfig_path = kernel.get('kernel_config')
        if kconfig_path and not os.path.isfile(kconfig_path):
            kconfig_path = None

        build_dir = kernel.get('build_dir')
        if build_dir and not os.path.isdir(build_dir):
            build_dir = None

        # ── 1. Kernel config symbols ─────────────────────────────────────────
        update_stage_progress(2, 7, 0.10, 'loading kernel config')
        kernel_config = load_kernel_config_symbols(kconfig_path, source_dir)

        # ── 2. Parse .config ─────────────────────────────────────────────────
        update_stage_progress(2, 7, 0.25, 'parsing .config')
        kernel_config_parsed = parse_kernel_config(kconfig_path)

        # ── 3. Build logs ─────────────────────────────────────────────────────
        update_stage_progress(2, 7, 0.40, 'reading build logs')
        kernel_build_log = _read_lines(kernel.get('kernel_build_log'))
        yocto_build_log  = _read_lines(kernel.get('yocto_build_log'))

        # ── 4. Build artifacts ────────────────────────────────────────────────
        update_stage_progress(2, 7, 0.55, 'scanning build dir')
        build_artifacts = _scan_build_dir(build_dir)

        # ── 5. Single os.walk for Kbuild tree ─────────────────────────────────
        update_stage_progress(2, 7, 0.70, 'walking kbuild tree')
        if source_dir and os.path.isdir(source_dir):
            static_config_map, kbuild_files = scan_kbuild_tree(source_dir)
        else:
            static_config_map, kbuild_files = {}, []

        # Cache static_config_map so stage 03 can skip its own tree walk
        save_json(os.path.join(cache, 'kbuild_static_map.json'),
                  static_config_map)

        # ── 6. Save context ───────────────────────────────────────────────────
        update_stage_progress(2, 7, 0.90, 'saving build context')
        ctx = {
            'kernel_config':        kernel_config,
            'kernel_config_parsed': kernel_config_parsed,
            'kernel_build_log':     kernel_build_log,
            'yocto_build_log':      yocto_build_log,
            'dts_roots':            list(kernel.get('dts_roots') or []),
            'build_dir':            build_dir,
            'build_artifacts':      build_artifacts,
            'kbuild_files':         kbuild_files,
        }
        save_json(os.path.join(cache, 'build_context.json'), ctx)

        sys.stdout.write('\n')
        sys.stdout.flush()

        print('  build context captured')
        print_stage_output('build context entries', len(product_map),
            elapsed=__import__('time').time()-_t0_stage)
        finish_stage(state_path, 'collect_build_context', started, status='ok',
                     extra={
                         'build_artifact_count': len(build_artifacts),
                         'kbuild_file_count':    len(kbuild_files),
                         'enabled_config_count': len(kernel_config),
                         'static_config_map_symbols': len(static_config_map),
                     })

    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        fail_stage(state_path, 'collect_build_context', started,
                   error_msg=str(exc))
        raise


if __name__ == '__main__':
    main()
