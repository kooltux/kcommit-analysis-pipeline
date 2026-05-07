from lib.profile_rules import _merged_patterns
"""Commit scoring helpers for kcommit-analysis-pipeline.

v9.12 changes:
  - extract_stable_hints backward-compat alias removed.
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

from lib.patterns import match as _pat_match, precompile_rules

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
    _profile_blacklisted = set()
    for _pname, _pdata in (profile_rules or {}).items():
        if not isinstance(_pdata, dict):
            continue
        _merged = _merged_patterns(_pdata)
        for _pat in _merged.get('keywords_blacklist', []):
            if _pat_match(_pat, subject):
                _profile_blacklisted.add(_pname)
                break
        if _pname not in _profile_blacklisted:
            for _pat in _merged.get('commit_blacklist', []):
                if _pat_match(_pat, commit.get('commit', '')):
                    _profile_blacklisted.add(_pname)
                    break

    # ── Second pass: profile rule scoring ────────────────────────────────────
    matched_profiles = []
    profile_scores   = {}

    for pname, pdata in (profile_rules or {}).items():
        if not isinstance(pdata, dict):
            continue
        if pname in _profile_blacklisted:
            profile_scores[pname] = 0
            continue
        merged = _merged_patterns(pdata)
        rules  = (pdata or {}).get('rules',  {}) or {}
        pmult  = prof_mults.get(pname, 1.0)

        if any(_pat_match(pat, commit.get('commit', ''))
               for pat in merged.get('commit_blacklist', [])):
            profile_scores[pname] = 0
            continue

        profile_hit = (
            any(_pat_match(pat, commit.get('commit', ''))
                for pat in merged.get('commit_whitelist', []))
            or any(_pat_match(pat, subject) or _pat_match(pat, body)
                   for pat in merged.get('keywords_whitelist', []))
            or any(_pat_match(pat, f)
                   for pat in merged.get('path_whitelist', [])
                   for f in commit_files)
        )

        per_rule_total = 0
        for rdata in rules.values():
            rw    = rdata.get('weight', 50)
            r_hit = (
                any(_pat_match(pat, subject) or _pat_match(pat, body)
                    for pat in rdata.get('keywords_whitelist', []))
                or any(_pat_match(pat, f)
                       for pat in rdata.get('path_whitelist', [])
                       for f in commit_files)
            )
            if r_hit:
                per_rule_total += rw

        per_rule_total = min(per_rule_total, 100)
        final = int(per_rule_total * pmult)
        profile_scores[pname] = final

        if profile_hit or final > 0:
            matched_profiles.append(pname)

    combined = sum(profile_scores.values())

    result.update({
        'score':            combined,
        'scoring':          {'profiles': profile_scores},
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
