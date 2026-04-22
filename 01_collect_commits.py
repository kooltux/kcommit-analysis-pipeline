#!/usr/bin/env python3
# Collect commits from the requested git revision range and cache them for later stages.
from __future__ import print_function
import argparse
import os

from lib.config import load_config
from lib.io_utils import ensure_dir, save_json
from lib.validation import validate_inputs
from lib.pipeline_runtime import start_stage, finish_stage
from lib.gitutils import iter_git_log_records


def main():
    # Parse arguments, validate required source/config inputs, and collect commits in the revision range.
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    args = ap.parse_args()

    cfg = load_config(args.config)
    collect_cfg = cfg.get('collect', {}) or {}
    max_commits = int(collect_cfg.get('max_commits', 0) or 0)
    state_path = os.path.join(cfg.get('project', {}).get('work_dir', './work'), 'pipeline_state.json')
    started = start_stage(state_path, 'collect_commits', 1, 6)

    problems, notices = validate_inputs(cfg)
    for note in notices:
        print(note)
    if problems:
        for problem in problems:
            print(problem)
        raise SystemExit(2)

    work = cfg.get('project', {}).get('work_dir', './work')
    cache = os.path.join(work, 'cache')
    ensure_dir(cache)

    commits = []
    try:
        for rec in iter_git_log_records(cfg):
            if max_commits and len(commits) >= max_commits:
                print('warning: stopping collection after %d commits (collect.max_commits)' % max_commits)
                break
            commits.append({
                'commit': rec.get('commit'),
                'subject': rec.get('subject', ''),
                'body': rec.get('body', ''),
                'files': rec.get('files', []),
                'numstat': rec.get('numstat', []),
                'author_time': rec.get('author_time'),
                'commit_time': rec.get('commit_time'),
                'author_name': rec.get('author_name'),
                'author_email': rec.get('author_email'),
                'parents': rec.get('parents', []),
            })
    except Exception as e:
        print('ERROR: failed to collect commits via git log: %s' % e)
        raise

    save_json(os.path.join(cache, 'commits.json'), commits)
    print('collected %d commits' % len(commits))
    finish_stage(state_path, 'collect_commits', started, status='ok', extra={'commit_count': len(commits)})


if __name__ == '__main__':
    main()
