#!/usr/bin/env python3
"""Stage 02: Gather kernel build context (.config, artifacts, logs, Kbuild).

v7.17: kernel_config and build_dir are optional (notices only); fail_stage.
"""
from __future__ import print_function
import argparse
import os

from lib.config import load_config
from lib.io_utils import ensure_dir, save_json
from lib.kbuild import load_kernel_config_symbols, scan_kbuild_makefiles
from lib.parse_kconfig import parse_kernel_config
from lib.validation import validate_inputs
from lib.pipeline_runtime import start_stage, finish_stage, fail_stage


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
                objects.append(os.path.relpath(os.path.join(root, name), build_dir))
    return sorted(objects)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    args = ap.parse_args()

    cfg        = load_config(args.config)
    work       = cfg.get('project', {}).get('work_dir', './work')
    state_path = os.path.join(work, 'pipeline_state.json')
    started    = start_stage(state_path, 'collect_build_context', 3, 7)

    try:
        problems, notices = validate_inputs(cfg)
        for note in notices:
            print(note)
        if problems:
            for p in problems:
                print(p)
            fail_stage(state_path, 'collect_build_context', started,
                       error_msg='; '.join(problems))
            raise SystemExit(2)

        cache      = os.path.join(work, 'cache')
        ensure_dir(cache)

        inputs     = cfg.get('inputs', {}) or {}
        source_dir = cfg.get('kernel', {}).get('source_dir')

        kconfig_path = inputs.get('kernel_config')
        if kconfig_path and not os.path.isfile(kconfig_path):
            kconfig_path = None

        build_dir = inputs.get('build_dir')
        if build_dir and not os.path.isdir(build_dir):
            build_dir = None

        ctx = {
            'kernel_config':        load_kernel_config_symbols(kconfig_path, source_dir),
            'kernel_config_parsed': parse_kernel_config(kconfig_path),
            'kernel_build_log':     _read_lines(inputs.get('kernel_build_log')),
            'yocto_build_log':      _read_lines(inputs.get('yocto_build_log')),
            'dts_roots':            inputs.get('dts_roots', []),
            'build_dir':            build_dir,
            'build_artifacts':      _scan_build_dir(build_dir),
            'kbuild_files':         scan_kbuild_makefiles(source_dir),
        }

        save_json(os.path.join(cache, 'build_context.json'), ctx)
        print('build context captured')
        finish_stage(state_path, 'collect_build_context', started, status='ok',
                     extra={
                         'build_artifact_count': len(ctx.get('build_artifacts', [])),
                         'kbuild_file_count':    len(ctx.get('kbuild_files', [])),
                         'enabled_config_count': len(ctx.get('kernel_config', [])),
                     })

    except SystemExit:
        raise
    except Exception as exc:
        fail_stage(state_path, 'collect_build_context', started, error_msg=str(exc))
        raise


if __name__ == '__main__':
    main()
