#!/usr/bin/env python3
"""Stage 05: Score commits using product map, profile rules, and scoring config.
"""
import json
import argparse
import os
import time
import sys

from lib.config import load_config
from lib.config import load_json, save_json
from lib.scoring import score_commit, precompile_rules
from lib.profile_rules import load_profile_rules
from lib.validation import validate_config_only as validate_inputs
from lib.pipeline_runtime import (
    start_stage, finish_stage, fail_stage, update_stage_progress,
    print_stage_input, print_stage_output
)


# ── module-level globals for pool worker initializer ─────────────────────────
# These are set once per worker process by _worker_init(), avoiding the cost of
# pickling large product_map / profile_rules dicts for every individual task.
_g_product_map   = None
_g_profile_rules = None
_g_cfg           = None


def _worker_init(product_map, profile_rules, cfg):
    global _g_product_map, _g_profile_rules, _g_cfg
    _g_product_map   = product_map
    _g_profile_rules = profile_rules
    _g_cfg           = cfg
    precompile_rules(_g_profile_rules)  # compile patterns once per worker process


def _score_one_global(commit):
    """Picklable worker function; uses globals set by _worker_init."""
    return score_commit(commit, _g_product_map, _g_profile_rules, _g_cfg)


def _score_all(commits, product_map, profile_rules, cfg):
    collect = cfg.get('collect', {}) or {}
    try:
        import os as _os
        default_workers = _os.cpu_count() or 1
    except Exception:
        default_workers = 1
    configured = collect.get('score_workers', 0)
    workers = int(configured or 0) if int(configured or 0) > 0 else default_workers
    total   = len(commits)
    step    = max(1, total // 80)

    # ── serial path ───────────────────────────────────────────────────────────
    if workers <= 1 or total < 100:
        results = []
        for i, c in enumerate(commits):
            results.append(score_commit(c, product_map, profile_rules, cfg))
            if i % step == 0 or i == total - 1:
                update_stage_progress(5, 7, (i + 1) / max(total, 1),
                                      'scoring', n_done=i + 1, n_total=total)
        return results

    # ── parallel path with initializer ────────────────────────────────────────
    try:
        from multiprocessing import Pool, cpu_count
        max_w   = max(1, min(workers, cpu_count()))
        results = []
        with Pool(processes=max_w,
                  initializer=_worker_init,
                  initargs=(product_map, profile_rules, cfg)) as pool:
            # imap preserves order and allows streaming progress updates
            for i, scored in enumerate(
                    pool.imap(_score_one_global, commits, chunksize=64)):
                results.append(scored)
                if i % step == 0 or i == total - 1:
                    update_stage_progress(5, 7, (i + 1) / max(total, 1),
                                          f'scoring ({max_w} workers)',
                                          n_done=i + 1, n_total=total)
        return results

    except Exception as _mp_exc:
        print(f'\nWARNING: multiprocessing pool failed ({_mp_exc}); falling back to serial scoring',
              flush=True)
        results = []
        for i, c in enumerate(commits):
            results.append(score_commit(c, product_map, profile_rules, cfg))
            if i % step == 0 or i == total - 1:
                update_stage_progress(5, 7, (i + 1) / max(total, 1),
                                      'scoring (serial fallback)',
                                      n_done=i + 1, n_total=total)
        return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--override', default=None, metavar='JSON',
                    help='Deep-merge JSON into config (forwarded from kcommit_pipeline)')
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.override:
        from kcommit_pipeline import apply_override
        apply_override(cfg, args.override)
    work       = cfg['paths']['work_dir']
    state_path = os.path.join(work, 'pipeline_state.json')
    started    = start_stage(state_path, 'score_commits', 5, 7)

    try:
        problems, notices = validate_inputs(cfg)
        for note in notices:
            print('  NOTICE:', note)
        if problems:
            for p in problems:
                print('  ERROR:', p)
            fail_stage(state_path, 'score_commits', started,
                       error_msg='; '.join(problems))
            raise SystemExit(2)

        cache = os.path.join(work, 'cache')
        os.makedirs(cache, exist_ok=True)

        # Stage 04 always produces filtered_commits.json.
        commits = load_json(os.path.join(cache, 'filtered_commits.json'), default=[]) or []
        _t0_stage = time.time()
        print_stage_input('score input', commits)
        product_map   = load_json(os.path.join(cache, 'product_map.json'),
                                  default={}) or {}
        profile_rules = load_profile_rules(cfg)

        update_stage_progress(5, 7, 0.01, 'ready',
                              n_done=0, n_total=len(commits))

        scored = _score_all(commits, product_map, profile_rules, cfg)

        sys.stdout.write('\n')
        sys.stdout.flush()

        save_json(os.path.join(cache, 'scored_commits.json'), scored)
        print('  scored %d commits' % len(scored))
        _pos_05 = sum(1 for c in scored if c.get('score', 0) > 0)
        _neg_05 = len(scored) - _pos_05
        print_stage_output('scored commits', len(scored),
            reasons={'score>0': _pos_05, 'score=0': _neg_05},
            elapsed=time.time()-_t0_stage)
        finish_stage(state_path, 'score_commits', started, status='ok',
                     extra={'scored_commit_count': len(scored)})

    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        fail_stage(state_path, 'score_commits', started, error_msg=str(exc))
        raise


if __name__ == '__main__':
    main()
