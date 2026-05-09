"""kcommit-analysis-pipeline — cmd_run subcommand."""
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

    work       = cfg['paths']['work_dir']
    cache      = cfg['paths']['cache_dir']
    state_path = os.path.join(work, 'pipeline_state.json')
    os.makedirs(cache,  exist_ok=True)
    os.makedirs(cfg['paths']['output_dir'], exist_ok=True)
    if not os.path.exists(state_path):
        init_pipeline_state(state_path)

    # Determine run list
    if args.stage is not None:
        idx, key = resolve_stage(args.stage)
        run_list = [(idx, key, STAGES[idx][1])]
        if args.force:
            wipe_downstream(state_path, key, work, STAGE_OUTPUTS,
                            stage_order=STAGE_ORDER)
    elif args.from_ is not None:
        from_idx, from_key = resolve_stage(args.from_)
        run_list = [(i, k, fn) for i, (k, fn) in enumerate(STAGES) if i >= from_idx]
        wipe_downstream(state_path, from_key, work, STAGE_OUTPUTS,
                        stage_order=STAGE_ORDER)
    elif args.resume:
        state    = load_state(state_path)
        run_list = [(i, k, fn) for i, (k, fn) in enumerate(STAGES)
                    if stage_needs_run(k, work, state)]
        if not run_list:
            print('All stages complete — nothing to do. Use --force to re-run.')
            return
        print(f'  resume: running {len(run_list)} pending stage(s): '
              + ', '.join(str(i) for i, _, _ in run_list))
    else:
        run_list = [(i, k, fn) for i, (k, fn) in enumerate(STAGES)]

    for (idx, key, fn) in run_list:
        run_stage(idx, key, fn, cfg, cache, work, state_path, args)

    if args.progress_json:
        emit_progress(-1, 'pipeline', 'complete')
    else:
        print('\nPipeline completed successfully.')


# ── Sub-command: status ───────────────────────────────────────────────────────
