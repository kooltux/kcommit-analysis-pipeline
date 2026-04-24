"""Commit scoring helpers for kcommit-analysis-pipeline.

v7.20 scoring model
===================
- Normalized to score_total as the primary ranking metric.
- Profiles contribute to score_total via weighted rule matches.
- Non-profile bonuses (product, stable, etc.) are added to score_total.
- score_profiles and score_bonus provide the breakdown.
"""
import fnmatch
import json
import os
import re

# ── Scoring Constants ────────────────────────────────────────────────────────
# Default multipliers for non-profile bonuses
W_PRODUCT     = 1.0
W_SECURITY    = 1.5
W_PERFORMANCE = 1.0
W_STABLE      = 1.2

# Base points for technical signals
P_SECURITY_HINT    = 40
P_SECURITY_CVE     = 30
P_SECURITY_SYZBOT  = 20
P_PERFORMANCE_HINT = 40
P_STABLE_HINT      = 20
P_STABLE_FIX       = 20
P_STABLE_TRIFECTA  = 30 # CVE + Fixes + Cc:stable

P_PRODUCT_FILE_MATCH   = 20
P_PRODUCT_DIR_MATCH    = 10
P_PRODUCT_LOG_MATCH    = 5
P_PRODUCT_ART_MATCH    = 5
P_PRODUCT_TEXT_MATCH   = 5
P_PRODUCT_MAX          = 100

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
_HINTS_CACHE = {}

def _load_hints(cfg):
    """Load subsystem-keyword -> path-prefix hints from configs/scoring/."""
    global _HINTS_CACHE
    if _HINTS_CACHE:
        return _HINTS_CACHE
    if not cfg:
        return {}
    meta    = cfg.get('_meta', {}) or {}
    vars_   = (meta.get('vars', {}) or {})
    config_dir = meta.get('config_dir', '.')
    
    scoring_dir = cfg.get('inputs', {}).get('scoring_dir')
    if not scoring_dir:
        tooldir = vars_.get('TOOLDIR') or os.path.abspath(os.path.join(config_dir, '..'))
        scoring_dir = os.path.join(tooldir, 'configs', 'scoring')
    
    hints_path = os.path.join(scoring_dir, 'subsystem_path_hints.json')
    if not os.path.exists(hints_path):
        return {}
    try:
        with open(hints_path, 'r', encoding='utf-8') as f:
            _HINTS_CACHE = json.load(f)
            return _HINTS_CACHE
    except Exception:
        return {}


def _get_weights(cfg):
    """Merge default scoring weights with any cfg['scoring'] overrides."""
    w = {
        'product':     W_PRODUCT,
        'security':    W_SECURITY,
        'performance': W_PERFORMANCE,
        'stable':      W_STABLE,
    }
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
    active = cfg.get('profiles', {}).get('active', {})
    if not isinstance(active, dict):
        return {}
    return {name: max(0.0, float(val)) / 100.0 for name, val in active.items()}


# ── Public API ─────────────────────────────────────────────────────────────────

def extract_stable_hints(commit):
    """Extract security/performance/stable indicators from the full commit dict."""
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


def infer_touched_paths(subject, cfg=None):
    """Guess relevant kernel path prefixes from a commit subject."""
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
    """Score a single commit.
    
    Returns a copy of commit augmented with:
        score_total      - aggregate weighted score
        score_profiles   - breakdown by profile
        score_bonus      - breakdown by technical signal (product, stable, etc)
        evidence         - structured machine-readable hints
        matched_profiles - list of profiles that hit
    """
    weights    = _get_weights(cfg)
    prof_mults = _profile_multipliers(cfg)
    result     = dict(commit)
    evidence   = []

    subject = commit.get('subject', '') or ''
    body    = commit.get('body',    '') or ''
    full    = (subject + '\n' + body).lower()
    files   = set(commit.get('files', []) or [])

    # ── 0. Global filter ──────────────────────────────────────────────────────
    for pname, pdata in (profile_rules or {}).items():
        merged = (pdata or {}).get('merged', {}) or {}
        for pat in merged.get('keywords_blacklist', []):
            if _match(pat, subject):
                result.update({
                    'score_total': 0.0,
                    'score_profiles': {},
                    'score_bonus': {},
                    'evidence': [],
                    'matched_profiles': [],
                    'filtered': True
                })
                return result

    # ── 1. Technical Signals (Bonuses) ────────────────────────────────────────
    hints = commit.get('stable_hints') or extract_stable_hints(commit)
    
    b_sec = 0.0
    if hints.get('is_security'):   b_sec += P_SECURITY_HINT
    if hints.get('has_cve'):        b_sec += P_SECURITY_CVE
    if hints.get('has_syzbot'):     b_sec += P_SECURITY_SYZBOT
    
    b_perf = 0.0
    if hints.get('is_performance'): b_perf += P_PERFORMANCE_HINT
    
    b_stable = 0.0
    if hints.get('is_stable'):      b_stable += P_STABLE_HINT
    if hints.get('is_fix'):         b_stable += P_STABLE_FIX
    if hints.get('has_cve') and hints.get('is_fix') and hints.get('has_stable_cc'):
        b_stable += P_STABLE_TRIFECTA

    # ── 2. Product Evidence ───────────────────────────────────────────────────
    b_prod = 0.0
    pm = product_map or {}
    c2p = pm.get('config_to_paths', {}) or {}
    
    # actual changed files present in config_to_paths
    matched_syms = set()
    for sym, sym_paths in c2p.items():
        for sp in (sym_paths or []):
            sp_dir = os.path.dirname(sp)
            if any(cf == sp or (sp_dir and cf.startswith(sp_dir + '/')) for cf in files):
                if sym not in matched_syms:
                    b_prod += P_PRODUCT_FILE_MATCH
                    evidence.append({'type': 'config_map', 'symbol': sym})
                    matched_syms.add(sym)
                break
    
    # touched path guesses
    touched = set(commit.get('touched_paths_guess', []) or [])
    config_dirs = pm.get('config_dirs', []) or []
    for tp in touched:
        for cd in config_dirs:
            if cd.startswith(tp) or tp.startswith(cd.rstrip('/')):
                b_prod += P_PRODUCT_DIR_MATCH
                evidence.append({'type': 'config_dir', 'path': cd})
                break
    
    # Basename matches in build log / artifacts
    log_objs = set(pm.get('built_objects_from_log', []) or [])
    art_objs = set(pm.get('built_artifacts_from_dir', []) or [])
    for tp in touched:
        base = os.path.basename(tp.rstrip('/'))
        if not base: continue
        if base in log_objs:
            b_prod += P_PRODUCT_LOG_MATCH
            evidence.append({'type': 'build_log', 'basename': base})
        if base in art_objs:
            b_prod += P_PRODUCT_ART_MATCH
            evidence.append({'type': 'artifact', 'basename': base})
            
    # Mentioned symbols
    enabled = set(pm.get('enabled_configs', []) or [])
    for sym in enabled:
        if sym.startswith('CONFIG_') and sym[7:].lower() in full:
            b_prod += P_PRODUCT_TEXT_MATCH
            evidence.append({'type': 'config_text', 'symbol': sym})

    b_prod = min(b_prod, P_PRODUCT_MAX)
    
    score_bonus = {
        'product':     round(b_prod * weights['product'], 1),
        'security':    round(b_sec * weights['security'], 1),
        'performance': round(b_perf * weights['performance'], 1),
        'stable':      round(b_stable * weights['stable'], 1),
    }

    # ── 3. Profile Scoring ────────────────────────────────────────────────────
    score_profiles = {}
    matched_profiles = []
    
    for pname, pdata in (profile_rules or {}).items():
        pmult  = prof_mults.get(pname, 1.0)
        merged = (pdata or {}).get('merged', {}) or {}
        rules  = (pdata or {}).get('rules', {}) or {}
        
        # Profile-level blacklist
        if any(_match(pat, commit.get('commit', '')) for pat in merged.get('commit_blacklist', [])):
            continue
            
        # Per-rule evaluation
        p_total = 0.0
        for rname, rdata in rules.items():
            r_hit = (
                any(_match(pat, subject) or _match(pat, body) for pat in rdata.get('keywords_whitelist', []))
                or any(_match(pat, f) for pat in rdata.get('path_whitelist', []) for f in files)
            )
            if r_hit:
                p_total += rdata.get('weight', 50)
        
        p_total = min(p_total, 100.0)
        contribution = round(p_total * pmult, 1)
        if contribution > 0:
            score_profiles[pname] = contribution
            matched_profiles.append(pname)

    # ── 4. Final Aggregation ──────────────────────────────────────────────────
    score_total = sum(score_profiles.values()) + sum(score_bonus.values())
    
    result.update({
        'score_total':      round(score_total, 1),
        'score_profiles':   score_profiles,
        'score_bonus':      score_bonus,
        'evidence':         evidence,
        'matched_profiles': sorted(matched_profiles),
    })
    
    # Maintain legacy 'score' for basic compatibility if needed, but primary is score_total
    result['score'] = int(score_total)
    
    return result
