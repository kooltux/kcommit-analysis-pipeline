#!/usr/bin/env python3
"""Stage 01: Collect commits from the git revision range.

v7.17: fail_stage on error; collect.max_commits safety valve;
       optional JSONL output via collect.jsonl = true.
"""
from __future__ import print_function
import argparse
import json
import os

from lib.config import load_config
from lib.io_utils import ensure_dir, save_json
from lib.validation import validate_inputs
from lib.pipeline_runtime import start_stage, finish_stage, fail_stage
from lib.gitutils import iter_git_log_records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    args = ap.parse_args()

    cfg         = load_config(args.config)
    collect_cfg = cfg.get('collect', {}) or {}
    max_commits = int(collect_cfg.get('max_commits', 0) or 0)
    work        = cfg.get('project', {}).get('work_dir', './work')
    state_path  = os.path.join(work, 'pipeline_state.json')
    started     = start_stage(state_path, 'collect_commits', 2, 7)

    try:
        problems, notices = validate_inputs(cfg)
        for note in notices:
            print(note)
        if problems:
            for p in problems:
                print(p)
            fail_stage(state_path, 'collect_commits', started,
                       error_msg='; '.join(problems))
            raise SystemExit(2)

        cache = os.path.join(work, 'cache')
        ensure_dir(cache)

        commits = []
        for rec in iter_git_log_records(cfg):
            if max_commits and len(commits) >= max_commits:
                print('warning: stopping at %d commits (collect.max_commits)' % max_commits)
                break
            commits.append({
                'commit':       rec.get('commit'),
                'subject':      rec.get('subject', ''),
                'body':         rec.get('body', ''),
                'files':        rec.get('files', []),
                'numstat':      rec.get('numstat', []),
                'author_time':  rec.get('author_time'),
                'commit_time':  rec.get('commit_time'),
                'author_name':  rec.get('author_name'),
                'author_email': rec.get('author_email'),
                'parents':      rec.get('parents', []),
            })

        save_json(os.path.join(cache, 'commits.json'), commits)
        if collect_cfg.get('jsonl'):
            with open(os.path.join(cache, 'commits.jsonl'), 'w', encoding='utf-8') as f:
                for rec in commits:
                    f.write(json.dumps(rec, sort_keys=True) + '\n')

        print('collected %d commits' % len(commits))
        finish_stage(state_path, 'collect_commits', started, status='ok',
                     extra={'commit_count': len(commits)})

    except SystemExit:
        raise
    except Exception as exc:
        fail_stage(state_path, 'collect_commits', started, error_msg=str(exc))
        raise


if __name__ == '__main__':
    main()
