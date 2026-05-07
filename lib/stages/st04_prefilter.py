from lib.manifest import NSTAGES
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
from lib.pipeline_runtime import update_stage_progress
from lib.scoring import extract_commit_meta, precompile_rules
from lib.kbuild import infer_touched_paths
from lib.manifest import CACHE_FILES

_BUILD_SYS_NAMES = frozenset({'Makefile', 'Kbuild', 'Kconfig'})


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
    for pdata in (profile_rules or {}).values():
        merged = (pdata or {}).get('merged', {}) or {}
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
    stem, _ = os.path.splitext(f)
    if stem in cs['artifact_stems']:
        return True
    bn_stem, _ = os.path.splitext(os.path.basename(f))
    return bn_stem in cs['log_basenames']


def _file_is_kconfig_covered(f, cs):
    if f in cs['compiled_files']:
        return True
    fdir = os.path.dirname(f)
    if fdir and fdir in cs['compiled_dirs']:
        return True
    return _is_build_system_file(f)


def filter_decision(commit, lists, compiled_sets, filter_cfg, kconfig_enabled):
    """Return (action, reason): action='keep'|'drop'."""
    sha   = commit.get('commit', '') or ''
    files = list(commit.get('files', []) or [])
    text  = (commit.get('subject', '') or '') + '\n' + (commit.get('body', '') or '')

    commit_wl = lists['commit_wl']
    commit_bl = lists['commit_bl']
    path_wl   = lists['path_wl']
    path_bl   = lists['path_bl']
    kw_wl     = lists['kw_wl']
    kw_bl     = lists['kw_bl']

    # L3 absolute
    if commit_wl and _any_matches(commit_wl, sha):
        return 'keep', 'commit_whitelist'
    if commit_bl and _any_matches(commit_bl, sha):
        return 'drop', 'commit_blacklist'

    enabled = (filter_cfg or {}).get('enabled', True)
    if not enabled:
        return 'keep', 'filter_disabled'

    # L2a path blacklist (ALL files)
    if path_bl and files and _all_files_match(path_bl, files):
        return 'drop', 'path_blacklist_all'

    # L2b path whitelist (ANY file)
    if path_wl and files and _any_file_matches(path_wl, files):
        return 'keep', 'path_whitelist'

    # L2½ build artifact
    if files and any(_file_has_artifact(f, compiled_sets) for f in files):
        return 'keep', 'build_artifact'

    # L2½ kconfig coverage
    if kconfig_enabled:
        require = (filter_cfg or {}).get('require_kconfig_coverage', None)
        if require is None:
            require = compiled_sets.get('available', False)
        if require:
            any_covered = any(
                _file_is_kconfig_covered(f, compiled_sets) for f in files
            ) if files else False
            if not any_covered:
                if kw_wl and _any_matches(kw_wl, text):
                    pass  # keywords_whitelist saves it
                else:
                    return 'drop', 'no_kconfig_coverage'

    # L1a keywords whitelist
    if kw_wl and _any_matches(kw_wl, text):
        return 'keep', 'keywords_whitelist'

    # L1b keywords blacklist
    if kw_bl and _any_matches(kw_bl, text):
        return 'drop', 'keywords_blacklist'

    return 'keep', 'default'


def run(cfg, cache):
    """Enrich + filter commits. Returns (kept, dropped_commits, reasons)."""
    from lib.config import load_json
    from lib.profile_rules import load_profile_rules

    filter_cfg  = cfg.get('filter', {}) or {}
    commits     = load_json(os.path.join(cache, CACHE_FILES['commits']), default=[]) or []
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
    kconfig_enabled = compiled_sets.get('available', False)

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

    kept            = []
    dropped_commits = []
    reasons         = {}
    for i, c in enumerate(commits):
        action, reason = filter_decision(c, lists, compiled_sets, filter_cfg, kconfig_enabled)
        if action == 'drop':
            c['_filter_reason'] = reason
            reasons[reason] = reasons.get(reason, 0) + 1
            dropped_commits.append(c)
        else:
            kept.append(c)
        if i % step == 0 or i == total - 1:
            update_stage_progress(4, NSTAGES, 0.4 + 0.6 * (i + 1) / max(total, 1),
                                  'filtering', n_done=i + 1, n_total=total)
    sys.stdout.write('\n'); sys.stdout.flush()

    save_json(os.path.join(cache, CACHE_FILES['filtered']), kept)
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
                    '; '.join(c.get('matched_profiles') or []),
                    '; '.join(c.get('product_evidence') or []),
                    c.get('_filter_reason', ''),
                ])
        print(f'  filtered CSV:  {cp}')

    if reports.get('outputs') and 'html' in (reports.get('outputs') or []):
        try:
            from lib.html_report import generate_html_report
            hp = os.path.join(outdir, 'filtered_commits.html')
            title = reports.get('title', 'kcommit Analysis Report') + ' — Filtered'
            generate_html_report(dropped_commits, {}, {}, hp, title=title, is_filtered=True)
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