#!/usr/bin/env python3
"""Top-level pipeline driver for kcommit-analysis-pipeline.

Usage:
  # Run all stages
  python3 kcommit_pipeline.py --config /path/to/cfg.json

  # Run a single stage
  python3 kcommit_pipeline.py --config /path/to/cfg.json --stage 4

  # Re-run from stage 3 onwards
  python3 kcommit_pipeline.py --config /path/to/cfg.json --from 3

  # Dry-run: validate and print resolved config
  python3 kcommit_pipeline.py --config /path/to/cfg.json --dry-run
"""
import argparse
import os
import subprocess
import sys

from lib.config import load_config
from lib.manifest import VERSION, load_manifest
from lib.validation import validate_inputs
from lib.pipeline_runtime import (is_stage_done,
                                   wipe_downstream, init_pipeline_state)

# Derive STAGES list from MANIFEST.json — single source of truth.
_manifest = load_manifest()
STAGES = [(s['index'], s['script'], s['key'])
          for s in _manifest['pipeline_stages']]

# Explicit stage ordering for wipe_downstream — deterministic on fresh workspaces.
STAGE_ORDER = [s[2] for s in STAGES]

STAGE_OUTPUTS = {
    'prepare_pipeline':       ['cache/compiled_rules.json', 'cache/prepare_summary.json'],
    'collect_commits':        ['cache/commits.json'],
    'collect_build_context':  ['cache/build_context.json', 'cache/kbuild_static_map.json'],
    'build_product_map':      ['cache/product_map.json'],
    'enrich_commits':         ['cache/enriched_commits.json'],
    'score_commits':          ['cache/scored_commits.json'],
    'report_commits':         ['output/relevant_commits.csv',
                               'output/relevant_commits.json',
                               'output/report_stats.json',
                               'output/profile_summary.json',
                               'output/profile_matrix.csv',
                               'output/summary.html'],
}


def _resolve_stage(val):
    """Return (index, script, key) for a stage given name, script, or int."""
    if val is None:
        return None
    try:
        idx = int(val)
        for s in STAGES:
            if s[0] == idx:
                return s
        raise SystemExit(f'unknown stage number: {idx}')
    except ValueError:
        for s in STAGES:
            if val in (s[1], s[2], s[1].replace('.py', '')):
                return s
        raise SystemExit(f'unknown stage: {val}')


def _dry_run(cfg, args):
    meta       = cfg.get('_meta', {}) or {}
    work       = cfg['paths']['work_dir']
    kernel_cfg = (cfg.get('kernel', {}) or {}).get('kernel_config', 'N/A')
    build_dir  = (cfg.get('kernel', {}) or {}).get('build_dir', 'N/A')
    source_dir = (cfg.get('kernel', {}) or {}).get('source_dir', 'N/A')
    rev_old    = (cfg.get('kernel', {}) or {}).get('rev_old', 'N/A')
    rev_new    = (cfg.get('kernel', {}) or {}).get('rev_new', 'N/A')
    profiles   = (cfg.get('profiles', {}) or {}).get('active') or \
                 cfg.get('active_profiles', [])

    print(f'=== kcommit-analysis-pipeline {VERSION} -- DRY RUN ===')
    print('Config    :', args.config)
    print('TOOLDIR   :', (meta.get('vars', {}) or {}).get('TOOLDIR', os.environ.get('TOOLDIR', '?')))
    print('Work dir  :', work)
    print('Source dir:', source_dir)
    print(f'Revision  : {rev_old} .. {rev_new}')
    print('Kernel cfg:', kernel_cfg)
    print('Build dir :', build_dir)
    if isinstance(profiles, dict):
        print('Profiles  :')
        for pn, pw in profiles.items():
            print(f'  {pn} (weight {pw})')
    else:
        print('Profiles  :', ', '.join(str(p) for p in profiles))
    print('Scoring   :', cfg.get('scoring', {}))
    print('Collect   :', cfg.get('collect', {}))

    problems, notices = validate_inputs(cfg)
    for n in notices:
        print('NOTICE:', n)
    if problems:
        for p in problems:
            print('ERROR:', p)
        raise SystemExit(1)
    print('Configuration looks OK.')


def main():
    ap = argparse.ArgumentParser(
        description=f'kcommit-analysis-pipeline runner {VERSION}')
    ap.add_argument('--config',   required=True,  help='Path to JSON config file')
    ap.add_argument('--stage',    default=None,   help='Run only this stage (number or name)')
    ap.add_argument('--from',     dest='from_',   default=None,
                    help='Run from this stage onwards (wipes downstream cache)')
    ap.add_argument('--force',    action='store_true',
                    help='Re-run stage even if already OK (implies --from)')
    ap.add_argument('--dry-run',  action='store_true',
                    help='Validate config and print resolved paths; do not run')
    args = ap.parse_args()

    # --stage and --from are mutually exclusive
    if args.stage is not None and args.from_ is not None:
        ap.error('--stage and --from are mutually exclusive')

    cfg        = load_config(args.config)
    work       = cfg['paths']['work_dir']
    state_path = os.path.join(work, 'pipeline_state.json')
    os.makedirs(os.path.join(work, 'cache'),  exist_ok=True)
    os.makedirs(os.path.join(work, 'output'), exist_ok=True)

    if not os.path.exists(state_path):
        init_pipeline_state(state_path)

    if args.dry_run:
        _dry_run(cfg, args)
        raise SystemExit(0)

    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Determine which stages to run
    if args.stage is not None:
        target   = _resolve_stage(args.stage)
        run_list = [target]
        if args.force:
            wipe_downstream(state_path, target[2], work, STAGE_OUTPUTS,
                            stage_order=STAGE_ORDER)
    elif args.from_ is not None:
        from_stage = _resolve_stage(args.from_)
        run_list   = [s for s in STAGES if s[0] >= from_stage[0]]
        wipe_downstream(state_path, from_stage[2], work, STAGE_OUTPUTS,
                        stage_order=STAGE_ORDER)
    else:
        run_list = list(STAGES)

    for (idx, script, key) in run_list:
        if not args.force and is_stage_done(state_path, key):
            print(f'[stage {idx}] {key} already OK – skipping (use --force to re-run)')
            continue

        script_path = os.path.join(script_dir, script)
        print(f'\n[stage {idx}] running {script} ...')
        ret = subprocess.run(
            [sys.executable, script_path, '--config', args.config]
        ).returncode
        if ret != 0:
            print(f'\n[stage {idx}] FAILED (exit {ret})')
            next_stages = [s for s in STAGES if s[0] > idx]
            if next_stages:
                print(f'  re-run hint:  python3 kcommit_pipeline.py '
                      f'--config {args.config} --from {idx}')
            raise SystemExit(ret)

    print('\nPipeline completed successfully.')


if __name__ == '__main__':
    main()
