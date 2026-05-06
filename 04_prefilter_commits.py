#!/usr/bin/env python3
"""Stage 04: Enrich and pre-filter commits before scoring."""
import argparse, os, time
from lib.logsetup import setup_logging
from lib.config import load_config, apply_override
from lib.pipeline_runtime import (start_stage, finish_stage, fail_stage,
                                   print_stage_input, print_stage_output)
from lib.stages.prefilter import run as stage_run, write_outputs


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
    os.makedirs(cache, exist_ok=True)
    state  = os.path.join(work, 'pipeline_state.json')
    t0     = time.time()
    t      = start_stage(state, 'prefilter_commits', 4, 7)
    try:
        kept, dropped, reasons = stage_run(cfg, cache)
        write_outputs(cfg, dropped, outdir)
        print_stage_output('prefilter', len(kept), dropped=len(dropped),
                           reasons=reasons, elapsed=time.time()-t0)
        finish_stage(state, 'prefilter_commits', t, status='ok',
                     extra={'total': len(kept)+len(dropped),
                            'kept': len(kept), 'dropped': len(dropped),
                            'reasons': reasons})
    except SystemExit: raise
    except Exception as exc:
        import traceback; traceback.print_exc()
        fail_stage(state, 'prefilter_commits', t, error_msg=str(exc)); raise

if __name__ == '__main__': main()
