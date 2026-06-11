"""kcommit-analysis-pipeline -- cmd_diagnose subcommand.

A pure post-run read-only diagnostic tool.  It reads cache files produced
by a completed pipeline run and reconstructs the complete decision trace
for one commit.  It executes NO pipeline code whatsoever -- no rule
compilation, no profile loading, no git access, no scoring.

Usage
-----
  kcommit_pipeline.py diagnose --cache-dir <path> --sha <SHA_PREFIX>
  kcommit_pipeline.py diagnose --cache-dir <path> --sha <SHA_PREFIX> --out report.json

  SHA prefix must be at least 7 characters.

Cache files read (all optional; missing files are noted in warnings)
--------------------------------------------------------------------
  commits.json                    stage 01 -- raw collected commits
  prefilter_kept_commits.json     stage 04 -- commits that passed the prefilter
  filtered_commits.json           stage 04 -- commits dropped by the prefilter
  prefilter_debug.json            stage 04 -- per-dropped-commit debug detail
  scored_commits.json             stage 05 -- all scored commits
  relevant_commits.json           stage 06 -- commits kept after postfilter
  postfilter_dropped_commits.json stage 06 -- commits dropped by postfilter
  postfilter_debug.json           stage 06 -- postfilter summary (threshold, dist)

Output JSON top-level keys
--------------------------
  meta               -- tool version, cache_dir, sha_query, generated_at (UTC)
  commit             -- every raw commit field: sha, sha12, subject,
                        author_name, author_email, author_time, files, stats, body
  kernel_annotations -- is_fix, has_cve, has_syzbot, has_stable_cc
                        (extracted from commit.meta set during stage 04 enrichment)
  pipeline_stages    -- one sub-object per relevant stage:
    stage_01_collect
    stage_04_prefilter
    stage_05_scoring
    stage_06_postfilter
  final              -- stage_reached, stage_label, rank, score,
                        in_report, summary (one human sentence)
  warnings           -- data quality / consistency notes

Stage 04 prefilter section detail (v14.1.0)
-------------------------------------------
For DROPPED commits the section contains the full filter_decision() debug
trace, exactly as written by st04_prefilter.py:
  outcome, reason, filter_enabled, kconfig_required
  layers:
    L3_sha_whitelist / L3_sha_blacklist   -- force-keep / force-drop SHA match
    L2a_path_bl_matches                   -- all-files path-blacklist match
    L2half_artifact_files                 -- files with build-artifact evidence
    L2half_kconfig_covered_files          -- files covered by enabled kconfig symbol
    L2half_kconfig_uncovered_files        -- files NOT covered (trigger for drop)

For KEPT commits: outcome='kept', layers=null (debug not stored for kept commits).

Stage 05 scoring section detail
---------------------------------
Surfaced verbatim from scoring.trace.profiles written by scoring.py:
  total_score, matched_profiles, product_evidence (informational)
  profiles:<profile_name>:
    final_score, raw_rule_total, raw_rule_total_capped, multiplier
    blocked, block_reason
    merged_matches:  -- profile-level pattern matches across all rule lists
      keywords_whitelist, keywords_blacklist, path_whitelist,
      path_blacklist, commit_whitelist, commit_blacklist
    rules:<rule_name>:
      weight, matched, matched_level (matched|no-match|blocked), score
      matches:
        keywords_whitelist: [{pattern, value}]  -- exact matched strings
        path_whitelist:     [{pattern, file}]
        commit_whitelist:   [{pattern, value}]

Stage 06 postfilter section detail
------------------------------------
  outcome (kept|dropped|not_run), reason, threshold, score, rank
  threshold sourced from postfilter_debug.json summary.threshold
"""
import datetime
import json
import os
import sys

from lib.config import load_json
from lib.manifest import CACHE_FILES, VERSION


# ---------------------------------------------------------------------------
# tiny private helpers
# ---------------------------------------------------------------------------

def _sha_matches(sha, query):
    """True when sha starts with query (case-insensitive)."""
    return (sha or '').lower().startswith(query.lower())


def _find(pool, query):
    """Return the first commit in pool whose SHA starts with query."""
    for c in (pool or []):
        if _sha_matches(c.get('commit', ''), query):
            return c
    return None


def _load(cache_dir, key, warnings):
    """Load a cache JSON file by CACHE_FILES key.
    Appends to warnings on missing or invalid file; returns None.
    DOES NOT run any pipeline code.
    """
    path = os.path.join(cache_dir, CACHE_FILES[key])
    if not os.path.exists(path):
        warnings.append('cache file missing: %s (stage not yet run?)' % CACHE_FILES[key])
        return None
    try:
        return load_json(path, default=None)
    except Exception as exc:
        warnings.append('failed to read %s: %s' % (CACHE_FILES[key], exc))
        return None


# ---------------------------------------------------------------------------
# section builders
# ---------------------------------------------------------------------------

def _commit_section(c):
    """All raw commit fields exactly as stored.  Body is NOT truncated."""
    return {
        'sha':          c.get('commit', ''),
        'sha12':        (c.get('commit', '') or '')[:12],
        'subject':      c.get('subject', ''),
        'author_name':  c.get('author_name', ''),
        'author_email': c.get('author_email', ''),
        'author_time':  c.get('author_time', ''),
        'files':        list(c.get('files', []) or []),
        'stats':        c.get('stats'),
        'body':         c.get('body', ''),
    }


def _kernel_annotations(c):
    """Kernel annotation flags written to commit.meta by stage 04 enrichment."""
    meta = c.get('meta') or {}
    return {
        'is_fix':        bool(meta.get('is_fix',        False)),
        'has_cve':       bool(meta.get('has_cve',       False)),
        'has_syzbot':    bool(meta.get('has_syzbot',    False)),
        'has_stable_cc': bool(meta.get('has_stable_cc', False)),
    }


# -- Stage 04 ----------------------------------------------------------------

def _stage04(c, prefilter_debug_data):
    """Build stage_04_prefilter section.

    v14.1.0: layers dict no longer contains kw_wl_rescue_suppressed,
    L2b_path_wl_matches, L1a_kw_wl_matches, L1b_kw_bl_matches.
    These were removed from filter_decision() in v14.1.0 (B).
    """
    drop_reason = c.get('_filter_reason')

    if drop_reason:
        dbg = dict(c.get('_prefilter_debug') or {})

        if prefilter_debug_data:
            sha_full = (c.get('commit') or '')
            for entry in (prefilter_debug_data.get('dropped') or []):
                entry_sha = entry.get('sha') or ''
                if sha_full.startswith(entry_sha[:12]) or entry_sha.startswith(sha_full[:12]):
                    dbg = dict(entry.get('debug') or dbg)
                    break

        return {
            'outcome':          'dropped',
            'reason':           drop_reason,
            'filter_enabled':   dbg.get('filter_enabled'),
            'kconfig_required': dbg.get('kconfig_required'),
            'layers': {
                'L3_sha_whitelist':               dbg.get('l3_commit_wl_match'),
                'L3_sha_blacklist':               dbg.get('l3_commit_bl_match'),
                'L2a_path_bl_matches':            dbg.get('l2a_path_bl_matches', []),
                'L2half_artifact_files':          dbg.get('l2half_artifact_files', []),
                'L2half_kconfig_covered_files':   dbg.get('l2half_kconfig_covered_files', []),
                'L2half_kconfig_uncovered_files': dbg.get('l2half_kconfig_uncovered_files', []),
            },
            'explanation': _prefilter_explanation(drop_reason, dbg),
        }

    return {
        'outcome':          'kept',
        'reason':           c.get('_prefilter_reason', 'passed'),
        'filter_enabled':   None,
        'kconfig_required': None,
        'layers':           None,
        'explanation':      'Commit passed the prefilter and was forwarded to scoring.',
    }


def _prefilter_explanation(reason, dbg):
    """Return a plain-English sentence explaining the drop reason."""
    expls = {
        'no_kconfig_coverage': (
            'All commit files are absent from the product build '
            '(no enabled kconfig symbol covers them and no build artifact matches). '
            'Files: ' + ', '.join(dbg.get('l2half_kconfig_uncovered_files', [])) + '.'
        ),
        'path_blacklist_all': (
            'Every file in the commit matches a path blacklist rule, '
            'indicating all touched subsystems are irrelevant to the product. '
            'Matching rules: '
            + ', '.join(
                '%s -> %s' % (m.get('pattern', ''), m.get('file', ''))
                for m in dbg.get('l2a_path_bl_matches', [])
            ) + '.'
        ),
        'commit_blacklist': (
            'The commit SHA is explicitly blacklisted. '
            'Match: %s.' % (dbg.get('l3_commit_bl_match') or '')
        ),
    }
    return expls.get(reason,
                     'Commit was dropped at prefilter. Reason code: %s.' % reason)


# -- Stage 05 ----------------------------------------------------------------

def _stage05(c):
    """Build stage_05_scoring section."""
    scoring = c.get('scoring') or {}
    trace   = (scoring.get('trace') or {}).get('profiles') or {}

    profiles_out = {}

    if trace:
        for pname, pt in trace.items():
            if not isinstance(pt, dict):
                continue
            profiles_out[pname] = {
                'final_score':           pt.get('final_score', 0),
                'raw_rule_total':        pt.get('raw_rule_total', 0),
                'raw_rule_total_capped': pt.get('raw_rule_total_capped', 0),
                'multiplier':            pt.get('multiplier', 1.0),
                'blocked':               pt.get('blocked', False),
                'block_reason':          pt.get('block_reason', ''),
                'merged_matches':        pt.get('merged_matches', {}),
                'rules':                 pt.get('rules', {}),
                'explanation':           _profile_explanation(pname, pt),
            }
    else:
        compact = scoring.get('profiles') or {}
        for pname, val in compact.items():
            if isinstance(val, int):
                profiles_out[pname] = {
                    'final_score': val,
                    'note': 'Compact format -- full rule trace not available in this cache version.',
                }
            elif isinstance(val, dict):
                profiles_out[pname] = val

    return {
        'total_score':      c.get('score'),
        'matched_profiles': c.get('matched_profiles', []),
        'product_evidence': c.get('product_evidence', []),
        'product_evidence_note': (
            'product_evidence is informational only. '
            'It has no effect on the score. '
            'Score is determined solely by profile rules.'
        ),
        'profiles': profiles_out,
    }


def _profile_explanation(pname, pt):
    """Return a plain-English sentence for a profile scoring result."""
    if pt.get('blocked'):
        return (
            'Profile %r was BLOCKED (score=0). Reason: %s. '
            'One or more blacklist patterns matched before any rule was evaluated.'
            % (pname, pt.get('block_reason', 'profile_blacklist'))
        )
    fs          = pt.get('final_score', 0)
    rr          = pt.get('raw_rule_total', 0)
    mult        = pt.get('multiplier', 1.0)
    rules       = pt.get('rules') or {}
    matched     = [rn for rn, rd in rules.items()
                   if isinstance(rd, dict) and rd.get('matched')]
    total_rules = len(rules)
    if fs == 0:
        return (
            'Profile %r contributed 0 points (%d/%d rules matched, none scored).'
            % (pname, len(matched), total_rules)
        )
    capped_note = ' (capped at 100 before multiplier)' if rr > 100 else ''
    mult_note   = ' x%.2f multiplier' % mult if mult != 1.0 else ''
    return (
        'Profile %r: %d/%d rules matched, raw total=%d%s%s, final=%d. '
        'Matched rules: %s.'
        % (pname, len(matched), total_rules, rr, capped_note, mult_note, fs,
           ', '.join(matched) if matched else 'none')
    )


# -- Stage 06 ----------------------------------------------------------------

def _stage06(c, postfilter_debug, threshold):
    """Build stage_06_postfilter section."""
    rank      = c.get('_rank')
    pf_reason = (c.get('_postfilter_reason') or c.get('_filter_reason') or '')
    score     = c.get('score')

    if rank is not None:
        return {
            'outcome':     'kept',
            'reason':      'score >= threshold',
            'threshold':   threshold,
            'score':       score,
            'rank':        rank,
            'explanation': (
                'Commit scored %s which is >= threshold %s. '
                'Assigned final rank %d.'
                % (score, threshold, rank)
            ),
        }

    if pf_reason and ('score_below' in pf_reason or 'threshold' in pf_reason.lower()):
        return {
            'outcome':     'dropped',
            'reason':      pf_reason,
            'threshold':   threshold,
            'score':       score,
            'rank':        None,
            'explanation': (
                'Commit scored %s which is below the min_score threshold of %s. '
                'It was excluded from the final report.'
                % (score, threshold)
            ),
        }

    return {
        'outcome':     'not_run',
        'reason':      None,
        'threshold':   threshold,
        'score':       score,
        'rank':        None,
        'explanation': 'Stage 06 postfilter has not run yet, or its output cache is missing.',
    }


# -- Final verdict -----------------------------------------------------------

_STAGE_LABELS = {
    'relevant':           'kept -- present in final report (stage 07 output)',
    'postfilter_dropped': 'dropped at stage 06 postfilter (score below threshold)',
    'scored':             'scored at stage 05; stage 06 postfilter not yet run',
    'prefilter_kept':     'passed stage 04 prefilter; stage 05 scoring not yet run',
    'filtered':           'dropped at stage 04 prefilter (never scored)',
    'commits_only':       'collected at stage 01; pipeline stages 04+ not yet run',
    'not_found':          'not found in any cache file',
}


def _final(stage, c):
    sha12   = (c.get('commit', '') or '')[:12]
    subject = (c.get('subject', '') or '')[:80]
    score   = c.get('score')
    rank    = c.get('_rank')
    reason  = (c.get('_filter_reason') or c.get('_postfilter_reason') or '').strip()

    summaries = {
        'relevant':
            'Commit %s ("%s") is in the final report at rank %s with score %s.'
            % (sha12, subject, rank, score),
        'postfilter_dropped':
            'Commit %s ("%s") was scored %s but dropped (below threshold). Reason: %s.'
            % (sha12, subject, score, reason),
        'scored':
            'Commit %s ("%s") was scored %s. Postfilter has not yet run.'
            % (sha12, subject, score),
        'prefilter_kept':
            'Commit %s ("%s") passed the prefilter. Scoring has not yet run.'
            % (sha12, subject),
        'filtered':
            'Commit %s ("%s") was dropped at prefilter and never scored. Reason: %s.'
            % (sha12, subject, reason),
        'commits_only':
            'Commit %s ("%s") was collected but no subsequent pipeline stage has run.'
            % (sha12, subject),
        'not_found':
            'SHA prefix not found in any cache file. '
            'Verify the SHA and that stage 01 has completed.',
    }

    return {
        'stage_reached': stage,
        'stage_label':   _STAGE_LABELS.get(stage, stage),
        'rank':          rank,
        'score':         score,
        'in_report':     (stage == 'relevant'),
        'summary':       summaries.get(stage,
                                       'Commit %s found at stage: %s.' % (sha12, stage)),
    }


# ---------------------------------------------------------------------------
# main entry point (pure cache read)
# ---------------------------------------------------------------------------

def diagnose_commit(cache_dir, sha_query):
    """Read pipeline cache files and return a complete diagnosis dict."""
    warnings = []

    relevant           = _load(cache_dir, 'relevant',           warnings) or []
    postfilter_dropped = _load(cache_dir, 'postfilter_dropped', warnings) or []
    scored             = _load(cache_dir, 'scored',             warnings) or []
    prefilter_kept     = _load(cache_dir, 'prefilter_kept',     warnings) or []
    filtered           = _load(cache_dir, 'filtered',           warnings) or []
    all_commits        = _load(cache_dir, 'commits',            warnings) or []
    prefilter_debug    = _load(cache_dir, 'prefilter_debug',    warnings)
    postfilter_debug   = _load(cache_dir, 'postfilter_debug',   warnings)

    all_pools = (relevant + postfilter_dropped + scored
                 + prefilter_kept + filtered + all_commits)
    matching_shas = {
        (c.get('commit') or '').lower()
        for c in all_pools
        if (c.get('commit') or '').lower().startswith(sha_query.lower())
    }
    if len(matching_shas) > 1:
        sample = ', '.join(sorted(matching_shas)[:6])
        warnings.append(
            'SHA prefix %r is ambiguous: matches %d commits (%s). '
            'Provide more characters.' % (sha_query, len(matching_shas), sample)
        )

    commit = None
    stage  = 'not_found'

    for pool, label in [
        (relevant,           'relevant'),
        (postfilter_dropped, 'postfilter_dropped'),
        (scored,             'scored'),
        (prefilter_kept,     'prefilter_kept'),
        (filtered,           'filtered'),
        (all_commits,        'commits_only'),
    ]:
        hit = _find(pool, sha_query)
        if hit:
            commit = hit
            stage  = label
            break

    if stage == 'commits_only':
        warnings.append(
            'Commit found only in raw commits.json. '
            'Stages 04+ have not processed it yet.')

    if commit is None:
        warnings.append(
            'Commit with SHA prefix %r not found in any cache file.' % sha_query)
        commit = {'commit': sha_query}

    threshold = None
    if isinstance(postfilter_debug, dict):
        threshold = (postfilter_debug.get('summary') or {}).get('threshold')

    s01 = {
        'found': bool(_find(all_commits, sha_query)),
        'sha':   commit.get('commit') or None,
    }

    s04 = _stage04(commit, prefilter_debug)

    s05 = None
    s06 = None
    if stage in ('relevant', 'postfilter_dropped', 'scored'):
        s05 = _stage05(commit)
        s06 = _stage06(commit, postfilter_debug, threshold)

    return {
        'meta': {
            'pipeline_version': VERSION,
            'cache_dir':        cache_dir,
            'sha_query':        sha_query,
            'generated_at':     datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z',
            'note':             (
                'This report was generated by reading pipeline cache files only. '
                'No pipeline code was executed.'
            ),
        },
        'commit':             _commit_section(commit),
        'kernel_annotations': _kernel_annotations(commit),
        'pipeline_stages': {
            'stage_01_collect':    s01,
            'stage_04_prefilter':  s04,
            'stage_05_scoring':    s05,
            'stage_06_postfilter': s06,
        },
        'final':    _final(stage, commit),
        'warnings': warnings,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def cmd_diagnose(args):
    """Called from kcommit_pipeline.py main()."""
    sha_query = (getattr(args, 'sha', '') or '').strip()
    if not sha_query:
        print('ERROR: --sha is required', file=sys.stderr)
        raise SystemExit(1)
    if len(sha_query) < 7:
        print('ERROR: --sha must be at least 7 characters', file=sys.stderr)
        raise SystemExit(1)

    cache_dir = os.path.abspath(getattr(args, 'cache_dir', '') or '')
    if not cache_dir:
        print('ERROR: --cache-dir is required', file=sys.stderr)
        raise SystemExit(1)
    if not os.path.isdir(cache_dir):
        print('ERROR: cache directory does not exist: %s' % cache_dir, file=sys.stderr)
        raise SystemExit(1)

    report = diagnose_commit(cache_dir, sha_query)
    output = json.dumps(report, indent=2, default=str)

    out_path = getattr(args, 'out', None)
    if out_path:
        with open(out_path, 'w', encoding='utf-8') as fh:
            fh.write(output)
        print('diagnose: report written to %s' % out_path, file=sys.stderr)
    else:
        print(output)

    if report['warnings']:
        n = len(report['warnings'])
        print('diagnose: %d warning(s) -- see "warnings" key in output' % n,
              file=sys.stderr)
