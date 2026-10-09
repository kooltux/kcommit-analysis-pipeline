"""Run pipeline stages; Stage 08 (AI work package) runs when the config enables AI."""
import os

from lib.commands.base import (
    STAGE_ORDER, emit_progress, load_cfg, load_state, resolve_stage,
    run_stage, stage_needs_run,
)
from lib.config import ai_active
from lib.manifest import STAGE_OUTPUTS
from lib.pipeline_runtime import init_pipeline_state, set_stage_total, wipe_downstream
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
    # v20.1.0: AI preparation is driven by the configuration only (ai section
    # present and ai.enabled not false); there is no --ai option.
    enabled = ai_active(cfg)
    ai_error = ('AI is not enabled in the configuration: declare an "ai" section '
                'and do not set "ai.enabled" to false')
    selected = [(i, k, fn) for i, (k, fn) in enumerate(STAGES)
                if enabled or k != 'prepare_ai_analysis']
    if args.stage is not None:
        idx, key = resolve_stage(args.stage)
        if key == 'prepare_ai_analysis' and not enabled:
            raise SystemExit(ai_error)
        if args.force:
            wipe_downstream(state_path, key, work, STAGE_OUTPUTS,
                            stage_order=STAGE_ORDER, base_dirs=base_dirs)
        run_list = [(idx, key, STAGES[idx][1])]
    elif args.from_ is not None:
        from_idx, from_key = resolve_stage(args.from_)
        if from_key == 'prepare_ai_analysis' and not enabled:
            raise SystemExit(ai_error)
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
    # v20.1.0: the displayed stage total is the number of stages of this
    # configuration (8, or 9 when the optional AI stage is active).
    set_stage_total(len(selected))
    try:
        for idx, key, fn in run_list:
            run_stage(idx, key, fn, cfg, cache, work, state_path, args)
    finally:
        set_stage_total(None)
    if args.progress_json:
        emit_progress(-1, 'pipeline', 'complete')
    else:
        print('\nPipeline completed successfully.')
