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
import sys
import time

from lib.logsetup import setup_logging
from lib.config import load_config, apply_override, load_json
from lib.manifest import VERSION, STAGE_OUTPUTS, CACHE_FILES
from lib.validation import validate_inputs
from lib.pipeline_runtime import (is_stage_done, wipe_downstream,
                                   init_pipeline_state, start_stage,
                                   finish_stage, fail_stage, print_stage_output)
from lib.stages import STAGES, NSTAGES

# Ordered list of stage keys for wipe_downstream
STAGE_ORDER = [key for key, _ in STAGES]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_cfg(args):
    """Load config and apply --override in one step."""
    cfg = load_config(args.config)
    if getattr(args, 'override', None):
        apply_override(cfg, args.override)
    return cfg


def _resolve_stage(token):
    """Resolve a stage by index (0-7) or key name."""
    for idx, (key, _fn) in enumerate(STAGES):
        if str(idx) == str(token) or key == token:
            return idx, key
    raise SystemExit(f'Unknown stage: {token!r}')


def _load_state(state_path):
    if not os.path.exists(state_path):
        return {}
    try:
        return json.load(open(state_path)).get('stages', {})
    except Exception:
        return {}


def _stage_needs_run(key, work, state):
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

def _run_stage(idx, key, fn, cfg, cache, work, state_path, args):
    """Run a single stage function in-process with start/finish/fail tracking."""
    if not args.force and not getattr(args, 'resume', False) and is_stage_done(state_path, key):
        if args.progress_json:
            _emit_progress(idx, key, 'skipped')
        else:
            print(f'[stage {idx}] {key} already OK – skipping')
        return

    if args.progress_json:
        _emit_progress(idx, key, 'running')
    else:
        print(f'\n[stage {idx}] {key} …')

    t0 = time.time()
    t  = start_stage(state_path, key, idx, NSTAGES)
    outdir = cfg.get('paths', {}).get('output_dir') or os.path.join(work, 'output')

    try:
        # Stages with extra arguments
        if key == 'report_commits':
            result = fn(cfg, cache, outdir)
        else:
            result = fn(cfg, cache)

        elapsed = time.time() - t0
        extra   = {}

        # Stage-specific finish metadata
        if key == 'prepare_pipeline' and result:
            extra = {'profile_count': len(result.get('profiles', []))}
        elif key == 'collect_commits' and result:
            extra = {'commit_count': len(result)}
            print(f'  collected {len(result)} commits')
        elif key == 'collect_build_context' and result:
            ctx, smap = result
            extra = {'enabled_config_count': len(ctx.get('kernel_config',[])),
                     'kbuild_file_count':    len(ctx.get('kbuild_files',[])),
                     'static_config_map_symbols': len(smap)}
        elif key == 'build_product_map' and result:
            extra = {'config_symbol_count': len(result.get('config_to_paths',{}))}
        elif key == 'prefilter_commits' and result:
            kept, dropped, reasons = result
            print_stage_output('prefilter', len(kept), dropped=len(dropped),
                               reasons=reasons, elapsed=elapsed)
            extra = {'kept_count': len(kept), 'dropped_count': len(dropped)}
        elif key == 'score_commits' and result:
            extra = {'scored_count': len(result)}
        elif key == 'postfilter_commits' and result:
            relevant, low_score, threshold = result
            print_stage_output('postfilter', len(relevant),
                               dropped=len(low_score),
                               reasons={f'score>={threshold}': len(relevant),
                                        f'score<{threshold}': len(low_score)},
                               elapsed=elapsed)
            extra = {'output_count': len(relevant), 'dropped_count': len(low_score),
                     'min_score': threshold}
        elif key == 'report_commits' and result:
            extra = {'total_scored_commits': result.get('total_scored_commits', 0)}

        finish_stage(state_path, key, t, status='ok', extra=extra or None)

        if args.progress_json:
            _emit_progress(idx, key, 'ok', extra={'elapsed_sec': round(elapsed, 1)})

    except SystemExit:
        fail_stage(state_path, key, t, error_msg='SystemExit')
        raise
    except Exception as exc:
        import traceback; traceback.print_exc()
        fail_stage(state_path, key, t, error_msg=str(exc))
        if args.progress_json:
            _emit_progress(idx, key, 'failed', extra={'error': str(exc)})
        else:
            print(f'\n[stage {idx}] FAILED: {exc}')
        raise SystemExit(1)


def cmd_run(args):
    cfg = _load_cfg(args)

    work       = cfg['paths']['work_dir']
    cache      = cfg['paths']['cache_dir']
    state_path = os.path.join(work, 'pipeline_state.json')
    os.makedirs(cache,  exist_ok=True)
    os.makedirs(cfg['paths']['output_dir'], exist_ok=True)
    if not os.path.exists(state_path):
        init_pipeline_state(state_path)

    # Determine run list
    if args.stage is not None:
        idx, key = _resolve_stage(args.stage)
        run_list = [(idx, key, STAGES[idx][1])]
        if args.force:
            wipe_downstream(state_path, key, work, STAGE_OUTPUTS,
                            stage_order=STAGE_ORDER)
    elif args.from_ is not None:
        from_idx, from_key = _resolve_stage(args.from_)
        run_list = [(i, k, fn) for i, (k, fn) in enumerate(STAGES) if i >= from_idx]
        wipe_downstream(state_path, from_key, work, STAGE_OUTPUTS,
                        stage_order=STAGE_ORDER)
    elif args.resume:
        state    = _load_state(state_path)
        run_list = [(i, k, fn) for i, (k, fn) in enumerate(STAGES)
                    if _stage_needs_run(k, work, state)]
        if not run_list:
            print('All stages complete — nothing to do. Use --force to re-run.')
            return
        print(f'  resume: running {len(run_list)} pending stage(s): '
              + ', '.join(str(i) for i, _, _ in run_list))
    else:
        run_list = [(i, k, fn) for i, (k, fn) in enumerate(STAGES)]

    for (idx, key, fn) in run_list:
        _run_stage(idx, key, fn, cfg, cache, work, state_path, args)

    if args.progress_json:
        _emit_progress(-1, 'pipeline', 'complete')
    else:
        print('\nPipeline completed successfully.')


# ── Sub-command: status ───────────────────────────────────────────────────────

def cmd_status(args):
    cfg = _load_cfg(args)
    work       = cfg['paths']['work_dir']
    state_path = os.path.join(work, 'pipeline_state.json')
    state      = _load_state(state_path)

    print(f'{"#":<3}  {"Key":<30}  {"Status":<10}  Duration')
    print('-' * 70)
    for idx, (key, _fn) in enumerate(STAGES):
        s    = state.get(key, {})
        st   = s.get('status', 'pending')
        dur  = f"{s['duration_sec']:.1f}s" if 'duration_sec' in s else ''
        mark = {'ok': '✓', 'failed': '✗', 'running': '…'}.get(st, ' ')
        print(f'{mark}{idx:<3}  {key:<30}  {st:<10}  {dur}')

    print()
    for key, files in STAGE_OUTPUTS.items():
        for rel in files:
            full = os.path.join(work, rel)
            tag  = '✓' if os.path.exists(full) else '✗'
            print(f'  {tag}  {rel}')


# ── Sub-command: validate ─────────────────────────────────────────────────────

def cmd_validate(args):
    cfg = _load_cfg(args)
    work     = cfg['paths']['work_dir']
    kernel   = cfg.get('kernel', {}) or {}
    filt     = cfg.get('filter', {}) or {}
    profiles = (cfg.get('profiles', {}) or {}).get('active') or []

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


# ── Sub-command: report (E.10) ────────────────────────────────────────────────

def cmd_report(args):
    cfg = _load_cfg(args)
    work   = cfg['paths']['work_dir']
    cache  = cfg['paths']['cache_dir']
    outdir = cfg['paths']['output_dir']

    if args.format:
        reports = cfg.setdefault('reports', {})
        reports['outputs'] = args.format

    from lib.stages.st07_report import run as stage_run
    stats = stage_run(cfg, cache, outdir)
    print(f'Reports written to {outdir}')
    print(f'  {stats.get("total_scored_commits", 0)} commits')


# ── Sub-command: dropped ──────────────────────────────────────────────────────

def cmd_dropped(args):
    cfg = _load_cfg(args)
    work  = cfg['paths']['work_dir']
    cache = cfg['paths']['cache_dir']

    filtered = load_json(os.path.join(cache, CACHE_FILES['filtered']), default=[]) or []

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
    p_rep.add_argument('--format',   action='append',
                       choices=['html', 'csv', 'xlsx', 'ods'],
                       help='Output format(s); may be repeated')

    p_dr = sub.add_parser('dropped', help='Inspect filtered-out commits')
    p_dr.add_argument('--config',   required=True)
    p_dr.add_argument('--override', default=None, metavar='JSON')
    p_dr.add_argument('--reason',   default='all',
                      choices=['all', 'prefilter', 'low-score'])
    p_dr.add_argument('--json',     action='store_true')

    args = ap.parse_args()
    setup_logging(args.verbose)
    dispatch = {'run': cmd_run, 'status': cmd_status, 'validate': cmd_validate,
                'report': cmd_report, 'dropped': cmd_dropped}
    dispatch[args.cmd](args)


if __name__ == '__main__':
    main()
