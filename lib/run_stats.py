"""lib/run_stats.py -- build exhaustive pipeline-run statistics.

Called from stage 07 (st07_report.run()) after all pipeline stages have
completed.  Reads every cache file written by stages 01-06 and aggregates
them into pipeline_run_stats.json in the output directory.

The resulting file is the sole data source for the HTML report's right-pane
"Global Stats" panel.  All lists are exhaustive (no top-N truncation) and
sorted descending by count so the UI renderer is a simple loop.

Design rules
------------
* Every ranked list follows the shape:  {"items": [{"<key>": v, "count": N}, ...]}
* Zero-count entries ARE included for reason/rule/pattern lists so inactive
  escape hatches are visible in the UI.
* All aggregation is done here at write time; the HTML page does zero math.

v14.1.0: initial implementation.
v16.8.0: _build_stage05() now emits score_max, score_min, score_avg and
         score_median at the top level of the stage_05_scoring dict so that
         html_report._sidebar_payload() can read them directly.  Previously
         those fields only existed inside the per-profile sub-dicts, which
         caused the global avg/median to always display 0 in the HTML report.
v16.12.0: replaced fixed 100+ score buckets with dynamic equal-width
          histogram using observed score range (lo/hi/mid/label/count).
"""
import datetime
import math
import os
import statistics
from collections import Counter

from lib.config import load_json, save_json
from lib.manifest import CACHE_FILES, VERSION


# ---------------------------------------------------------------------------
# Score bucket helpers
# ---------------------------------------------------------------------------

def _nice_step(span, target_bins=16):
    """Return a human-friendly histogram step for the observed score span."""
    if span <= 0:
        return 1
    raw = float(span) / max(1, int(target_bins))
    mag = 10 ** math.floor(math.log10(raw))
    for mult in (1, 2, 2.5, 5, 10):
        step = mult * mag
        if step >= raw:
            return max(1, int(step))
    return max(1, int(10 * mag))


def _score_dist(commits, target_bins=16):
    """Return an equal-width histogram over the observed score range.

    Each bucket item has the shape:
        {'label': '0-24', 'lo': 0, 'hi': 24, 'mid': 12.0, 'count': N}

    The range is computed from the actual min/max of the supplied commits
    so the chart always spans the full observed domain.
    """
    scores = [int(x.get('score', 0) or 0) for x in commits]
    if not scores:
        return []

    lo = min(scores)
    hi = max(scores)

    if lo == hi:
        return [{
            'label': str(lo),
            'lo': lo,
            'hi': hi,
            'mid': float(lo),
            'count': len(scores),
        }]

    step = _nice_step(hi - lo, target_bins=target_bins)
    start = int(math.floor(lo / step) * step)
    end = int(math.ceil(hi / step) * step)
    if end <= hi:
        end += step

    edges = list(range(start, end + 1, step))
    bins = []
    for i in range(len(edges) - 1):
        b_lo = int(edges[i])
        b_hi = int(edges[i + 1] - 1)
        bins.append({
            'label': f'{b_lo}-{b_hi}',
            'lo': b_lo,
            'hi': b_hi,
            'mid': (b_lo + b_hi) / 2.0,
            'count': 0,
        })

    for s in scores:
        idx = min(int((s - start) // step), len(bins) - 1)
        bins[idx]['count'] += 1

    return bins


# ---------------------------------------------------------------------------
# Generic ranked-list helpers
# ---------------------------------------------------------------------------

def _rank_items(counter, key_name, zero_keys=None):
    """Return sorted-descending items list from *counter*.

    If *zero_keys* is provided, every key in the list appears in the output
    even when its count is zero.  Items from *counter* that are NOT in
    *zero_keys* are still included if they have a non-zero count.
    """
    merged = dict(counter)
    if zero_keys:
        for k in zero_keys:
            merged.setdefault(k, 0)
    return [
        {key_name: k, 'count': int(v)}
        for k, v in sorted(merged.items(), key=lambda kv: (-kv[1], str(kv[0])))
    ]


def _threshold_sensitivity(scored, thresholds=None):
    """Pre-compute kept-count at a set of threshold values."""
    if thresholds is None:
        thresholds = [0, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100]
    scores = [float(c.get('score', 0) or 0) for c in scored]
    return [
        {'threshold': t, 'kept': int(sum(1 for s in scores if s >= t))}
        for t in thresholds
    ]


# ---------------------------------------------------------------------------
# Stage-04 prefilter aggregations
# ---------------------------------------------------------------------------

_ALL_DROP_REASONS = [
    'no_kconfig_coverage',
    'path_blacklist_all',
    'commit_blacklist',
    'no_files_layer',
]

_ALL_KEEP_REASONS = [
    'build_artifact',
    'default',
    'filter_disabled',
    'commit_whitelist',
    'no_files_layer',
]


def _build_stage04(filtered, prefilter_kept, pf_sum, product_map, filter_cfg):
    """Aggregate stage-04 prefilter stats from dropped + kept commits."""
    drop_reasons_raw = pf_sum.get('drop_reasons') or {}
    pattern_counts   = pf_sum.get('pattern_counts') or {}

    dropped_files      = Counter()
    dropped_dirs       = Counter()
    dropped_subsystems = Counter()
    dropped_authors    = Counter()
    kept_authors       = Counter()
    path_bl_hits       = Counter()
    commit_bl_hits     = Counter()
    keep_reasons_ctr   = Counter()

    for c in filtered:
        dropped_authors[c.get('author_name', '') or ''] += 1
        for f in (c.get('files') or []):
            dropped_files[f] += 1
            d = os.path.dirname(f)
            dropped_dirs[(d + '/') if d else '(root)/'] += 1
            top = f.split('/', 1)[0]
            dropped_subsystems[top] += 1
        dbg = c.get('_prefilter_debug') or {}
        for m in (dbg.get('l2a_path_bl_matches') or []):
            pat = m.get('pattern', '') if isinstance(m, dict) else str(m)
            path_bl_hits[pat] += 1
        if c.get('_filter_reason') == 'commit_blacklist':
            hit = dbg.get('l3_commit_bl_match') or {}
            sha = hit.get('pattern', '') if isinstance(hit, dict) else str(hit)
            commit_bl_hits[sha] += 1

    for c in prefilter_kept:
        kept_authors[c.get('author_name', '') or ''] += 1
        reason = c.get('_prefilter_reason', 'default') or 'default'
        keep_reasons_ctr[reason] += 1

    # ensure all configured path_bl patterns appear (even if count=0)
    for pat in (filter_cfg.get('path_blacklist') or []):
        path_bl_hits.setdefault(str(pat), 0)

    artifact_stems  = len(product_map.get('built_artifacts_from_dir') or [])
    log_basenames   = len(product_map.get('built_objects_from_log') or [])

    return {
        'filter_enabled':      bool(pf_sum),
        'kconfig_active':      bool(pf_sum.get('kconfig_active', False)),
        'compiled_files':      int(pf_sum.get('compiled_files', 0) or 0),
        'compiled_dirs':       int(pf_sum.get('compiled_dirs', 0) or 0),
        'artifact_stems':      artifact_stems,
        'log_basenames':       log_basenames,
        'pattern_counts':      pattern_counts,
        'drop_reasons':        {'items': _rank_items(Counter(drop_reasons_raw), 'reason',
                                                     zero_keys=_ALL_DROP_REASONS)},
        'keep_reasons':        {'items': _rank_items(keep_reasons_ctr, 'reason',
                                                     zero_keys=_ALL_KEEP_REASONS)},
        'dropped_files':       {'items': _rank_items(dropped_files, 'file')},
        'dropped_dirs':        {'items': _rank_items(dropped_dirs, 'dir')},
        'dropped_subsystems':  {'items': _rank_items(dropped_subsystems, 'subsystem')},
        'path_bl_pattern_hits':{'items': _rank_items(path_bl_hits, 'pattern')},
        'commit_bl_sha_hits':  {'items': _rank_items(commit_bl_hits, 'sha')},
        'dropped_authors':     {'items': _rank_items(dropped_authors, 'author')},
        'kept_authors':        {'items': _rank_items(kept_authors, 'author')},
    }


# ---------------------------------------------------------------------------
# Stage-05 scoring aggregations
# ---------------------------------------------------------------------------

def _build_stage05(scored):
    """Aggregate stage-05 scoring stats from scored_commits.json.

    v16.8.0: emits score_max, score_min, score_avg, score_median at the
    top level of the returned dict (in addition to the per-profile
    equivalents inside 'profiles').  html_report._sidebar_payload() reads
    these top-level fields to populate the global Score Distribution block;
    without them it falls back to 0, causing wrong avg / median display.

    v16.12.0: per-profile and global score_distribution now use
    dynamic equal-width bins over the observed score range instead of
    fixed 100+ buckets.
    """
    profiles_hit  = Counter()
    profile_data  = {}   # pname -> accumulator dict

    for c in scored:
        matched = c.get('matched_profiles') or []
        for p in matched:
            profiles_hit[p] += 1

        trace = ((c.get('scoring') or {}).get('trace') or {}).get('profiles') or {}
        for pname, pd in trace.items():
            if not isinstance(pd, dict):
                continue
            d = profile_data.setdefault(pname, {
                'commits_nonzero': 0,
                'score_sum':  0,
                'score_max':  0,
                'score_min':  None,
                'rules_hit':  Counter(),
                'raw_scores': [],
            })
            s = int(pd.get('final_score', 0) or 0)
            if s > 0:
                d['commits_nonzero'] += 1
            d['score_sum'] += s
            d['score_max']  = max(d['score_max'], s)
            d['score_min']  = s if d['score_min'] is None else min(d['score_min'], s)
            d['raw_scores'].append(s)
            for rname, rd in (pd.get('rules') or {}).items():
                if isinstance(rd, dict) and rd.get('matched'):
                    d['rules_hit'][rname] += 1

    profiles_out = {}
    for pname, d in profile_data.items():
        cnt = d['commits_nonzero']
        profiles_out[pname] = {
            'commits_scored':     cnt,
            'score_sum':          d['score_sum'],
            'score_avg':          round(d['score_sum'] / cnt, 1) if cnt else 0,
            'score_max':          d['score_max'],
            'score_min':          d['score_min'] if d['score_min'] is not None else 0,
            'score_distribution': _score_dist(
                [{'score': s} for s in d['raw_scores']]
            ),
            'rules_hit':          [{'rule': k, 'count': int(v)}
                                    for k, v in sorted(d['rules_hit'].items(),
                                                       key=lambda kv: (-kv[1], kv[0]))],
        }

    # ------------------------------------------------------------------
    # Global score statistics across ALL scored commits
    # (including zero-score commits — consistent with the distribution).
    # These top-level fields are read by html_report._sidebar_payload()
    # to populate the Score Distribution stat block.
    # ------------------------------------------------------------------
    all_scores = [int(c.get('score', 0) or 0) for c in scored]
    nonzero    = [s for s in all_scores if s > 0]

    g_max    = max(all_scores)          if all_scores else 0
    g_min    = min(nonzero)             if nonzero    else 0
    g_avg    = round(statistics.mean(all_scores),          1) if all_scores else 0
    g_median = round(statistics.median(all_scores),        1) if all_scores else 0

    return {
        'total_scored':           len(scored),
        'zero_score_commits':     sum(1 for s in all_scores if s == 0),
        'multi_profile_commits':  sum(1 for c in scored if len(c.get('matched_profiles') or []) > 1),
        # Global score stats — consumed by html_report._sidebar_payload()
        'score_max':              g_max,
        'score_min':              g_min,
        'score_avg':              g_avg,
        'score_median':           g_median,
        'score_distribution':     {'items': _score_dist(scored)},
        'profiles_hit':           {'items': _rank_items(profiles_hit, 'profile')},
        'profiles':               profiles_out,
    }


# ---------------------------------------------------------------------------
# Stage-06 postfilter aggregations
# ---------------------------------------------------------------------------

def _build_stage06(scored, relevant, postfilter_dropped, pf6_sum):
    """Aggregate stage-06 postfilter stats."""
    return {
        'threshold':           pf6_sum.get('threshold', None),
        'total_scored':        len(scored),
        'kept':                len(relevant),
        'dropped':             len(postfilter_dropped),
        'top_score':           pf6_sum.get('top_score', 0),
        'bottom_kept_score':   pf6_sum.get('bottom_kept_score', 0),
        'top_dropped_score':   pf6_sum.get('top_dropped_score', 0),
        'score_distribution': {
            'all_scored': {'items': _score_dist(scored)},
            'kept':       {'items': _score_dist(relevant)},
            'dropped':    {'items': _score_dist(postfilter_dropped)},
        },
        'threshold_sensitivity': {'items': _threshold_sensitivity(scored)},
    }


# ---------------------------------------------------------------------------
# Product-map summary
# ---------------------------------------------------------------------------

def _build_product_map_summary(product_map, pf_sum):
    """Summarise product_map.json for the right-pane product section."""
    cem = product_map.get('config_enabled_map') or {}

    # Build per-subsystem file counts from the enabled map paths
    subsystem_files = Counter()
    subsystem_dirs  = Counter()
    for paths in cem.values():
        for p in (paths or []):
            top = p.split('/', 1)[0]
            subsystem_files[top] += 1
            d = os.path.dirname(p)
            if d:
                subsystem_dirs[top] += 1

    subsystem_items = [
        {'subsystem': k, 'files': subsystem_files[k], 'dirs': subsystem_dirs.get(k, 0)}
        for k in sorted(subsystem_files, key=lambda x: -subsystem_files[x])
    ]

    return {
        'kconfig_symbols_enabled': len(cem),
        'compiled_files':          int(pf_sum.get('compiled_files', 0) or 0),
        'compiled_dirs':           int(pf_sum.get('compiled_dirs', 0) or 0),
        'artifact_stems':          len(product_map.get('built_artifacts_from_dir') or []),
        'log_basenames':           len(product_map.get('built_objects_from_log') or []),
        'subsystems':              {'items': subsystem_items},
    }


# ---------------------------------------------------------------------------
# Kernel annotation cross-reference
# ---------------------------------------------------------------------------

def _build_kernel_annotations(collected, relevant):
    """Cross-reference is_fix / CVE / syzbot / stable flags vs kept set."""
    kept_shas = {(c.get('commit') or '') for c in relevant}

    def _flag(commits, key):
        return sum(1 for c in commits if (c.get('meta') or {}).get(key, False))

    def _flag_kept(commits, key):
        return sum(1 for c in commits
                   if (c.get('meta') or {}).get(key, False)
                   and (c.get('commit') or '') in kept_shas)

    return {
        'total_commits':        len(collected),
        'is_fix':               _flag(collected, 'is_fix'),
        'has_cve':              _flag(collected, 'has_cve'),
        'has_syzbot':           _flag(collected, 'has_syzbot'),
        'has_stable_cc':        _flag(collected, 'has_stable_cc'),
        'is_fix_and_kept':      _flag_kept(collected, 'is_fix'),
        'has_cve_and_kept':     _flag_kept(collected, 'has_cve'),
        'has_syzbot_and_kept':  _flag_kept(collected, 'has_syzbot'),
        'has_stable_cc_and_kept': _flag_kept(collected, 'has_stable_cc'),
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_run_stats(cfg, cache, outdir=None):
    """Build and return the pipeline_run_stats dict.

    Reads all cache files written by stages 01-06.  Missing files are
    treated as empty; their absence is noted in the 'warnings' list.

    When *outdir* is provided, writes pipeline_run_stats.json there.
    Always returns the dict regardless of *outdir*.
    """
    warnings = []

    def _load(key):
        path = os.path.join(cache, CACHE_FILES[key])
        if not os.path.exists(path):
            warnings.append('cache file missing: %s' % CACHE_FILES[key])
            return None
        return load_json(path, default=None)

    collected          = _load('commits')            or []
    prefilter_kept     = _load('prefilter_kept')     or []
    filtered           = _load('filtered')           or []
    scored             = _load('scored')             or []
    relevant           = _load('relevant')           or []
    postfilter_dropped = _load('postfilter_dropped') or []
    pf_debug           = _load('prefilter_debug')    or {}
    pf6_debug          = _load('postfilter_debug')   or {}
    product_map        = _load('product_map')        or {}

    pf_sum  = pf_debug.get('summary')  or {}
    pf6_sum = pf6_debug.get('summary') or {}

    filter_cfg = (cfg.get('filter') or {}) if isinstance(cfg, dict) else {}

    git      = (cfg.get('git') or {}) if isinstance(cfg, dict) else {}
    base_rev = git.get('base_rev') or ''
    head_rev = git.get('head_rev') or ''

    stats = {
        'meta': {
            'pipeline_version': VERSION,
            'generated_at':     datetime.datetime.now(datetime.timezone.utc).strftime(
                '%Y-%m-%dT%H:%M:%S.%f') + 'Z',
            'cache_dir':        cache,
            'git_range':        ('%s..%s' % (base_rev, head_rev))
                                 if base_rev and head_rev else None,
            'kernel_version':   git.get('kernel_version') or None,
            'product_name':     (cfg.get('reports') or {}).get('title') or None,
        },
        'funnel': {
            'collected':          len(collected),
            'prefilter_kept':     len(prefilter_kept),
            'prefilter_dropped':  len(filtered),
            'scored':             len(scored),
            'postfilter_kept':    len(relevant),
            'postfilter_dropped': len(postfilter_dropped),
            'final_report':       len(relevant),
            'pass_rate_pct':      round(len(relevant) / len(collected) * 100, 1)
                                  if collected else 0,
        },
        'stage_04_prefilter':  _build_stage04(
            filtered, prefilter_kept, pf_sum, product_map, filter_cfg),
        'stage_05_scoring':    _build_stage05(scored),
        'stage_06_postfilter': _build_stage06(
            scored, relevant, postfilter_dropped, pf6_sum),
        'product_map_summary': _build_product_map_summary(product_map, pf_sum),
        'kernel_annotations':  _build_kernel_annotations(collected, relevant),
        'warnings':            warnings,
    }

    if outdir:
        os.makedirs(outdir, exist_ok=True)
        save_json(os.path.join(outdir, CACHE_FILES['run_stats']), stats)

    return stats
