"""Stage 02: Gather kernel build context (.config, artifacts, logs, Kbuild).

Stage 02 of the kcommit pipeline (absorbed into lib/stages in v9.13).

Kbuild placeholder aggregators (e.g. built-in.o, built-in.a) are produced by
the kernel build system to concatenate directory-level objects for upward
linking.  They carry no source-level meaning and must not enter the product
map as build-artifact evidence — doing so causes stage 04's L2½ `build_artifact`
check to keep commits that should have been eliminated by the prefilter —
resulting in insufficient commit reduction when a real build tree was provided.
_scan_build_dir() therefore skips these files at collection time.
The authoritative set of excluded names is KBUILD_PLACEHOLDER_NAMES in
lib.kbuild, shared with st03_product_map._extract_log_objects().

v13.0.2 changes (Bug-2 fix):
  - run(): emits a logging.warning (and console print) when static_config_map
    is empty after scanning source_dir.  Kernel sources are mandatory, so an
    empty Kbuild map indicates a scan failure (wrong source_dir, unreadable
    Makefiles, etc.) that should be visible to the user.
  - run(): prints the kconfiglib availability status and the kernel_config
    path being used so the user can confirm the correct inputs are loaded.
"""
import logging
import os

from lib.config import save_json
from lib.kbuild import load_kernel_config_symbols, KBUILD_PLACEHOLDER_NAMES
from lib.parse_kconfig import parse_kernel_config, scan_kbuild_tree
from lib.pipeline_runtime import update_stage_progress, finish_progress_line
from lib.manifest import CACHE_FILES, NSTAGES

# Re-export for backwards compatibility and independent testing.
_KBUILD_PLACEHOLDER_NAMES = KBUILD_PLACEHOLDER_NAMES


def _read_lines(path):
    if not path or not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        return [line.rstrip() for line in f]


def _scan_build_dir(build_dir):
    """Walk *build_dir* and return relative paths of compiled objects.

    Only ``.o`` and ``.ko`` files are collected.  Kbuild directory-aggregator
    placeholders listed in ``KBUILD_PLACEHOLDER_NAMES`` (``built-in.o``,
    ``built-in.a``) are excluded because they are synthetic linker inputs with
    no 1-to-1 source-file correspondence and would cause spurious
    build-artifact hits in the stage-04 prefilter.
    """
    objects = []
    if not build_dir or not os.path.isdir(build_dir):
        return objects
    for root, _, files in os.walk(build_dir):
        for name in files:
            if name in KBUILD_PLACEHOLDER_NAMES:
                continue
            if name.endswith('.o') or name.endswith('.ko'):
                objects.append(
                    os.path.relpath(os.path.join(root, name), build_dir))
    return sorted(objects)


def run(cfg, cache):
    try:
        import kconfiglib as _kcl
        _kcl_available = True
    except Exception:
        _kcl_available = False

    kernel       = cfg.get('kernel', {}) or {}
    source_dir   = kernel.get('source_dir')
    kconfig_path = kernel.get('kernel_config')
    if kconfig_path and not os.path.isfile(kconfig_path):
        logging.warning(
            'st02: kernel_config path does not exist: %s — '
            'kconfig symbol filtering will be disabled.', kconfig_path)
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

    # 4. Build artifacts (built-in.o / built-in.a placeholders excluded)
    update_stage_progress(2, NSTAGES, 0.55, 'scanning build dir')
    build_artifacts = _scan_build_dir(build_dir)

    # 5. Single os.walk for Kbuild tree (mandatory — sources required)
    update_stage_progress(2, NSTAGES, 0.70, 'walking kbuild tree')
    if source_dir and os.path.isdir(source_dir):
        static_config_map, kbuild_files = scan_kbuild_tree(source_dir)
        if not static_config_map:
            logging.warning(
                'st02: kbuild_map is empty after scanning source_dir=%s — '
                'no CONFIG_* symbols found in Makefiles/Kbuild files. '
                'Check that source_dir points to the kernel source root '
                'and that Makefile/Kbuild files are readable.',
                source_dir)
            print('  WARNING: kbuild_map is empty — check source_dir and Makefile access')
    else:
        static_config_map, kbuild_files = {}, []
        logging.warning(
            'st02: source_dir not set or does not exist — '
            'kbuild_map will be empty and kconfig filtering will be disabled. '
            'kernel.source_dir is mandatory for meaningful product-scope filtering.')
        print('  WARNING: source_dir not available — kbuild_map empty')

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
    print('    kconfiglib     : %s' % ('available' if _kcl_available else 'NOT available — using fallback parser'))
    print('    kernel_config  : %s' % (kconfig_path or 'not provided — kconfig filtering disabled'))
    print('    kbuild_map     : %d symbols' % len(static_config_map))
    print('    build_log lines: %d kernel + %d yocto' % (len(kernel_build_log), len(yocto_build_log)))
    print('    build_artifacts: %d objects' % len(build_artifacts))
    return ctx, static_config_map
