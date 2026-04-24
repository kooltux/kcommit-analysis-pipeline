#!/usr/bin/env python3
"""Stage 04: Score commits using product map, profile rules, and scoring config.

"""
import os
import sys

from lib.io_utils import ensure_dir, load_json, save_json
from lib.scoring import score_commit
from lib.profile_rules import load_profile_rules
from lib.pipeline_runtime import stage_main, update_stage_progress


# ── module-level globals for pool worker initializer ─────────────────────────
# These are set once per worker process by _worker_init(), avoiding the cost of
# pickling large product_map / profile_rules dicts for every individual task.
_g_product_map   = None
_g_profile_rules = None
_g_cfg           = None


def _worker_init(product_map, profile_rules, cfg):
    global _g_product_map, _g_profile_rules, _g_cfg
    _g_product_map   = product_map
    _g_profile_rules = profile_rules
    _g_cfg           = cfg


def _score_one_global(commit):
    """Picklable worker function; uses globals set by _worker_init."""
    return score_commit(commit, _g_product_map, _g_profile_rules, _g_cfg)


def _score_all(commits, product_map, profile_rules, cfg):
    collect = cfg.get('collect', {}) or {}
    try:
        from multiprocessing import cpu_count as _cpu
        default_workers = min(4, _cpu())
    except Exception:
        default_workers = 1
    workers = int(collect.get('score_workers', default_workers) or default_workers)
    
    total = len(commits) if isinstance(commits, list) else 0
    step  = max(1, total // 80) if total else 5000

    # ── serial path ───────────────────────────────────────────────────────────
    if workers <= 1:
        for i, c in enumerate(commits):
            yield score_commit(c, product_map, profile_rules, cfg)
            if total and (i % step == 0 or i == total - 1):
                update_stage_progress(3, 5, (i + 1) / max(total, 1),
                                      'scoring', n_done=i + 1, n_total=total)
            elif not total and i % 5000 == 0:
                update_stage_progress(3, 5, 0.5, 'scoring (stream)', n_done=i + 1)
        return

    # ── parallel path with initializer ────────────────────────────────────────
    try:
        from multiprocessing import Pool, cpu_count
        max_w = max(1, min(workers, cpu_count()))
        with Pool(processes=max_w,
                  initializer=_worker_init,
                  initargs=(product_map, profile_rules, cfg)) as pool:
            for i, scored in enumerate(
                    pool.imap(_score_one_global, commits, chunksize=64)):
                yield scored
                if total and (i % step == 0 or i == total - 1):
                    update_stage_progress(3, 5, (i + 1) / max(total, 1),
                                          'scoring (parallel)',
                                          n_done=i + 1, n_total=total)
                elif not total and i % 5000 == 0:
                    update_stage_progress(3, 5, 0.5, 'scoring (stream parallel)', n_done=i + 1)

    except Exception as e:
        print('\n  warning: parallel scoring failed: %s' % e)
        # Fallback to serial if anything goes wrong with multiprocessing
        for i, c in enumerate(commits):
            yield score_commit(c, product_map, profile_rules, cfg)
            if total and (i % step == 0 or i == total - 1):
                update_stage_progress(3, 5, (i + 1) / max(total, 1),
                                      'scoring (serial fallback)',
                                      n_done=i + 1, n_total=total)
            elif not total and i % 5000 == 0:
                update_stage_progress(3, 5, 0.5, 'scoring (fallback stream)', n_done=i + 1)


@stage_main('score_commits', 3, 5)
def main(cfg, work):
    cache = os.path.join(work, 'cache')
    ensure_dir(cache)

    # Prefer JSONL for massive ranges (200k+), fallback to JSON
    jsonl_path = os.path.join(cache, 'enriched_commits.jsonl')
    json_path  = os.path.join(cache, 'enriched_commits.json')
    if not os.path.exists(jsonl_path) and not os.path.exists(json_path):
        jsonl_path = os.path.join(cache, 'commits.jsonl')
        json_path  = os.path.join(cache, 'commits.json')

    if os.path.exists(jsonl_path):
        from lib.io_utils import iter_jsonl
        commits = iter_jsonl(jsonl_path)
        total   = 0 # unknown
    else:
        commits = load_json(json_path, default=[]) or []
        total   = len(commits)

    product_map   = load_json(os.path.join(cache, 'product_map.json'),
                              default={}) or {}
    profile_rules = load_profile_rules(cfg)

    update_stage_progress(3, 5, 0.01, 'ready',
                          n_done=0, n_total=total if total else None)

    # _score_all needs an iterable; if we have a list it works, if we have a generator it works.
    # But _score_all currently calculates 'step' based on 'total'.
    # I'll update _score_all to handle unknown total.
    
    scored_stream = _score_all(commits, product_map, profile_rules, cfg)

    sys.stdout.write('\n')
    sys.stdout.flush()

    from lib.io_utils import save_jsonl
    stats = {'count': 0}
    def _count_stream(it):
        for item in it:
            stats['count'] += 1
            yield item

    save_jsonl(os.path.join(cache, 'scored_commits.jsonl'), _count_stream(scored_stream))
    
    print('  scored %d commits' % stats['count'])
    return {'scored_commit_count': stats['count']}


if __name__ == '__main__':
    main()
