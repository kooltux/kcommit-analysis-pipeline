#!/usr/bin/env python3
"""kcommit-analysis-pipeline — top-level CLI.

Subcommands
───────────
  run       Run the full pipeline (or a subset of stages)
  status    Show stage completion status for a work directory
  validate  Validate config without running anything
  report    Re-generate output reports from cached scored data
  dropped   Inspect commits dropped by pre/post filter

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
"""
import argparse
import json
import logging
import os
import subprocess
import sys
import time

from lib.logsetup import setup_logging
from lib.config import load_config, deep_merge, apply_override
from lib.manifest import VERSION, load_manifest
from lib.validation import validate_inputs
from lib.pipeline_runtime import (is_stage_done, wipe_downstream,
                                   init_pipeline_state)

_manifest   = load_manifest()
STAGES      = [(s['index'], s['script'], s['key'])
               for s in _manifest['pipeline_stages']]
STAGE_ORDER = [s[2] for s in STAGES]
STAGE_OUTPUTS = {
    'prepare_pipeline':      ['cache/00_compiled_rules.json', 'cache/00_prepare_summary.json'],
    'collect_commits':       ['cache/01_commits.json'],
    'collect_build_context': ['cache/02_build_context.json', 'cache/02_kbuild_static_map.json'],
    'build_product_map':     ['cache/03_product_map.json'],
    'prefilter_commits':     ['cache/04_filtered_commits.json'],
    'score_commits':         ['cache/05_scored_commits.json'],
    'postfilter_commits':    ['cache/06_relevant_commits.json'],
    'report_commits':        ['output/relevant_commits.csv',
                              'output/06_relevant_commits.json',
                              'output/report_stats.json',
                              'output/profile_summary.json',
                              'output/profile_matrix.csv',
                              'output/summary.html'],
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_stage(token):
    for s in STAGES:
        if str(s[0]) == str(token) or s[2] == token or s[1] == token:
            return s
    raise SystemExit(f'Unknown stage: {token!r}')


def _load_state(state_path):
    if not os.path.exists(state_path):
        return {}
    try:
        return json.load(open(state_path)).get('stages', {})
    except Exception:
        return {}


def _stage_needs_run(key, work, state):
    """True when the stage is not yet done OR its outputs are missing."""
    s = state.get(key, {})
    if s.get('status') != 'ok':
        return True
    for rel in (STAGE_OUTPUTS.get(key) or []):
        if not os.path.exists(os.path.join(work, rel)):
            return True
    return False


def _emit_progress(stage_idx, key, status, pct=None, extra=None):
    obj = {'stage': stage_idx, 'key': key, 'status': status}
    if pct is not None:
        obj['pct'] = pct
    if extra:
        obj.update(extra)
    print(json.dumps(obj), flush=True)


# ── Sub-command: run ──────────────────────────────────────────────────────────

def cmd_run(args):
    cfg  = load_config(args.config)
    if args.override:
        apply_override(cfg, args.override)

    work       = cfg['paths']['work_dir']
    state_path = os.path.join(work, 'pipeline_state.json')
    os.makedirs(os.path.join(work, 'cache'),  exist_ok=True)
    os.makedirs(os.path.join(work, 'output'), exist_ok=True)
    if not os.path.exists(state_path):
        init_pipeline_state(state_path)

    script_dir       = os.path.dirname(os.path.abspath(__file__))
    extra_stage_args = ['--override', args.override] if args.override else []
    if args.verbose:
        extra_stage_args += ['-' + 'v' * args.verbose]

    # Determine run list
    if args.stage is not None:
        target   = _resolve_stage(args.stage)
        run_list = [target]
        if args.force:
            wipe_downstream(state_path, target[2], work, STAGE_OUTPUTS,
                            stage_order=STAGE_ORDER)
    elif args.from_ is not None:
        from_stage = _resolve_stage(args.from_)
        run_list   = [s for s in STAGES if s[0] >= from_stage[0]]
        wipe_downstream(state_path, from_stage[2], work, STAGE_OUTPUTS,
                        stage_order=STAGE_ORDER)
    elif args.resume:
        state    = _load_state(state_path)
        run_list = [s for s in STAGES if _stage_needs_run(s[2], work, state)]
        if not run_list:
            print('All stages complete — nothing to do. Use --force to re-run.')
            return
        print(f'  resume: running {len(run_list)} pending stage(s): '
              + ', '.join(str(s[0]) for s in run_list))
    else:
        run_list = list(STAGES)

    for (idx, script, key) in run_list:
        if not args.force and not args.resume and is_stage_done(state_path, key):
            if args.progress_json:
                _emit_progress(idx, key, 'skipped')
            else:
                print(f'[stage {idx}] {key} already OK – skipping')
            continue

        if args.progress_json:
            _emit_progress(idx, key, 'running')
        else:
            print(f'\n[stage {idx}] running {script} …')

        t0  = time.time()
        ret = subprocess.run(
            [sys.executable, os.path.join(script_dir, script),
             '--config', args.config] + extra_stage_args
        ).returncode

        elapsed = time.time() - t0
        if ret != 0:
            if args.progress_json:
                _emit_progress(idx, key, 'failed', extra={'exit': ret})
            else:
                print(f'\n[stage {idx}] FAILED (exit {ret})')
                next_stages = [s for s in STAGES if s[0] > idx]
                if next_stages:
                    print(f'  re-run hint: kcommit_pipeline.py run '
                          f'--config {args.config} --from {idx}')
            raise SystemExit(ret)

        if args.progress_json:
            _emit_progress(idx, key, 'ok', extra={'elapsed_sec': round(elapsed, 1)})

    if args.progress_json:
        _emit_progress(-1, 'pipeline', 'complete')
    else:
        print('\nPipeline completed successfully.')


# ── Sub-command: status ───────────────────────────────────────────────────────

def cmd_status(args):
    cfg        = load_config(args.config)
    if args.override: apply_override(cfg, args.override)
    work       = cfg['paths']['work_dir']
    state_path = os.path.join(work, 'pipeline_state.json')
    state      = _load_state(state_path)

    print(f'{"#":<3}  {"Key":<30}  {"Script":<36}  {"Status":<10}  Duration')
    print('-' * 97)
    for (idx, script, key) in STAGES:
        s    = state.get(key, {})
        st   = s.get('status', 'pending')
        dur  = f"{s['duration_sec']:.1f}s" if 'duration_sec' in s else ''
        mark = {'ok': '✓', 'failed': '✗', 'running': '…'}.get(st, ' ')
        print(f'{mark}{idx:<3}  {key:<30}  {script:<36}  {st:<10}  {dur}')

    # Cache files presence
    print()
    for key, files in STAGE_OUTPUTS.items():
        for rel in files:
            full = os.path.join(work, rel)
            tag  = '✓' if os.path.exists(full) else '✗'
            print(f'  {tag}  {rel}')


# ── Sub-command: validate ─────────────────────────────────────────────────────

def cmd_validate(args):
    cfg = load_config(args.config)
    if args.override: apply_override(cfg, args.override)
    meta     = cfg.get('_meta', {}) or {}
    work     = cfg['paths']['work_dir']
    kernel   = cfg.get('kernel', {}) or {}
    filt     = cfg.get('filter', {}) or {}
    profiles = (cfg.get('profiles', {}) or {}).get('active') or \
               cfg.get('active_profiles', [])

    print(f'=== kcommit-analysis-pipeline {VERSION} — validate ===')
    print(f'Config   : {args.config}')
    print(f'Work dir : {work}')
    print(f'Repo     : {kernel.get("source_dir","N/A")}')
    print(f'Range    : {kernel.get("rev_old","?")} .. {kernel.get("rev_new","?")}')
    print(f'Filter   : {filt}')
    if isinstance(profiles, dict):
        for pn, pw in profiles.items():
            print(f'  profile: {pn} (weight {pw})')
    problems, notices = validate_inputs(cfg)
    for n in notices:
        print(f'  NOTICE: {n}')
    if problems:
        for p in problems:
            logging.error('%s', p)
        raise SystemExit(1)
    print('Configuration OK.')


# ── Sub-command: report ───────────────────────────────────────────────────────

def cmd_report(args):
    cfg    = load_config(args.config)
    if args.override: apply_override(cfg, args.override)
    work   = cfg['paths']['work_dir']
    cache  = os.path.join(work, 'cache')
    outdir = cfg.get('paths', {}).get('output_dir') or os.path.join(work, 'output')

    # Override format flags from --format arguments
    if args.format:
        tmpl = cfg.setdefault('templates', {})
        tmpl['html_summary'] = 'html'  in args.format
        tmpl['csv_output']   = 'csv'   in args.format
        tmpl['xls_output']   = 'xlsx'  in args.format
        tmpl['ods_output']   = 'ods'   in args.format

    from lib.stages.report import run as stage_run
    stats = stage_run(cfg, cache, outdir)
    print(f'Reports written to {outdir}')
    print(f'  {stats.get("total_scored_commits",0)} commits')


# ── Sub-command: dropped ──────────────────────────────────────────────────────

def cmd_dropped(args):
    cfg    = load_config(args.config)
    if args.override: apply_override(cfg, args.override)
    work   = cfg['paths']['work_dir']
    cache  = os.path.join(work, 'cache')

    from lib.config import load_json
    filtered = load_json(os.path.join(cache, '04_filtered_commits.json'), default=[]) or []

    reason_filter = args.reason or 'all'
    if reason_filter == 'prefilter':
        commits = [c for c in filtered
                   if not (c.get('_filter_reason') or '').startswith('score_below')]
    elif reason_filter == 'low-score':
        commits = [c for c in filtered
                   if (c.get('_filter_reason') or '').startswith('score_below')]
    else:
        commits = filtered

    if args.json:
        print(json.dumps(commits, indent=2, default=str))
        return

    # Tabular summary grouped by reason
    from collections import Counter
    counts = Counter(c.get('_filter_reason', 'unknown') for c in commits)
    print(f'Dropped commits ({reason_filter}): {len(commits)}')
    print()
    for reason, n in counts.most_common():
        print(f'  {n:>6}  {reason}')

    if args.verbose:
        print()
        for c in commits[:50]:
            sha     = (c.get('commit') or '')[:12]
            subject = (c.get('subject') or '')[:72]
            reason  = c.get('_filter_reason', '')
            print(f'  {sha}  {reason:<30}  {subject}')
        if len(commits) > 50:
            print(f'  … and {len(commits)-50} more')


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        prog='kcommit_pipeline.py',
        description=f'kcommit-analysis-pipeline {VERSION}',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('-v', '--verbose', action='count', default=0)
    sub = ap.add_subparsers(dest='cmd', metavar='SUBCOMMAND')
    sub.required = True

    # ── run ──
    p_run = sub.add_parser('run', help='Run pipeline stages')
    p_run.add_argument('--config',    required=True)
    p_run.add_argument('--override',  default=None, metavar='JSON')
    p_run.add_argument('--stage',     default=None)
    p_run.add_argument('--from',      dest='from_', default=None)
    p_run.add_argument('--resume',    action='store_true',
                       help='Run only stages whose outputs are missing or stale')
    p_run.add_argument('--force',     action='store_true',
                       help='Re-run even if already done')
    p_run.add_argument('--progress-json', action='store_true',
                       help='Emit machine-readable JSON progress lines to stdout')

    # ── status ──
    p_st = sub.add_parser('status', help='Show stage completion status')
    p_st.add_argument('--config',   required=True)
    p_st.add_argument('--override', default=None, metavar='JSON')

    # ── validate ──
    p_val = sub.add_parser('validate', help='Validate config without running')
    p_val.add_argument('--config',   required=True)
    p_val.add_argument('--override', default=None, metavar='JSON')

    # ── report ──
    p_rep = sub.add_parser('report', help='Re-generate reports from cached data')
    p_rep.add_argument('--config',   required=True)
    p_rep.add_argument('--override', default=None, metavar='JSON')
    p_rep.add_argument('--format',   action='append',
                       choices=['html', 'csv', 'xlsx', 'ods'],
                       help='Output format(s); may be repeated')

    # ── dropped ──
    p_dr = sub.add_parser('dropped', help='Inspect filtered-out commits')
    p_dr.add_argument('--config',   required=True)
    p_dr.add_argument('--override', default=None, metavar='JSON')
    p_dr.add_argument('--reason',   default='all',
                      choices=['all', 'prefilter', 'low-score'])
    p_dr.add_argument('--json',     action='store_true', help='Output raw JSON')

    args = ap.parse_args()
    setup_logging(args.verbose)

    # Backward-compat shim: bare --config without subcommand was the old usage.
    dispatch = {
        'run':      cmd_run,
        'status':   cmd_status,
        'validate': cmd_validate,
        'report':   cmd_report,
        'dropped':  cmd_dropped,
    }
    dispatch[args.cmd](args)


if __name__ == '__main__':
    main()
