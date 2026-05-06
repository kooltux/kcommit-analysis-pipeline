#!/usr/bin/env python3
"""Stage 00: Validate configuration and compile profile rules."""
import argparse, os
from lib.logsetup import setup_logging
from lib.config import load_config, apply_override
from lib.pipeline_runtime import start_stage, finish_stage, fail_stage
from lib.stages.prepare import run as stage_run


def main():
    ap = argparse.ArgumentParser(description='Validate config and compile rules')
    ap.add_argument('-v', '--verbose', action='count', default=0)
    ap.add_argument('--config',   required=True)
    ap.add_argument('--override', default=None, metavar='JSON')
    args = ap.parse_args()
    setup_logging(args.verbose)

    cfg  = load_config(args.config)
    if args.override: apply_override(cfg, args.override)

    work  = cfg['paths']['work_dir']
    cache = os.path.join(work, 'cache')
    os.makedirs(cache, exist_ok=True)
    state = os.path.join(work, 'pipeline_state.json')
    t     = start_stage(state, 'prepare_pipeline', 0, 7)
    try:
        summary = stage_run(cfg, cache)
        finish_stage(state, 'prepare_pipeline', t, status='ok',
                     extra={'profile_count': len(summary['active_profiles'])})
    except SystemExit:
        fail_stage(state, 'prepare_pipeline', t, error_msg='validation failed'); raise
    except Exception as exc:
        import traceback; traceback.print_exc()
        fail_stage(state, 'prepare_pipeline', t, error_msg=str(exc)); raise

if __name__ == '__main__': main()
