"""kcommit-analysis-pipeline — cmd_dropped subcommand."""
import json
import os

from lib.commands.base import load_cfg
from lib.config import load_json
from lib.manifest import CACHE_FILES


def cmd_dropped(args):
    cfg = load_cfg(args)
    work  = cfg['paths']['work_dir']
    cache = cfg['paths']['cache_dir']

    filtered = load_json(os.path.join(cache, CACHE_FILES['filtered']), default=[]) or []

    reason_filter = args.reason or 'all'
    if reason_filter == 'prefilter':
        commits = [c for c in filtered
                   if not (c.get('_filter_reason') or '').startswith('score_below')]
    elif reason_filter == 'low-score':
        commits = [c for c in filtered
                   if (c.get('_filter_reason') or '').startswith('score_below')]
    else:
        commits = filtered

    if args.json:
        print(json.dumps(commits, indent=2, default=str))
        return

    from collections import Counter
    counts = Counter(c.get('_filter_reason', 'unknown') for c in commits)
    print(f'Dropped commits ({reason_filter}): {len(commits)}')
    print()
    for reason, n in counts.most_common():
        print(f'  {n:>6}  {reason}')

    if args.verbose:
        print()
        for c in commits[:50]:
            sha     = (c.get('commit') or '')[:12]
            subject = (c.get('subject') or '')[:72]
            reason  = c.get('_filter_reason', '')
            print(f'  {sha}  {reason:<30}  {subject}')
        if len(commits) > 50:
            print(f'  … and {len(commits)-50} more')


# ── Entry point ───────────────────────────────────────────────────────────────
