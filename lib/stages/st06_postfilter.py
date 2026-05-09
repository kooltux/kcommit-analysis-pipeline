"""Stage 06 logic: apply min_score threshold, merge low-score drops."""
import os
from lib.config import load_json, save_json
from lib.manifest import CACHE_FILES


def _get_threshold(cfg):
    """Return the min_score threshold from filter.min_score (default 0)."""
    filt = cfg.get('filter', {}) or {}
    raw  = filt.get('min_score', 0)
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def run(cfg, cache):
    scored = load_json(os.path.join(cache, CACHE_FILES['scored']), default=[]) or []
    scored = sorted(scored, key=lambda c: c.get('score', 0) or 0, reverse=True)

    threshold = _get_threshold(cfg)
    if threshold > 0:
        relevant  = [c for c in scored if (c.get('score', 0) or 0) >= threshold]
        low_score = [c for c in scored if (c.get('score', 0) or 0) < threshold]
        print(f'  threshold {threshold}: kept {len(relevant)}/{len(scored)}, '
              f'dropped {len(low_score)}')
    else:
        relevant  = scored
        low_score = []
        print(f'  no threshold (min_score=0): keeping all {len(relevant)} commits')

    for rank, c in enumerate(relevant, 1):
        c['_rank'] = rank

    save_json(os.path.join(cache, CACHE_FILES['relevant']), relevant)

    if low_score:
        label    = f'score_below_threshold ({threshold})'
        for c in low_score:
            c['_filter_reason'] = label
        existing = load_json(os.path.join(cache, CACHE_FILES['filtered']), default=[]) or []
        save_json(os.path.join(cache, CACHE_FILES['filtered']), existing + low_score)
        print(f'  appended {len(low_score)} low-score commits to {CACHE_FILES["filtered"]}')

    return relevant, low_score, threshold