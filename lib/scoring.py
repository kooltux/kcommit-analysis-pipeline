"""Commit scoring helpers for kcommit-analysis-pipeline.

v7.17 changes vs v7.13:
  - extract_patch_features(subject) renamed to extract_stable_hints(commit).
    The new function reads the full commit dict (subject + body) to detect
    Fixes:/Cc:stable/CVE trailers, and the old name is kept as a compat alias.
  - infer_touched_paths(subject, cfg=None): new cfg parameter loads
    subsystem->path hints from configs/scoring/subsystem_path_hints.json
    (resolved via TOOLDIR) instead of using a hardcoded inline table.
  - score_commit(commit, product_map, profile_rules, cfg=None):
      * cfg used to read scoring weight multipliers from cfg['scoring'].
      * cfg['profiles']['active'] dict form used for per-profile multipliers.
      * Message blacklist pre-filter: skip expensive scoring early.
      * Real commit files intersected with config_to_paths for strong evidence.
      * Triple-threat stable bonus: CVE + Fixes: + Cc:stable -> +30 pts.
      * Output shape: 'score' (int) + 'scoring' sub-dict replaces the old flat
        candidate_score / security_score / performance_score / stable_score.
"""
from __future__ import print_function
import fnmatch
import json
import os
import re

# ── Default scoring weight multipliers ────────────────────────────────────────
_DEFAULT_WEIGHTS = {
    'product':     1.0,
    'security':    1.5,
    'performance': 1.0,
    'stable':      1.2,
}

# ── Keyword sets ───────────────────────────────────────────────────────────────
_SECURITY_KEYWORDS = {
    'cve', 'vulnerability', 'exploit', 'overflow', 'uaf', 'use-after-free',
    'oob', 'out-of-bounds', 'privilege escalation', 'sandbox', 'seccomp',
    'smack', 'selinux', 'apparmor', 'tomoyo', 'capabilities',
    'hardening', 'mitigation', 'attack', 'injection', 'bypass', 'disclosure',
    'crypto', 'encryption', 'authentication', 'authorization', 'race condition',
    'double free', 'heap spray', 'stack overflow', 'integer overflow',
}

_PERFORMANCE_KEYWORDS = {
    'performance', 'latency', 'throughput', 'bandwidth', 'optimize',
    'optimization', 'speedup', 'bottleneck', 'cache', 'preempt',
    'scheduler', 'cpufreq', 'power management', 'sleep', 'idle',
    'lock contention', 'spinlock', 'rcu', 'hugepage', 'numa',
    'jitter', 'overhead', 'profiling', 'benchmark', 'regression',
    'faster', 'slow', 'cpu usage', 'memory pressure',
}

# ── Stable/fix trailer patterns ───────────────────────────────────────────────
_RE_STABLE  = re.compile(r'cc\s*:.*stable', re.I)
_RE_FIXES   = re.compile(r'^fixes\s*:\s+[0-9a-f]{6,}', re.I | re.MULTILINE)
_RE_CVE     = re.compile(r'CVE-\d{4}-\d{4,}', re.I)
_RE_SYZBOT  = re.compile(r'syzbot', re.I)


# ── Pattern matching ───────────────────────────────────────────────────────────

def _match(pattern, text):
    """Match a pattern against text; supports 're:', globs, and substrings."""
    if pattern.startswith('re:'):
        try:
            return bool(re.search(pattern[3:], text, re.I))
        except re.error:
            return False
    if any(c in pattern for c in ('*', '?', '[')):
        return fnmatch.fnmatch(text, pattern)
    return pattern.lower() in text.lower()


# ── Config-hint loading ────────────────────────────────────────────────────────

def _load_hints(cfg):
    """Load subsystem-keyword -> path-prefix hints from configs/scoring/."""
    if not cfg:
        return {}
    meta    = cfg.get('_meta', {}) or {}
    vars_   = (meta.get('vars', {}) or {})
    tooldir = (vars_.get('TOOLDIR')
               or os.environ.get('TOOLDIR')
               or os.path.abspath(os.path.join(meta.get('config_dir', '.'), '..')))
    hints_path = os.path.join(tooldir, 'configs', 'scoring', 'subsystem_path_hints.json')
    if not os.path.exists(hints_path):
        return {}
    try:
        with open(hints_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _get_weights(cfg):
    """Merge default scoring weights with any cfg['scoring'] overrides."""
    w = dict(_DEFAULT_WEIGHTS)
    if cfg:
        for k, v in (cfg.get('scoring', {}) or {}).items():
            if k in w:
                try:
                    w[k] = float(v)
                except (TypeError, ValueError):
                    pass
    return w


def _profile_multipliers(cfg):
    """Return per-profile weight multipliers from cfg['profiles']['active'] dict."""
    if not cfg:
        return {}
    active = ((cfg.get('profiles', {}) or {}).get('active')
              or cfg.get('active_profiles') or {})
    if not isinstance(active, dict):
        return {}
    out = {}
    for name, val in active.items():
        try:
            out[name] = max(0.0, float(val)) / 100.0
        except (TypeError, ValueError):
            out[name] = 1.0
    return out


# ── Public API ─────────────────────────────────────────────────────────────────

def extract_stable_hints(commit):
    """Extract security/performance/stable indicators from the full commit dict.

    Returns a dict with boolean flags:
        is_stable, is_fix, has_cve, has_syzbot, is_security, is_performance
    """
    subject = commit.get('subject', '') or ''
    body    = commit.get('body',    '') or ''
    full    = subject + '\n' + body

    is_fix    = bool(_RE_FIXES.search(full))
    has_cve   = bool(_RE_CVE.search(full))
    has_syzbot = bool(_RE_SYZBOT.search(full))
    has_stable = bool(_RE_STABLE.search(full))
    is_stable  = is_fix or has_cve or has_syzbot or has_stable

    low = full.lower()
    is_security    = any(k in low for k in _SECURITY_KEYWORDS)
    is_performance = any(k in low for k in _PERFORMANCE_KEYWORDS)

    return {
        'is_stable':      is_stable,
        'is_fix':         is_fix,
        'has_cve':        has_cve,
        'has_syzbot':     has_syzbot,
        'has_stable_cc':  has_stable,
        'is_security':    is_security,
        'is_performance': is_performance,
    }


def extract_patch_features(subject):
    """Backward-compatibility alias; prefer extract_stable_hints(commit)."""
    return extract_stable_hints({'subject': subject})


def infer_touched_paths(subject, cfg=None):
    """Guess relevant kernel path prefixes from a commit subject.

    Loads keyword->path mappings from configs/scoring/subsystem_path_hints.json
    (resolved via TOOLDIR in cfg) instead of using a hardcoded inline table.
    Falls back to an empty list when the hints file cannot be loaded.
    """
    hints  = _load_hints(cfg)
    low    = (subject or '').lower()
    result = []
    for keyword, paths in hints.items():
        if keyword.lower() in low:
            if isinstance(paths, list):
                result.extend(paths)
            else:
                result.append(str(paths))
    return sorted(set(result))


def score_commit(commit, product_map, profile_rules, cfg=None):
    """Score a single commit for product/security/performance/stable relevance.

    Returns a shallow copy of *commit* augmented with:
        score            – combined weighted integer score
        scoring          – dict: product, security, performance, stable, profiles
        matched_profiles – list of profile names that matched
        product_evidence – list of evidence tags ('config_map:CONFIG_FOO', ...)
    """
    weights     = _get_weights(cfg)
    prof_mults  = _profile_multipliers(cfg)
    result      = dict(commit)
    evidence    = []

    subject = commit.get('subject', '') or ''
    body    = commit.get('body',    '') or ''
    full    = (subject + '\n' + body).lower()

    # ── 0. Early message blacklist pre-filter ─────────────────────────────────
    for pdata in (profile_rules or {}).values():
        merged = (pdata or {}).get('merged', {}) or {}
        for pat in merged.get('keywords_blacklist', []):
            if _match(pat, subject):
                result.update({
                    'score':            0,
                    'scoring':          {'product': 0, 'security': 0,
                                         'performance': 0, 'stable': 0,
                                         'profiles': {}},
                    'matched_profiles': [],
                    'product_evidence': [],
                    'filtered_by_blacklist': True,
                })
                return result

    # ── 1. Stable / security / performance hints ───────────────────────────────
    hints = commit.get('stable_hints') or extract_stable_hints(commit)

    security_score    = 0
    performance_score = 0
    stable_score      = 0

    if hints.get('is_security'):
        security_score += 40
    if hints.get('has_cve'):
        security_score += 30
    if hints.get('has_syzbot'):
        security_score += 20
    if hints.get('is_performance'):
        performance_score += 40

    if hints.get('is_stable'):
        stable_score += 20
    if hints.get('is_fix'):
        stable_score += 20
    # Triple-threat bonus: CVE + Fixes: trailer + Cc: stable → extra confidence
    if hints.get('has_cve') and hints.get('is_fix') and hints.get('has_stable_cc'):
        stable_score += 30

    # ── 2. Product score ───────────────────────────────────────────────────────
    product_score = 0
    c2p           = (product_map or {}).get('config_to_paths', {}) or {}
    commit_files  = set(commit.get('files', []) or [])
    config_dirs   = list((product_map or {}).get('config_dirs', []) or [])
    touched       = set(commit.get('touched_paths_guess', []) or [])
    enabled_cfgs  = set((product_map or {}).get('enabled_configs', []) or [])
    build_log_set = set((product_map or {}).get('built_objects_from_log', []) or [])
    artifact_set  = set((product_map or {}).get('built_artifacts_from_dir', []) or [])

    # Strong evidence: actual changed files present in config_to_paths mapping
    matched_syms = set()
    for sym, sym_paths in c2p.items():
        for sp in (sym_paths or []):
            sp_dir = os.path.dirname(sp)
            if any(cf == sp or (sp_dir and cf.startswith(sp_dir + '/'))
                   for cf in commit_files):
                if sym not in matched_syms:
                    product_score += 20
                    evidence.append('config_map:%s' % sym)
                    matched_syms.add(sym)
                break

    # Medium evidence: touched path guesses vs config_dirs
    for tp in touched:
        for cd in config_dirs:
            if cd.startswith(tp) or tp.startswith(cd.rstrip('/')):
                product_score += 10
                evidence.append('config_dir:%s' % cd)
                break

    # Weaker evidence: build log / artifact basename matches
    for tp in touched:
        base = os.path.basename(tp.rstrip('/'))
        if not base:
            continue
        for line in build_log_set:
            if base in line:
                product_score += 5
                evidence.append('build_log:%s' % base)
                break
        for art in artifact_set:
            if base in art:
                product_score += 5
                evidence.append('artifact:%s' % base)
                break

    # Config symbol mentioned in commit text
    for sym in enabled_cfgs:
        if sym.startswith('CONFIG_') and sym[7:].lower() in full:
            product_score += 5
            evidence.append('config_text:%s' % sym)

    product_score = min(product_score, 100)
    evidence = sorted(set(evidence))

    # ── 3. Profile rule scoring ────────────────────────────────────────────────
    matched_profiles = []
    profile_scores   = {}

    for pname, pdata in (profile_rules or {}).items():
        merged = (pdata or {}).get('merged', {}) or {}
        rules  = (pdata or {}).get('rules',  {}) or {}
        pmult  = prof_mults.get(pname, 1.0)

        # Commit-level blacklist check for this profile
        if any(_match(pat, commit.get('commit', ''))
               for pat in merged.get('commit_blacklist', [])):
            profile_scores[pname] = 0
            continue

        # Commit-level whitelist or keyword/path hits determine 'matched'
        hit = (
            any(_match(pat, commit.get('commit', ''))
                for pat in merged.get('commit_whitelist', []))
            or any(_match(pat, subject) or _match(pat, body)
                   for pat in merged.get('keywords_whitelist', []))
            or any(_match(pat, f)
                   for pat in merged.get('path_whitelist', [])
                   for f in commit_files)
        )

        # Per-rule weighted contribution
        per_rule_total = 0
        for rdata in rules.values():
            rw = rdata.get('weight', 50)
            r_hit = (
                any(_match(pat, subject) or _match(pat, body)
                    for pat in rdata.get('keywords_whitelist', []))
                or any(_match(pat, f)
                       for pat in rdata.get('path_whitelist', [])
                       for f in commit_files)
            )
            if r_hit:
                per_rule_total += rw

        per_rule_total = min(per_rule_total, 100)
        final = int(per_rule_total * pmult)
        profile_scores[pname] = final

        if hit or final > 0:
            matched_profiles.append(pname)

    # ── 4. Combined score ──────────────────────────────────────────────────────
    w = weights
    combined = int(
        product_score     * w['product']     +
        security_score    * w['security']    +
        performance_score * w['performance'] +
        stable_score      * w['stable']
    ) + sum(profile_scores.values())

    result.update({
        'score': combined,
        'scoring': {
            'product':     product_score,
            'security':    security_score,
            'performance': performance_score,
            'stable':      stable_score,
            'profiles':    profile_scores,
        },
        'matched_profiles': matched_profiles,
        'product_evidence': evidence,
    })
    return result
