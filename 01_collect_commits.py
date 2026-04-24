#!/usr/bin/env python3
"""Stage 01: Collect commits from the git revision range.

"""
import json
import os
import sys

from lib.io_utils import ensure_dir, save_json
from lib.pipeline_runtime import stage_main, update_stage_progress
from lib.gitutils import iter_git_log_records

_PROGRESS_INTERVAL = 5000


@stage_main('collect_commits', 0, 5)
def main(cfg, work):
    collect_cfg     = cfg.get('collect', {}) or {}
    max_commits     = int(collect_cfg.get('max_commits', 0) or 0)
    include_parents = bool(collect_cfg.get('include_parents', False))
    cache           = os.path.join(work, 'cache')
    ensure_dir(cache)

    commits = []
    for rec in iter_git_log_records(cfg):
        if max_commits and len(commits) >= max_commits:
            print('\n  WARNING: stopping at %d commits (collect.max_commits)'
                  % max_commits)
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
            update_stage_progress(0, 5, frac,
                                  'collecting commits', n_done=n)

    sys.stdout.write('\n')
    sys.stdout.flush()

    save_json(os.path.join(cache, 'commits.json'), commits)
    if collect_cfg.get('jsonl'):
        with open(os.path.join(cache, 'commits.jsonl'), 'w',
                  encoding='utf-8') as f:
            for rec in commits:
                f.write(json.dumps(rec, sort_keys=True) + '\n')

    print('  collected %d commits' % len(commits))
    return {'commit_count': len(commits)}


if __name__ == '__main__':
    main()
