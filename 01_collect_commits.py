#!/usr/bin/env python3
"""Stage 01: Collect commits from the git revision range.
"""
import argparse
import json
import os
import sys

from lib.config import load_config
from lib.config import save_json
from lib.validation import validate_config_only as validate_inputs
from lib.pipeline_runtime import (
    start_stage, finish_stage, fail_stage, update_stage_progress
)
from lib.gitutils import iter_git_log_records

_PROGRESS_INTERVAL = 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    args = ap.parse_args()

    cfg             = load_config(args.config)
    collect_cfg     = cfg.get('collect', {}) or {}
    max_commits     = int(collect_cfg.get('max_commits', 0) or 0)
    include_parents = bool(collect_cfg.get('include_parents', False))
    work            = cfg['paths']['work_dir']
    state_path      = os.path.join(work, 'pipeline_state.json')
    started         = start_stage(state_path, 'collect_commits', 1, 7)

    try:
        problems, notices = validate_inputs(cfg)
        for note in notices:
            print('  NOTICE:', note)
        if problems:
            for p in problems:
                print('  ERROR:', p)
            fail_stage(state_path, 'collect_commits', started,
                       error_msg='; '.join(problems))
            raise SystemExit(2)

        cache = os.path.join(work, 'cache')
        os.makedirs(cache, exist_ok=True)

        commits = []
        for rec in iter_git_log_records(cfg):
            if max_commits and len(commits) >= max_commits:
                print(f'\n  WARNING: stopping at {max_commits} commits (collect.max_commits)')
                break

            entry = {
                'commit':       rec.get('commit'),
                'subject':      rec.get('subject', ''),
                'body':         rec.get('body', ''),
                'files':        rec.get('files', []),
                'numstat':      rec.get('numstat', []),
                'author_time':  rec.get('author_time'),
                'commit_time':  rec.get('commit_time'),
                'author_name':  rec.get('author_name'),
                'author_email': rec.get('author_email'),
            }
            if include_parents:
                entry['parents'] = rec.get('parents', [])
            commits.append(entry)

            n = len(commits)
            if n % _PROGRESS_INTERVAL == 0:
                # Total is unknown upfront; show open-ended count
                frac = min(0.99, n / max(max_commits, n + 1)) if max_commits else 0.5
                update_stage_progress(1, 7, frac,
                                      'collecting commits', n_done=n)

        sys.stdout.write('\n')
        sys.stdout.flush()

        save_json(os.path.join(cache, 'commits.json'), commits)
        if collect_cfg.get('jsonl'):
            with open(os.path.join(cache, 'commits.jsonl'), 'w',
                      encoding='utf-8') as f:
                for rec in commits:
                    f.write(json.dumps(rec, sort_keys=True) + '\n')

        print(f'  collected {len(commits)} commits')
        finish_stage(state_path, 'collect_commits', started, status='ok',
                     extra={'commit_count': len(commits)})

    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        fail_stage(state_path, 'collect_commits', started, error_msg=str(exc))
        raise


if __name__ == '__main__':
    main()
