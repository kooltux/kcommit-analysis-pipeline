#!/usr/bin/env python3
# Add lightweight derived features to commits based on commit subject content.
from __future__ import print_function
import argparse
import os
from lib.config import load_config
from lib.io_utils import ensure_dir, load_json, save_json
from lib.scoring import extract_patch_features, infer_touched_paths
from lib.validation import validate_inputs
from lib.pipeline_runtime import start_stage, finish_stage


def main():
    # Parse arguments, load prior stage outputs, and enrich commits with shared scoring features.
    ap = argparse.ArgumentParser(); ap.add_argument('--config', required=True); args = ap.parse_args()
    cfg = load_config(args.config)
    state_path = os.path.join(cfg.get('project', {}).get('work_dir', './work'), 'pipeline_state.json')
    started = start_stage(state_path, 'enrich_commits', 4, 6)
    problems, notices = validate_inputs(cfg)
    for note in notices:
        print(note)
    if problems:
        for problem in problems:
            print(problem)
        raise SystemExit(2)
    work = cfg.get('project', {}).get('work_dir', './work')
    cache = os.path.join(work, 'cache'); ensure_dir(cache)
    commits = load_json(os.path.join(cache, 'commits.json'), default=[]) or []
    for c in commits:
        c['patch_features'] = extract_patch_features(c.get('subject', ''))
        c['touched_paths_guess'] = infer_touched_paths(c.get('subject', ''))
    save_json(os.path.join(cache, 'enriched_commits.json'), commits)
    print('commits enriched')
    finish_stage(state_path, 'enrich_commits', started, status='ok', extra={'commit_count': len(commits)})


if __name__ == '__main__':
    main()
