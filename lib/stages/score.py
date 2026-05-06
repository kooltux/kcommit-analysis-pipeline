"""Stage 05 logic: score filtered commits."""
import os
import sys
from lib.config import load_json, save_json
from lib.scoring import score_commit, precompile_rules
from lib.profile_rules import load_profile_rules
from lib.pipeline_runtime import update_stage_progress

_g_product_map   = None
_g_profile_rules = None
_g_cfg           = None


def _worker_init(product_map, profile_rules, cfg):
    global _g_product_map, _g_profile_rules, _g_cfg
    _g_product_map   = product_map
    _g_profile_rules = profile_rules
    _g_cfg           = cfg
    precompile_rules(_g_profile_rules)


def _score_one_global(commit):
    return score_commit(commit, _g_product_map, _g_profile_rules, _g_cfg)


def score_all(commits, product_map, profile_rules, cfg):
    collect    = cfg.get('collect', {}) or {}
    configured = collect.get('score_workers', 0)
    try:
        import os as _os
        default_workers = _os.cpu_count() or 1
    except Exception:
        default_workers = 1
    workers = int(configured or 0) if int(configured or 0) > 0 else default_workers
    total   = len(commits)
    step    = max(1, total // 80)

    if workers <= 1 or total < 100:
        results = []
        for i, c in enumerate(commits):
            results.append(score_commit(c, product_map, profile_rules, cfg))
            if i % step == 0 or i == total - 1:
                update_stage_progress(5, 7, (i + 1) / max(total, 1),
                                      'scoring', n_done=i + 1, n_total=total)
        return results

    try:
        from multiprocessing import Pool, cpu_count
        max_w   = max(1, min(workers, cpu_count()))
        results = []
        with Pool(processes=max_w, initializer=_worker_init,
                  initargs=(product_map, profile_rules, cfg)) as pool:
            for i, scored in enumerate(
                    pool.imap(_score_one_global, commits, chunksize=64)):
                results.append(scored)
                if i % step == 0 or i == total - 1:
                    update_stage_progress(5, 7, (i + 1) / max(total, 1),
                                          f'scoring ({max_w} workers)',
                                          n_done=i + 1, n_total=total)
        return results
    except Exception as _mp_exc:
        print(f'\nWARNING: multiprocessing pool failed ({_mp_exc}); falling back to serial')
        results = []
        for i, c in enumerate(commits):
            results.append(score_commit(c, product_map, profile_rules, cfg))
            if i % step == 0 or i == total - 1:
                update_stage_progress(5, 7, (i + 1) / max(total, 1),
                                      'scoring (serial fallback)',
                                      n_done=i + 1, n_total=total)
        return results


def run(cfg, cache):
    commits     = load_json(os.path.join(cache, '04_filtered_commits.json'), default=[]) or []
    product_map = load_json(os.path.join(cache, '03_product_map.json'), default={}) or {}
    profile_rules = load_profile_rules(cfg)
    update_stage_progress(5, 7, 0.01, 'ready', n_done=0, n_total=len(commits))
    scored = score_all(commits, product_map, profile_rules, cfg)
    sys.stdout.write('\n'); sys.stdout.flush()
    save_json(os.path.join(cache, '05_scored_commits.json'), scored)
    return scored
