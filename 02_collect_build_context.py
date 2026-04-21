#!/usr/bin/env python3
# Gather product build context such as .config lines, optional build artifacts, build logs, DTS roots, and Kbuild metadata.
from __future__ import print_function
import argparse
import os
from lib.config import load_config
from lib.io_utils import ensure_dir, save_json
from lib.kbuild import load_kernel_config_symbols, scan_kbuild_makefiles
from lib.validation import validate_inputs
from lib.pipeline_runtime import start_stage, finish_stage


def read_lines(path):
    if not path or not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        return [line.rstrip('
') for line in f]


def scan_build_dir(build_dir):
    # If a build directory exists, collect a lightweight inventory of object and module artifacts.
    objects = []
    if not build_dir or not os.path.isdir(build_dir):
        return objects
    for root, _, files in os.walk(build_dir):
        for name in files:
            if name.endswith('.o') or name.endswith('.ko'):
                objects.append(os.path.relpath(os.path.join(root, name), build_dir))
    return sorted(objects)


def main():
    # Parse arguments, load the merged configuration, validate mandatory inputs, and capture build context.
    ap = argparse.ArgumentParser(); ap.add_argument('--config', required=True); args = ap.parse_args()
    cfg = load_config(args.config)
    state_path = os.path.join(cfg.get('project', {}).get('work_dir', './work'), 'pipeline_state.json')
    started = start_stage(state_path, 'collect_build_context', 2, 6)
    problems, notices = validate_inputs(cfg)
    for note in notices:
        print(note)
    if problems:
        for problem in problems:
            print(problem)
        raise SystemExit(2)
    work = cfg.get('project', {}).get('work_dir', './work')
    cache = os.path.join(work, 'cache'); ensure_dir(cache)
    inputs = cfg.get('inputs', {})
    source_dir = cfg.get('kernel', {}).get('source_dir')
    ctx = {
        'kernel_config': load_kernel_config_symbols(inputs.get('kernel_config')),
        'kernel_build_log': read_lines(inputs.get('kernel_build_log')),
        'yocto_build_log': read_lines(inputs.get('yocto_build_log')),
        'dts_roots': inputs.get('dts_roots', []),
        'build_dir': inputs.get('build_dir'),
        'build_artifacts': scan_build_dir(inputs.get('build_dir')),
        'kbuild_files': scan_kbuild_makefiles(source_dir),
    }
    save_json(os.path.join(cache, 'build_context.json'), ctx)
    print('build context captured')
    finish_stage(state_path, 'collect_build_context', started, status='ok', extra={'build_artifact_count': len(ctx.get('build_artifacts', [])), 'kbuild_file_count': len(ctx.get('kbuild_files', []))})


if __name__ == '__main__':
    main()
