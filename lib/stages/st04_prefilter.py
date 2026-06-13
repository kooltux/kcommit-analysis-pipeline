"""Stage 04 logic: enrich and pre-filter commits before scoring.

Filter hierarchy (higher level wins):
  L3 SHA whitelist  -> FORCE-KEEP
  L3 SHA blacklist  -> FORCE-DROP
  L2a path_blacklist ALL files -> DROP
        Note: a commit whose files are a *mix* of blacklisted and non-blacklisted
        paths is NOT dropped at L2a; it falls through to L2half and below.  The
        rationale is that a path blacklist entry means "this subsystem is not
        relevant", not "any commit that merely touches this subsystem is junk".
        Only commits where every file lives under a blacklisted prefix are dropped.
  L2half build artifact evidence -> KEEP
  L2half kconfig coverage miss   -> DROP  (no rescue)
        The keyword whitelist is a *scoring* concept, not a filter concept.
        If no build evidence is available at all (compiled_files empty, no
        artifacts, no log) the filter is inactive (available=False) and every
        commit is kept for scoring to resolve.
  L0  default                    -> KEEP

Zero-file commits (merge commits, tag objects):
  A commit with no files bypasses all path/artifact/kconfig layers and
  is kept unconditionally with reason='no_files_layer'.

Design contract (v14.1.0):
  The prefilter answers exactly one question: is this commit built in the
  product?  Keywords are irrelevant to that question -- they describe
  importance/severity, not build membership.  All keyword and path-whitelist
  matching belongs exclusively in the stage-05 scoring engine.

  path_blacklist is kept as an operator escape hatch for paths that are
  structurally never relevant regardless of build evidence (e.g.
  Documentation/, tools/testing/).  SHA overrides are kept for explicit
  per-commit operator decisions.

v12.0.0 (A.1) -- filter_decision() returns a 3-tuple
  (action, reason, debug_detail) where debug_detail is a dict keyed by:
    sha, files, filter_enabled, kconfig_required,
    l3_commit_wl_match, l3_commit_bl_match,
    l2a_path_bl_matches,
    l2half_artifact_files,
    l2half_kconfig_covered_files, l2half_kconfig_uncovered_files
  All dropped commits carry this field in the cache and in the
  prefilter_debug.json output file.

v13.0.0 changes (E.1.1-E.1.6, E.6):
  E.1.1 -- _file_has_artifact() called only once per commit in filter_decision();
           result reused for both the guard condition and debug capture.
  E.1.2 -- kconfig_covered / kconfig_uncovered computed unconditionally before
           the drop decision so debug output is always accurate.
  E.1.4 -- L2a semantics documented: only drops when ALL files are blacklisted.
  E.1.5 -- zero-file commits get explicit early handling.
  E.1.6 -- build_compiled_sets(): removed ambiguous else-branch that added raw
           'CONFIG_FOO=m' strings (with '=') to enabled_set when the entry had no
           '=' separator.
  E.6   -- removed dead 'tmpl = reports' assignment and stale comment in
           write_outputs().
  G     -- filter_decision(): zero-file default keep now emits reason='no_files_layer'.

v13.0.1 changes (Bug-1 fix):
  H     -- build_compiled_sets(): reads product_map['config_enabled_map'] and
           product_map['config_enabled_dirs'] instead of 'config_to_paths'.

v13.0.2 changes (Bug-2 fix):
  I     -- build_compiled_sets(): available=True when ANY evidence source is
           non-empty (config_enabled_map, built_artifacts_from_dir, or
           built_objects_from_log).

v14.0.0 changes (A -- kw_wl rescue suppression):
  Partial fix: suppressed kw_wl rescue when compiled_files was non-empty.
  Superseded by v14.1.0.

v14.1.0 changes (B -- keyword/path-wl decoupling):
  B     -- Removed keyword whitelist/blacklist and path whitelist from the
           prefilter entirely.  These are scoring concepts, not filter concepts.
           build_merged_lists() deleted.  filter_decision() no longer accepts
           a `lists` argument.  L2b (path_whitelist), L1a (kw_wl), L1b (kw_bl)
           layers and the kw_wl rescue mechanism (including
           kw_wl_rescue_suppressed debug field) are all removed.
           The filter now answers only: "is this commit built in the product?"
           Scoring resolves importance/severity via profile rules.

v16.0.0 changes (C -- Kconfig/Makefile directory-scoped coverage):
  C     -- _file_is_kconfig_covered(): build-system files (Kconfig, Makefile,
           Kbuild, *.mk) no longer receive an unconditional coverage pass.
           A build-system file is now considered covered only when its own
           directory is present in compiled_dirs (i.e. the subsystem it
           configures is built into the product), or when the file lives at
           the kernel root (fdir == '', e.g. the top-level Makefile/Kconfig).

           Previously, _is_build_system_file() returned True for any such file
           regardless of location, causing false-keeps for commits touching
           e.g. fs/btrfs/Kconfig when CONFIG_BTRFS_FS was absent from the
           product .config.  The file matched _is_build_system_file() -> True,
           which short-circuited the coverage check and kept the commit as if
           it were product-relevant.

           The fix is consistent with the design contract: the prefilter
           answers "is this commit built in the product?"  A Kconfig or
           Makefile in an uncovered subsystem directory is not built.

           Additionally, the compiled_dirs membership check is now performed
           with a trailing-slash normalisation (fdir + '/') to match the form
           stored in compiled_dirs by st03 _derive_config_dirs().  This makes
           the directory lookup reliable for all file types, not just
           build-system files.

           Root-level exception: files at the kernel root (os.path.dirname
           returns '') are always considered covered -- the top-level Kconfig
           and Makefile are unconditionally product-relevant.

v16.0.1 changes (D -- artifact trailing-slash normalisation):
  D     -- _file_has_artifact(): applied the same trailing-slash normalisation
           to the compiled_dirs membership check that was applied to
           _file_is_kconfig_covered() in v16.0.0.  Prior to this fix,
           os.path.dirname() returns paths without a trailing slash (e.g.
           "drivers/usb/core") while compiled_dirs stores entries with one
           (e.g. "drivers/usb/core/"), causing the directory-scope guard for
           log_basenames to always fail silently.  Log-basename artifact hits
           were therefore only accepted via the exact compiled_files match,
           making the directory-scope guard effectively dead code since
           v13.0.1 (v12.0.2) when _derive_config_dirs() began storing
           trailing-slash paths.

           Effect: commits whose files are identified via build-log basenames
           AND whose directory is in compiled_dirs are now correctly kept via
           the build_artifact layer, as originally intended by the
           directory-scope guard design (v12.0.2).

prefilter_debug.json schema (v14.1.0):
  {
    "summary": {
      "total_commits":   <int>,
      "kept":            <int>,
      "dropped":         <int>,
      "drop_reasons":    { reason: count, ... },
      "pattern_counts":  { commit_wl: N, commit_bl: N, path_bl: N },
      "kconfig_active":  <bool>,
      "compiled_files":  <int>,
      "compiled_dirs":   <int>
    },
    "dropped": [
      {
        "sha":         <str>,
        "sha12":       <str>,
        "subject":     <str>,
        "author":      <str>,
        "files":       [<str>, ...],
        "drop_reason": <str>,
        "debug":       {
          "sha", "files", "filter_enabled", "kconfig_required",
          "l3_commit_wl_match", "l3_commit_bl_match",
          "l2a_path_bl_matches",
          "l2half_artifact_files",
          "l2half_kconfig_covered_files",
          "l2half_kconfig_uncovered_files"
        }
      },
      ...
    ]
  }
"""
import csv
import json
import logging
import os
import re
import sys

from lib.config import save_json
from lib.patterns import (
    match as _match,
    anyfilematches as _any_file_matches,
    allfilesmatch as _all_files_match,
)
from lib.pipeline_runtime import update_stage_progress, finish_progress_line
from lib.profile_rules import load_profile_rules
from lib.scoring import extract_commit_meta, precompile_rules, fmt_profiles, fmt_evidence
from lib.kbuild import infer_touched_paths
from lib.manifest import CACHE_FILES, NSTAGES
from lib.schema import validate_commit_list, validate_filtered_commit_list

_BUILD_SYS_NAMES = frozenset({'Makefile', 'Kbuild', 'Kconfig'})


def _is_build_system_file(path):
    base = os.path.basename(path)
    if base in _BUILD_SYS_NAMES:
        return True
    if base.startswith('Makefile.') or base.startswith('Kconfig.'):
        return True
    _, ext = os.path.splitext(base)
    return ext in ('.mk',)


def build_compiled_sets(product_map):
    """Build the compiled_sets lookup structure used by _file_has_artifact() and
    _file_is_kconfig_covered().

    v13.0.1 (H): reads config_enabled_map and config_enabled_dirs from
    product_map instead of config_to_paths.  config_enabled_map is the
    enabled-symbol-only subset computed by st03 _filter_to_enabled(); it
    contains only CONFIG symbols that are =y or =m in the product .config.

    Falls back gracefully when config_enabled_map is absent (pre-v13.0.1 cache).

    v13.0.2 (Bug-2 fix): available=True is set based on whether ANY evidence
    source is non-empty (config_enabled_map, built_artifacts_from_dir, or
    built_objects_from_log), not solely on config_enabled_map.

    Design contract:
      available=True  -> at least one evidence source is non-empty; commits with
                         zero coverage across all sources are confidently dropped.
      available=False -> all evidence sources empty; kconfig filter inactive;
                         scoring resolves ambiguities (correct when the user
                         provides kernel sources only, with no .config/logs/dir).
    """
    empty = dict(compiled_files=set(), compiled_dirs=set(),
                 artifact_stems=set(), log_basenames=set(), available=False)
    if not product_map:
        return empty

    cem = product_map.get('config_enabled_map')
    if cem is None:
        logging.warning(
            'build_compiled_sets: config_enabled_map not found in product_map '
            '(cache pre-dates v13.0.1). Re-run stage 03 to fix. '
            'Falling back to empty compiled set to avoid false-positive keeps.')
        return empty

    compiled_files = set()
    for paths in cem.values():
        compiled_files.update(paths)

    ced = product_map.get('config_enabled_dirs') or []
    compiled_dirs = set(d for d in ced if d)

    artifact_stems = set()
    for p in (product_map.get('built_artifacts_from_dir', []) or []):
        stem, _ = os.path.splitext(p)
        artifact_stems.add(stem)

    log_basenames = set()
    for p in (product_map.get('built_objects_from_log', []) or []):
        bn = os.path.basename(p)
        stem, _ = os.path.splitext(bn)
        log_basenames.add(stem)

    has_evidence = bool(compiled_files or artifact_stems or log_basenames)
    if not has_evidence:
        logging.info(
            'build_compiled_sets: no compiled-file evidence found in product_map '
            '(config_enabled_map={}, no build artifacts, no build log). '
            'kconfig coverage filter will be inactive; scoring will resolve ambiguities.')

    return dict(compiled_files=compiled_files, compiled_dirs=compiled_dirs,
                artifact_stems=artifact_stems, log_basenames=log_basenames,
                available=has_evidence)


def _file_has_artifact(f, cs):
    """Return True if *f* has build-artifact evidence.

    Two evidence sources are checked in order:

    1. ``artifact_stems`` -- full path stems derived from ``built_artifacts_from_dir``
       (e.g. ``'drivers/usb/core/hub'``).  A full-path stem match is precise and
       needs no further qualification.

    2. ``log_basenames`` -- bare filename stems derived from build-log tokens
       (e.g. ``'hub'`` from ``hub.o``).  Directory-scoped: a log-basename hit is
       only accepted when the file's parent directory is in ``compiled_dirs`` or
       the file itself is in ``compiled_files``.

    Trailing-slash normalisation (v16.0.1):
       ``compiled_dirs`` stores entries with a trailing slash (as produced by st03
       ``_derive_config_dirs()``), while ``os.path.dirname()`` returns paths without
       one.  The directory lookup is normalised here so that the membership test
       is reliable.  This is the same normalisation applied in
       ``_file_is_kconfig_covered()`` since v16.0.0.
    """
    stem, _ = os.path.splitext(f)
    if stem in cs['artifact_stems']:
        return True

    bn_stem, _ = os.path.splitext(os.path.basename(f))
    if bn_stem not in cs['log_basenames']:
        return False
    fdir = os.path.dirname(f)
    fdir_norm = (fdir.rstrip('/') + '/') if fdir else ''
    return (
        (fdir and fdir_norm in cs['compiled_dirs'])
        or f in cs['compiled_files']
    )


def _file_is_kconfig_covered(f, cs):
    """Return True if *f* is considered covered by the product build.

    Coverage is established by three evidence sources, checked in order:

    1. ``compiled_files`` -- exact path match against the set of source files
       associated with enabled CONFIG symbols (config_enabled_map).  This is
       the most precise evidence.

    2. ``compiled_dirs`` -- the file's parent directory (normalised to the
       trailing-slash form stored by st03 _derive_config_dirs, e.g.
       ``"drivers/usb/core/"``) is present in the set of directories derived
       from enabled CONFIG symbols.  A file in a compiled directory is
       considered product-relevant even when it does not appear directly in
       compiled_files (e.g. inline headers, generated stubs).

    3. Build-system files (Kconfig, Makefile, Kbuild, *.mk) -- covered *only*
       when their own directory satisfies rule 2 above, OR when they live at
       the kernel root (os.path.dirname returns '').

       v16.0.0 (C): prior to this version, _is_build_system_file() returned an
       unconditional True for any such file regardless of its location.  This
       caused false-keeps for commits like "btrfs: add Kconfig option for ..."
       that touch fs/btrfs/Kconfig when CONFIG_BTRFS_FS is absent from the
       product .config -- the file matched the build-system check and bypassed
       kconfig coverage entirely.

       The root exception (fdir == '') preserves correct behaviour for the
       kernel's top-level Kconfig and Makefile, which are unconditionally
       product-relevant regardless of which CONFIG symbols are enabled.

    Trailing-slash normalisation (v16.0.0):
       st03 _derive_config_dirs() stores directory paths with a trailing slash
       (e.g. ``"drivers/usb/core/"``), while os.path.dirname() returns paths
       without one (e.g. ``"drivers/usb/core"``).  The lookup is normalised
       here so that the membership test is reliable for all file types.
    """
    if f in cs['compiled_files']:
        return True

    fdir = os.path.dirname(f)
    # compiled_dirs stores trailing-slash normalised paths (e.g. "drivers/usb/core/").
    # os.path.dirname returns paths without a trailing slash.  Normalise before
    # lookup so the membership test is reliable for all file types.
    fdir_norm = (fdir.rstrip('/') + '/') if fdir else ''

    if fdir and fdir_norm in cs['compiled_dirs']:
        return True

    # Build-system files (Kconfig, Makefile, Kbuild, *.mk): product-relevant
    # only when their directory is compiled into the product, or when they live
    # at the kernel root (fdir == '').  The compiled_dirs check above already
    # handles the "directory is compiled" case; we reach here only when it did
    # not match, so we apply the root exception only.
    if _is_build_system_file(f):
        return not fdir   # True only at root level (fdir == '')

    return False


# -- Pattern repr helper -------------------------------------------------------

def _pat_repr(pat):
    return getattr(pat, 'pattern', str(pat))


def _collect_file_hits(patterns, files):
    """Return list of {pattern, file} for each matching (pattern, file) pair."""
    hits = []
    seen = set()
    for pat in (patterns or []):
        for f in (files or []):
            if _match(pat, f):
                key = (_pat_repr(pat), f)
                if key not in seen:
                    seen.add(key)
                    hits.append({'pattern': _pat_repr(pat), 'file': f})
    return hits


def _collect_hits(patterns, values):
    """Return list of {pattern, value} for each matching (pattern, value) pair."""
    hits = []
    seen = set()
    for pat in (patterns or []):
        for val in (values or []):
            if _match(pat, val):
                key = (_pat_repr(pat), val)
                if key not in seen:
                    seen.add(key)
                    hits.append({'pattern': _pat_repr(pat), 'value': val})
    return hits


def _build_prefilter_debug_entry(commit, reason, debug_detail):
    """Build a lightweight debug record for a dropped commit."""
    sha = (commit.get('commit') or '')[:40]
    return {
        'sha':         sha,
        'sha12':       sha[:12],
        'subject':     commit.get('subject', '') or '',
        'author':      commit.get('author_name', '') or '',
        'files':       list(commit.get('files', []) or []),
        'drop_reason': reason,
        'debug':       debug_detail,
    }


# -- Main filter decision ------------------------------------------------------

def filter_decision(commit, compiled_sets, filter_cfg, kconfig_enabled):
    """Return (action, reason, debug_detail): action='keep'|'drop'.

    v14.1.0 (B): `lists` parameter removed.  The filter no longer accepts or
    evaluates keyword whitelist/blacklist or path whitelist patterns.  Those
    are scoring concepts handled exclusively by stage 05.

    Only the following signals are evaluated:
      L3  SHA whitelist / blacklist  -- explicit operator per-commit overrides
      L2a path_blacklist ALL files   -- structural path exclusions
      L2half build artifact evidence -- files confirmed built in the product
      L2half kconfig coverage miss   -- files absent from the product build
      L0  default keep

    debug_detail keys:
      sha                           -- commit SHA
      files                         -- list of commit files evaluated
      filter_enabled                -- bool
      kconfig_required              -- bool
      l3_commit_wl_match            -- {pattern, value} or None
      l3_commit_bl_match            -- {pattern, value} or None
      l2a_path_bl_matches           -- [{pattern, file}, ...]
      l2half_artifact_files         -- [file, ...] with artifact evidence
      l2half_kconfig_covered_files  -- [file, ...] with kconfig coverage
      l2half_kconfig_uncovered_files-- [file, ...] without kconfig coverage
    """
    sha   = commit.get('commit', '') or ''
    files = list(commit.get('files', []) or [])

    commit_wl = (filter_cfg or {}).get('commit_whitelist', []) or []
    commit_bl = (filter_cfg or {}).get('commit_blacklist', []) or []
    path_bl   = (filter_cfg or {}).get('path_blacklist',   []) or []

    enabled = (filter_cfg or {}).get('enabled', True)
    require = (filter_cfg or {}).get('require_kconfig_coverage', None)
    if require is None:
        require = compiled_sets.get('available', False) and kconfig_enabled

    # -- Pre-compute L3 hit info -----------------------------------------------
    l3_wl_match = None
    if commit_wl:
        hits = _collect_hits(commit_wl, [sha])
        if hits:
            l3_wl_match = hits[0]

    l3_bl_match = None
    if commit_bl:
        hits = _collect_hits(commit_bl, [sha])
        if hits:
            l3_bl_match = hits[0]

    # -- Pre-compute kconfig coverage (always, so debug is accurate) -----------
    kconfig_covered   = []
    kconfig_uncovered = []
    if kconfig_enabled and require and files:
        for f in files:
            if _file_is_kconfig_covered(f, compiled_sets):
                kconfig_covered.append(f)
            else:
                kconfig_uncovered.append(f)

    # -- Pre-compute artifact evidence (compute once, reuse) -------------------
    artifact_files = []
    if files and compiled_sets.get('available'):
        artifact_files = [f for f in files if _file_has_artifact(f, compiled_sets)]

    # -- Build debug_detail dict -----------------------------------------------
    def _debug():
        return {
            'sha':                            sha,
            'files':                          files,
            'filter_enabled':                 enabled,
            'kconfig_required':               require if (kconfig_enabled and compiled_sets.get('available')) else False,
            'l3_commit_wl_match':             l3_wl_match,
            'l3_commit_bl_match':             l3_bl_match,
            'l2a_path_bl_matches':            [],
            'l2half_artifact_files':          artifact_files,
            'l2half_kconfig_covered_files':   kconfig_covered,
            'l2half_kconfig_uncovered_files': kconfig_uncovered,
        }

    # ========== Filter hierarchy ==============================================

    # L3 SHA whitelist (absolute keep)
    if l3_wl_match:
        return 'keep', 'commit_whitelist', _debug()

    # L3 SHA blacklist (absolute drop)
    if l3_bl_match:
        return 'drop', 'commit_blacklist', _debug()

    # Filter globally disabled
    if not enabled:
        return 'keep', 'filter_disabled', _debug()

    # Zero-file commits (merge commits, tag objects): always keep
    if not files:
        return 'keep', 'no_files_layer', _debug()

    # L2a path blacklist (ALL files must match for drop)
    if path_bl and _all_files_match(path_bl, files):
        d = _debug()
        d['l2a_path_bl_matches'] = _collect_file_hits(path_bl, files)
        return 'drop', 'path_blacklist_all', d

    # L2half build artifact evidence
    if artifact_files:
        return 'keep', 'build_artifact', _debug()

    # L2half kconfig coverage miss
    if kconfig_enabled and require:
        if not kconfig_covered:
            return 'drop', 'no_kconfig_coverage', _debug()

    # L0 default keep
    return 'keep', 'default', _debug()


def run(cfg, cache):
    """Enrich + filter commits. Returns (kept, dropped_commits, reasons)."""
    from lib.config import load_json

    filter_cfg  = cfg.get('filter', {}) or {}
    commits     = load_json(os.path.join(cache, CACHE_FILES['commits']), default=[]) or []
    validate_commit_list(commits)
    product_map = load_json(os.path.join(cache, CACHE_FILES['product_map']), default={}) or {}

    # Enrichment
    print('  enriching commits ...')
    total = len(commits)
    step  = max(1, total // 50)
    for i, c in enumerate(commits):
        c['meta']                = extract_commit_meta(c)
        c['touched_paths_guess'] = infer_touched_paths(c.get('subject', ''), cfg)
        if i % step == 0 or i == total - 1:
            update_stage_progress(4, NSTAGES, 0.4 * (i + 1) / max(total, 1),
                                  'enriching', n_done=i + 1, n_total=total)
    sys.stdout.write('\n')

    compiled_sets  = build_compiled_sets(product_map)
    kconfig_active = compiled_sets.get('available', False)

    commit_wl = filter_cfg.get('commit_whitelist', []) or []
    commit_bl = filter_cfg.get('commit_blacklist', []) or []
    path_bl   = filter_cfg.get('path_blacklist',   []) or []

    print('  compiled_files  : %d' % len(compiled_sets['compiled_files']))
    print('  compiled_dirs   : %d' % len(compiled_sets['compiled_dirs']))
    print('  artifact_stems  : %d' % len(compiled_sets['artifact_stems']))
    print('  log_basenames   : %d' % len(compiled_sets['log_basenames']))
    print('  commit_wl       : %d patterns' % len(commit_wl))
    print('  commit_bl       : %d patterns' % len(commit_bl))
    print('  path_bl         : %d patterns' % len(path_bl))
    print('  kconfig_active  : %s' % kconfig_active)

    kept            = []
    dropped_commits = []
    reasons         = {}
    debug_entries   = []

    for i, c in enumerate(commits):
        action, reason, dbg = filter_decision(c, compiled_sets, filter_cfg, kconfig_active)
        if action == 'drop':
            c['_filter_reason'] = reason
            c['_prefilter_debug'] = dbg
            reasons[reason] = reasons.get(reason, 0) + 1
            dropped_commits.append(c)
            debug_entries.append(_build_prefilter_debug_entry(c, reason, dbg))
        else:
            kept.append(c)
        if i % step == 0 or i == total - 1:
            update_stage_progress(4, NSTAGES, 0.4 + 0.6 * (i + 1) / max(total, 1),
                                  'filtering', n_done=i + 1, n_total=total)
    sys.stdout.write('\n')
    sys.stdout.flush()

    validate_commit_list(kept)
    validate_filtered_commit_list(dropped_commits)
    save_json(os.path.join(cache, CACHE_FILES['prefilter_kept']), kept)
    save_json(os.path.join(cache, CACHE_FILES['filtered']), dropped_commits)

    reason_summary = {}
    for r, cnt in sorted(reasons.items(), key=lambda kv: -kv[1]):
        reason_summary[r] = cnt
    debug_output = {
        'summary': {
            'total_commits':  total,
            'kept':           len(kept),
            'dropped':        len(dropped_commits),
            'drop_reasons':   reason_summary,
            'pattern_counts': {
                'commit_wl': len(commit_wl),
                'commit_bl': len(commit_bl),
                'path_bl':   len(path_bl),
            },
            'kconfig_active': kconfig_active,
            'compiled_files': len(compiled_sets['compiled_files']),
            'compiled_dirs':  len(compiled_sets['compiled_dirs']),
        },
        'dropped': debug_entries,
    }
    save_json(os.path.join(cache, CACHE_FILES['prefilter_debug']), debug_output)
    logging.debug('prefilter_debug.json: %d dropped commit entries written', len(debug_entries))

    return kept, dropped_commits, reasons


def write_outputs(cfg, dropped_commits, outdir):
    """Write filtered output files (JSON, CSV, HTML, XLSX, ODS)."""
    from lib.spreadsheet import COMMIT_COLS, write_xlsx, write_ods
    reports = cfg.get('reports', {}) or {}
    os.makedirs(outdir, exist_ok=True)

    jp = os.path.join(outdir, 'filtered_commits.json')
    with open(jp, 'w', encoding='utf-8') as f:
        json.dump(dropped_commits, f, indent=2, default=str)
    print('  filtered JSON: %s' % jp)

    if reports.get('outputs') and 'csv' in (reports.get('outputs') or []):
        cp = os.path.join(outdir, 'filtered_commits.csv')
        with open(cp, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(list(COMMIT_COLS) + ['Filter reason'])
            for c in dropped_commits:
                w.writerow([
                    c.get('_rank', ''),
                    (c.get('commit') or '')[:12],
                    c.get('subject', ''),
                    c.get('author_name', ''),
                    c.get('author_time', ''),
                    c.get('score', 0) or 0,
                    fmt_profiles(c),
                    fmt_evidence(c),
                    c.get('_filter_reason', ''),
                ])
        print('  filtered CSV:  %s' % cp)

    if reports.get('outputs') and 'html' in (reports.get('outputs') or []):
        try:
            from lib.html_report import generate_html_report
            hp = os.path.join(outdir, 'filtered_commits.html')
            title = reports.get('title', 'kcommit Analysis Report') + ' -- Filtered'
            generate_html_report(dropped_commits, {}, {}, hp, title=title, is_filtered=True,
                          templates_dir=cfg['paths'].get('templates_dir'))
            print('  filtered HTML: %s' % hp)
        except Exception as e:
            logging.warning('filtered HTML failed: %s', e)

    if reports.get('outputs') and 'xlsx' in (reports.get('outputs') or []):
        try:
            xp = os.path.join(outdir, 'filtered_commits.xlsx')
            write_xlsx(xp, dropped_commits, {})
            print('  filtered XLSX: %s' % xp)
        except Exception as e:
            logging.warning('filtered XLSX failed: %s', e)

    if reports.get('outputs') and 'ods' in (reports.get('outputs') or []):
        try:
            op = os.path.join(outdir, 'filtered_commits.ods')
            write_ods(op, dropped_commits, {})
            print('  filtered ODS:  %s' % op)
        except Exception as e:
            logging.warning('filtered ODS failed: %s', e)
