#!/usr/bin/env python3
"""Stage 01: Collect commits from the git revision range."""
import argparse, os, time
from lib.logsetup import setup_logging
from lib.config import load_config, apply_override
from lib.pipeline_runtime import (start_stage, finish_stage, fail_stage,
                                   print_stage_input, print_stage_output)
from lib.stages.collect import run as stage_run


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
    k     = cfg.get('kernel', {}) or {}
    print_stage_input('git log', f"{k.get('rev_old','')}..{k.get('rev_new','')}")
    t0    = time.time()
    t     = start_stage(state, 'collect_commits', 1, 7)
    try:
        commits = stage_run(cfg, cache)
        print(f'  collected {len(commits)} commits')
        print_stage_output('commits', len(commits), elapsed=time.time()-t0)
        finish_stage(state, 'collect_commits', t, status='ok',
                     extra={'commit_count': len(commits)})
    except SystemExit: raise
    except Exception as exc:
        import traceback; traceback.print_exc()
        fail_stage(state, 'collect_commits', t, error_msg=str(exc)); raise

if __name__ == '__main__': main()
