#!/usr/bin/env python3
# Score commits for product, security, and performance relevance using shared scoring helpers.
from __future__ import print_function
import argparse
import os
from lib.config import load_config
from lib.io_utils import ensure_dir, load_json, save_json
from lib.scoring import score_commit
from lib.validation import validate_inputs
from lib.pipeline_runtime import start_stage, finish_stage


def main():
    # Parse arguments, load commit enrichments and product evidence, then rank candidates.
    ap = argparse.ArgumentParser(); ap.add_argument('--config', required=True); args = ap.parse_args()
    cfg = load_config(args.config)
    state_path = os.path.join(cfg.get('project', {}).get('work_dir', './work'), 'pipeline_state.json')
    started = start_stage(state_path, 'score_commits', 5, 6)
    problems, notices = validate_inputs(cfg)
    for note in notices:
        print(note)
    if problems:
        for problem in problems:
            print(problem)
        raise SystemExit(2)
    work = cfg.get('project', {}).get('work_dir', './work')
    cache = os.path.join(work, 'cache'); ensure_dir(cache)
    commits = load_json(os.path.join(cache, 'enriched_commits.json'), default=[]) or []
    product_map = load_json(os.path.join(cache, 'product_map.json'), default={}) or {}
    scored = [score_commit(c, product_map, cfg.get('active_profiles', [])) for c in commits]
    save_json(os.path.join(cache, 'scored_commits.json'), scored)
    print('commits scored')
    finish_stage(state_path, 'score_commits', started, status='ok', extra={'scored_commit_count': len(scored)})


if __name__ == '__main__':
    main()
