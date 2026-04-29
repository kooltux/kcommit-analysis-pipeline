#!/usr/bin/env python3
"""Stage 04: Enrich and filter commits before scoring.

v8.8: Kconfig-coverage filter completely rewritten.

Filter rules (applied in order, each commit tested against all rules):

  Rule 1  — SHA blacklist
      Always active.  Any commit whose SHA matches a profile commit_blacklist
      entry is dropped.

  Rule 2  — Path blacklist (profile-merged)
      Active when filter.path_blacklist_global = true (default).
      Drops commits where EVERY touched file matches the merged path_blacklist
      of all active profiles.

  Rule 3  — Kconfig-coverage  ← REWRITTEN in v8.8
      Active when:
        a) filter.require_kconfig_coverage = true  (default when compiled_files
           is non-empty, i.e. both config_to_paths AND enabled_configs are
           present in the product map)
        b) The compiled_files set is non-empty after intersecting
           config_to_paths keys with enabled CONFIG symbols.

      A commit is DROPPED (score = 0) when NONE of its touched files passes
      any of these coverage tests:

        C1. Source (.c/.cpp) file appears in compiled_files
            (the exact set of .c paths belonging to enabled CONFIG symbols).

        C2. Stem of a touched file appears in artifact_stems
            (stems of .o/.ko files found in the build directory).

        C3. Basename stem of a touched file appears in log_basenames
            (basenames of .o files extracted from the build log).

        C4. Touched file's directory is in compiled_dirs
            (directories that contain at least one compiled source file).
            This handles headers, ASM, DTS and other non-.c files in a
            directory that is compiled.

        C5. Touched file is a build-system file (Makefile, Kbuild, Kconfig,
            *.mk, Makefile.*).  Build-system files always pass — they affect
            what gets compiled and are always relevant.

      The old 'require_product_map' option is replaced by
      'require_kconfig_coverage' which is smarter and correct by default.

Config section (all keys optional):
  "filter": {
    "enabled":               true,   // false disables rules 2+3 (rule 1 always on)
    "path_blacklist_global": true,   // rule 2: merged profile path_blacklist
    "require_kconfig_coverage": null // rule 3: null = auto (on when data available)
                                     //          true  = always enforce
                                     //          false = disable
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


# ── Build-system file patterns (always pass coverage check) ──────────────────
_BUILD_SYS_NAMES = frozenset({'Makefile', 'Kbuild', 'Kconfig'})
_BUILD_SYS_EXTS  = frozenset({'.mk'})

def _is_build_system_file(path):
    base = os.path.basename(path)
    if base in _BUILD_SYS_NAMES:
        return True
    if base.startswith('Makefile.') or base.startswith('Kconfig.'):
        return True
    _, ext = os.path.splitext(base)
    return ext in _BUILD_SYS_EXTS


# ── Import helper (avoid top-level side-effects from kcommit_pipeline) ────────
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


# ── Blacklist extraction ──────────────────────────────────────────────────────
def _build_global_blacklists(profile_rules):
    """Merge path_blacklist and commit_blacklist from all active profiles."""
    path_bl   = []
    commit_bl = []
    for pdata in (profile_rules or {}).values():
        merged = (pdata or {}).get('merged', {}) or {}
        path_bl.extend(merged.get('path_blacklist', []))
        commit_bl.extend(merged.get('commit_blacklist', []))
    return list(set(path_bl)), list(set(commit_bl))


# ── Compiled-file sets (core of Rule 3) ──────────────────────────────────────
def _build_compiled_sets(product_map):
    """Derive coverage sets from the product map.

    Returns a dict with:
      compiled_files  — set of .c paths belonging to ENABLED CONFIG symbols
      compiled_dirs   — set of directories that contain a compiled_file
      artifact_stems  — set of path stems (no extension) from build_dir .o/.ko
      log_basenames   — set of basename stems from build-log .o lines
      available       — True when compiled_files is non-empty (data is usable)
    """
    empty = dict(compiled_files=set(), compiled_dirs=set(),
                 artifact_stems=set(), log_basenames=set(), available=False)
    if not product_map:
        return empty

    c2p         = product_map.get('config_to_paths', {}) or {}
    enabled_raw = product_map.get('enabled_configs',  []) or []

    # Build enabled_set: keep only CONFIG symbols with value =y or =m
    # load_kernel_config_symbols() returns strings like 'CONFIG_FOO=y'
    # We must NOT include symbols that are =n, =2, or any other value.
    enabled_set = set()
    for s in enabled_raw:
        if '=' in s:
            sym, _, val = s.partition('=')
            if val.strip() in ('y', 'm'):
                enabled_set.add(sym)
        else:
            # bare symbol (no = sign) — assume enabled
            enabled_set.add(s)

    # compiled_files: only .c paths belonging to enabled CONFIG symbols
    compiled_files = set()
    for sym, paths in c2p.items():
        if sym in enabled_set:
            compiled_files.update(paths)

    if not compiled_files:
        return empty   # no usable data → rule auto-disables

    compiled_dirs = {os.path.dirname(f) for f in compiled_files}
    compiled_dirs.discard('')   # normalise root-level files

    # artifact_stems: from _scan_build_dir() — full relative paths like "mm/slab.o"
    artifact_stems = set()
    for p in (product_map.get('built_artifacts_from_dir', []) or []):
        stem, _ = os.path.splitext(p)
        artifact_stems.add(stem)

    # log_basenames: only basenames stored by _extract_log_objects()
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


def _file_is_covered(f, cs):
    """Return True if file *f* has coverage evidence in compiled sets *cs*."""
    # C5: build-system file — always covered
    if _is_build_system_file(f):
        return True

    stem, _ = os.path.splitext(f)
    bn_stem  = os.path.splitext(os.path.basename(f))[0]
    fdir     = os.path.dirname(f)

    # C1: exact compiled_files match (handles .c and also .h with same stem)
    if f in cs['compiled_files']:
        return True

    # C2: stem matches a build-dir artifact (handles .c, .S, .cpp → .o)
    if stem in cs['artifact_stems']:
        return True

    # C3: basename stem in build-log (less precise — only use as tiebreaker)
    if bn_stem in cs['log_basenames']:
        return True

    # C4: file lives in a directory that has compiled source files
    #     Handles headers (.h), ASM (.S), DTS (.dts/.dtsi), README in same dir
    if fdir and fdir in cs['compiled_dirs']:
        return True

    return False


# ── Per-commit filter decision ────────────────────────────────────────────────
def _is_filtered(commit, path_bl, commit_bl, compiled_sets, filter_cfg,
                 kconfig_enabled):
    """Return (filtered: bool, reason: str).

    filtered=True  → drop commit (score treated as 0, removed from pipeline).
    """
    sha   = commit.get('commit', '') or ''
    files = list(commit.get('files', []) or [])

    # ── Rule 1: SHA blacklist (always active) ─────────────────────────────────
    for pat in commit_bl:
        if _match(pat, sha):
            return True, f'commit_blacklist:{sha[:12]}'

    if not filter_cfg.get('enabled', True):
        return False, ''

    # ── Rule 2: all touched files are path-blacklisted ────────────────────────
    if path_bl and files and filter_cfg.get('path_blacklist_global', True):
        if all(any(_match(pat, f) for pat in path_bl) for f in files):
            return True, 'all_paths_blacklisted'

    # ── Rule 3: Kconfig-coverage ──────────────────────────────────────────────
    # Default: auto (on when compiled_files set is non-empty)
    kc_cfg = filter_cfg.get('require_kconfig_coverage', None)
    use_kconfig = kconfig_enabled if kc_cfg is None else bool(kc_cfg)

    if use_kconfig and files and compiled_sets.get('available'):
        if not any(_file_is_covered(f, compiled_sets) for f in files):
            return True, 'no_kconfig_coverage'

    return False, ''


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config',   required=True)
    ap.add_argument('--override', default=None, metavar='JSON')
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

        # ── Enrichment ────────────────────────────────────────────────────────
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

        # ── Build filter data structures ──────────────────────────────────────
        profile_rules  = load_profile_rules(cfg)
        precompile_rules(profile_rules)
        path_bl, commit_bl = _build_global_blacklists(profile_rules)
        compiled_sets      = _build_compiled_sets(product_map)
        kconfig_enabled    = compiled_sets.get('available', False)

        print(f'  compiled_files: {len(compiled_sets["compiled_files"])} '
              f'| compiled_dirs: {len(compiled_sets["compiled_dirs"])} '
              f'| artifact_stems: {len(compiled_sets["artifact_stems"])} '
              f'| log_basenames: {len(compiled_sets["log_basenames"])}')
        if not kconfig_enabled:
            print('  NOTE: Kconfig-coverage check inactive '
                  '(no enabled_configs / config_to_paths available)')

        # Fast-path: nothing to filter
        if (not filter_cfg.get('enabled', True) and not commit_bl
                and not kconfig_enabled):
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
                c, path_bl, commit_bl, compiled_sets, filter_cfg, kconfig_enabled)
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
