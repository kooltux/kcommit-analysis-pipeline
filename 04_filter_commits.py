#!/usr/bin/env python3
"""Stage 04: Enrich and filter commits before scoring.

v9.0: Complete 3-level whitelist/blacklist hierarchy.

═══════════════════════════════════════════════════════════════
  FILTER DECISION HIERARCHY  (higher level wins over lower)
═══════════════════════════════════════════════════════════════

  Level 3 — Absolute (SHA-based)
  ─────────────────────────────────────────────────────────────
  commit_whitelist  SHA ∈ list  →  FORCE-KEEP
                    Beats everything including commit_blacklist.

  commit_blacklist  SHA ∈ list  →  FORCE-DROP
                    Beaten only by commit_whitelist.

  Level 2 — Path-based (file paths touched by the commit)
  ─────────────────────────────────────────────────────────────
  path_blacklist    ALL touched files match  →  DROP
                    Beaten by: commit_whitelist.
                    Beats: path_whitelist, build_artifact, Kconfig,
                           keywords_whitelist, keywords_blacklist.

  path_whitelist    ANY touched file matches  →  KEEP
                    Beaten by: commit_blacklist, path_blacklist(all).
                    Beats: Kconfig drop, keywords_blacklist.

  Level 2½ — Build context (derived from actual build)
  ─────────────────────────────────────────────────────────────
  build_artifact    ANY touched file stem found in build_dir .o/.ko
                    files OR in build-log  →  KEEP
                    Beaten by: commit_blacklist, path_blacklist(all).
                    Beats: Kconfig drop, keywords_blacklist.
                    Rationale: if the file is actually compiled in
                    the current build, the commit is always relevant.

  Kconfig-coverage  NO touched file maps to an enabled CONFIG symbol
                    AND NOT path_whitelist AND NOT build_artifact
                    → DROP (unless keywords_whitelist saves it)
                    Auto-enabled when product_map data is available.

  Level 1 — Keyword-based (commit subject + body text)
  ─────────────────────────────────────────────────────────────
  keywords_whitelist  ANY keyword matches text  →  KEEP
                      Beaten by: commit_blacklist, path_blacklist(all).
                      Beats: Kconfig drop (saves commit from it),
                             keywords_blacklist.

  keywords_blacklist  ANY keyword matches text  →  DROP
                      Beaten by: commit_whitelist, path_whitelist,
                                 build_artifact, keywords_whitelist.

  Level 0 — Default
  ─────────────────────────────────────────────────────────────
  No rule fired  →  KEEP  (let scoring decide relevance)

═══════════════════════════════════════════════════════════════
  DECISION FLOW (pseudo-code)
═══════════════════════════════════════════════════════════════

  if sha ∈ commit_whitelist               → KEEP  (L3, absolute)
  if sha ∈ commit_blacklist               → DROP  (L3, absolute)
  if all(f ∈ path_blacklist)              → DROP  (L2a)
  if any(f ∈ path_whitelist)             → KEEP  (L2b)
  if any(f has build-artifact evidence)  → KEEP  (L2½)
  if kconfig_data AND NOT any_covered:
      if NOT any(kw ∈ kw_whitelist):     → DROP  (Kconfig)
      # else: keywords_whitelist saves it; fall through
  if any(kw ∈ keywords_whitelist)        → KEEP  (L1a)
  if any(kw ∈ keywords_blacklist)        → DROP  (L1b)
  → KEEP                                          (L0 default)

═══════════════════════════════════════════════════════════════

Config section (all optional):
  "filter": {
    "enabled":                  true,  // false = skip L2/L2½/L1 (L3 always on)
    "path_blacklist_global":    true,  // L2a: merged path_blacklist from profiles
    "require_kconfig_coverage": null   // L2½: null=auto, true=force, false=disable
  }

Reads:   cache/commits.json
         cache/product_map.json
         cache/compiled_rules.json  (via load_profile_rules)
Writes:  cache/filtered_commits.json
"""
import argparse
import fnmatch
import os
import re
import sys


# ── Build-system file patterns (always pass Kconfig coverage, C5) ─────────────
_BUILD_SYS_NAMES = frozenset({'Makefile', 'Kbuild', 'Kconfig'})

def _is_build_system_file(path):
    base = os.path.basename(path)
    if base in _BUILD_SYS_NAMES:
        return True
    if base.startswith('Makefile.') or base.startswith('Kconfig.'):
        return True
    _, ext = os.path.splitext(base)
    return ext in ('.mk',)


# ── Import helper ─────────────────────────────────────────────────────────────
def _import_override():
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location(
        'kcommit_pipeline',
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     'kcommit_pipeline.py'))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.apply_override


# ── Pattern matching ──────────────────────────────────────────────────────────
def _match(pattern, text):
    """Match pattern against text. Supports re:/glob/substring modes."""
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


def _any_matches(patterns, text):
    """Return True if any pattern matches text."""
    return any(_match(p, text) for p in patterns)


def _any_file_matches(patterns, files):
    """Return True if ANY file matches ANY pattern (OR semantics)."""
    return any(_match(p, f) for p in patterns for f in files)


def _all_files_match(patterns, files):
    """Return True if ALL files match at least one pattern (AND over files)."""
    return bool(files) and all(
        any(_match(p, f) for p in patterns)
        for f in files)


# ── List extraction from merged profile data ─────────────────────────────────
def _build_merged_lists(profile_rules):
    """Merge all 6 list types from every active profile's merged data.

    Returns a dict with keys:
      commit_wl, commit_bl, path_wl, path_bl, kw_wl, kw_bl
    """
    out = {k: [] for k in ('commit_wl','commit_bl',
                            'path_wl','path_bl',
                            'kw_wl','kw_bl')}
    MAP = {
        'commit_whitelist':   'commit_wl',
        'commit_blacklist':   'commit_bl',
        'path_whitelist':     'path_wl',
        'path_blacklist':     'path_bl',
        'keywords_whitelist': 'kw_wl',
        'keywords_blacklist': 'kw_bl',
    }
    for pdata in (profile_rules or {}).values():
        merged = (pdata or {}).get('merged', {}) or {}
        for src_key, dst_key in MAP.items():
            out[dst_key].extend(merged.get(src_key, []))
    # Deduplicate preserving order
    for k in out:
        seen = set()
        dedup = []
        for p in out[k]:
            pk = p.pattern if isinstance(p, re.Pattern) else p
            if pk not in seen:
                seen.add(pk)
                dedup.append(p)
        out[k] = dedup
    return out


# ── Compiled-file sets (build context) ───────────────────────────────────────
def _build_compiled_sets(product_map):
    """Derive coverage sets from the product map.

    Returns a dict:
      compiled_files  — .c paths belonging to ENABLED CONFIG symbols
      compiled_dirs   — directories of compiled_files (for header/ASM/DTS)
      artifact_stems  — path stems of .o/.ko in build_dir (C2: strong signal)
      log_basenames   — basename stems from build-log .o lines (C3: weaker)
      available       — True when compiled_files is non-empty
    """
    empty = dict(compiled_files=set(), compiled_dirs=set(),
                 artifact_stems=set(), log_basenames=set(), available=False)
    if not product_map:
        return empty

    c2p         = product_map.get('config_to_paths', {}) or {}
    enabled_raw = product_map.get('enabled_configs',  []) or []

    # Strip "=y" / "=m" suffix; skip disabled (=n) and non-tristate values
    enabled_set = set()
    for s in enabled_raw:
        if '=' in s:
            sym, _, val = s.partition('=')
            if val.strip() in ('y', 'm'):
                enabled_set.add(sym)
        else:
            enabled_set.add(s)   # bare symbol — assume enabled

    compiled_files = set()
    for sym, paths in c2p.items():
        if sym in enabled_set:
            compiled_files.update(paths)

    if not compiled_files:
        return empty

    compiled_dirs = {os.path.dirname(f) for f in compiled_files}
    compiled_dirs.discard('')

    # artifact_stems: build_dir scan gives full relative paths e.g. "mm/slab.o"
    artifact_stems = set()
    for p in (product_map.get('built_artifacts_from_dir', []) or []):
        stem, _ = os.path.splitext(p)
        artifact_stems.add(stem)

    # log_basenames: only basenames stored e.g. "slab.o" → "slab"
    log_basenames = set()
    for p in (product_map.get('built_objects_from_log', []) or []):
        bn = os.path.basename(p)
        stem, _ = os.path.splitext(bn)
        log_basenames.add(stem)

    return dict(compiled_files=compiled_files,
                compiled_dirs=compiled_dirs,
                artifact_stems=artifact_stems,
                log_basenames=log_basenames,
                available=True)


def _file_has_artifact(f, cs):
    """C2+C3: direct build evidence — file stem in build-dir artifacts or log.

    This is the *strong* build signal (actual .o files found).
    Used for the build_artifact KEEP decision at level 2½.
    """
    stem, _ = os.path.splitext(f)
    if stem in cs['artifact_stems']:
        return True
    bn_stem, _ = os.path.splitext(os.path.basename(f))
    return bn_stem in cs['log_basenames']


def _file_is_kconfig_covered(f, cs):
    """C1+C4+C5: Kconfig/directory coverage.

    C1 — exact match in compiled_files (CONFIG-enabled .c path)
    C4 — file lives in a directory that has compiled sources
         (handles .h headers, .S ASM, .dts DTS in the same directory)
    C5 — build-system file (Makefile/Kbuild/Kconfig always pass)
    """
    if f in cs['compiled_files']:
        return True
    fdir = os.path.dirname(f)
    if fdir and fdir in cs['compiled_dirs']:
        return True
    return _is_build_system_file(f)


# ── Core decision function ────────────────────────────────────────────────────
def filter_decision(commit, lists, compiled_sets, filter_cfg, kconfig_enabled):
    """Apply the 3-level hierarchy and return (action, reason).

    action: 'keep' | 'drop'
    reason: short label for statistics and debug output.
    """
    sha   = commit.get('commit', '') or ''
    files = list(commit.get('files', []) or [])
    text  = (commit.get('subject', '') or '') + '\n' + (commit.get('body', '') or '')

    commit_wl = lists['commit_wl']
    commit_bl = lists['commit_bl']
    path_wl   = lists['path_wl']
    path_bl   = lists['path_bl']
    kw_wl     = lists['kw_wl']
    kw_bl     = lists['kw_bl']

    # ── Level 3: Absolute SHA overrides ──────────────────────────────────────
    if commit_wl and any(_match(p, sha) for p in commit_wl):
        return 'keep', 'commit_whitelist'

    if commit_bl and any(_match(p, sha) for p in commit_bl):
        return 'drop', 'commit_blacklist'

    # ── filter.enabled=false: skip L2/L2½/L1 (only L3 was active above) ─────
    if not filter_cfg.get('enabled', True):
        return 'keep', 'filter_disabled'

    # ── Level 2a: All touched files are path-blacklisted ─────────────────────
    if path_bl and filter_cfg.get('path_blacklist_global', True):
        if _all_files_match(path_bl, files):
            return 'drop', 'all_paths_blacklisted'

    # ── Level 2b: Any touched file is path-whitelisted ───────────────────────
    if path_wl and _any_file_matches(path_wl, files):
        return 'keep', 'path_whitelist'

    # ── Level 2½: Build artifact evidence ────────────────────────────────────
    # Direct build evidence (actual .o files): beats Kconfig drop + kw_blacklist
    if compiled_sets.get('available') and files:
        if any(_file_has_artifact(f, compiled_sets) for f in files):
            return 'keep', 'build_artifact'

    # ── Kconfig coverage ─────────────────────────────────────────────────────
    kc_cfg  = filter_cfg.get('require_kconfig_coverage', None)
    use_kc  = kconfig_enabled if kc_cfg is None else bool(kc_cfg)

    if use_kc and compiled_sets.get('available') and files:
        kconfig_covered = any(_file_is_kconfig_covered(f, compiled_sets)
                              for f in files)
        if not kconfig_covered:
            # Last rescue: keywords_whitelist can save a Kconfig-uncovered commit
            # (e.g. a CVE fix in a disabled driver still worth tracking)
            if kw_wl and _any_matches(kw_wl, text):
                pass   # fall through — keywords_whitelist saves it
            else:
                return 'drop', 'no_kconfig_coverage'

    # ── Level 1a: Keywords whitelist ─────────────────────────────────────────
    if kw_wl and _any_matches(kw_wl, text):
        return 'keep', 'keywords_whitelist'

    # ── Level 1b: Keywords blacklist ─────────────────────────────────────────
    if kw_bl and _any_matches(kw_bl, text):
        return 'drop', 'keywords_blacklist'

    # ── Level 0: Default ─────────────────────────────────────────────────────
    return 'keep', 'default'


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config',   required=True)
    ap.add_argument('--override', default=None, metavar='JSON')
    args = ap.parse_args()

    from lib.config           import load_config, load_json, save_json
    from lib.scoring          import extract_commit_meta, infer_touched_paths, precompile_rules
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

        # ── Enrichment ────────────────────────────────────────────────────────
        print('  enriching commits …')
        total = len(commits)
        step  = max(1, total // 50)
        for i, c in enumerate(commits):
            c['meta']                = extract_commit_meta(c)
            c['touched_paths_guess'] = infer_touched_paths(c.get('subject',''), cfg)
            if i % step == 0 or i == total - 1:
                update_stage_progress(4, 7, 0.4 * (i + 1) / max(total, 1),
                                      'enriching', n_done=i + 1, n_total=total)
        sys.stdout.write('\n')

        # ── Build filter data structures ──────────────────────────────────────
        profile_rules  = load_profile_rules(cfg)
        precompile_rules(profile_rules)
        lists          = _build_merged_lists(profile_rules)
        compiled_sets  = _build_compiled_sets(product_map)
        kconfig_enabled = compiled_sets.get('available', False)

        # Report coverage data
        print(f'  compiled_files  : {len(compiled_sets["compiled_files"])}')
        print(f'  compiled_dirs   : {len(compiled_sets["compiled_dirs"])}')
        print(f'  artifact_stems  : {len(compiled_sets["artifact_stems"])}')
        print(f'  log_basenames   : {len(compiled_sets["log_basenames"])}')
        print(f'  commit_wl       : {len(lists["commit_wl"])} patterns')
        print(f'  commit_bl       : {len(lists["commit_bl"])} patterns')
        print(f'  path_wl         : {len(lists["path_wl"])} patterns')
        print(f'  path_bl         : {len(lists["path_bl"])} patterns')
        print(f'  keywords_wl     : {len(lists["kw_wl"])} patterns')
        print(f'  keywords_bl     : {len(lists["kw_bl"])} patterns')
        print(f'  kconfig_active  : {kconfig_enabled}')

        # ── Apply filter ──────────────────────────────────────────────────────
        kept    = []
        dropped = 0
        reasons = {}

        for i, c in enumerate(commits):
            action, reason = filter_decision(
                c, lists, compiled_sets, filter_cfg, kconfig_enabled)
            if action == 'drop':
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
