"""Stage 06 logic: apply min_score threshold and persist postfilter drops.

v13.0.0 changes (E.7):
  - run() now writes postfilter_debug.json alongside the existing
    postfilter_dropped_commits.json.  It contains an aggregated summary
    (total/kept/dropped, threshold, score distribution buckets) analogous
    to prefilter_debug.json, giving the user a fast overview of why commits
    were dropped at this stage without having to inspect the full JSON list.
  - CACHE_FILES['postfilter_debug'] key added to lib/manifest.py.
  - Convert f-strings to %%-format for Python 3.6 compatibility.

v18.0.1 fix (Fix 5):
  - Top score bucket label renamed '100+' -> '>=100' to match uncapped score
    semantics introduced in v16.5.0.
"""
import os
from lib.config import load_json, save_json
from lib.manifest import CACHE_FILES
from lib.gitutils import batch_count_hunks
from lib.backport import enrich_commit_backport


def _get_threshold(cfg):
    """Return the min_score threshold from filter.min_score (default 0)."""
    filt = cfg.get('filter', {}) or {}
    raw = filt.get('min_score', 0)
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def _score_buckets(commits):
    """Return a dict mapping score-range labels to commit counts.

    Buckets: 0, 1-9, 10-19, 20-29, 30-49, 50-74, 75-99, >=100
    """
    buckets = {
        '0':     0,
        '1-9':   0,
        '10-19': 0,
        '20-29': 0,
        '30-49': 0,
        '50-74': 0,
        '75-99': 0,
        '>=100': 0,
    }
    for c in commits:
        s = int(c.get('score', 0) or 0)
        if s == 0:
            buckets['0'] += 1
        elif s < 10:
            buckets['1-9'] += 1
        elif s < 20:
            buckets['10-19'] += 1
        elif s < 30:
            buckets['20-29'] += 1
        elif s < 50:
            buckets['30-49'] += 1
        elif s < 75:
            buckets['50-74'] += 1
        elif s < 100:
            buckets['75-99'] += 1
        else:
            buckets['>=100'] += 1
    return buckets


def _enrich_backport(cfg, relevant):
    """Attach backport indicators (and optional hunk counts) to relevant commits.

    Runs *after* filtering, over the small relevant set only, so the optional
    patch-inspection pass for hunk counting never touches the full commit
    range (perf).  Hunk counting is opt-in via collect.count_hunks; when off,
    stats['hunks'] stays 0 and the hunks term contributes nothing to
    backport_complexity.

    Order of operations:
      1. (optional) count hunks per commit via a single batched git show.
      2. compute score_norm / backport_complexity / pick_priority, using the
         run-relative max score for score normalization.
    """
    if not relevant:
        return relevant

    collect = cfg.get('collect', {}) or {}
    if collect.get('count_hunks'):
        shas = [c.get('commit') for c in relevant if c.get('commit')]
        try:
            counts = batch_count_hunks(cfg, shas)
        except Exception as exc:   # git access is best-effort; never crash stage 06
            print('  warning: hunk counting failed (%s); hunks set to 0' % exc)
            counts = {}
        for c in relevant:
            stats = c.get('stats')
            if not isinstance(stats, dict):
                stats = {}
                c['stats'] = stats
            stats['hunks'] = int(counts.get(c.get('commit'), 0) or 0)

    max_score = max((int(c.get('score', 0) or 0) for c in relevant), default=0)
    for c in relevant:
        enrich_commit_backport(c, max_score)
    return relevant


def run(cfg, cache):
    """Sort, threshold-filter, rank commits and write output caches.

    Returns (relevant, low_score, threshold).

    Outputs written:
      CACHE_FILES['relevant']           -- kept commits with _rank assigned
      CACHE_FILES['postfilter_dropped'] -- commits below threshold
      CACHE_FILES['postfilter_debug']   -- aggregated summary (E.7)
    """
    scored = load_json(os.path.join(cache, CACHE_FILES['scored']), default=[]) or []
    scored = sorted(scored, key=lambda c: c.get('score', 0) or 0, reverse=True)

    threshold = _get_threshold(cfg)
    if threshold > 0:
        relevant  = [c for c in scored if (c.get('score', 0) or 0) >= threshold]
        low_score = [c for c in scored if (c.get('score', 0) or 0) <  threshold]
        print('  threshold %s: kept %d/%d, dropped %d' % (
            threshold, len(relevant), len(scored), len(low_score)))
    else:
        relevant  = scored
        low_score = []
        print('  no threshold (min_score=0): keeping all %d commits' % len(relevant))

    for rank, c in enumerate(relevant, 1):
        c['_rank'] = rank

    _enrich_backport(cfg, relevant)

    save_json(os.path.join(cache, CACHE_FILES['relevant']), relevant)

    label = 'score_below_threshold (%s)' % threshold
    for c in low_score:
        c['_filter_reason'] = label
    save_json(os.path.join(cache, CACHE_FILES['postfilter_dropped']), low_score)

    # E.7: write postfilter_debug.json -- aggregated observability summary
    debug_output = {
        'summary': {
            'total_scored':      len(scored),
            'kept':              len(relevant),
            'dropped':           len(low_score),
            'threshold':         threshold,
            'top_score':         int((relevant[0].get('score', 0) or 0))  if relevant  else 0,
            'bottom_kept_score': int((relevant[-1].get('score', 0) or 0)) if relevant  else 0,
            'top_dropped_score': int((low_score[0].get('score', 0) or 0)) if low_score else 0,
        },
        'score_distribution': {
            'all_scored': _score_buckets(scored),
            'kept':       _score_buckets(relevant),
            'dropped':    _score_buckets(low_score),
        },
    }
    save_json(os.path.join(cache, CACHE_FILES['postfilter_debug']), debug_output)

    return relevant, low_score, threshold
