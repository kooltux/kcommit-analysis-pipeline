"""Stage 05 logic: score filtered commits.

Uses concurrent.futures.ProcessPoolExecutor for parallel scoring.
Falls back gracefully to serial execution when:
  - workers <= 1 or fewer than 100 commits
  - ProcessPoolExecutor is unavailable (Python 3.1 on exotic platforms)
  - the executor raises on submit (e.g. pickling error with some configs)
"""
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from lib.config import load_json, save_json
from lib.scoring import score_commit, precompile_rules
from lib.profile_rules import load_profile_rules
from lib.pipeline_runtime import update_stage_progress, _eprint
from lib.manifest import CACHE_FILES, NSTAGES

# ── Process-pool worker state ─────────────────────────────────────────────────
# These globals are initialised once per worker process by _worker_init().

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


# ── Serial path ───────────────────────────────────────────────────────────────

def _score_serial(commits, product_map, profile_rules, cfg, label='scoring'):
    precompile_rules(profile_rules)
    total   = len(commits)
    step    = max(1, total // 80)
    results = []
    for i, c in enumerate(commits):
        results.append(score_commit(c, product_map, profile_rules, cfg))
        if i % step == 0 or i == total - 1:
            update_stage_progress(5, NSTAGES, (i + 1) / max(total, 1),
                                  label, n_done=i + 1, n_total=total)
    return results


# ── Parallel path ─────────────────────────────────────────────────────────────

def _score_parallel(commits, product_map, profile_rules, cfg, workers):
    """Score commits using ProcessPoolExecutor.

    Each worker is initialised once with shared state via _worker_init so
    pickling per-commit is cheap (only the commit dict is transferred).
    Results are collected in submission order.
    """
    total     = len(commits)
    step      = max(1, total // 80)
    results   = [None] * total
    label     = f'scoring ({workers} workers)'

    with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_worker_init,
            initargs=(product_map, profile_rules, cfg)) as ex:

        future_to_idx = {ex.submit(_score_one_global, c): i
                         for i, c in enumerate(commits)}

        done_count = 0
        for fut in as_completed(future_to_idx):
            idx          = future_to_idx[fut]
            results[idx] = fut.result()
            done_count  += 1
            if done_count % step == 0 or done_count == total:
                update_stage_progress(5, NSTAGES, done_count / max(total, 1),
                                      label, n_done=done_count, n_total=total)

    return results


# ── Public entry point ────────────────────────────────────────────────────────

def score_all(commits, product_map, profile_rules, cfg):
    collect    = cfg.get('collect', {}) or {}
    configured = int(collect.get('score_workers', 0) or 0)
    try:
        default_workers = os.cpu_count() or 1
    except Exception:
        default_workers = 1
    workers = configured if configured > 0 else default_workers
    total   = len(commits)

    if workers <= 1 or total < 100:
        return _score_serial(commits, product_map, profile_rules, cfg)

    try:
        return _score_parallel(commits, product_map, profile_rules, cfg, workers)
    except Exception as exc:
        _eprint(f'\nWARNING: parallel scoring failed ({exc}); falling back to serial')
        return _score_serial(commits, product_map, profile_rules, cfg,
                             label='scoring (serial fallback)')


def run(cfg, cache):
    commits       = load_json(os.path.join(cache, CACHE_FILES['filtered']), default=[]) or []
    product_map   = load_json(os.path.join(cache, CACHE_FILES['product_map']), default={}) or {}
    profile_rules = load_profile_rules(cfg)
    update_stage_progress(5, NSTAGES, 0.01, 'ready', n_done=0, n_total=len(commits))
    scored = score_all(commits, product_map, profile_rules, cfg)
    sys.stderr.write('\n')
    sys.stderr.flush()
    save_json(os.path.join(cache, CACHE_FILES['scored']), scored)
    return scored