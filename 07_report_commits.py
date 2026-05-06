#!/usr/bin/env python3
"""Stage 07: Generate all output formats (HTML, CSV, XLSX, ODS, JSON)."""
import argparse, os, time
from lib.logsetup import setup_logging
from lib.config import load_config, apply_override
from lib.pipeline_runtime import (start_stage, finish_stage, fail_stage,
                                   print_stage_output)
from lib.stages.report import run as stage_run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-v', '--verbose', action='count', default=0)
    ap.add_argument('--config',   required=True)
    ap.add_argument('--override', default=None, metavar='JSON')
    args = ap.parse_args()
    setup_logging(args.verbose)

    cfg  = load_config(args.config)
    if args.override: apply_override(cfg, args.override)

    work   = cfg['paths']['work_dir']
    cache  = os.path.join(work, 'cache')
    outdir = cfg.get('paths', {}).get('output_dir') or os.path.join(work, 'output')
    os.makedirs(outdir, exist_ok=True)
    state  = os.path.join(work, 'pipeline_state.json')
    t0     = time.time()
    t      = start_stage(state, 'report_commits', 7, 7)
    try:
        stats = stage_run(cfg, cache, outdir)
        print_stage_output('reports', stats.get('total_scored_commits', 0),
                           elapsed=time.time()-t0)
        finish_stage(state, 'report_commits', t, status='ok', extra=stats)
    except SystemExit: raise
    except Exception as exc:
        import traceback; traceback.print_exc()
        fail_stage(state, 'report_commits', t, error_msg=str(exc)); raise

if __name__ == '__main__': main()
