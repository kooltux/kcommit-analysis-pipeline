#!/usr/bin/env python3
# Collect commits from the requested git revision range and cache them for later stages.
from __future__ import print_function
import argparse
import os
import subprocess
from lib.config import load_config
from lib.io_utils import ensure_dir, save_json
from lib.validation import validate_inputs
from lib.pipeline_runtime import start_stage, finish_stage


def run_git(repo, args):
    return subprocess.check_output(['git', '-C', repo] + args).decode('utf-8', 'replace')


def main():
    # Parse arguments, validate required source/config inputs, and collect commits in the revision range.
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    args = ap.parse_args()
    cfg = load_config(args.config)
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
    repo = cfg.get('kernel', {}).get('source_dir')
    rev_old = cfg.get('kernel', {}).get('rev_old')
    rev_new = cfg.get('kernel', {}).get('rev_new')
    commits = []
    if repo and rev_old and rev_new and os.path.isdir(repo):
        fmt = '%H%x1f%s'
        out = run_git(repo, ['log', '--no-merges', '--format=' + fmt, '%s..%s' % (rev_old, rev_new)])
        for line in out.splitlines():
            if '' in line:
                sha, subj = line.split('', 1)
                commits.append({'commit': sha, 'subject': subj})
    save_json(os.path.join(cache, 'commits.json'), commits)
    print('collected %d commits' % len(commits))
    finish_stage(state_path, 'collect_commits', started, status='ok', extra={'commit_count': len(commits)})


if __name__ == '__main__':
    main()
