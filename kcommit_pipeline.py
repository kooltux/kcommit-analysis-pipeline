#!/usr/bin/env python3
"""kcommit-analysis-pipeline — top-level CLI entry point.

All subcommand logic lives in lib/commands/cmd_*.py.

Subcommands
───────────
  run       Run the full pipeline (or a subset of stages)
  status    Show stage completion status for a work directory
  validate  Validate config without running anything
  report    Re-generate output reports from cached scored data
  dropped   Inspect commits dropped by pre/post filter
  diagnose  Full JSON diagnosis of one commit across all pipeline stages

Usage examples
──────────────
  kcommit_pipeline.py run      --config cfg.json
  kcommit_pipeline.py run      --config cfg.json --from 4
  kcommit_pipeline.py run      --config cfg.json --stage 5
  kcommit_pipeline.py run      --config cfg.json --resume
  kcommit_pipeline.py run      --config cfg.json --override '{"filter":{"min_score":20}}'
  kcommit_pipeline.py run      --config cfg.json --progress-json
  kcommit_pipeline.py status   --config cfg.json
  kcommit_pipeline.py validate --config cfg.json
  kcommit_pipeline.py report   --config cfg.json [--format html] [--format xlsx]
  kcommit_pipeline.py dropped  --config cfg.json [--reason all|prefilter|low-score]
  kcommit_pipeline.py diagnose --cache-dir work/cache --sha <SHA_PREFIX>
  kcommit_pipeline.py diagnose --cache-dir work/cache --sha <SHA_PREFIX> --out report.json
  kcommit_pipeline.py diagnose --config cfg.json     --sha <SHA_PREFIX>   # config fallback
"""
import argparse
import sys

from lib.logsetup import setup_logging
from lib.manifest import VERSION
from lib.commands.cmd_run      import cmd_run
from lib.commands.cmd_status   import cmd_status
from lib.commands.cmd_validate import cmd_validate
from lib.commands.cmd_report   import cmd_report
from lib.commands.cmd_dropped  import cmd_dropped
from lib.commands.cmd_diagnose import cmd_diagnose

def main():
    ap = argparse.ArgumentParser(
        prog='kcommit_pipeline.py',
        description=f'kcommit-analysis-pipeline {VERSION}',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('-v', '--verbose', action='count', default=0)
    sub = ap.add_subparsers(dest='cmd', metavar='SUBCOMMAND')
    sub.required = True

    p_run = sub.add_parser('run', help='Run pipeline stages')
    p_run.add_argument('--config',   required=True)
    p_run.add_argument('--override', default=None, metavar='JSON')
    p_run.add_argument('--stage',    default=None)
    p_run.add_argument('--from',     dest='from_', default=None)
    p_run.add_argument('--resume',   action='store_true')
    p_run.add_argument('--force',    action='store_true')
    p_run.add_argument('--progress-json', action='store_true')

    p_st = sub.add_parser('status', help='Show stage completion status')
    p_st.add_argument('--config',   required=True)
    p_st.add_argument('--override', default=None, metavar='JSON')

    p_val = sub.add_parser('validate', help='Validate config without running')
    p_val.add_argument('--config',   required=True)
    p_val.add_argument('--override', default=None, metavar='JSON')

    p_rep = sub.add_parser('report', help='Re-generate reports from cached data')
    p_rep.add_argument('--config',   required=True)
    p_rep.add_argument('--override', default=None, metavar='JSON')
    p_rep.add_argument('--format', action='append', dest='format',
                       metavar='FMT',
                       help='Output format(s): html,csv,xlsx,ods — '
                            'comma-separated or repeated (e.g. --format html,ods)')

    p_dr = sub.add_parser('dropped', help='Inspect filtered-out commits')
    p_dr.add_argument('--config',   required=True)
    p_dr.add_argument('--override', default=None, metavar='JSON')
    p_dr.add_argument('--reason',   default='all',
                      choices=['all', 'prefilter', 'low-score'])
    p_dr.add_argument('--json',     action='store_true')

    p_diag = sub.add_parser(
        'diagnose',
        help='Full JSON diagnosis of one commit across all pipeline stages',
        description=(
            'Trace a single commit through every pipeline stage and emit a '
            'self-contained JSON report.  Only the cache directory is required; '
            'no config file needed.\n\n'
            'Report sections: meta, commit, cache_presence, prefilter '
            '(with full debug_detail), scoring (per-profile breakdown), '
            'postfilter (threshold + outcome), final (rank + human summary), '
            'warnings.'
        ),
    )
    # Primary: just the cache dir -- no config file needed
    p_diag.add_argument('--cache-dir', dest='cache_dir', default=None,
                        metavar='DIR',
                        help='Path to the pipeline cache directory '
                             '(e.g. work/cache).  Takes precedence over --config.')
    # Fallback: derive cache_dir from a config file
    p_diag.add_argument('--config', default=None,
                        help='Config file to derive cache_dir from '
                             '(used only when --cache-dir is not provided).')
    p_diag.add_argument('--sha',   required=True,
                        help='SHA prefix to look up (min 7 chars)')
    p_diag.add_argument('--out',   default=None, metavar='FILE',
                        help='Write JSON report to FILE instead of stdout')

    args = ap.parse_args()
    setup_logging(args.verbose)
    dispatch = {
        'run':      cmd_run,
        'status':   cmd_status,
        'validate': cmd_validate,
        'report':   cmd_report,
        'dropped':  cmd_dropped,
        'diagnose': cmd_diagnose,
    }
    dispatch[args.cmd](args)


if __name__ == '__main__':
    main()
