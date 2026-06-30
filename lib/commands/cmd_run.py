"""kcommit-analysis-pipeline — cmd_run subcommand.

v18.2.0 — fix --force and artifact wipe:
  Bug 1: --stage N --force now correctly wipes artifacts for stage N and all
         downstream stages before running only stage N.
  Bug 2: wipe_downstream() is now passed base_dirs so that cache/ and output/
         prefixed paths are resolved against the real cache_dir / output_dir
         rather than work_dir.  This fixes the long-standing issue where
         --force left stale artifacts on disk.
  Bug 3: --stage N (with or without --force) runs only stage N, never
         downstream stages.  Use --from N to run N and all downstream.

v18.2.1 — fix residual path-mismatch in wipe_downstream:
  All paths fed to wipe_downstream are now normalised with os.path.realpath()
  so that relative vs. absolute or symlinked paths never cause a mismatch
  between what the wipe targets and what the stage functions actually wrote.
  stage_needs_run() in base.py receives the same base_dirs so that --resume
  also finds files correctly.

  Fix dynamic output wipe for report_commits:
  MANIFEST.json 'outputs' for report_commits now enumerates all conditional
  output files (csv, xlsx, ods variants, filtered_commits.json,
  prefilter_debug.json, pipeline_run_stats.json, summary.*) so that
  wipe_downstream() deletes them on --force runs without any directory-glob
  logic.  Only files explicitly owned by report_commits are touched;
  upstream cache/ and output/ files from other stages are preserved.
"""
import os

from lib.commands.base import (
    STAGE_ORDER,
    emit_progress,
    load_cfg,
    load_state,
    resolve_stage,
    run_stage,
    stage_needs_run,
)
from lib.manifest import STAGE_OUTPUTS
from lib.pipeline_runtime import init_pipeline_state, wipe_downstream
from lib.stages import STAGES


def cmd_run(args):
    cfg = load_cfg(args)

    # Normalise all paths up-front so every subsystem sees identical strings.
    work   = os.path.realpath(cfg['paths']['work_dir'])
    cache  = os.path.realpath(cfg['paths']['cache_dir'])
    outdir = os.path.realpath(cfg['paths']['output_dir'])

    # Propagate normalised paths back into cfg so stage functions use them too.
    cfg['paths']['work_dir']   = work
    cfg['paths']['cache_dir']  = cache
    cfg['paths']['output_dir'] = outdir

    state_path = os.path.join(work, 'pipeline_state.json')
    os.makedirs(cache,  exist_ok=True)
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(work,   exist_ok=True)
    if not os.path.exists(state_path):
        init_pipeline_state(state_path)

    # base_dirs lets wipe_downstream resolve 'cache/...' and 'output/...'
    # paths correctly regardless of where work_dir lives.
    _base_dirs = {'cache': cache, 'output': outdir}

    # Determine run list
    if args.stage is not None:
        idx, key = resolve_stage(args.stage)
        if args.force:
            # Wipe the target stage and all downstream stages from both
            # state and disk, then run only the target stage.
            # Use --from N to rebuild N and everything downstream in one go.
            wipe_downstream(state_path, key, work, STAGE_OUTPUTS,
                            stage_order=STAGE_ORDER, base_dirs=_base_dirs)
        run_list = [(idx, key, STAGES[idx][1])]

    elif args.from_ is not None:
        from_idx, from_key = resolve_stage(args.from_)
        wipe_downstream(state_path, from_key, work, STAGE_OUTPUTS,
                        stage_order=STAGE_ORDER, base_dirs=_base_dirs)
        run_list = [(i, k, fn) for i, (k, fn) in enumerate(STAGES) if i >= from_idx]

    elif args.resume:
        state    = load_state(state_path)
        run_list = [(i, k, fn) for i, (k, fn) in enumerate(STAGES)
                    if stage_needs_run(k, work, state, base_dirs=_base_dirs)]
        if not run_list:
            print('All stages complete — nothing to do. Use --force to re-run.')
            return
        print(f'  resume: running {len(run_list)} pending stage(s): '
              + ', '.join(str(i) for i, _, _ in run_list))

    else:
        run_list = [(i, k, fn) for i, (k, fn) in enumerate(STAGES)]
        if args.force:
            wipe_downstream(state_path, STAGE_ORDER[0], work, STAGE_OUTPUTS,
                            stage_order=STAGE_ORDER, base_dirs=_base_dirs)

    for (idx, key, fn) in run_list:
        run_stage(idx, key, fn, cfg, cache, work, state_path, args)

    if args.progress_json:
        emit_progress(-1, 'pipeline', 'complete')
    else:
        print('\nPipeline completed successfully.')
