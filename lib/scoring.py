"""Commit scoring helpers for kcommit-analysis-pipeline.

v9.12 changes:
  - _collect_product_evidence() extracted from score_commit().
  - infer_touched_paths() moved to lib/kbuild.py.
  - _load_hints / _load_hints_from_path removed from this module;
    subsystem hints are loaded directly in _collect_product_evidence()
    via lib.kbuild.infer_touched_paths().
  - Legacy fixed scoring categories fully
    removed. Scoring is exclusively driven by user-defined profiles and rules.
"""
import os
import re

from lib.profile_rules import _merged_patterns
from lib.patterns import match as _pat_match, precompile_rules


def order_commit_details(commit):
    """Return commit dict ordered like git log details."""
    commit = dict(commit or {})
    ordered = {}
    first = [
        'commit', 'subject', 'author_name', 'author_email', 'author_time',
        'files', 'stats', 'touched_paths_guess', 'meta', 'product_evidence',
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


# ── Kernel commit annotation regexes ─────────────────────────────────────────
_RE_FIXES  = re.compile(r'^fixes\s*:\s+[0-9a-f]{6,}', re.I | re.MULTILINE)
_RE_CVE    = re.compile(r'CVE-\d{4}-\d{4,}', re.I)
_RE_SYZBOT = re.compile(r'syzbot', re.I)
_RE_STABLE = re.compile(r'cc\s*:.*stable', re.I)   # kept for has_stable_cc metadata only


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


# ── Public helpers ────────────────────────────────────────────────────────────


def _pattern_repr(pat):
    return getattr(pat, 'pattern', pat)



def _first_match(patterns, values):
    """Return first {pattern, value} match across patterns×values, or None."""
    for pat in (patterns or []):
        for val in (values or []):
            if _pat_match(pat, val):
                return {'pattern': _pattern_repr(pat), 'value': val}
    return None


def _all_matches(patterns, values):
    """Return all unique {pattern, value} matches across patterns×values."""
    out, seen = [], set()
    for pat in (patterns or []):
        for val in (values or []):
            if _pat_match(pat, val):
                key = (pat, val)
                if key not in seen:
                    seen.add(key)
                    out.append({'pattern': _pattern_repr(pat), 'value': val})
    return out

# ── Public API ────────────────────────────────────────────────────────────────

def extract_commit_meta(commit):
    """Linux kernel commit annotation flags (informational metadata only).

    These are structural properties defined by Linux kernel commit conventions.
    They do NOT contribute to the score — profiles and rules are the sole
    source of score points.

    Returned keys (all boolean):
      is_fix        -- commit has a Fixes: tag pointing at a prior commit
      has_cve       -- commit references a CVE identifier
      has_syzbot    -- commit references a syzbot bug report
      has_stable_cc -- commit has a Cc: stable trailer (backport candidate)
    """
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
    """Informational product-coverage evidence tags (set by scoring, not prefilter).

    prefilter's build_compiled_sets() serves filtering decisions only.
    This function produces the 'product_evidence' field in scored commit dicts
    for display in reports. Both use product_map but for different purposes.
    """
    # (docstring replaces old one below)
    """Collect informational product-coverage evidence tags for *commit*.

    Purely informational — evidence tags appear in the report but do NOT
    contribute to the score. Scoring is entirely the responsibility of
    profile rules.

    Returns a sorted, deduplicated list of 'type:detail' tag strings.
    """
    commit_files  = set(commit.get('files', []) or [])
    touched       = set(commit.get('touched_paths_guess') or [])
    full_lower    = ((commit.get('subject', '') or '') + '\n' +
                     (commit.get('body', '') or '')).lower()

    c2p           = (product_map or {}).get('config_to_paths', {}) or {}
    enabled_cfgs  = set((product_map or {}).get('enabled_configs', []) or [])
    config_dirs   = list((product_map or {}).get('config_dirs', []) or [])
    build_log_set = set((product_map or {}).get('built_objects_from_log', []) or [])
    artifact_set  = set((product_map or {}).get('built_artifacts_from_dir', []) or [])

    evidence     = []
    matched_syms = set()

    for sym, sym_paths in c2p.items():
        for sp in (sym_paths or []):
            sp_dir = os.path.dirname(sp)
            if any(cf == sp or (sp_dir and cf.startswith(sp_dir + '/'))
                   for cf in commit_files):
                if sym not in matched_syms:
                    evidence.append('config_map:%s' % sym)
                    matched_syms.add(sym)
                break

    for tp in touched:
        for cd in config_dirs:
            if cd.startswith(tp) or tp.startswith(cd.rstrip('/')):
                evidence.append('config_dir:%s' % cd)
                break

    for tp in touched:
        base = os.path.basename(tp.rstrip('/'))
        if not base:
            continue
        for line in build_log_set:
            if base in line:
                evidence.append('build_log:%s' % base)
                break
        for art in artifact_set:
            if base in art:
                evidence.append('artifact:%s' % base)
                break

    for sym in enabled_cfgs:
        if sym.startswith('CONFIG_') and sym[7:].lower() in full_lower:
            evidence.append('config_text:%s' % sym)

    return sorted(set(evidence))


def score_commit(commit, product_map, profile_rules, cfg=None):
    """Score a single commit against all active profiles.

    score = sum of per-profile rule scores ONLY.

    Kernel annotation metadata (CVE, Fixes:, stable cc, syzbot) is extracted
    via extract_commit_meta() and stored in the result for display; it does
    NOT affect the score.

    Product-evidence tags are collected via _collect_product_evidence() and
    stored in the result for display; they do NOT affect the score.

    Path-based filtering is handled upstream by stage 04 (prefilter_commits).

    Returns a shallow copy of *commit* augmented with:
        score            -- combined integer score (profile rules only)
        scoring          -- {'profiles': {name: int}}
        matched_profiles -- profile names that contributed score > 0
        product_evidence -- evidence tags (informational)
        meta             -- kernel annotation flags that are True
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

    # ── First pass: per-profile blacklist exclusions ──────────────────────────
    commit_sha = commit.get('commit', '') or ''
    message_values = [subject, body]
    file_values = sorted(commit_files)
    matched_profiles = []
    profile_scores = {}
    scoring_trace = {'profiles': {}}

    for pname, pdata in (profile_rules or {}).items():
        if not isinstance(pdata, dict):
            continue
        merged = _merged_patterns(pdata)
        rules = (pdata or {}).get('rules', {}) or {}
        pmult = prof_mults.get(pname, 1.0)

        kw_black = _all_matches(merged.get('keywords_blacklist', []), message_values)
        sha_black = _all_matches(merged.get('commit_blacklist', []), [commit_sha])
        path_black = _all_matches(merged.get('path_blacklist', []), file_values)

        blocked = bool(kw_black or sha_black or path_black)
        profile_trace = {
            'multiplier': pmult,
            'merged_matches': {
                'keywords_whitelist': _all_matches(merged.get('keywords_whitelist', []), message_values),
                'keywords_blacklist': kw_black,
                'path_whitelist': _all_matches(merged.get('path_whitelist', []), file_values),
                'path_blacklist': path_black,
                'commit_whitelist': _all_matches(merged.get('commit_whitelist', []), [commit_sha]),
                'commit_blacklist': sha_black,
            },
            'blocked': blocked,
            'block_reason': 'profile_blacklist' if blocked else '',
            'rules': {},
            'raw_rule_total': 0,
            'raw_rule_total_capped': 0,
            'final_score': 0,
        }

        per_rule_total = 0
        if not blocked:
            for rname, rdata in rules.items():
                rw = int(rdata.get('weight', 50) or 0)
                kw_hits = _all_matches(rdata.get('keywords_whitelist', []), message_values)
                path_hits = _all_matches(rdata.get('path_whitelist', []), file_values)
                sha_hits = _all_matches(rdata.get('commit_whitelist', []), [commit_sha])
                r_hit = bool(kw_hits or path_hits or sha_hits)
                rule_score = rw if r_hit else 0
                if r_hit:
                    per_rule_total += rw
                profile_trace['rules'][rname] = {
                    'weight': rw,
                    'matched': r_hit,
                    'matched_level': 'matched' if r_hit else 'no-match',
                    'score': rule_score,
                    'matches': {
                        'keywords_whitelist': kw_hits,
                        'path_whitelist': path_hits,
                        'commit_whitelist': sha_hits,
                    },
                }
        else:
            for rname, rdata in rules.items():
                rw = int(rdata.get('weight', 50) or 0)
                profile_trace['rules'][rname] = {
                    'weight': rw,
                    'matched': False,
                    'matched_level': 'blocked',
                    'score': 0,
                    'matches': {
                        'keywords_whitelist': [],
                        'path_whitelist': [],
                        'commit_whitelist': [],
                    },
                }

        capped = min(per_rule_total, 100)
        final = int(capped * pmult)
        profile_trace['raw_rule_total'] = per_rule_total
        profile_trace['raw_rule_total_capped'] = capped
        profile_trace['final_score'] = final
        scoring_trace['profiles'][pname] = profile_trace
        profile_scores[pname] = final

        profile_hit = any(profile_trace['merged_matches'].get(k) for k in profile_trace['merged_matches'])
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


# ── Commit display helpers ────────────────────────────────────────────────────

def fmt_profiles(commit):
    """Return matched_profiles as a semicolon-separated string."""
    return '; '.join(commit.get('matched_profiles') or [])


def fmt_evidence(commit):
    """Return product_evidence as a semicolon-separated string."""
    return '; '.join(commit.get('product_evidence') or [])



from lib.profile_rules import _merged_patterns
# ── Kernel commit annotation regexes ─────────────────────────────────────────
_RE_FIXES  = re.compile(r'^fixes\s*:\s+[0-9a-f]{6,}', re.I | re.MULTILINE)
_RE_CVE    = re.compile(r'CVE-\d{4}-\d{4,}', re.I)
_RE_SYZBOT = re.compile(r'syzbot', re.I)
_RE_STABLE = re.compile(r'cc\s*:.*stable', re.I)   # kept for has_stable_cc metadata only


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


# ── Public helpers ────────────────────────────────────────────────────────────


def _pattern_repr(pat):
    return getattr(pat, 'pattern', pat)



def _first_match(patterns, values):
    """Return first {pattern, value} match across patterns×values, or None."""
    for pat in (patterns or []):
        for val in (values or []):
            if _pat_match(pat, val):
                return {'pattern': _pattern_repr(pat), 'value': val}
    return None


def _all_matches(patterns, values):
    """Return all unique {pattern, value} matches across patterns×values."""
    out, seen = [], set()
    for pat in (patterns or []):
        for val in (values or []):
            if _pat_match(pat, val):
                key = (pat, val)
                if key not in seen:
                    seen.add(key)
                    out.append({'pattern': _pattern_repr(pat), 'value': val})
    return out

# ── Public API ────────────────────────────────────────────────────────────────

def extract_commit_meta(commit):
    """Linux kernel commit annotation flags (informational metadata only).

    These are structural properties defined by Linux kernel commit conventions.
    They do NOT contribute to the score — profiles and rules are the sole
    source of score points.

    Returned keys (all boolean):
      is_fix        -- commit has a Fixes: tag pointing at a prior commit
      has_cve       -- commit references a CVE identifier
      has_syzbot    -- commit references a syzbot bug report
      has_stable_cc -- commit has a Cc: stable trailer (backport candidate)
    """
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
    """Informational product-coverage evidence tags (set by scoring, not prefilter).

    prefilter's build_compiled_sets() serves filtering decisions only.
    This function produces the 'product_evidence' field in scored commit dicts
    for display in reports. Both use product_map but for different purposes.
    """
    # (docstring replaces old one below)
    """Collect informational product-coverage evidence tags for *commit*.

    Purely informational — evidence tags appear in the report but do NOT
    contribute to the score. Scoring is entirely the responsibility of
    profile rules.

    Returns a sorted, deduplicated list of 'type:detail' tag strings.
    """
    commit_files  = set(commit.get('files', []) or [])
    touched       = set(commit.get('touched_paths_guess') or [])
    full_lower    = ((commit.get('subject', '') or '') + '\n' +
                     (commit.get('body', '') or '')).lower()

    c2p           = (product_map or {}).get('config_to_paths', {}) or {}
    enabled_cfgs  = set((product_map or {}).get('enabled_configs', []) or [])
    config_dirs   = list((product_map or {}).get('config_dirs', []) or [])
    build_log_set = set((product_map or {}).get('built_objects_from_log', []) or [])
    artifact_set  = set((product_map or {}).get('built_artifacts_from_dir', []) or [])

    evidence     = []
    matched_syms = set()

    for sym, sym_paths in c2p.items():
        for sp in (sym_paths or []):
            sp_dir = os.path.dirname(sp)
            if any(cf == sp or (sp_dir and cf.startswith(sp_dir + '/'))
                   for cf in commit_files):
                if sym not in matched_syms:
                    evidence.append('config_map:%s' % sym)
                    matched_syms.add(sym)
                break

    for tp in touched:
        for cd in config_dirs:
            if cd.startswith(tp) or tp.startswith(cd.rstrip('/')):
                evidence.append('config_dir:%s' % cd)
                break

    for tp in touched:
        base = os.path.basename(tp.rstrip('/'))
        if not base:
            continue
        for line in build_log_set:
            if base in line:
                evidence.append('build_log:%s' % base)
                break
        for art in artifact_set:
            if base in art:
                evidence.append('artifact:%s' % base)
                break

    for sym in enabled_cfgs:
        if sym.startswith('CONFIG_') and sym[7:].lower() in full_lower:
            evidence.append('config_text:%s' % sym)

    return sorted(set(evidence))


def score_commit(commit, product_map, profile_rules, cfg=None):
    """Score a single commit against all active profiles.

    score = sum of per-profile rule scores ONLY.

    Kernel annotation metadata (CVE, Fixes:, stable cc, syzbot) is extracted
    via extract_commit_meta() and stored in the result for display; it does
    NOT affect the score.

    Product-evidence tags are collected via _collect_product_evidence() and
    stored in the result for display; they do NOT affect the score.

    Path-based filtering is handled upstream by stage 04 (prefilter_commits).

    Returns a shallow copy of *commit* augmented with:
        score            -- combined integer score (profile rules only)
        scoring          -- {'profiles': {name: int}}
        matched_profiles -- profile names that contributed score > 0
        product_evidence -- evidence tags (informational)
        meta             -- kernel annotation flags that are True
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

    # ── First pass: per-profile blacklist exclusions ──────────────────────────
    commit_sha = commit.get('commit', '') or ''
    message_values = [subject, body]
    file_values = sorted(commit_files)
    matched_profiles = []
    profile_scores = {}
    scoring_trace = {'profiles': {}}

    for pname, pdata in (profile_rules or {}).items():
        if not isinstance(pdata, dict):
            continue
        merged = _merged_patterns(pdata)
        rules = (pdata or {}).get('rules', {}) or {}
        pmult = prof_mults.get(pname, 1.0)

        kw_black = _all_matches(merged.get('keywords_blacklist', []), message_values)
        sha_black = _all_matches(merged.get('commit_blacklist', []), [commit_sha])
        path_black = _all_matches(merged.get('path_blacklist', []), file_values)

        blocked = bool(kw_black or sha_black or path_black)
        profile_trace = {
            'multiplier': pmult,
            'merged_matches': {
                'keywords_whitelist': _all_matches(merged.get('keywords_whitelist', []), message_values),
                'keywords_blacklist': kw_black,
                'path_whitelist': _all_matches(merged.get('path_whitelist', []), file_values),
                'path_blacklist': path_black,
                'commit_whitelist': _all_matches(merged.get('commit_whitelist', []), [commit_sha]),
                'commit_blacklist': sha_black,
            },
            'blocked': blocked,
            'block_reason': 'profile_blacklist' if blocked else '',
            'rules': {},
            'raw_rule_total': 0,
            'raw_rule_total_capped': 0,
            'final_score': 0,
        }

        per_rule_total = 0
        if not blocked:
            for rname, rdata in rules.items():
                rw = int(rdata.get('weight', 50) or 0)
                kw_hits = _all_matches(rdata.get('keywords_whitelist', []), message_values)
                path_hits = _all_matches(rdata.get('path_whitelist', []), file_values)
                sha_hits = _all_matches(rdata.get('commit_whitelist', []), [commit_sha])
                r_hit = bool(kw_hits or path_hits or sha_hits)
                rule_score = rw if r_hit else 0
                if r_hit:
                    per_rule_total += rw
                profile_trace['rules'][rname] = {
                    'weight': rw,
                    'matched': r_hit,
                    'matched_level': 'matched' if r_hit else 'no-match',
                    'score': rule_score,
                    'matches': {
                        'keywords_whitelist': kw_hits,
                        'path_whitelist': path_hits,
                        'commit_whitelist': sha_hits,
                    },
                }
        else:
            for rname, rdata in rules.items():
                rw = int(rdata.get('weight', 50) or 0)
                profile_trace['rules'][rname] = {
                    'weight': rw,
                    'matched': False,
                    'matched_level': 'blocked',
                    'score': 0,
                    'matches': {
                        'keywords_whitelist': [],
                        'path_whitelist': [],
                        'commit_whitelist': [],
                    },
                }

        capped = min(per_rule_total, 100)
        final = int(capped * pmult)
        profile_trace['raw_rule_total'] = per_rule_total
        profile_trace['raw_rule_total_capped'] = capped
        profile_trace['final_score'] = final
        scoring_trace['profiles'][pname] = profile_trace
        profile_scores[pname] = final

        profile_hit = any(profile_trace['merged_matches'].get(k) for k in profile_trace['merged_matches'])
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


# ── Commit display helpers ────────────────────────────────────────────────────

def fmt_profiles(commit):
    """Return matched_profiles as a semicolon-separated string."""
    return '; '.join(commit.get('matched_profiles') or [])


def fmt_evidence(commit):
    """Return product_evidence as a semicolon-separated string."""
    return '; '.join(commit.get('product_evidence') or [])


