#!/usr/bin/env python3
"""Stage 06: Apply score threshold; append low-score drops to filtered list."""
import argparse, os, time
from lib.logsetup import setup_logging
from lib.config import load_config, apply_override
from lib.pipeline_runtime import (start_stage, finish_stage, fail_stage,
                                   print_stage_output)
from lib.stages.postfilter import run as stage_run


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
    threshold = float((cfg.get('filter', {}) or {}).get('min_score', 0) or 0)
    t0    = time.time()
    t     = start_stage(state, 'postfilter_commits', 6, 7)
    try:
        relevant, low_score = stage_run(cfg, cache)
        print_stage_output('postfilter', len(relevant),
                           dropped=len(low_score),
                           reasons={f'score>={threshold}': len(relevant),
                                    f'score<{threshold}':  len(low_score)},
                           elapsed=time.time()-t0)
        finish_stage(state, 'postfilter_commits', t, status='ok',
                     extra={'output_count': len(relevant),
                            'dropped_count': len(low_score),
                            'min_score': threshold})
    except SystemExit: raise
    except Exception as exc:
        import traceback; traceback.print_exc()
        fail_stage(state, 'postfilter_commits', t, error_msg=str(exc)); raise

if __name__ == '__main__': main()
