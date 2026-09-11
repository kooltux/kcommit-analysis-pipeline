"""Stage 01 logic: collect commits from git log.

E.4 (v13.0.0): moved docstring to top of file (was after the first import,
rendering it a dead string literal).

v19.9.1:
  Hunk counting now reports real progress via update_stage_progress(),
  matching the pattern already used by the main collect loop and by
  stage 04/05's progress-wired loops. Previously batch_count_hunks() was
  called with no progress_callback at all, so on large commit ranges
  (tens to hundreds of thousands of commits) the pipeline showed only two
  static print() lines with nothing in between -- silent for minutes on
  real-world runs. The total (len(shas)) is already known before the call,
  so a real determinate progress bar (not a spinner) is shown throughout.
"""
import json
import os
from lib.config import save_json
from lib.gitutils import iter_git_log_records, compute_numstat_totals, batch_count_hunks
from lib.pipeline_runtime import update_stage_progress, finish_progress_line
from lib.manifest import CACHE_FILES, NSTAGES

_PROGRESS_INTERVAL = 100


def _extract_author_org(email):
    """Extract organization domain from author email address.
    
    Returns the domain part after '@' if email is valid, otherwise empty string.
    """
    if not email:
        return ''
    parts = str(email).rsplit('@', 1)
    if len(parts) == 2:
        return parts[1]
    return ''


def run(cfg, cache):
    collect_cfg     = cfg.get('collect', {}) or {}
    max_commits     = int(collect_cfg.get('max_commits', 0) or 0)
    include_parents = bool(collect_cfg.get('include_parents', False))

    commits = []
    update_stage_progress(1, NSTAGES, 0.01, 'collecting commits', n_done=0, n_total=max_commits if max_commits else None)
    for rec in iter_git_log_records(cfg):
        if max_commits and len(commits) >= max_commits:
            print('\n  WARNING: stopping at %d commits (collect.max_commits)' % max_commits)
            break
        files   = rec.get('files', []) or []
        numstat = rec.get('numstat', []) or []
        stats   = compute_numstat_totals(numstat)
        # In --name-only mode numstat is empty, so derive files_changed from
        # the files list; line totals stay 0 because git supplied no deltas.
        if not numstat and files:
            stats['files_changed'] = len(files)
        entry = {
            'commit':       rec.get('commit'),
            'subject':      rec.get('subject', ''),
            'body':         rec.get('body', ''),
            'files':        files,
            'numstat':      numstat,
            'stats':        stats,
            'author_time':  rec.get('author_time'),
            'commit_time':  rec.get('commit_time'),
            'author_name':  rec.get('author_name'),
            'author_email': rec.get('author_email'),
            'author_org':   _extract_author_org(rec.get('author_email')),
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
    finish_progress_line()

    # Compute actual hunk counts for all commits (replaces placeholder hunks=0)
    #
    # v19.9.1: the total (len(shas)) is known before this call starts, so we
    # wire a real progress_callback into batch_count_hunks() instead of
    # leaving the user staring at two static print() lines with nothing in
    # between for however long the git show batches take. This mirrors the
    # step = max(1, total // 80) throttling pattern used by
    # st04_prefilter.py / st05_score.py so update frequency is consistent
    # across stages regardless of commit-range size.
    if commits:
        shas = [c['commit'] for c in commits if c.get('commit')]
        if shas:
            total = len(shas)
            step = max(1, total // 80)

            def _hunk_progress(done, total_n):
                if done % step == 0 or done == total_n:
                    update_stage_progress(1, NSTAGES, done / max(total_n, 1),
                                          'counting hunks', n_done=done, n_total=total_n)

            print('  counting hunks for %d commits...' % total)
            hunk_counts = batch_count_hunks(cfg, shas, progress_callback=_hunk_progress)
            finish_progress_line()
            for c in commits:
                sha = c.get('commit')
                if sha and sha in hunk_counts:
                    c['stats']['hunks'] = hunk_counts[sha]
            print('  done counting hunks')

    save_json(os.path.join(cache, CACHE_FILES['commits']), commits)

    if collect_cfg.get('jsonl'):
        with open(os.path.join(cache, 'commits.jsonl'), 'w', encoding='utf-8') as f:
            for rec in commits:
                f.write(json.dumps(rec, sort_keys=True) + '\n')

    return commits
