"""Stage 04 logic: enrich and pre-filter commits before scoring.

Filter hierarchy (higher level wins):
  L3 SHA whitelist  → FORCE-KEEP
  L3 SHA blacklist  → FORCE-DROP
  L2a path_blacklist ALL files → DROP
  L2b path_whitelist ANY file  → KEEP
  L2½ build artifact evidence  → KEEP
  L2½ kconfig coverage miss    → DROP (unless kw_whitelist saves)
  L1a keywords_whitelist       → KEEP
  L1b keywords_blacklist       → DROP
  L0  default                  → KEEP

Changes:
  v12.0.0 (A.1) — filter_decision() now returns a third value: a
                  `_prefilter_debug` dict with:
                    reason        -- same short reason string as before
                    matched_rule  -- the pattern/list that triggered the decision
                    files_checked -- commit files evaluated
                    text_snippet  -- first 300 chars of subject+body used for kw match
                    kw_hits       -- list of {pattern, value} for kw matches
                    path_hits     -- list of {pattern, file} for path matches
                    sha_hit       -- sha that matched a whitelist/blacklist entry
                  All dropped commits carry this field in the cache and in the
                  prefilter_debug.json output file.
                  run() now writes CACHE_FILES['prefilter_debug'] with one
                  entry per dropped commit, plus a summary section, for
                  human inspection.
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
                seen.add(pk); dedup.append(p)
        out[k] = dedup
    return out


def build_compiled_sets(product_map):
    empty = dict(compiled_files=set(), compiled_dirs=set(),
                 artifact_stems=set(), log_basenames=set(), available=False)
    if not product_map:
        return empty
    c2p         = product_map.get('config_to_paths', {}) or {}
    enabled_raw = product_map.get('enabled_configs',  []) or []
    enabled_set = set()
    for s in enabled_raw:
        if '=' in s:
            sym, _, val = s.partition('=')
            if val.strip() in ('y', 'm'):
                enabled_set.add(sym)
        else:
            enabled_set.add(s)
    compiled_files = set()
    for sym, paths in c2p.items():
        if sym in enabled_set:
            compiled_files.update(paths)
    if not compiled_files:
        return empty
    compiled_dirs  = {os.path.dirname(f) for f in compiled_files}
    compiled_dirs.discard('')
    artifact_stems = set()
    for p in (product_map.get('built_artifacts_from_dir', []) or []):
        stem, _ = os.path.splitext(p)
        artifact_stems.add(stem)
    log_basenames = set()
    for p in (product_map.get('built_objects_from_log', []) or []):
        bn = os.path.basename(p)
        stem, _ = os.path.splitext(bn)
        log_basenames.add(stem)
    return dict(compiled_files=compiled_files, compiled_dirs=compiled_dirs,
                artifact_stems=artifact_stems, log_basenames=log_basenames, available=True)


def _file_has_artifact(f, cs):
    """Return True if *f* has build-artifact evidence.

    Two evidence sources are checked in order:

    1. ``artifact_stems`` — full path stems derived from ``built_artifacts_from_dir``
       (e.g. ``'drivers/usb/core/hub'``).  A full-path stem match is precise and
       needs no further qualification.

    2. ``log_basenames`` — bare filename stems derived from build-log tokens
       (e.g. ``'hub'`` from ``hub.o``).  These are intentionally basename-only
       because the build log rarely includes the full source path.  However,
       matching on basename alone would be far too broad: the stem ``'hub'``
       would match ``drivers/usb/hub.c``, ``sound/usb/hub.c``,
       ``net/hub.c``, etc. indiscriminately.

       To prevent this false-positive explosion, a log-basename hit is only
       accepted when the file's **parent directory** is also in
       ``compiled_dirs`` (i.e. the directory is known to produce compiled
       objects for an enabled kconfig symbol) **or** the file itself is in
       ``compiled_files``.  This scopes the match to \"same compiled directory\"
       rather than \"anywhere in the tree\".
    """
    # Source 1: full-path artifact stem (precise, no extra qualification needed)
    stem, _ = os.path.splitext(f)
    if stem in cs['artifact_stems']:
        return True

    # Source 2: log basename stem — only valid when directory is compiled
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


# ── Pattern repr helper ────────────────────────────────────────────────────────

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


# ── Main filter decision ───────────────────────────────────────────────────────

def filter_decision(commit, lists, compiled_sets, filter_cfg, kconfig_enabled):
    """Return (action, reason, debug): action='keep'|'drop'.

    A.1: the third return value `debug` is a dict with full diagnostics:
      reason         -- short reason token (same as before)
      matched_rule   -- which list/check triggered the decision
      files_checked  -- list of files evaluated
      text_snippet   -- first 300 chars of subject+body used for kw matching
      kw_hits        -- [{pattern, value}] for keyword matches (whitelist or blacklist)
      path_hits      -- [{pattern, file}] for path matches (whitelist or blacklist)
      sha_hit        -- str sha that matched a wl/bl entry, or ''
      kconfig_covered_files   -- files that passed kconfig coverage check
      kconfig_uncovered_files -- files that failed kconfig coverage check
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

    snippet = text[:_DEBUG_TEXT_SNIPPET_LEN]

    def _debug(reason, matched_rule='', kw_hits=None, path_hits=None, sha_hit='',
               kconfig_covered=None, kconfig_uncovered=None):
        return {
            'reason':                   reason,
            'matched_rule':             matched_rule,
            'files_checked':            files,
            'text_snippet':             snippet,
            'kw_hits':                  kw_hits or [],
            'path_hits':                path_hits or [],
            'sha_hit':                  sha_hit,
            'kconfig_covered_files':    kconfig_covered or [],
            'kconfig_uncovered_files':  kconfig_uncovered or [],
        }

    # L3 absolute
    if commit_wl and _any_matches(commit_wl, sha):
        hits = _collect_hits(commit_wl, [sha])
        return 'keep', 'commit_whitelist', _debug('commit_whitelist', 'commit_wl',
                                                    sha_hit=hits[0]['value'] if hits else sha)
    if commit_bl and _any_matches(commit_bl, sha):
        hits = _collect_hits(commit_bl, [sha])
        return 'drop', 'commit_blacklist', _debug('commit_blacklist', 'commit_bl',
                                                   sha_hit=hits[0]['value'] if hits else sha)

    enabled = (filter_cfg or {}).get('enabled', True)
    if not enabled:
        return 'keep', 'filter_disabled', _debug('filter_disabled')

    # L2a path blacklist (ALL files)
    if path_bl and files and _all_files_match(path_bl, files):
        hits = _collect_file_hits(path_bl, files)
        return 'drop', 'path_blacklist_all', _debug('path_blacklist_all', 'path_bl',
                                                     path_hits=hits)

    # L2b path whitelist (ANY file)
    if path_wl and files and _any_file_matches(path_wl, files):
        hits = _collect_file_hits(path_wl, files)
        return 'keep', 'path_whitelist', _debug('path_whitelist', 'path_wl',
                                                  path_hits=hits)

    # L2½ build artifact
    if files and any(_file_has_artifact(f, compiled_sets) for f in files):
        artifact_files = [f for f in files if _file_has_artifact(f, compiled_sets)]
        return 'keep', 'build_artifact', _debug('build_artifact',
                                                  path_hits=[{'pattern': 'artifact_match', 'file': f}
                                                              for f in artifact_files])

    # L2½ kconfig coverage
    kconfig_covered   = []
    kconfig_uncovered = []
    if kconfig_enabled:
        require = (filter_cfg or {}).get('require_kconfig_coverage', None)
        if require is None:
            require = compiled_sets.get('available', False)
        if require:
            for f in files:
                if _file_is_kconfig_covered(f, compiled_sets):
                    kconfig_covered.append(f)
                else:
                    kconfig_uncovered.append(f)
            any_covered = bool(kconfig_covered)
            if not any_covered:
                if kw_wl and _any_matches(kw_wl, text):
                    hits = _collect_hits(kw_wl, [subj, body])
                    # keyword whitelist saves it — fall through to L1a
                else:
                    return 'drop', 'no_kconfig_coverage', _debug(
                        'no_kconfig_coverage', 'kconfig_check',
                        kconfig_covered=kconfig_covered,
                        kconfig_uncovered=kconfig_uncovered,
                    )

    # L1a keywords whitelist
    if kw_wl and _any_matches(kw_wl, text):
        hits = _collect_hits(kw_wl, [subj, body])
        return 'keep', 'keywords_whitelist', _debug('keywords_whitelist', 'kw_wl',
                                                     kw_hits=hits,
                                                     kconfig_covered=kconfig_covered,
                                                     kconfig_uncovered=kconfig_uncovered)

    # L1b keywords blacklist
    if kw_bl and _any_matches(kw_bl, text):
        hits = _collect_hits(kw_bl, [subj, body])
        return 'drop', 'keywords_blacklist', _debug('keywords_blacklist', 'kw_bl',
                                                     kw_hits=hits,
                                                     kconfig_covered=kconfig_covered,
                                                     kconfig_uncovered=kconfig_uncovered)

    return 'keep', 'default', _debug('default',
                                      kconfig_covered=kconfig_covered,
                                      kconfig_uncovered=kconfig_uncovered)


def run(cfg, cache):
    """Enrich + filter commits. Returns (kept, dropped_commits, reasons)."""
    from lib.config import load_json

    filter_cfg  = cfg.get('filter', {}) or {}
    commits     = load_json(os.path.join(cache, CACHE_FILES['commits']), default=[]) or []
    validate_commit_list(commits)
    product_map = load_json(os.path.join(cache, CACHE_FILES['product_map']), default={}) or {}

    # Enrichment
    print('  enriching commits …')
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
    print(f'  kconfig_active  : {kconfig_active}')

    kept            = []
    dropped_commits = []
    reasons         = {}
    debug_entries   = []   # A.1: per-dropped-commit debug records

    for i, c in enumerate(commits):
        action, reason, dbg = filter_decision(c, lists, compiled_sets, filter_cfg, kconfig_active)
        if action == 'drop':
            c['_filter_reason'] = reason
            c['_prefilter_debug'] = dbg          # A.1: attach debug to commit
            reasons[reason] = reasons.get(reason, 0) + 1
            dropped_commits.append(c)
            # A.1: collect lightweight debug record for the debug output file
            debug_entries.append({
                'sha':          (c.get('commit') or '')[:12],
                'full_sha':     c.get('commit') or '',
                'subject':      c.get('subject', '') or '',
                'author':       c.get('author_name', '') or '',
                'filter_reason': reason,
                'debug':        dbg,
            })
        else:
            kept.append(c)
        if i % step == 0 or i == total - 1:
            update_stage_progress(4, NSTAGES, 0.4 + 0.6 * (i + 1) / max(total, 1),
                                  'filtering', n_done=i + 1, n_total=total)
    sys.stdout.write('\n'); sys.stdout.flush()

    validate_commit_list(kept)
    validate_filtered_commit_list(dropped_commits)
    save_json(os.path.join(cache, CACHE_FILES['prefilter_kept']), kept)
    save_json(os.path.join(cache, CACHE_FILES['filtered']), dropped_commits)

    # A.1: write prefilter_debug.json — human-readable diagnostics for dropped commits
    reason_summary = {}
    for r, cnt in sorted(reasons.items(), key=lambda kv: -kv[1]):
        reason_summary[r] = cnt
    debug_output = {
        'summary': {
            'total_commits':   total,
            'kept':            len(kept),
            'dropped':         len(dropped_commits),
            'reason_counts':   reason_summary,
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
        'dropped_commits': debug_entries,
    }
    save_json(os.path.join(cache, CACHE_FILES['prefilter_debug']), debug_output)
    logging.debug('prefilter_debug.json: %d dropped commit entries written', len(debug_entries))

    return kept, dropped_commits, reasons


def write_outputs(cfg, dropped_commits, outdir):
    """Write filtered output files (JSON, CSV, HTML, XLSX, ODS)."""
    from lib.spreadsheet import COMMIT_COLS, write_xlsx, write_ods
    reports = cfg.get('reports', {}) or {}
    tmpl    = reports  # reports.* is canonical; templates.* removed in v9.12
    os.makedirs(outdir, exist_ok=True)

    # Always write dropped JSON
    jp = os.path.join(outdir, 'filtered_commits.json')
    with open(jp, 'w', encoding='utf-8') as f:
        json.dump(dropped_commits, f, indent=2, default=str)
    print(f'  filtered JSON: {jp}')

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
        print(f'  filtered CSV:  {cp}')

    if reports.get('outputs') and 'html' in (reports.get('outputs') or []):
        try:
            from lib.html_report import generate_html_report
            hp = os.path.join(outdir, 'filtered_commits.html')
            title = reports.get('title', 'kcommit Analysis Report') + ' — Filtered'
            generate_html_report(dropped_commits, {}, {}, hp, title=title, is_filtered=True,
                          templates_dir=cfg['paths'].get('templates_dir'))
            print(f'  filtered HTML: {hp}')
        except Exception as e:
            logging.warning('filtered HTML failed: %s', e)

    if reports.get('outputs') and 'xlsx' in (reports.get('outputs') or []):
        try:
            xp = os.path.join(outdir, 'filtered_commits.xlsx')
            write_xlsx(xp, dropped_commits, {})
            print(f'  filtered XLSX: {xp}')
        except Exception as e:
            logging.warning('filtered XLSX failed: %s', e)

    if reports.get('outputs') and 'ods' in (reports.get('outputs') or []):
        try:
            op = os.path.join(outdir, 'filtered_commits.ods')
            write_ods(op, dropped_commits, {})
            print(f'  filtered ODS:  {op}')
        except Exception as e:
            logging.warning('filtered ODS failed: %s', e)
