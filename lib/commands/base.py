"""Shared helpers for kcommit-analysis-pipeline subcommands."""
import json
import os
import time

from lib.config import load_config, apply_override, load_json
from lib.manifest import VERSION, STAGE_OUTPUTS, NSTAGES, CACHE_FILES
from lib.pipeline_runtime import (
    is_stage_done, wipe_downstream, init_pipeline_state,
    start_stage, finish_stage, fail_stage,
    print_stage_output, StageResult,
)
from lib.stages import STAGES, NSTAGES as _NSTAGES  # noqa: F811

STAGE_ORDER = [key for key, _ in STAGES]


def load_cfg(args):
    cfg = load_config(args.config)
    if getattr(args, 'override', None):
        apply_override(cfg, args.override)
    return cfg


def resolve_stage(token):
    for idx, (key, _fn) in enumerate(STAGES):
        if str(idx) == str(token) or key == token:
            return idx, key
    raise SystemExit(f'Unknown stage: {token!r}')


def load_state(state_path):
    if not os.path.exists(state_path):
        return {}
    try:
        return json.load(open(state_path)).get('stages', {})
    except Exception:
        return {}


def stage_needs_run(key, work, state):
    s = state.get(key, {})
    if s.get('status') != 'ok':
        return True
    for rel in (STAGE_OUTPUTS.get(key) or []):
        if not os.path.exists(os.path.join(work, rel)):
            return True
    return False


def emit_progress(stage_idx, key, status, pct=None, extra=None):
    obj = {'stage': stage_idx, 'key': key, 'status': status}
    if pct is not None:
        obj['pct'] = pct
    if extra:
        obj.update(extra)
    print(json.dumps(obj), flush=True)


def stage_extra(key, result, elapsed):
    """Extract finish metadata from a stage result."""
    if result is None:
        return {}
    if isinstance(result, StageResult):
        return result.to_extra_dict()
    if key == 'prepare_pipeline':
        return {'profile_count': len((result or {}).get('profiles', []))}
    if key == 'collect_commits':
        print(f'  collected {len(result)} commits')
        return {'commit_count': len(result)}
    if key == 'collect_build_context':
        ctx, smap = result
        return {'enabled_config_count': len(ctx.get('kernel_config', [])),
                'kbuild_file_count':    len(ctx.get('kbuild_files', [])),
                'static_config_map_symbols': len(smap)}
    if key == 'build_product_map':
        return {'config_symbol_count': len((result or {}).get('config_to_paths', {}))}
    if key == 'prefilter_commits':
        kept, dropped, reasons = result
        print_stage_output('prefilter', len(kept), dropped=len(dropped),
                           reasons=reasons, elapsed=elapsed)
        return {'kept_count': len(kept), 'dropped_count': len(dropped)}
    if key == 'score_commits':
        return {'scored_count': len(result)}
    if key == 'postfilter_commits':
        relevant, low_score, threshold = result
        print_stage_output('postfilter', len(relevant), dropped=len(low_score),
                           reasons={f'score>={threshold}': len(relevant),
                                    f'score<{threshold}': len(low_score)},
                           elapsed=elapsed)
        return {'output_count': len(relevant), 'dropped_count': len(low_score),
                'min_score': threshold}
    if key == 'report_commits':
        return {'total_scored_commits': (result or {}).get('total_scored_commits', 0)}
    return {}


def run_stage(idx, key, fn, cfg, cache, work, state_path, args):
    """Run one stage with start/finish/fail tracking."""
    if not args.force and not getattr(args, 'resume', False) and is_stage_done(state_path, key):
        if args.progress_json:
            emit_progress(idx, key, 'skipped')
        else:
            print(f'[stage {idx}] {key} already OK – skipping')
        return

    if args.progress_json:
        emit_progress(idx, key, 'running')
    else:
        print(f'\n[stage {idx}] {key} …')

    t0     = time.time()
    t      = start_stage(state_path, key, idx, NSTAGES)
    outdir = cfg.get('paths', {}).get('output_dir') or os.path.join(work, 'output')

    try:
        result  = fn(cfg, cache, outdir) if key == 'report_commits' else fn(cfg, cache)
        elapsed = time.time() - t0
        extra   = stage_extra(key, result, elapsed)
        finish_stage(state_path, key, t, status='ok', extra=extra or None)
        if args.progress_json:
            emit_progress(idx, key, 'ok', extra={'elapsed_sec': round(elapsed, 1)})
    except SystemExit:
        fail_stage(state_path, key, t, error_msg='SystemExit')
        raise
    except Exception as exc:
        import traceback; traceback.print_exc()
        fail_stage(state_path, key, t, error_msg=str(exc))
        if args.progress_json:
            emit_progress(idx, key, 'failed', extra={'error': str(exc)})
        else:
            print(f'\n[stage {idx}] FAILED: {exc}')
        raise SystemExit(1)
