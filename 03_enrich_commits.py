#!/usr/bin/env python3
"""Stage 03: Enrich commits with stable hints and touched-path guesses.

"""
import os
import sys

from lib.io_utils import ensure_dir, load_json, save_json
from lib.scoring import extract_stable_hints, infer_touched_paths
from lib.pipeline_runtime import stage_main, update_stage_progress


@stage_main('enrich_commits', 2, 5)
def main(cfg, work):
    cache = os.path.join(work, 'cache')
    ensure_dir(cache)

    # Prefer JSONL for massive ranges (200k+), fallback to JSON
    jsonl_path = os.path.join(cache, 'commits.jsonl')
    json_path  = os.path.join(cache, 'commits.json')
    
    if os.path.exists(jsonl_path):
        from lib.io_utils import iter_jsonl
        commits = iter_jsonl(jsonl_path)
        # We don't know the total upfront from JSONL without a pre-scan
        # but iter_git_log_records already knows it if max_commits was set.
        total = 0 # unknown
    else:
        commits = load_json(json_path, default=[]) or []
        total   = len(commits)

    stats = {'count': 0}
    def _enrich_stream(it):
        for i, c in enumerate(it):
            c['stable_hints']        = extract_stable_hints(c)
            c['touched_paths_guess'] = infer_touched_paths(
                c.get('subject', ''), cfg)
            stats['count'] += 1
            if total and (i % max(1, total // 50) == 0 or i == total - 1):
                update_stage_progress(2, 5, (i + 1) / max(total, 1),
                                      'enriching', n_done=i + 1, n_total=total)
            elif not total and i % 5000 == 0:
                update_stage_progress(2, 5, 0.5, 'enriching (stream)', n_done=i + 1)
            yield c
        if not total:
            sys.stdout.write('\n')

    from lib.io_utils import save_jsonl
    save_jsonl(os.path.join(cache, 'enriched_commits.jsonl'), _enrich_stream(commits))
    
    print('  enriched %d commits' % stats['count'])
    return {'enriched_count': stats['count']}


if __name__ == '__main__':
    main()
