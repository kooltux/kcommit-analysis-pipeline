#!/usr/bin/env python3
"""Stage 05: Score filtered commits via profile/rule matching."""
import argparse, os, time
from lib.logsetup import setup_logging
from lib.config import load_config, apply_override
from lib.pipeline_runtime import (start_stage, finish_stage, fail_stage,
                                   print_stage_input, print_stage_output)
from lib.stages.score import run as stage_run


def main():
    ap = argparse.ArgumentParser()
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
    t0    = time.time()
    t     = start_stage(state, 'score_commits', 5, 7)
    try:
        scored = stage_run(cfg, cache)
        print_stage_output('scored commits', len(scored), elapsed=time.time()-t0)
        finish_stage(state, 'score_commits', t, status='ok',
                     extra={'scored_count': len(scored)})
    except SystemExit: raise
    except Exception as exc:
        import traceback; traceback.print_exc()
        fail_stage(state, 'score_commits', t, error_msg=str(exc)); raise

if __name__ == '__main__': main()
