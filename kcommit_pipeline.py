#!/usr/bin/env python3
"""kcommit-analysis-pipeline — top-level CLI entry point.

Run stages 00–07 normally; Stage 08 (AI preparation) runs when the configuration
declares an "ai" section that is not disabled with "ai.enabled": false.
Subcommands: run, status, validate, report, dropped, diagnose, cp-check, ai-import.
"""
import argparse

from lib.logsetup import setup_logging
from lib.manifest import VERSION
from lib.commands.cmd_run import cmd_run
from lib.commands.cmd_status import cmd_status
from lib.commands.cmd_validate import cmd_validate
from lib.commands.cmd_report import cmd_report
from lib.commands.cmd_dropped import cmd_dropped
from lib.commands.cmd_diagnose import cmd_diagnose
from lib.commands.cmd_cp_check import cmd_cp_check
from lib.commands.cmd_ai_import import cmd_ai_import

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
    p_run.add_argument('--config', required=True)
    p_run.add_argument('--override', default=None, metavar='JSON')
    p_run.add_argument('--stage', default=None)
    p_run.add_argument('--from', dest='from_', default=None)
    p_run.add_argument('--resume', action='store_true')
    p_run.add_argument('--force', action='store_true')
    p_run.add_argument('--progress-json', action='store_true')

    p_st = sub.add_parser('status', help='Show stage completion status')
    p_st.add_argument('--config', required=True)
    p_st.add_argument('--override', default=None, metavar='JSON')

    p_val = sub.add_parser('validate', help='Validate config without running')
    p_val.add_argument('--config', required=True)
    p_val.add_argument('--override', default=None, metavar='JSON')

    p_rep = sub.add_parser('report', help='Re-generate reports from cached data')
    p_rep.add_argument('--config', required=True)
    p_rep.add_argument('--override', default=None, metavar='JSON')
    p_rep.add_argument('--format', action='append', dest='format', metavar='FMT',
                       help='Output formats html,csv,xlsx,ods (comma-separated or repeated)')

    p_import = sub.add_parser('ai-import', help='Validate and import AI analysis results')
    p_import.add_argument('--config', required=True)
    p_import.add_argument('--override', default=None, metavar='JSON')
    p_import.add_argument('--results-bundle', required=True, metavar='ZIP')

    p_dr = sub.add_parser('dropped', help='Inspect filtered-out commits')
    p_dr.add_argument('--config', required=True)
    p_dr.add_argument('--override', default=None, metavar='JSON')
    p_dr.add_argument('--reason', default='all',
                      choices=['all', 'prefilter', 'low-score'])
    p_dr.add_argument('--json', action='store_true')

    p_diag = sub.add_parser(
        'diagnose', help='Full JSON diagnosis of one commit across all pipeline stages',
        description=(
            'Post-run diagnostic tool. Requires only the cache directory.\n'
            'Traces a commit through collection, prefilter, scoring, and postfilter;\n'
            'reports source metadata, cache presence, final rank and warnings.'),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_diag.add_argument('--cache-dir', dest='cache_dir', required=True, metavar='DIR')
    p_diag.add_argument('--sha', required=True, help='Full or partial SHA (min 7 chars)')
    p_diag.add_argument('--out', default=None, metavar='FILE')

    p_cp = sub.add_parser(
        'cp-check', help='Test cherry-pick feasibility for the prefilter commit set',
        description=('Standalone cherry-pick feasibility checker. Requires stage 04 '
                     'cache and a target revision. --force resets target cache; '
                     '--update tests untested commits only.'),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_cp.add_argument('--config', required=True)
    p_cp.add_argument('--override', default=None, metavar='JSON')
    p_cp_mode = p_cp.add_mutually_exclusive_group()
    p_cp_mode.add_argument('--force', action='store_true')
    p_cp_mode.add_argument('--update', action='store_true')
    p_cp.add_argument('--json', action='store_true')

    args = ap.parse_args()
    setup_logging(args.verbose)
    dispatch = {
        'run': cmd_run, 'status': cmd_status, 'validate': cmd_validate,
        'report': cmd_report, 'ai-import': cmd_ai_import,
        'dropped': cmd_dropped, 'diagnose': cmd_diagnose, 'cp-check': cmd_cp_check,
    }
    dispatch[args.cmd](args)


if __name__ == '__main__':
    main()
