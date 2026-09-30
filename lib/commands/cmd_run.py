"""Run pipeline stages, with optional AI work-package preparation."""
import os

from lib.commands.base import (
    STAGE_ORDER, emit_progress, load_cfg, load_state, resolve_stage,
    run_stage, stage_needs_run,
)
from lib.manifest import STAGE_OUTPUTS
from lib.pipeline_runtime import init_pipeline_state, wipe_downstream
from lib.stages import STAGES


def cmd_run(args):
    cfg = load_cfg(args)
    work = os.path.realpath(cfg['paths']['work_dir'])
    cache = os.path.realpath(cfg['paths']['cache_dir'])
    outdir = os.path.realpath(cfg['paths']['output_dir'])
    cfg['paths']['work_dir'] = work
    cfg['paths']['cache_dir'] = cache
    cfg['paths']['output_dir'] = outdir
    state_path = os.path.join(work, 'pipeline_state.json')
    os.makedirs(cache, exist_ok=True)
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(work, exist_ok=True)
    if not os.path.exists(state_path):
        init_pipeline_state(state_path)
    base_dirs = {'cache': cache, 'output': outdir}
    enabled = getattr(args, 'ai', False) is True
    selected = [(i, k, fn) for i, (k, fn) in enumerate(STAGES)
                if enabled or k != 'prepare_ai_analysis']
    if args.stage is not None:
        idx, key = resolve_stage(args.stage)
        if enabled and key != 'prepare_ai_analysis':
            raise SystemExit('--ai cannot be combined with --stage other than 8')
        if args.force:
            wipe_downstream(state_path, key, work, STAGE_OUTPUTS,
                            stage_order=STAGE_ORDER, base_dirs=base_dirs)
        run_list = [(idx, key, STAGES[idx][1])]
    elif args.from_ is not None:
        from_idx, from_key = resolve_stage(args.from_)
        if from_key == 'prepare_ai_analysis' and not enabled:
            raise SystemExit('Use --ai with --from 8, or use --stage 8')
        wipe_downstream(state_path, from_key, work, STAGE_OUTPUTS,
                        stage_order=STAGE_ORDER, base_dirs=base_dirs)
        run_list = [(i, k, fn) for i, k, fn in selected if i >= from_idx]
    elif args.resume:
        state = load_state(state_path)
        run_list = [(i, k, fn) for i, k, fn in selected
                    if stage_needs_run(k, work, state, base_dirs=base_dirs)]
        if not run_list:
            print('All stages complete — nothing to do. Use --force to re-run.')
            return
        print(f'  resume: running {len(run_list)} pending stage(s): '
              + ', '.join(str(i) for i, _, _ in run_list))
    else:
        run_list = selected
        if args.force:
            wipe_downstream(state_path, STAGE_ORDER[0], work, STAGE_OUTPUTS,
                            stage_order=STAGE_ORDER, base_dirs=base_dirs)
    for idx, key, fn in run_list:
        run_stage(idx, key, fn, cfg, cache, work, state_path, args)
    if args.progress_json:
        emit_progress(-1, 'pipeline', 'complete')
    else:
        print('\nPipeline completed successfully.')
