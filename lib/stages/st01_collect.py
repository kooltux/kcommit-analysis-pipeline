from lib.manifest import NSTAGES
"""Stage 01 logic: collect commits from git log."""
import json
import os
import sys
from lib.config import save_json
from lib.gitutils import iter_git_log_records
from lib.pipeline_runtime import update_stage_progress
from lib.manifest import CACHE_FILES

_PROGRESS_INTERVAL = 100


def run(cfg, cache):
    collect_cfg     = cfg.get('collect', {}) or {}
    max_commits     = int(collect_cfg.get('max_commits', 0) or 0)
    include_parents = bool(collect_cfg.get('include_parents', False))

    commits = []
    update_stage_progress(1, NSTAGES, 0.01, 'collecting commits', n_done=0, n_total=max_commits if max_commits else None)
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
            if max_commits:
                update_stage_progress(1, NSTAGES, min(0.99, n / max_commits),
                                      'collecting commits', n_done=n, n_total=max_commits)
            else:
                update_stage_progress(1, NSTAGES, 0.0, 'collecting commits', n_done=n)

    update_stage_progress(1, NSTAGES, 1.0, 'collecting commits', n_done=len(commits), n_total=max_commits if max_commits else len(commits))
    sys.stderr.write('\n'); sys.stderr.flush()
    save_json(os.path.join(cache, CACHE_FILES['commits']), commits)

    if collect_cfg.get('jsonl'):
        with open(os.path.join(cache, '01_commits.jsonl'), 'w', encoding='utf-8') as f:
            for rec in commits:
                f.write(json.dumps(rec, sort_keys=True) + '\n')

    return commits