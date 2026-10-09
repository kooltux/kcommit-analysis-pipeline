"""kcommit-analysis-pipeline — cmd_report subcommand."""
import os

from lib.commands.base import load_cfg
from lib.config import ai_active
from lib.manifest import NSTAGES
from lib.pipeline_runtime import (
    fail_stage, finish_stage, init_pipeline_state, start_stage,
)


def cmd_report(args):
    cfg = load_cfg(args)
    work = cfg['paths']['work_dir']
    cache = cfg['paths']['cache_dir']
    outdir = cfg['paths']['output_dir']
    state_path = os.path.join(work, 'pipeline_state.json')
    os.makedirs(outdir, exist_ok=True)
    if not os.path.exists(state_path):
        init_pipeline_state(state_path)
    if args.format:
        valid = {'html', 'csv', 'xlsx', 'ods'}
        formats = [f.strip() for group in args.format for f in group.split(',') if f.strip()]
        invalid = [f for f in formats if f not in valid]
        if invalid:
            import sys
            print(f'Unknown format(s): {", ".join(invalid)}  '
                  f'(valid: html, csv, xlsx, ods)', file=sys.stderr)
            sys.exit(1)
        cfg.setdefault('reports', {})['outputs'] = formats
    from lib.stages.st07_ai_report import run as stage_run
    # v20.1.0: total = stages of this configuration (the AI stage counts only when active).
    total = NSTAGES if ai_active(cfg) else NSTAGES - 1
    token = start_stage(state_path, 'report_commits', 7, total)
    try:
        stats = stage_run(cfg, cache, outdir)
        finish_stage(state_path, 'report_commits', token, status='ok',
                     extra={'total_scored_commits': stats.get('total_scored_commits', 0),
                            'generated_files': stats.get('generated_files', [])})
    except Exception as exc:
        fail_stage(state_path, 'report_commits', token, error_msg=str(exc))
        raise SystemExit(1)
    print(f'Reports written to {outdir}')
    print(f'  {stats.get("total_scored_commits", 0)} commits')
