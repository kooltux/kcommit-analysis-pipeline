"""Stage 05 logic: score filtered commits and test cherry-pick feasibility.

Uses concurrent.futures.ProcessPoolExecutor for parallel scoring.
Falls back gracefully to serial execution when:
  - workers <= 1 or fewer than 100 commits
  - ProcessPoolExecutor is unavailable (Python 3.1 on exotic platforms)
  - the executor raises on submit (e.g. pickling error with some configs)

v19.2.0:
  - Cherry-pick testing moved from stage 06 to stage 05 (G). Cherry-pick
    feasibility is an enrichment signal (like scoring), not a filtering
    criterion, so it belongs alongside scoring. This preserves all
    product-touching commits through scoring, even if they score low due to
    incomplete patterns. Stage 06 can then use both score and cherry_pickable
    as signals for thresholding/ranking.
"""
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from lib.config import load_json, save_json
from lib.scoring import score_commit, precompile_rules
from lib.profile_rules import load_profile_rules
from lib.pipeline_runtime import update_stage_progress, _eprint
from lib.manifest import CACHE_FILES, NSTAGES
from lib.schema import validate_commit_list, validate_scored_commit_list
from lib.gitutils import batch_can_cherry_pick_cached

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


def _enrich_cherry_pick(cfg, scored):
    """Attach cherry-pick feasibility to scored commits (v19.2.0).
    
    This is an enrichment operation (like scoring), not a filtering criterion.
    It runs after scoring, before stage 06 thresholding, so all product-touching
    commits preserve their cherry-pick feasibility signal regardless of score.
    
    Cherry-pick test is opt-in via collect.cherry_pick_test; when disabled,
    this function returns immediately without testing.
    
    Args:
        cfg: pipeline config dict
        scored: list of scored commits (from score_all())
    
    Returns:
        scored list with cherry_pickable and cherry_pick_info fields added
    """
    collect = cfg.get('collect', {}) or {}
    kernel = cfg.get('kernel', {}) or {}
    
    if not collect.get('cherry_pick_test') or not kernel.get('rev_old'):
        # Cherry-pick test disabled or no target revision — skip enrichment
        return scored
    
    shas = [c.get('commit') for c in scored if c.get('commit')]
    if not shas:
        return scored
    
    target_rev = kernel['rev_old']
    
    # Progress callback for cherry-pick test using standard mechanism
    total = len(shas)
    step = max(1, total // 80)
    
    def _progress(done, total, eta_seconds=None):
        """Update stage progress (eta_seconds is ignored for pipeline progress)."""
        if done % step == 0 or done == total:
            update_stage_progress(5, NSTAGES, done / max(total, 1),
                                  'cherry-pick test', n_done=done, n_total=total)
    
    try:
        # Use cached version - only tests new commits, shows progress bar with ETA
        cp_results = batch_can_cherry_pick_cached(cfg, shas, target_rev, progress_callback=_progress)
    except Exception as exc:
        _eprint(f'\nWARNING: cherry-pick test failed ({exc}); skipping')
        cp_results = {}
    
    ok_count = sum(1 for r in cp_results.values() if r.get('ok'))
    fail_count = len(cp_results) - ok_count
    _eprint(f'  cherry-pick: {ok_count}/{len(cp_results)} clean, {fail_count} with conflicts')
    
    for c in scored:
        sha = c.get('commit', '')
        if sha in cp_results:
            result = cp_results[sha]
            c['cherry_pickable'] = result.get('ok', False)
            # Store full result for inspection if needed
            c['cherry_pick_info'] = {
                'ok': result.get('ok', False),
                'conflicts': result.get('conflicts', []),
                'error': result.get('error'),
            }
        else:
            # Commit not in results (e.g., missing SHA)
            c['cherry_pickable'] = None
            c['cherry_pick_info'] = None
    
    return scored


def run(cfg, cache):
    commits       = load_json(os.path.join(cache, CACHE_FILES['prefilter_kept']), default=[]) or []
    validate_commit_list(commits)
    product_map   = load_json(os.path.join(cache, CACHE_FILES['product_map']), default={}) or {}
    profile_rules = load_profile_rules(cfg)
    update_stage_progress(5, NSTAGES, 0.01, 'ready', n_done=0, n_total=len(commits))
    scored = score_all(commits, product_map, profile_rules, cfg)
    sys.stderr.write('\n')
    sys.stderr.flush()
    
    # v19.2.0: enrich with cherry-pick feasibility (opt-in, cached, parallel-capable)
    scored = _enrich_cherry_pick(cfg, scored)
    
    validate_scored_commit_list(scored)
    save_json(os.path.join(cache, CACHE_FILES['scored']), scored)
    return scored
