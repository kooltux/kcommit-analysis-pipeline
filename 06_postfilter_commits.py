#!/usr/bin/env python3
"""Stage 06: Post-filter commits by applying a score threshold to the scored results.

Reads:   cache/05_scored_commits.json
         cache/04_filtered_commits.json   (to append low-score commits)
Writes:  cache/06_relevant_commits.json  (commits that pass the threshold)
         cache/04_filtered_commits.json  (updated: pre-filter drops + low-score drops)

The threshold is configured via ``filter.min_score`` in the config file.
Commits whose score is **strictly less than** the threshold are dropped with
reason ``score_below_threshold`` and appended to ``04_filtered_commits.json``
so that all dropped commits (pre-filter and post-filter) are collected in one
place with their individual reasons.

Config key (in the ``filter`` section)::

    "filter": {
        "min_score": 10
    }

A value of 0 (the default) keeps every commit. Can be overridden at runtime::

    --override '{"filter":{"min_score":25}}'
"""
import argparse
import logging
import os
import time

from lib.config import load_config, apply_override, load_json, save_json
from lib.logsetup import setup_logging
from lib.validation import validate_config_only
from lib.pipeline_runtime import (
    start_stage, finish_stage, fail_stage,
    print_stage_input, print_stage_output,
)


def _get_threshold(cfg):
    """Return the min_score threshold as a float (default 0 — keep everything)."""
    sc = cfg.get('filter', {}) or {}
    try:
        return float(sc.get('min_score', 0) or 0)
    except (TypeError, ValueError):
        logging.warning('filter.min_score is not a number; defaulting to 0')
        return 0.0


def main():
    ap = argparse.ArgumentParser(
        description='Post-filter commits: keep only those meeting the score threshold')
    ap.add_argument('-v', '--verbose', action='count', default=0,
                    help='Verbosity: -v INFO, -vv DEBUG')
    ap.add_argument('--config', required=True)
    ap.add_argument('--override', default=None, metavar='JSON',
                    help='Deep-merge JSON into config (forwarded from kcommit_pipeline)')
    args = ap.parse_args()
    setup_logging(args.verbose)

    cfg = load_config(args.config)
    if args.override:
        apply_override(cfg, args.override)

    work       = cfg['paths']['work_dir']
    cache      = os.path.join(work, 'cache')
    state_path = os.path.join(work, 'pipeline_state.json')
    started    = start_stage(state_path, 'postfilter_commits', 6, 8)

    try:
        problems, notices = validate_config_only(cfg)
        for note in notices:
            print(f'  NOTICE: {note}')
        if problems:
            for p in problems:
                logging.error('%s', p)
            fail_stage(state_path, 'postfilter_commits', started,
                       error_msg='; '.join(problems))
            raise SystemExit(2)

        os.makedirs(cache, exist_ok=True)
        t0 = time.time()

        scored = load_json(os.path.join(cache, '05_scored_commits.json'), default=[]) or []
        scored = sorted(scored, key=lambda c: c.get('score', 0) or 0, reverse=True)
        print_stage_input('postfilter input', scored)

        threshold = _get_threshold(cfg)
        if threshold > 0:
            before   = len(scored)
            relevant = [c for c in scored if (c.get('score', 0) or 0) >= threshold]
            low_score = [c for c in scored if (c.get('score', 0) or 0) < threshold]
            dropped  = len(low_score)
            print(f'  threshold {threshold}: kept {len(relevant)}/{before}'
                  f' commits, dropped {dropped}')
        else:
            relevant  = scored
            low_score = []
            dropped   = 0
            print(f'  no threshold (min_score=0): keeping all {len(relevant)} commits')

        # Assign 1-based rank after filtering
        for rank, c in enumerate(relevant, 1):
            c['_rank'] = rank

        save_json(os.path.join(cache, '06_relevant_commits.json'), relevant)

        # ── Merge low-score drops into 04_filtered_commits.json ──────────────
        if low_score:
            reason_label = f'score_below_threshold ({threshold})'
            for c in low_score:
                c['_filter_reason'] = reason_label
            existing_filtered = load_json(
                os.path.join(cache, '04_filtered_commits.json'), default=[]) or []
            merged_filtered = existing_filtered + low_score
            save_json(os.path.join(cache, '04_filtered_commits.json'), merged_filtered)
            print(f'  appended {len(low_score)} low-score commits to'
                  f' 04_filtered_commits.json'
                  f' (total filtered: {len(merged_filtered)})')

        print_stage_output(
            'postfilter output', len(relevant), dropped=dropped,
            reasons={
                f'score >= {threshold}': len(relevant),
                f'score < {threshold}':  dropped,
            },
            elapsed=time.time() - t0)

        finish_stage(state_path, 'postfilter_commits', started, status='ok',
                     extra={
                         'input_count':        len(scored),
                         'output_count':       len(relevant),
                         'dropped_count':      dropped,
                         'min_score':          threshold,
                     })

    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        fail_stage(state_path, 'postfilter_commits', started, error_msg=str(exc))
        raise


if __name__ == '__main__':
    main()
