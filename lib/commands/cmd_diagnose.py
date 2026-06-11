"""kcommit-analysis-pipeline -- cmd_diagnose subcommand.

Produces a self-contained JSON report summarising every aspect of one commit's
journey through the pipeline: raw metadata, prefilter decision, scoring detail,
postfilter decision, and final rank (if kept).

Design note
-----------
This command does NOT require --config.  It reads only cache files and needs
only the path to the cache directory.  --config is intentionally absent to
keep the command runnable without a config file (e.g. after the pipeline was
run by another user or on another machine and only the cache is available).

Usage
-----
  kcommit_pipeline.py diagnose --cache-dir <path> --sha <SHA_PREFIX>
  kcommit_pipeline.py diagnose --cache-dir <path> --sha <SHA_PREFIX> --out report.json

  # Convenience: derive cache_dir from config when available
  kcommit_pipeline.py diagnose --config cfg.json --sha <SHA_PREFIX>
  kcommit_pipeline.py diagnose --config cfg.json --sha <SHA_PREFIX> --out report.json

  When both --config and --cache-dir are provided, --cache-dir wins.
  At least one of --config or --cache-dir is required.

Output schema (top-level keys)
-------------------------------
  meta            -- pipeline version, cache_dir, sha queried
  commit          -- raw commit fields from commits.json (or whichever cache
                     the commit was found in)
  cache_presence  -- which cache files exist and their sizes
  prefilter       -- outcome, reason, and full debug_detail from prefilter_debug.json
                     (or from filtered_commits.json for dropped commits)
  scoring         -- score, matched_profiles, profile breakdown, product_evidence
                     (None when commit was dropped before scoring)
  postfilter      -- outcome, reason, threshold (None when not reached)
  final           -- stage the commit is in, _rank (if relevant), summary sentence
  warnings        -- list of data-quality or consistency issues noticed during
                     the diagnosis (e.g. missing cache files, SHA ambiguity)

Search order
------------
  1. relevant_commits.json              (kept through full pipeline)
  2. postfilter_dropped_commits.json    (scored but below min_score)
  3. scored_commits.json                (scored; postfilter cache missing or not run)
  4. prefilter_kept_commits.json        (passed prefilter; scoring not yet done)
  5. filtered_commits.json              (dropped at prefilter)
  6. commits.json                       (raw collected commits, no stage processed yet)

  The first file that contains a commit matching the SHA prefix is used.
"""
import json
import os
import sys

from lib.config import load_json
from lib.manifest import CACHE_FILES, VERSION


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _sha_matches(commit_sha, query):
    """True when commit_sha starts with query (case-insensitive)."""
    return (commit_sha or '').lower().startswith(query.lower())


def _find_in_list(commits, sha_query):
    """Return the first commit in the list whose SHA starts with sha_query."""
    for c in (commits or []):
        if _sha_matches(c.get('commit', ''), sha_query):
            return c
    return None


def _safe_load(cache_dir, key, warnings):
    """Load a cache JSON file; append to warnings on missing/invalid."""
    path = os.path.join(cache_dir, CACHE_FILES[key])
    if not os.path.exists(path):
        warnings.append(f'cache file missing: {CACHE_FILES[key]} (stage not yet run?)')
        return None
    try:
        return load_json(path, default=None)
    except Exception as exc:
        warnings.append(f'failed to read {CACHE_FILES[key]}: {exc}')
        return None


def _cache_presence(cache_dir):
    """Return a dict of {logical_key: {filename, exists, size_bytes}} for all
    known cache files."""
    result = {}
    for key, fname in CACHE_FILES.items():
        path = os.path.join(cache_dir, fname)
        exists = os.path.exists(path)
        result[key] = {
            'filename':   fname,
            'exists':     exists,
            'size_bytes': os.path.getsize(path) if exists else None,
        }
    return result


def _strip_internals(commit):
    """Return a copy of the commit dict without heavy internal fields.
    Body is truncated to 500 chars; pipeline-internal keys are removed."""
    c = dict(commit)
    if c.get('body'):
        c['body'] = c['body'][:500] + ('...' if len(c['body']) > 500 else '')
    for k in ('_filter_reason', '_prefilter_debug', '_postfilter_reason',
              'meta', 'touched_paths_guess'):
        c.pop(k, None)
    return c


def _prefilter_section(commit, prefilter_debug_data, warnings):
    """Build the 'prefilter' section of the diagnosis.

    For dropped commits: _filter_reason and _prefilter_debug are stored
    directly on the commit object (filtered_commits.json).
    For kept commits: prefilter_debug.json only contains dropped entries;
    the section reflects that the commit passed.
    """
    reason = commit.get('_filter_reason')

    if reason:  # commit was dropped at prefilter
        debug = commit.get('_prefilter_debug') or {}
        # Enrich from prefilter_debug.json if available
        if prefilter_debug_data:
            sha = (commit.get('commit') or '')[:40]
            for entry in (prefilter_debug_data.get('dropped') or []):
                if (entry.get('sha') or '').startswith(sha[:12]):
                    debug = entry.get('debug') or debug
                    break
        return {
            'outcome':                  'dropped',
            'reason':                   reason,
            'kw_wl_rescue_suppressed':  debug.get('kw_wl_rescue_suppressed', False),
            'debug': {
                'filter_enabled':                debug.get('filter_enabled'),
                'kconfig_required':              debug.get('kconfig_required'),
                'files_evaluated':               debug.get('files', []),
                'l3_commit_wl_match':            debug.get('l3_commit_wl_match'),
                'l3_commit_bl_match':            debug.get('l3_commit_bl_match'),
                'l2a_path_bl_matches':           debug.get('l2a_path_bl_matches', []),
                'l2b_path_wl_matches':           debug.get('l2b_path_wl_matches', []),
                'l2half_artifact_files':         debug.get('l2half_artifact_files', []),
                'l2half_kconfig_covered_files':  debug.get('l2half_kconfig_covered_files', []),
                'l2half_kconfig_uncovered_files': debug.get('l2half_kconfig_uncovered_files', []),
                'l1a_kw_wl_matches':             debug.get('l1a_kw_wl_matches', []),
                'l1b_kw_bl_matches':             debug.get('l1b_kw_bl_matches', []),
            },
        }

    return {
        'outcome': 'kept',
        'reason':  commit.get('_prefilter_reason', 'passed'),
        'kw_wl_rescue_suppressed': False,
        'debug': None,
    }


def _scoring_section(commit):
    """Build the 'scoring' section from a scored/relevant/postfilter_dropped commit."""
    scoring_raw = commit.get('scoring') or {}
    profiles_raw = scoring_raw.get('profiles') or {}

    profile_breakdown = {}
    for pname, pdata in profiles_raw.items():
        if not isinstance(pdata, dict):
            continue
        profile_breakdown[pname] = {
            'score':         pdata.get('score', 0),
            'weight':        pdata.get('weight'),
            'matched_rules': pdata.get('matched_rules', []),
            'keyword_hits':  pdata.get('keyword_hits', []),
            'path_hits':     pdata.get('path_hits', []),
        }

    return {
        'score':             commit.get('score'),
        'matched_profiles':  commit.get('matched_profiles', []),
        'product_evidence':  commit.get('product_evidence', []),
        'profile_breakdown': profile_breakdown,
    }


def _postfilter_section(commit, postfilter_debug_data, threshold):
    """Build the 'postfilter' section."""
    pf_reason = commit.get('_postfilter_reason') or commit.get('_filter_reason')

    if pf_reason and 'score' in (pf_reason or '').lower():
        return {
            'outcome':   'dropped',
            'reason':    pf_reason,
            'threshold': threshold,
            'score':     commit.get('score'),
        }

    rank = commit.get('_rank')
    if rank is not None:
        return {
            'outcome':   'kept',
            'reason':    'above_threshold',
            'threshold': threshold,
            'score':     commit.get('score'),
            'rank':      rank,
        }

    return {
        'outcome':   'unknown',
        'reason':    None,
        'threshold': threshold,
        'score':     commit.get('score'),
    }


def _final_section(stage_found, commit):
    """Build the human-readable 'final' summary section."""
    sha12   = (commit.get('commit') or '')[:12]
    subject = (commit.get('subject') or '')[:80]
    score   = commit.get('score')
    rank    = commit.get('_rank')
    reason  = commit.get('_filter_reason') or commit.get('_postfilter_reason')

    stage_labels = {
        'relevant':           'kept — present in final report',
        'postfilter_dropped': 'dropped at postfilter (score below threshold)',
        'scored':             'scored but postfilter not yet run',
        'prefilter_kept':     'passed prefilter but not yet scored',
        'filtered':           'dropped at prefilter',
        'commits_only':       'found only in raw commit list (no stage has processed it yet)',
        'not_found':          'not found in any cache file',
    }

    sentences = {
        'relevant':           f'Commit {sha12} ("{subject}") is in the final report at rank {rank} with score {score}.',
        'postfilter_dropped': f'Commit {sha12} ("{subject}") was scored ({score}) but dropped by the postfilter (below threshold). Reason: {reason}.',
        'scored':             f'Commit {sha12} ("{subject}") has been scored ({score}); postfilter has not run yet.',
        'prefilter_kept':     f'Commit {sha12} ("{subject}") passed the prefilter and is queued for scoring.',
        'filtered':           f'Commit {sha12} ("{subject}") was dropped at prefilter. Reason: {reason}.',
        'commits_only':       f'Commit {sha12} ("{subject}") was collected but no subsequent stage has run yet.',
        'not_found':          f'Commit {sha12} was not found in any cache file.  Check that stage 01 has run and the SHA is correct.',
    }

    return {
        'stage_found': stage_found,
        'stage_label': stage_labels.get(stage_found, stage_found),
        'rank':        rank,
        'score':       score,
        'summary':     sentences.get(stage_found, f'Commit {sha12} found at stage: {stage_found}.'),
    }


# ---------------------------------------------------------------------------
# main diagnosis logic
# ---------------------------------------------------------------------------

def diagnose_commit(cache_dir, sha_query):
    """Build and return the full diagnosis dict for the given SHA prefix.

    Args:
        cache_dir:  path to the pipeline cache directory.
        sha_query:  SHA prefix to search for (min 7 chars recommended).

    Returns a dict with keys: meta, commit, cache_presence, prefilter,
    scoring, postfilter, final, warnings.
    """
    warnings = []

    # -- Cache presence map --------------------------------------------------
    presence = _cache_presence(cache_dir)

    # -- Load cache files ----------------------------------------------------
    relevant           = _safe_load(cache_dir, 'relevant',           warnings) or []
    postfilter_dropped = _safe_load(cache_dir, 'postfilter_dropped', warnings) or []
    scored             = _safe_load(cache_dir, 'scored',             warnings) or []
    prefilter_kept     = _safe_load(cache_dir, 'prefilter_kept',     warnings) or []
    filtered           = _safe_load(cache_dir, 'filtered',           warnings) or []
    all_commits        = _safe_load(cache_dir, 'commits',            warnings) or []
    prefilter_debug_data  = _safe_load(cache_dir, 'prefilter_debug',  warnings)
    postfilter_debug_data = _safe_load(cache_dir, 'postfilter_debug', warnings)

    # -- SHA uniqueness check ------------------------------------------------
    all_pools = relevant + postfilter_dropped + scored + prefilter_kept + filtered + all_commits
    seen_shas = set()
    for c in all_pools:
        sha = (c.get('commit') or '').lower()
        if sha.startswith(sha_query.lower()):
            seen_shas.add(sha)
    if len(seen_shas) > 1:
        warnings.append(
            f'SHA prefix {sha_query!r} is ambiguous: matches {len(seen_shas)} commits '
            f'({", ".join(sorted(seen_shas)[:5])}).  Provide more characters.')

    # -- Find commit and determine stage -------------------------------------
    commit      = None
    stage_found = 'not_found'

    for pool, label in [
        (relevant,           'relevant'),
        (postfilter_dropped, 'postfilter_dropped'),
        (scored,             'scored'),
        (prefilter_kept,     'prefilter_kept'),
        (filtered,           'filtered'),
        (all_commits,        'commits_only'),
    ]:
        commit = _find_in_list(pool, sha_query)
        if commit:
            stage_found = label
            break

    if stage_found == 'commits_only':
        warnings.append(
            'Commit found only in raw commits.json.  '
            'Stages 04+ have not processed it yet, or the pipeline has not been run.')

    if not commit:
        warnings.append(
            f'Commit with SHA prefix {sha_query!r} not found in any cache file.')
        commit = {'commit': sha_query}

    # -- Postfilter threshold ------------------------------------------------
    threshold = None
    if postfilter_debug_data and isinstance(postfilter_debug_data, dict):
        threshold = postfilter_debug_data.get('summary', {}).get('threshold')

    # -- Build sections ------------------------------------------------------
    prefilter_sec  = _prefilter_section(commit, prefilter_debug_data, warnings)
    scoring_sec    = None
    postfilter_sec = None

    if stage_found in ('relevant', 'postfilter_dropped', 'scored'):
        scoring_sec    = _scoring_section(commit)
        postfilter_sec = _postfilter_section(commit, postfilter_debug_data, threshold)

    final_sec = _final_section(stage_found, commit)

    return {
        'meta': {
            'pipeline_version': VERSION,
            'cache_dir':        cache_dir,
            'sha_query':        sha_query,
        },
        'commit':         _strip_internals(commit),
        'cache_presence': presence,
        'prefilter':      prefilter_sec,
        'scoring':        scoring_sec,
        'postfilter':     postfilter_sec,
        'final':          final_sec,
        'warnings':       warnings,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def cmd_diagnose(args):
    """Entry point called from kcommit_pipeline.py main().

    Resolves cache_dir from --cache-dir (preferred) or --config (fallback),
    then delegates to diagnose_commit().
    """
    sha_query = (args.sha or '').strip()
    if not sha_query:
        print('ERROR: --sha is required', file=sys.stderr)
        raise SystemExit(1)
    if len(sha_query) < 7:
        print('ERROR: --sha must be at least 7 characters', file=sys.stderr)
        raise SystemExit(1)

    # Resolve cache_dir: --cache-dir wins over --config
    cache_dir = getattr(args, 'cache_dir', None)
    if not cache_dir:
        config_path = getattr(args, 'config', None)
        if not config_path:
            print('ERROR: one of --cache-dir or --config is required', file=sys.stderr)
            raise SystemExit(1)
        # Minimal config load: only extract cache_dir, no rule/profile loading
        from lib.commands.base import load_cfg
        cfg = load_cfg(args)
        cache_dir = cfg['paths']['cache_dir']

    cache_dir = os.path.abspath(cache_dir)
    if not os.path.isdir(cache_dir):
        print(f'ERROR: cache directory does not exist: {cache_dir}', file=sys.stderr)
        raise SystemExit(1)

    report = diagnose_commit(cache_dir, sha_query)

    output = json.dumps(report, indent=2, default=str)

    if getattr(args, 'out', None):
        with open(args.out, 'w', encoding='utf-8') as fh:
            fh.write(output)
        print(f'diagnose: report written to {args.out}', file=sys.stderr)
    else:
        print(output)

    # Non-zero exit when warnings present (useful in CI / scripts)
    if report['warnings']:
        print(f'diagnose: {len(report["warnings"])} warning(s) -- see "warnings" key in output',
              file=sys.stderr)
