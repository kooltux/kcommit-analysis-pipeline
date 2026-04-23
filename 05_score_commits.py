#!/usr/bin/env python3
"""Stage 05: Score commits using product map, profile rules, and scoring config.

v7.17: cfg passed to score_commit; module-level _score_one for multiprocessing
       pickling; score_workers defaults to min(4, cpu_count); fail_stage.
"""
from __future__ import print_function
import argparse
import os

from lib.config import load_config
from lib.io_utils import ensure_dir, load_json, save_json
from lib.scoring import score_commit
from lib.profile_rules import load_profile_rules
from lib.validation import validate_inputs
from lib.pipeline_runtime import start_stage, finish_stage, fail_stage


def _score_one(args):
    """Top-level picklable worker function for multiprocessing.Pool."""
    c, pm, pr, cfg = args
    return score_commit(c, pm, pr, cfg)


def _score_all(commits, product_map, profile_rules, cfg):
    collect = cfg.get('collect', {}) or {}
    try:
        from multiprocessing import cpu_count as _cpu
        default_workers = min(4, _cpu())
    except Exception:
        default_workers = 1
    workers = int(collect.get('score_workers', default_workers) or default_workers)

    if workers <= 1:
        return [score_commit(c, product_map, profile_rules, cfg) for c in commits]

    try:
        from multiprocessing import Pool, cpu_count
        max_w = max(1, min(workers, cpu_count()))
        args_list = [(c, product_map, profile_rules, cfg) for c in commits]
        with Pool(processes=max_w) as pool:
            return pool.map(_score_one, args_list)
    except Exception:
        return [score_commit(c, product_map, profile_rules, cfg) for c in commits]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    args = ap.parse_args()

    cfg        = load_config(args.config)
    work       = cfg.get('project', {}).get('work_dir', './work')
    state_path = os.path.join(work, 'pipeline_state.json')
    started    = start_stage(state_path, 'score_commits', 6, 7)

    try:
        problems, notices = validate_inputs(cfg)
        for note in notices:
            print(note)
        if problems:
            for p in problems:
                print(p)
            fail_stage(state_path, 'score_commits', started,
                       error_msg='; '.join(problems))
            raise SystemExit(2)

        cache = os.path.join(work, 'cache')
        ensure_dir(cache)

        commits       = load_json(os.path.join(cache, 'enriched_commits.json'), default=[]) or []
        product_map   = load_json(os.path.join(cache, 'product_map.json'),       default={}) or {}
        profile_rules = load_profile_rules(cfg)

        scored = _score_all(commits, product_map, profile_rules, cfg)

        save_json(os.path.join(cache, 'scored_commits.json'), scored)
        print('scored %d commits' % len(scored))
        finish_stage(state_path, 'score_commits', started, status='ok',
                     extra={'scored_commit_count': len(scored)})

    except SystemExit:
        raise
    except Exception as exc:
        fail_stage(state_path, 'score_commits', started, error_msg=str(exc))
        raise


if __name__ == '__main__':
    main()
