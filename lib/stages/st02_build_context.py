"""Stage 02: Gather kernel build context (.config, artifacts, logs, Kbuild).

Stage 02 of the kcommit pipeline (absorbed into lib/stages in v9.13).
"""
import os

from lib.config import save_json
from lib.kbuild import load_kernel_config_symbols
from lib.parse_kconfig import parse_kernel_config, scan_kbuild_tree
from lib.pipeline_runtime import update_stage_progress, finish_progress_line
from lib.manifest import CACHE_FILES, NSTAGES


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


def run(cfg, cache):
    kernel       = cfg.get('kernel', {}) or {}
    source_dir   = kernel.get('source_dir')
    kconfig_path = kernel.get('kernel_config')
    if kconfig_path and not os.path.isfile(kconfig_path):
        kconfig_path = None
    build_dir = kernel.get('build_dir')
    if build_dir and not os.path.isdir(build_dir):
        build_dir = None

    # 1. Kernel config symbols
    update_stage_progress(2, NSTAGES, 0.10, 'loading kernel config')
    kernel_config = load_kernel_config_symbols(kconfig_path, source_dir)

    # 2. Parse .config
    update_stage_progress(2, NSTAGES, 0.25, 'parsing .config')
    kernel_config_parsed = parse_kernel_config(kconfig_path)

    # 3. Build logs
    update_stage_progress(2, NSTAGES, 0.40, 'reading build logs')
    kernel_build_log = _read_lines(kernel.get('kernel_build_log'))
    yocto_build_log  = _read_lines(kernel.get('yocto_build_log'))

    # 4. Build artifacts
    update_stage_progress(2, NSTAGES, 0.55, 'scanning build dir')
    build_artifacts = _scan_build_dir(build_dir)

    # 5. Single os.walk for Kbuild tree
    update_stage_progress(2, NSTAGES, 0.70, 'walking kbuild tree')
    if source_dir and os.path.isdir(source_dir):
        static_config_map, kbuild_files = scan_kbuild_tree(source_dir)
    else:
        static_config_map, kbuild_files = {}, []

    # Cache static_config_map so stage 03 can skip its own tree walk
    save_json(os.path.join(cache, CACHE_FILES['kbuild_map']), static_config_map)

    # 6. Save context
    update_stage_progress(2, NSTAGES, 0.90, 'saving build context')
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
    save_json(os.path.join(cache, CACHE_FILES['build_context']), ctx)
    finish_progress_line()
    print('  build context captured')
    return ctx, static_config_map
