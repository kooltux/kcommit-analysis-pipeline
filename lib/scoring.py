"""Commit scoring helpers for kcommit-analysis-pipeline.

Scoring is exclusively driven by user-defined profiles and rules.
Kernel annotation metadata (CVE, Fixes:, Cc:stable, syzbot) is extracted
for informational display only and does not affect the score.
Product-evidence tags are collected for display; they do not affect the score.

v13.0.1 changes:
  _collect_product_evidence(): reads config_enabled_map and config_enabled_dirs
  from product_map instead of config_to_paths and config_dirs.  This ensures
  that product_evidence tags reference only symbols that are actually enabled
  in the product .config, not the full Kbuild universe.

vG changes (graceful degradation -- no build artifacts):
  _collect_product_evidence(): removed touched_paths_guess-based loops
  (config_dir:, artifact:, build_log: via keyword heuristics) and the
  config_text: loop (CONFIG symbol name vs commit message text matching).
  All three were noise sources: they fired on keyword guesses, not actual
  commit files, producing misleading evidence tags when build context was
  partial or absent.
  Replaced with file-accurate loops:
    T1 artifact:  -- full-path stem against built_artifacts_from_dir
    T2 build_log: -- basename stem against built_objects_from_log, scoped
                     to compiled_dirs (same guard as st04 _file_has_artifact)
  T3 config_map: loop unchanged (already file-accurate).
  When T1/T2 are absent, evidence is empty except for T3 -- correct graceful
  degradation.  touched_paths_guess renamed to _touched_paths_guess in st04
  (private field, excluded from JSON output ordering).

v16.5.0 changes (scoring formula -- remove per-profile cap):
  score_commit(): removed the min(per_rule_total, 100) cap that was applied
  before the profile multiplier.  Rule weights now accumulate without bound,
  so a commit that fires many rules in a profile scores higher than one that
  fires fewer -- the cap was silently discarding that signal.
  Formula change:
    before: final = int(min(raw_total, 100) * pmult)
    after:  final = int(raw_total * pmult)
  'raw_rule_total_capped' removed from the per-profile trace dict; only
  'raw_rule_total' and 'final_score' are emitted.

Pattern match provenance:
  _all_matches() now accepts an optional *sources* argument — a list of
  (filepath, lineno) tuples parallel to *patterns* — and includes
  source_file, source_line, match_start, match_end in every hit dict.
  score_commit() passes the _sources_<key> lists from each rule body.
"""
import os
import re

from lib.profile_rules import _merged_patterns
from lib.patterns import match as _pat_match, match_span as _pat_span, precompile_rules


def order_commit_details(commit):
    """Return commit dict ordered like git log details."""
    commit = dict(commit or {})
    ordered = {}
    first = [
        'commit', 'subject', 'author_name', 'author_email', 'author_time',
        'files', 'stats', 'meta', 'product_evidence',
        'matched_profiles', 'scoring', 'body', '_filter_reason',
    ]
    for key in first:
        if key in commit:
            ordered[key] = commit[key]
    for key, value in commit.items():
        if key not in ordered and not str(key).startswith('_'):
            ordered[key] = value
    for key, value in commit.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


# -- Kernel commit annotation regexes -----------------------------------------
_RE_FIXES  = re.compile(r'^fixes\s*:\s+[0-9a-f]{6,}', re.I | re.MULTILINE)
_RE_CVE    = re.compile(r'CVE-\d{4}-\d{4,}', re.I)
_RE_SYZBOT = re.compile(r'syzbot', re.I)
_RE_STABLE = re.compile(r'cc\s*:.*stable', re.I)


def _profile_multipliers(cfg):
    """Return {profile_name: float multiplier} from profiles.active config."""
    if not cfg:
        return {}
    active = ((cfg.get('profiles', {}) or {}).get('active') or {})
    if isinstance(active, list):
        return {name: 1.0 for name in active}
    if not isinstance(active, dict):
        return {}
    out = {}
    for name, val in active.items():
        try:
            out[name] = max(0.0, float(val)) / 100.0
        except (TypeError, ValueError):
            out[name] = 1.0
    return out


# -- Public helpers ------------------------------------------------------------

def _pattern_repr(pat):
    return getattr(pat, 'pattern', pat)


def _first_match(patterns, values):
    """Return first {pattern, value} match across patterns x values, or None."""
    for pat in (patterns or []):
        for val in (values or []):
            if _pat_match(pat, val):
                return {'pattern': _pattern_repr(pat), 'value': val}
    return None


def _all_matches(patterns, values, sources=None):
    """Return all unique match hit dicts across patterns x values.

    Each hit dict contains:
      pattern     -- string representation of the compiled pattern
      value       -- the full string that was matched (subject, body, or file path)
      source_file -- path to the .txt rule file that defined this pattern
      source_line -- 1-based line number within that file
      match_start -- start char offset of the match within *value*
      match_end   -- end char offset of the match within *value*

    *sources* is an optional list of (filepath, lineno) tuples parallel to
    *patterns*.  When absent (e.g. for merged-pattern calls that have no
    per-index source map), source_file and source_line are omitted.
    """
    out, seen = [], set()
    for idx, pat in enumerate(patterns or []):
        src = sources[idx] if (sources and idx < len(sources)) else None
        for val in (values or []):
            if _pat_match(pat, val):
                key = (_pattern_repr(pat), val)
                if key not in seen:
                    seen.add(key)
                    span = _pat_span(pat, val)
                    hit = {
                        'pattern':     _pattern_repr(pat),
                        'value':       val,
                        'match_start': span[0] if span else 0,
                        'match_end':   span[1] if span else len(val),
                    }
                    if src:
                        hit['source_file'] = src[0]
                        hit['source_line'] = src[1]
                    out.append(hit)
    return out


# -- Public API ----------------------------------------------------------------

def extract_commit_meta(commit):
    """Linux kernel commit annotation flags (informational metadata only)."""
    subject = commit.get('subject', '') or ''
    body    = commit.get('body',    '') or ''
    full    = subject + '\n' + body
    return {
        'is_fix':        bool(_RE_FIXES.search(full)),
        'has_cve':       bool(_RE_CVE.search(full)),
        'has_syzbot':    bool(_RE_SYZBOT.search(full)),
        'has_stable_cc': bool(_RE_STABLE.search(full)),
    }


def _collect_product_evidence(commit, product_map):
    """Collect informational product-coverage evidence tags for *commit*.

    Three evidence sources, all anchored to *actual commit files* (not guessed
    paths derived from the subject text):

    T3 config_map: -- the commit file path (or its directory) matches a path
       associated with an enabled CONFIG symbol in config_enabled_map.

    T1 artifact:   -- the commit file's full-path stem is found in
       built_artifacts_from_dir (exact match, e.g. drivers/usb/core/hub).

    T2 build_log:  -- the commit file's basename stem is found in
       built_objects_from_log, AND the file's directory is in
       config_enabled_dirs (same directory-scoped guard as _file_has_artifact
       in st04 to avoid cross-tree false positives).

    When T1/T2 are absent (no build artifacts or log provided), only T3 fires.
    When all three are absent (no product_map), evidence is empty.
    This ensures graceful degradation: partial or missing build context never
    produces misleading evidence tags.
    """
    commit_files = set(commit.get('files', []) or [])

    cem           = (product_map or {}).get('config_enabled_map', {}) or {}
    ced           = list((product_map or {}).get('config_enabled_dirs', []) or [])
    build_log_set = set((product_map or {}).get('built_objects_from_log', []) or [])
    artifact_set  = set((product_map or {}).get('built_artifacts_from_dir', []) or [])

    evidence     = []
    matched_syms = set()

    # T3: config_map -- exact commit-file match against config_enabled_map paths
    for sym, sym_paths in cem.items():
        for sp in (sym_paths or []):
            sp_dir = os.path.dirname(sp)
            if any(cf == sp or (sp_dir and cf.startswith(sp_dir + '/'))
                   for cf in commit_files):
                if sym not in matched_syms:
                    evidence.append('config_map:%s' % sym)
                    matched_syms.add(sym)
                break

    # T1: artifact -- full-path stem match against actual commit files
    artifact_stems = set()
    for p in artifact_set:
        stem, _ = os.path.splitext(p)
        artifact_stems.add(stem)
    for cf in commit_files:
        stem, _ = os.path.splitext(cf)
        if stem in artifact_stems:
            evidence.append('artifact:%s' % cf)

    # T2: build_log -- basename-stem match scoped to compiled dirs
    # Uses the same directory-scoped guard as _file_has_artifact() in st04:
    # a log-basename hit is only accepted when the file's parent directory is
    # in compiled_dirs (config_enabled_dirs) or the file itself is in
    # compiled_files (config_enabled_map paths).  This prevents cross-tree
    # false positives where a common basename (e.g. 'core') matches log
    # entries from an unrelated subsystem.
    log_stems = set()
    for p in build_log_set:
        bn = os.path.basename(p)
        s, _ = os.path.splitext(bn)
        log_stems.add(s)
    compiled_dirs_set = set(ced)
    compiled_files_set = set()
    for paths in cem.values():
        compiled_files_set.update(paths)
    for cf in commit_files:
        bn_stem, _ = os.path.splitext(os.path.basename(cf))
        if bn_stem in log_stems:
            fdir = os.path.dirname(cf)
            fdir_norm = (fdir.rstrip('/') + '/') if fdir else ''
            if (fdir and fdir_norm in compiled_dirs_set) or cf in compiled_files_set:
                evidence.append('build_log:%s' % bn_stem)

    return sorted(set(evidence))


def score_commit(commit, product_map, profile_rules, cfg=None):
    """Score a single commit against all active profiles.

    Scoring formula (v16.5.0 -- no cap):
      raw_rule_total = sum of weights of all matching rules in the profile
      final_score    = int(raw_rule_total * profile_multiplier)
      commit score   = sum of final_score across all active profiles

    Rule weights accumulate without an upper bound so that a commit matching
    more / heavier rules always ranks strictly higher than one that matches
    fewer -- the previous min(..., 100) cap was silently discarding that
    signal.
    """
    if profile_rules:
        precompile_rules(profile_rules)

    prof_mults   = _profile_multipliers(cfg)
    result       = dict(commit)
    subject      = commit.get('subject', '') or ''
    body         = commit.get('body',    '') or ''
    commit_files = set(commit.get('files', []) or [])

    hints    = commit.get('meta') or extract_commit_meta(commit)
    evidence = _collect_product_evidence(commit, product_map)

    commit_sha     = commit.get('commit', '') or ''
    message_values = [subject, body]
    file_values    = sorted(commit_files)
    matched_profiles = []
    profile_scores   = {}
    scoring_trace    = {'profiles': {}}

    for pname, pdata in (profile_rules or {}).items():
        if not isinstance(pdata, dict):
            continue
        merged = _merged_patterns(pdata)
        rules  = (pdata or {}).get('rules', {}) or {}
        pmult  = prof_mults.get(pname, 1.0)

        # Merged-level matches have no per-pattern source index, so sources=None
        kw_black   = _all_matches(merged.get('keywords_blacklist', []), message_values)
        sha_black  = _all_matches(merged.get('commit_blacklist',   []), [commit_sha])
        path_black = _all_matches(merged.get('path_blacklist',     []), file_values)

        blocked = bool(kw_black or sha_black or path_black)
        profile_trace = {
            'multiplier': pmult,
            'merged_matches': {
                'keywords_whitelist': _all_matches(merged.get('keywords_whitelist', []), message_values),
                'keywords_blacklist': kw_black,
                'path_whitelist':     _all_matches(merged.get('path_whitelist',     []), file_values),
                'path_blacklist':     path_black,
                'commit_whitelist':   _all_matches(merged.get('commit_whitelist',   []), [commit_sha]),
                'commit_blacklist':   sha_black,
            },
            'blocked':        blocked,
            'block_reason':   'profile_blacklist' if blocked else '',
            'rules':          {},
            'raw_rule_total': 0,
            'final_score':    0,
        }

        per_rule_total = 0
        if not blocked:
            for rname, rdata in rules.items():
                rw = int(rdata.get('weight', 50) or 0)
                # Pass _sources_<key> so each hit carries file+line provenance
                kw_hits   = _all_matches(
                    rdata.get('keywords_whitelist', []), message_values,
                    sources=rdata.get('_sources_keywords_whitelist'))
                path_hits = _all_matches(
                    rdata.get('path_whitelist', []), file_values,
                    sources=rdata.get('_sources_path_whitelist'))
                sha_hits  = _all_matches(
                    rdata.get('commit_whitelist', []), [commit_sha],
                    sources=rdata.get('_sources_commit_whitelist'))
                r_hit      = bool(kw_hits or path_hits or sha_hits)
                rule_score = rw if r_hit else 0
                if r_hit:
                    per_rule_total += rw
                profile_trace['rules'][rname] = {
                    'weight':        rw,
                    'matched':       r_hit,
                    'matched_level': 'matched' if r_hit else 'no-match',
                    'score':         rule_score,
                    'matches': {
                        'keywords_whitelist': kw_hits,
                        'path_whitelist':     path_hits,
                        'commit_whitelist':   sha_hits,
                    },
                }
        else:
            for rname, rdata in rules.items():
                rw = int(rdata.get('weight', 50) or 0)
                profile_trace['rules'][rname] = {
                    'weight':        rw,
                    'matched':       False,
                    'matched_level': 'blocked',
                    'score':         0,
                    'matches': {
                        'keywords_whitelist': [],
                        'path_whitelist':     [],
                        'commit_whitelist':   [],
                    },
                }

        # v16.5.0: no cap — raw total goes directly into the multiplier
        final  = int(per_rule_total * pmult)
        profile_trace['raw_rule_total'] = per_rule_total
        profile_trace['final_score']    = final
        scoring_trace['profiles'][pname] = profile_trace
        profile_scores[pname]            = final

        profile_hit = any(profile_trace['merged_matches'].get(k)
                          for k in profile_trace['merged_matches'])
        if profile_hit or final > 0:
            matched_profiles.append(pname)

    combined = sum(profile_scores.values())

    result.update({
        'score':            combined,
        'scoring':          {'profiles': profile_scores, 'trace': scoring_trace},
        'meta':             {k: v for k, v in hints.items() if v is True},
        'matched_profiles': matched_profiles,
        'product_evidence': evidence,
    })
    return result


# -- Commit display helpers ----------------------------------------------------

def fmt_profiles(commit):
    return '; '.join(commit.get('matched_profiles') or [])


def fmt_evidence(commit):
    return '; '.join(commit.get('product_evidence') or [])
