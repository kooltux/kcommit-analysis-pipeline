"""Stage 04 logic: enrich and pre-filter commits before scoring.

Filter hierarchy (higher level wins):
  L3 SHA whitelist  -> FORCE-KEEP
  L3 SHA blacklist  -> FORCE-DROP
  L2a path_blacklist ALL files -> DROP
        Note: a commit whose files are a *mix* of blacklisted and non-blacklisted
        paths is NOT dropped at L2a; it falls through to L2b and below.  The
        rationale is that a path blacklist entry means "this subsystem is not
        relevant", not "any commit that merely touches this subsystem is junk".
        Only commits where every file lives under a blacklisted prefix are dropped.
  L2b path_whitelist ANY file  -> KEEP
  L2half build artifact evidence -> KEEP
  L2half kconfig coverage miss   -> DROP  (unless kw_whitelist saves — see note)
        kconfig/path coverage is computed unconditionally before the drop
        decision so that the debug output is accurate even for commits saved
        by the keyword whitelist.

        kw_wl rescue at L2half:
          The keyword whitelist may rescue a commit from a kconfig-coverage miss
          ONLY when compiled_files is empty (i.e. no file-level coverage data
          exists at all).  When compiled_files is non-empty and a commit's files
          are conclusively uncovered, the keyword whitelist must NOT override the
          kconfig miss — the file evidence is authoritative.  This prevents
          generic security keywords in a commit message (e.g. "lockup", "BUG")
          from keeping commits that touch subsystems not built in the product.

          When the rescue is suppressed, the debug field
          'kw_wl_rescue_suppressed' is set to True and 'l1a_kw_wl_matches'
          is populated so the operator can see what would have matched.

  L1a keywords_whitelist         -> KEEP
  L1b keywords_blacklist         -> DROP
  L0  default                    -> KEEP

Zero-file commits (merge commits, tag objects):
  A commit with no files bypasses all path/artifact/kconfig layers and
  falls through to L1a/L1b/L0.  They receive reason='no_files_layer' in
  the debug output so they can be identified separately from true default
  keeps.

v12.0.0 (A.1) -- filter_decision() now returns a 3-tuple
  (action, reason, debug_detail) where debug_detail is a dict keyed by:
    sha, files, filter_enabled, kconfig_required,
    l3_commit_wl_match, l3_commit_bl_match,
    l2a_path_bl_matches, l2b_path_wl_matches,
    l2half_artifact_files,
    l2half_kconfig_covered_files, l2half_kconfig_uncovered_files,
    l1a_kw_wl_matches, l1b_kw_bl_matches,
    kw_wl_rescue_suppressed
  All dropped commits carry this field in the cache and in the
  prefilter_debug.json output file.

v13.0.0 changes (E.1.1-E.1.6, E.6):
  E.1.1 -- _file_has_artifact() called only once per commit in filter_decision();
           result reused for both the guard condition and debug capture.
  E.1.2 -- kconfig_covered / kconfig_uncovered computed unconditionally before
           the drop/save decision so debug output is accurate for kw-saved commits.
  E.1.4 -- L2a semantics documented: only drops when ALL files are blacklisted.
  E.1.5 -- zero-file commits get explicit early handling; they no longer silently
           fall through to kconfig coverage check with an empty file list.
           Reason is 'no_files_layer' for plain default keep, or the matching
           keyword reason when L1a/L1b fires.
  E.1.6 -- build_compiled_sets(): removed ambiguous else-branch that added raw
           'CONFIG_FOO=m' strings (with '=') to enabled_set when the entry had no
           '=' separator. All entries must be 'CONFIG_X=y' or 'CONFIG_X=m' form;
           bare symbols without a value suffix are now ignored with a debug log.
  E.6   -- removed dead 'tmpl = reports' assignment and stale comment in
           write_outputs().
  G     -- filter_decision(): zero-file default keep now emits reason='no_files_layer'
           (was incorrectly 'default'), matching the module docstring and E.1.5
           specification above.

v13.0.1 changes (Bug-1 fix):
  H     -- build_compiled_sets(): reads product_map['config_enabled_map'] and
           product_map['config_enabled_dirs'] instead of 'config_to_paths'.
           The enabled-symbol join (previously performed here) is now done
           upstream in st03 _filter_to_enabled(), so build_compiled_sets()
           no longer needs to re-filter.  compiled_files is built directly
           from config_enabled_map values; compiled_dirs is taken directly
           from config_enabled_dirs.  This removes the only place where
           disabled CONFIG symbols could still slip through (e.g. CONFIG_BTRFS_FS
           appearing in config_to_paths despite being disabled in .config).

v13.0.2 changes (Bug-2 fix):
  I     -- build_compiled_sets(): removed the `if not compiled_files: return empty`
           short-circuit that incorrectly set available=False whenever
           config_enabled_map was present but empty (e.g. .config not provided).

           Root cause: when the user does not provide a .config, st02 calls
           load_kernel_config_symbols(None) which returns [], st03 stores
           kernel_config=[] in build_context.json, and _filter_to_enabled({c2p},[])
           returns {}.  build_compiled_sets() then found cem={} (present, not None),
           skipped the pre-v13.0.1 warning, but hit `if not compiled_files: return
           empty` which silently set available=False — disabling the kconfig filter
           even when build artifacts or build-log objects were present and sufficient
           to make reliable coverage decisions.

           Fix: available is now set to True when ANY evidence source is non-empty
           (config_enabled_map, built_artifacts_from_dir, or built_objects_from_log).
           Only when all three are empty is available=False, meaning the pipeline
           genuinely has no coverage data and must keep everything for scoring.

           Design contract:
             available=True  → at least one evidence source present; commits with
                               zero coverage across all sources are confidently dropped.
             available=False → no evidence at all; kconfig filter inactive; scoring
                               resolves ambiguities (correct behaviour when the user
                               provides kernel sources only, with no .config/logs/dir).

v14.0.0 changes (A — kw_wl rescue suppression):
  A     -- filter_decision(): the keyword whitelist rescue inside the L2half
           kconfig-coverage miss path is now suppressed when compiled_files is
           non-empty.  When file-level coverage data exists and a commit's files
           are conclusively uncovered, the kw_wl must not override the kconfig
           miss — the file evidence is authoritative.

           Previously, a commit touching e.g. fs/btrfs/ioctl.c (CONFIG_BTRFS_FS
           disabled in .config) could be rescued by a keyword like 'lockup' or
           'BUG' in the commit body, keeping it in the output despite being
           demonstrably not built in the product.

           New behaviour:
             - compiled_files non-empty + files uncovered → DROP (no_kconfig_coverage)
               even if kw_wl would have matched.
             - compiled_files empty (no .config, no kconfig evidence) → kw_wl rescue
               still applies, unchanged.

           Debug field 'kw_wl_rescue_suppressed' (bool) added to debug_detail:
             True  → rescue was suppressed; l1a_kw_wl_matches shows what matched.
             False → rescue was not applicable or not triggered.

prefilter_debug.json schema (A.1 / v13.0.0 / v14.0.0):
  {
    "summary": {
      "total_commits":   <int>,
      "kept":            <int>,
      "dropped":         <int>,
      "drop_reasons":    { reason: count, ... },   # renamed from reason_counts in v13
      "pattern_counts":  { commit_wl: N, ... },
      "kconfig_active":  <bool>,
      "compiled_files":  <int>,
      "compiled_dirs":   <int>
    },
    "dropped": [                                  # renamed from dropped_commits in v13
      {
        "sha":         <str>,
        "sha12":       <str>,
        "subject":     <str>,
        "author":      <str>,
        "files":       [<str>, ...],
        "drop_reason": <str>,
        "debug":       {
          ...,
          "kw_wl_rescue_suppressed": <bool>   # new in v14.0.0
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
    anymatches as _any_matches,
    anyfilematches as _any_file_matches,
    allfilesmatch as _all_files_match,
)
from lib.pipeline_runtime import update_stage_progress, finish_progress_line
from lib.profile_rules import load_profile_rules, _merged_patterns
from lib.scoring import extract_commit_meta, precompile_rules, fmt_profiles, fmt_evidence
from lib.kbuild import infer_touched_paths
from lib.manifest import CACHE_FILES, NSTAGES
from lib.schema import validate_commit_list, validate_filtered_commit_list

_BUILD_SYS_NAMES = frozenset({'Makefile', 'Kbuild', 'Kconfig'})

_DEBUG_TEXT_SNIPPET_LEN = 300


def _is_build_system_file(path):
    base = os.path.basename(path)
    if base in _BUILD_SYS_NAMES:
        return True
    if base.startswith('Makefile.') or base.startswith('Kconfig.'):
        return True
    _, ext = os.path.splitext(base)
    return ext in ('.mk',)


def build_merged_lists(profile_rules):
    out = {k: [] for k in ('commit_wl', 'commit_bl', 'path_wl', 'path_bl', 'kw_wl', 'kw_bl')}
    MAP = {
        'commit_whitelist':   'commit_wl',
        'commit_blacklist':   'commit_bl',
        'path_whitelist':     'path_wl',
        'path_blacklist':     'path_bl',
        'keywords_whitelist': 'kw_wl',
        'keywords_blacklist': 'kw_bl',
    }
    for pname, pdata in (profile_rules or {}).items():
        if not isinstance(pdata, dict):
            continue  # skip sentinels injected by precompile_rules
        merged = _merged_patterns(pdata)
        for src, dst in MAP.items():
            out[dst].extend(merged.get(src, []))
    for k in out:
        seen, dedup = set(), []
        for p in out[k]:
            pk = p.pattern if isinstance(p, re.Pattern) else p
            if pk not in seen:
                seen.add(pk)
                dedup.append(p)
        out[k] = dedup
    return out


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
      available=True  → at least one evidence source is non-empty; commits with
                        zero coverage across all sources are confidently dropped.
      available=False → all evidence sources empty; kconfig filter inactive;
                        scoring resolves ambiguities (correct when the user
                        provides kernel sources only, with no .config/logs/dir).

    The previous `if not compiled_files: return empty` guard was the bug:
    it returned available=False whenever .config was absent (cem={}), silently
    disabling the coverage filter even when artifacts or log objects were present.
    """
    empty = dict(compiled_files=set(), compiled_dirs=set(),
                 artifact_stems=set(), log_basenames=set(), available=False)
    if not product_map:
        return empty

    # config_enabled_map must be present (not just truthy).
    # None means pre-v13.0.1 cache; warn and fall back to safe empty result.
    cem = product_map.get('config_enabled_map')
    if cem is None:
        logging.warning(
            'build_compiled_sets: config_enabled_map not found in product_map '
            '(cache pre-dates v13.0.1). Re-run stage 03 to fix. '
            'Falling back to empty compiled set to avoid false-positive keeps.')
        return empty

    # Build compiled_files and compiled_dirs from config_enabled_map.
    # cem may be {} when .config was not provided — that is valid; it simply
    # means no kconfig-based file coverage (artifact/log may still provide it).
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

    # v13.0.2 (Bug-2): available=True when ANY evidence source is non-empty.
    # If all three are empty the pipeline has no coverage data and must keep
    # everything — the scoring stage resolves ambiguities.
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
       (e.g. ``'hub'`` from ``hub.o``).  These are intentionally basename-only
       because the build log rarely includes the full source path.  However,
       matching on basename alone would be far too broad: the stem ``'hub'``
       would match ``drivers/usb/hub.c``, ``sound/usb/hub.c``,
       ``net/hub.c``, etc. indiscriminately.

       To prevent this false-positive explosion, a log-basename hit is only
       accepted when the file's **parent directory** is also in
       ``compiled_dirs`` (i.e. the directory is known to produce compiled
       objects for an enabled kconfig symbol) **or** the file itself is in
       ``compiled_files``.  This scopes the match to "same compiled directory"
       rather than "anywhere in the tree".
    """
    stem, _ = os.path.splitext(f)
    if stem in cs['artifact_stems']:
        return True

    bn_stem, _ = os.path.splitext(os.path.basename(f))
    if bn_stem not in cs['log_basenames']:
        return False
    return (
        os.path.dirname(f) in cs['compiled_dirs']
        or f in cs['compiled_files']
    )


def _file_is_kconfig_covered(f, cs):
    if f in cs['compiled_files']:
        return True
    fdir = os.path.dirname(f)
    if fdir and fdir in cs['compiled_dirs']:
        return True
    return _is_build_system_file(f)


# -- Pattern repr helper -------------------------------------------------------

def _pat_repr(pat):
    """Return a human-readable string for a pattern (compiled or raw)."""
    return getattr(pat, 'pattern', str(pat))


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


def _build_prefilter_debug_entry(commit, reason, debug_detail):
    """Build a lightweight debug record for a dropped commit.

    Used in run() to populate prefilter_debug.json.
    sha is truncated to 40 chars max (git SHAs are 40 hex chars).
    sha12 is the first 12 characters for display convenience.
    """
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

def filter_decision(commit, lists, compiled_sets, filter_cfg, kconfig_enabled):
    """Return (action, reason, debug_detail): action='keep'|'drop'.

    debug_detail keys (v12.0.0 A.1 / v14.0.0 A):
      sha                           -- commit SHA
      files                         -- list of commit files evaluated
      filter_enabled                -- bool, False when filter is globally disabled
      kconfig_required              -- bool, whether kconfig coverage was required
      l3_commit_wl_match            -- {pattern, value} or None
      l3_commit_bl_match            -- {pattern, value} or None
      l2a_path_bl_matches           -- [{pattern, file}, ...]
      l2b_path_wl_matches           -- [{pattern, file}, ...]
      l2half_artifact_files         -- [file, ...] with artifact evidence
      l2half_kconfig_covered_files  -- [file, ...] with kconfig coverage
      l2half_kconfig_uncovered_files-- [file, ...] without kconfig coverage
      l1a_kw_wl_matches             -- [{pattern, value}, ...]
      l1b_kw_bl_matches             -- [{pattern, value}, ...]
      kw_wl_rescue_suppressed       -- bool (v14.0.0 A): True when kw_wl rescue
                                       was suppressed because compiled_files is
                                       non-empty (file evidence is authoritative).
                                       l1a_kw_wl_matches is populated to show
                                       what would have matched.

    v13.0.0 (E.1.1): artifact_files computed once and reused.
    v13.0.0 (E.1.2): kconfig_covered/uncovered always computed before drop/save
                     decision so debug is accurate for kw-whitelist-saved commits.
    v13.0.0 (E.1.5): zero-file commits handled explicitly before path/kconfig
                     layers.  Reason is 'no_files_layer' for plain default keep
                     (G: was incorrectly 'default' before this fix), or the
                     matching keyword reason when L1a/L1b fires.
    v14.0.0 (A):     kw_wl rescue at L2half suppressed when compiled_files
                     is non-empty — file evidence is authoritative over keyword
                     matches when coverage data exists.
    """
    sha   = commit.get('commit', '') or ''
    files = list(commit.get('files', []) or [])
    subj  = commit.get('subject', '') or ''
    body  = commit.get('body', '') or ''
    text  = subj + '\n' + body

    commit_wl = lists['commit_wl']
    commit_bl = lists['commit_bl']
    path_wl   = lists['path_wl']
    path_bl   = lists['path_bl']
    kw_wl     = lists['kw_wl']
    kw_bl     = lists['kw_bl']

    enabled  = (filter_cfg or {}).get('enabled', True)
    require  = (filter_cfg or {}).get('require_kconfig_coverage', None)
    if require is None:
        require = compiled_sets.get('available', False) and kconfig_enabled

    # -- Pre-compute L3 hit info (used in debug regardless of outcome) ---------
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

    # -- Pre-compute kconfig coverage (E.1.2: always, before decision) ---------
    kconfig_covered   = []
    kconfig_uncovered = []
    if kconfig_enabled and require and files:
        for f in files:
            if _file_is_kconfig_covered(f, compiled_sets):
                kconfig_covered.append(f)
            else:
                kconfig_uncovered.append(f)

    # -- Pre-compute artifact evidence (E.1.1: compute once, reuse) -----------
    artifact_files = []
    if files and compiled_sets.get('available'):
        artifact_files = [f for f in files if _file_has_artifact(f, compiled_sets)]

    # -- Build debug_detail dict -----------------------------------------------
    def _debug(kw_wl_rescue_suppressed=False):
        return {
            'sha':                           sha,
            'files':                         files,
            'filter_enabled':                enabled,
            'kconfig_required':              require if (kconfig_enabled and compiled_sets.get('available')) else False,
            'l3_commit_wl_match':            l3_wl_match,
            'l3_commit_bl_match':            l3_bl_match,
            'l2a_path_bl_matches':           [],  # filled in per-decision below
            'l2b_path_wl_matches':           [],
            'l2half_artifact_files':         artifact_files,
            'l2half_kconfig_covered_files':  kconfig_covered,
            'l2half_kconfig_uncovered_files': kconfig_uncovered,
            'l1a_kw_wl_matches':             [],
            'l1b_kw_bl_matches':             [],
            'kw_wl_rescue_suppressed':       kw_wl_rescue_suppressed,
        }

    # ========== Filter hierarchy ==============================================

    # L3 SHA whitelist (absolute keep)
    if l3_wl_match:
        d = _debug()
        return 'keep', 'commit_whitelist', d

    # L3 SHA blacklist (absolute drop)
    if l3_bl_match:
        d = _debug()
        return 'drop', 'commit_blacklist', d

    # Filter globally disabled
    if not enabled:
        d = _debug()
        return 'keep', 'filter_disabled', d

    # E.1.5 / G: zero-file commits skip path/artifact/kconfig layers entirely.
    if not files:
        d = _debug()
        kw_wl_hits = _collect_hits(kw_wl, [subj, body]) if kw_wl else []
        kw_bl_hits = _collect_hits(kw_bl, [subj, body]) if kw_bl else []
        d['l1a_kw_wl_matches'] = kw_wl_hits
        d['l1b_kw_bl_matches'] = kw_bl_hits
        if kw_wl and kw_wl_hits:
            return 'keep', 'keywords_whitelist', d
        if kw_bl and kw_bl_hits:
            return 'drop', 'keywords_blacklist', d
        return 'keep', 'no_files_layer', d

    # L2a path blacklist (ALL files must match for drop)
    if path_bl and _all_files_match(path_bl, files):
        d = _debug()
        d['l2a_path_bl_matches'] = _collect_file_hits(path_bl, files)
        return 'drop', 'path_blacklist_all', d

    # L2b path whitelist (ANY file)
    if path_wl and _any_file_matches(path_wl, files):
        d = _debug()
        d['l2b_path_wl_matches'] = _collect_file_hits(path_wl, files)
        return 'keep', 'path_whitelist', d

    # L2half build artifact evidence (E.1.1: reuse pre-computed artifact_files)
    if artifact_files:
        d = _debug()
        return 'keep', 'build_artifact', d

    # L2half kconfig coverage miss
    if kconfig_enabled and require:
        if not kconfig_covered:
            # v14.0.0 (A): kw_wl rescue is suppressed when compiled_files is
            # non-empty.  File-level coverage data is authoritative: if the
            # pipeline knows which files are built and a commit's files are
            # conclusively absent, no keyword match should override that.
            # When compiled_files is empty (no .config, no kconfig evidence)
            # the rescue still applies — keyword matching is the best available
            # heuristic in that situation.
            if kw_wl and not compiled_sets.get('compiled_files'):
                kw_wl_hits = _collect_hits(kw_wl, [subj, body])
                if kw_wl_hits:
                    d = _debug()
                    d['l1a_kw_wl_matches'] = kw_wl_hits
                    return 'keep', 'keywords_whitelist', d
            elif kw_wl:
                # compiled_files non-empty: check if kw_wl would have matched
                # and record it in debug for traceability, but do NOT rescue.
                kw_wl_hits = _collect_hits(kw_wl, [subj, body])
                if kw_wl_hits:
                    d = _debug(kw_wl_rescue_suppressed=True)
                    d['l1a_kw_wl_matches'] = kw_wl_hits
                    return 'drop', 'no_kconfig_coverage', d
            d = _debug()
            return 'drop', 'no_kconfig_coverage', d

    # L1a keywords whitelist
    if kw_wl and _any_matches(kw_wl, text):
        hits = _collect_hits(kw_wl, [subj, body])
        d = _debug()
        d['l1a_kw_wl_matches'] = hits
        return 'keep', 'keywords_whitelist', d

    # L1b keywords blacklist
    if kw_bl and _any_matches(kw_bl, text):
        hits = _collect_hits(kw_bl, [subj, body])
        d = _debug()
        d['l1b_kw_bl_matches'] = hits
        return 'drop', 'keywords_blacklist', d

    # L0 default keep
    d = _debug()
    return 'keep', 'default', d


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

    profile_rules = load_profile_rules(cfg)
    precompile_rules(profile_rules)
    lists         = build_merged_lists(profile_rules)
    compiled_sets = build_compiled_sets(product_map)
    kconfig_active = compiled_sets.get('available', False)

    print('  compiled_files  : %d' % len(compiled_sets['compiled_files']))
    print('  compiled_dirs   : %d' % len(compiled_sets['compiled_dirs']))
    print('  artifact_stems  : %d' % len(compiled_sets['artifact_stems']))
    print('  log_basenames   : %d' % len(compiled_sets['log_basenames']))
    print('  commit_wl       : %d patterns' % len(lists['commit_wl']))
    print('  commit_bl       : %d patterns' % len(lists['commit_bl']))
    print('  path_wl         : %d patterns' % len(lists['path_wl']))
    print('  path_bl         : %d patterns' % len(lists['path_bl']))
    print('  keywords_wl     : %d patterns' % len(lists['kw_wl']))
    print('  keywords_bl     : %d patterns' % len(lists['kw_bl']))
    print('  kconfig_active  : %s' % kconfig_active)

    kept            = []
    dropped_commits = []
    reasons         = {}
    debug_entries   = []

    for i, c in enumerate(commits):
        action, reason, dbg = filter_decision(c, lists, compiled_sets, filter_cfg, kconfig_active)
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
            'total_commits':   total,
            'kept':            len(kept),
            'dropped':         len(dropped_commits),
            'drop_reasons':    reason_summary,
            'pattern_counts': {
                'commit_wl':  len(lists['commit_wl']),
                'commit_bl':  len(lists['commit_bl']),
                'path_wl':    len(lists['path_wl']),
                'path_bl':    len(lists['path_bl']),
                'kw_wl':      len(lists['kw_wl']),
                'kw_bl':      len(lists['kw_bl']),
            },
            'kconfig_active':  kconfig_active,
            'compiled_files':  len(compiled_sets['compiled_files']),
            'compiled_dirs':   len(compiled_sets['compiled_dirs']),
        },
        'dropped': debug_entries,
    }
    save_json(os.path.join(cache, CACHE_FILES['prefilter_debug']), debug_output)
    logging.debug('prefilter_debug.json: %d dropped commit entries written', len(debug_entries))

    return kept, dropped_commits, reasons


def write_outputs(cfg, dropped_commits, outdir):
    """Write filtered output files (JSON, CSV, HTML, XLSX, ODS).

    E.6 (v13.0.0): removed dead 'tmpl = reports' assignment and its stale
    comment ('templates.* removed in v9.12') -- that alias was never used.
    """
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
