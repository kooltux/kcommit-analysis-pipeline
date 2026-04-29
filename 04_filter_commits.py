#!/usr/bin/env python3
"""Stage 04: Enrich and filter commits before scoring.

v8.6: this stage replaces 04_enrich_commits.py and adds a pre-scoring filter
that eliminates commits that cannot possibly receive a non-zero score.
Enrichment (stable_hints, touched_paths_guess) is performed first so that
filter decisions can use the enriched data.

Filter rules (applied in order):
  1. SHA blacklist  — commit SHA matches any active profile's commit_blacklist.
     Always active, even when filter.enabled = false.
  2. All-paths blacklisted — every file touched by the commit matches the
     merged path_blacklist across all active profiles.
     Controlled by filter.path_blacklist_global (default: true).
  3. No product-map coverage — no touched file appears in the product map.
     Opt-in via filter.require_product_map (default: false).

Set filter.enabled = false to skip rules 2+3 while keeping rule 1.

Config section (all keys optional):
  "filter": {
    "enabled":              true,   // set false to disable path/product filtering
    "path_blacklist_global": true,  // apply merged path_blacklists from all profiles
    "require_product_map":  false   // drop commits with zero product-map coverage
  }

Reads:   cache/commits.json
Writes:  cache/filtered_commits.json
"""
import argparse
import fnmatch
import os
import re
import sys


def _import_override():
    """Import apply_override from kcommit_pipeline without side-effects."""
    import importlib.util, os as _os
    spec = importlib.util.spec_from_file_location(
        'kcommit_pipeline',
        _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                      'kcommit_pipeline.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.apply_override


def _match(pattern, text):
    """Match *pattern* against *text* with re:/glob/substring modes."""
    if isinstance(pattern, re.Pattern):
        return bool(pattern.search(text))
    if pattern.startswith('re:'):
        try:
            return bool(re.search(pattern[3:], text, re.I))
        except re.error:
            return False
    if any(c in pattern for c in ('*', '?', '[')):
        return fnmatch.fnmatch(text, pattern)
    return pattern.lower() in text.lower()


def _build_global_blacklists(profile_rules):
    """Merge path_blacklist and commit_blacklist from all active profiles."""
    path_bl   = []
    commit_bl = []
    for pdata in (profile_rules or {}).values():
        merged = (pdata or {}).get('merged', {}) or {}
        path_bl.extend(merged.get('path_blacklist', []))
        commit_bl.extend(merged.get('commit_blacklist', []))
    return list(set(path_bl)), list(set(commit_bl))


def _is_filtered(commit, path_bl, commit_bl, product_map, filter_cfg):
    """Return (filtered: bool, reason: str).

    filtered=True means the commit should be dropped (score=0).
    """
    sha   = commit.get('commit', '') or ''
    files = list(commit.get('files', []) or [])

    # Rule 1 — SHA blacklist (always active)
    for pat in commit_bl:
        if _match(pat, sha):
            return True, f'commit_blacklist:{sha[:12]}'

    if not filter_cfg.get('enabled', True):
        return False, ''

    # Rule 2 — all touched files are blacklisted
    if path_bl and files and filter_cfg.get('path_blacklist_global', True):
        if all(any(_match(pat, f) for pat in path_bl) for f in files):
            return True, 'all_paths_blacklisted'

    # Rule 3 — no product-map coverage (opt-in)
    if filter_cfg.get('require_product_map', False) and files:
        c2p       = (product_map or {}).get('config_to_paths', {}) or {}
        all_paths = {p for paths in c2p.values() for p in paths}
        covered   = any(
            any(f == pm or f.startswith(os.path.dirname(pm) + '/')
                for pm in all_paths)
            for f in files
        )
        if not covered:
            return True, 'no_product_map_coverage'

    return False, ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config',   required=True)
    ap.add_argument('--override', default=None, metavar='JSON',
                    help='Deep-merge JSON into config (forwarded from kcommit_pipeline)')
    args = ap.parse_args()

    from lib.config           import load_config, load_json, save_json
    from lib.scoring          import extract_stable_hints, infer_touched_paths, precompile_rules
    from lib.profile_rules    import load_profile_rules
    from lib.validation       import validate_config_only as validate_inputs
    from lib.pipeline_runtime import (start_stage, finish_stage,
                                      fail_stage, update_stage_progress)

    cfg = load_config(args.config)
    if args.override:
        _import_override()(cfg, args.override)

    work       = cfg['paths']['work_dir']
    state_path = os.path.join(work, 'pipeline_state.json')
    started    = start_stage(state_path, 'filter_commits', 4, 7)

    try:
        problems, notices = validate_inputs(cfg)
        for note in notices:
            print('  NOTICE:', note)
        if problems:
            for p in problems:
                print('  ERROR:', p)
            fail_stage(state_path, 'filter_commits', started,
                       error_msg='; '.join(problems))
            raise SystemExit(2)

        cache      = os.path.join(work, 'cache')
        filter_cfg = cfg.get('filter', {}) or {}

        commits     = load_json(os.path.join(cache, 'commits.json'), default=[]) or []
        product_map = load_json(os.path.join(cache, 'product_map.json'), default={}) or {}

        # ── Enrichment (was 04_enrich_commits.py) ─────────────────────────────
        print('  enriching commits …')
        total = len(commits)
        step  = max(1, total // 50)
        for i, c in enumerate(commits):
            c['stable_hints']        = extract_stable_hints(c)
            c['touched_paths_guess'] = infer_touched_paths(c.get('subject', ''), cfg)
            if i % step == 0 or i == total - 1:
                update_stage_progress(4, 7, 0.4 * (i + 1) / max(total, 1),
                                      'enriching', n_done=i + 1, n_total=total)
        sys.stdout.write('\n')

        # ── Filter ─────────────────────────────────────────────────────────────
        profile_rules = load_profile_rules(cfg)
        precompile_rules(profile_rules)
        path_bl, commit_bl = _build_global_blacklists(profile_rules)

        # Fast-path: filter disabled and no commit blacklist
        if not filter_cfg.get('enabled', True) and not commit_bl:
            save_json(os.path.join(cache, 'filtered_commits.json'), commits)
            print(f'  filter disabled – {total} commits passed through')
            finish_stage(state_path, 'filter_commits', started, status='ok',
                         extra={'total': total, 'kept': total, 'dropped': 0,
                                'enriched': total})
            return

        kept    = []
        dropped = 0
        reasons = {}

        for i, c in enumerate(commits):
            filtered, reason = _is_filtered(
                c, path_bl, commit_bl, product_map, filter_cfg)
            if filtered:
                dropped += 1
                reasons[reason] = reasons.get(reason, 0) + 1
            else:
                kept.append(c)
            if i % step == 0 or i == total - 1:
                update_stage_progress(4, 7, 0.4 + 0.6 * (i + 1) / max(total, 1),
                                      'filtering', n_done=i + 1, n_total=total)

        sys.stdout.write('\n')
        sys.stdout.flush()

        save_json(os.path.join(cache, 'filtered_commits.json'), kept)
        print(f'  filter: {total} total → {len(kept)} kept, {dropped} dropped')
        if reasons:
            for r, n in sorted(reasons.items(), key=lambda x: -x[1]):
                print(f'    {r}: {n}')

        finish_stage(state_path, 'filter_commits', started, status='ok',
                     extra={'total': total, 'kept': len(kept),
                            'dropped': dropped, 'reasons': reasons,
                            'enriched': total})

    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        fail_stage(state_path, 'filter_commits', started, error_msg=str(exc))
        raise


if __name__ == '__main__':
    main()
