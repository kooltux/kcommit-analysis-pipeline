"""kcommit-analysis-pipeline — cmd_report subcommand."""
import os
import time

from lib.commands.base import load_cfg
from lib.manifest import NSTAGES
from lib.pipeline_runtime import (
    fail_stage,
    finish_stage,
    init_pipeline_state,
    start_stage,
)


def cmd_report(args):
    cfg        = load_cfg(args)
    work       = cfg['paths']['work_dir']
    cache      = cfg['paths']['cache_dir']
    outdir     = cfg['paths']['output_dir']
    state_path = os.path.join(work, 'pipeline_state.json')
    os.makedirs(outdir, exist_ok=True)
    if not os.path.exists(state_path):
        init_pipeline_state(state_path)

    if args.format:
        _valid = {'html', 'csv', 'xlsx', 'ods'}
        _fmts  = [f.strip() for fs in args.format for f in fs.split(',') if f.strip()]
        _bad   = [f for f in _fmts if f not in _valid]
        if _bad:
            import sys as _sys
            print(f'Unknown format(s): {", ".join(_bad)}  '
                  f'(valid: html, csv, xlsx, ods)', file=_sys.stderr)
            _sys.exit(1)
        reports = cfg.setdefault('reports', {})
        reports['outputs'] = _fmts

    from lib.stages.st07_report import run as stage_run
    t0    = time.time()
    t_tok = start_stage(state_path, 'report_commits', 7, NSTAGES)
    try:
        stats = stage_run(cfg, cache, outdir)
        finish_stage(state_path, 'report_commits', t_tok, status='ok',
                     extra={'total_scored_commits': stats.get('total_scored_commits', 0),
                            'generated_files': stats.get('generated_files', [])})
    except Exception as exc:
        fail_stage(state_path, 'report_commits', t_tok, error_msg=str(exc))
        raise SystemExit(1)
    print(f'Reports written to {outdir}')
    print(f'  {stats.get("total_scored_commits", 0)} commits')


# ── Sub-command: dropped ──────────────────────────────────────────────────────
