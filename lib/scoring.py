# v8.6: scoring exclusively through profiles/rules.
# security/stable/product hints are metadata only — they do NOT add to score.

"""Commit scoring helpers for kcommit-analysis-pipeline.

v8.6 changes vs v8.5.1:
  - SCORING IS EXCLUSIVELY THROUGH PROFILES AND RULES.
    security_score, performance_score, stable_score and product_score no
    longer contribute to the combined score.  They are computed as metadata
    (stored under commit['scoring']['meta']) and surfaced in the HTML report
    for information only.
  - _DEFAULT_WEIGHTS and _get_weights() removed: they controlled the four
    direct-score dimensions that no longer exist.  The 'scoring' config
    section is now reserved for future non-profile extensions.
  - symbol_match weight removed from scoring (was applied to product evidence
    score which is now metadata-only).
  - score_commit() combined score = sum of per-profile rule scores only.
  - Path-based filtering delegated upstream to stage 04 (filter_commits).
    score_commit() no longer needs to replicate blacklist logic.
  - extract_stable_hints() and infer_touched_paths() unchanged (still used
    by stage 04 for enrichment and by the HTML report for badges).

v8.4.1 fix (preserved):
  - precompile_rules(): plain set of id() values instead of weakref.WeakSet()
    (Python 3.13 refuses weak references to plain dict objects).
"""
import fnmatch
import functools
import os
import re

from lib.config import _load_json as _load_json_commented

# ── Stable/fix/CVE trailer patterns ───────────────────────────────────────────
_RE_STABLE  = re.compile(r'cc\s*:.*stable', re.I)
_RE_FIXES   = re.compile(r'^fixes\s*:\s+[0-9a-f]{6,}', re.I | re.MULTILINE)
_RE_CVE     = re.compile(r'CVE-\d{4}-\d{4,}', re.I)
_RE_SYZBOT  = re.compile(r'syzbot', re.I)




# ── Pattern matching ───────────────────────────────────────────────────────────

def _match(pattern, text):
    """Match *pattern* against *text*.

    Modes:
      re:<expr>   – compiled regex search (case-insensitive)
      glob        – fnmatch (*, ?, [...])
      plain       – case-insensitive substring
    """
    if isinstance(pattern, re.Pattern):
        return bool(pattern.search(text))
    if pattern.startswith('re:'):
        try:
            return bool(re.search(pattern[3:], text, re.I))
        except re.error:
            return False
    if any(c in pattern for c in ('*', '?', '[')):
        return fnmatch.fnmatch(text, pattern)
    return pattern.lower() in text.lower()


# ── Rule pre-compilation ───────────────────────────────────────────────────────

_PRECOMPILED_IDS: set = set()


def precompile_rules(profile_rules):
    """Compile all pattern strings in *profile_rules* to re.Pattern objects.

    Idempotent: repeated calls on the same dict object are cheap (id check).
    Uses a plain set of id() values; weakref not used (Python 3.13 compat).
    """
    if id(profile_rules) in _PRECOMPILED_IDS:
        return
    _PRECOMPILED_IDS.add(id(profile_rules))
    for pdata in (profile_rules or {}).values():
        merged = (pdata or {}).get('merged', {}) or {}
        for key in ('keywords_whitelist', 'keywords_blacklist',
                    'path_whitelist', 'path_blacklist',
                    'commit_whitelist', 'commit_blacklist'):
            merged[key] = [_compile_pat(p) for p in merged.get(key, [])]
        for rdata in (pdata.get('rules', {}) or {}).values():
            for key in ('keywords_whitelist', 'path_whitelist'):
                rdata[key] = [_compile_pat(p) for p in rdata.get(key, [])]


def _compile_pat(pattern):
    if isinstance(pattern, re.Pattern):
        return pattern
    if pattern.startswith('re:'):
        try:
            return re.compile(pattern[3:], re.I)
        except re.error:
            return pattern
    return pattern


# ── Hints / path helpers ───────────────────────────────────────────────────────

@functools.lru_cache(maxsize=8)
def _load_hints_from_path(hints_path):
    try:
        return _load_json_commented(hints_path) or {}
    except Exception:
        return {}


def _load_hints(cfg):
    if not cfg:
        return {}
    meta    = cfg.get('_meta', {}) or {}
    vars_   = meta.get('vars', {}) or {}
    tooldir = (vars_.get('TOOLDIR')
               or os.environ.get('TOOLDIR')
               or os.path.abspath(os.path.join(meta.get('config_dir', '.'), '..')))
    hints_path = os.path.join(tooldir, 'configs', 'scoring', 'subsystem_path_hints.json')
    if not os.path.exists(hints_path):
        return {}
    return _load_hints_from_path(os.path.abspath(hints_path))


def _profile_multipliers(cfg):
    """Return {profile_name: float multiplier} from profiles.active config."""
    if not cfg:
        return {}
    active = ((cfg.get('profiles', {}) or {}).get('active')
              or cfg.get('active_profiles') or {})
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


# ── Public API ─────────────────────────────────────────────────────────────────

def extract_commit_meta(commit):
    """Linux kernel commit annotation flags (informational metadata only).

    Structural/format-level properties defined by Linux kernel commit
    conventions.  Do NOT contribute to scoring -- profiles and rules are
    the sole source of score points.

    Returned keys (all boolean):
      is_fix        -- commit has a Fixes: tag pointing at a prior commit
      has_cve       -- commit references a CVE identifier
      has_syzbot    -- commit references a syzbot bug report
      has_stable_cc -- commit has a Cc: stable trailer (backport candidate)

    Analysis categories (security, performance ...) are intentionally
    absent: those are the responsibility of profiles and rules.
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


# Backward-compatibility alias -- existing callers continue to work
extract_stable_hints = extract_commit_meta


def infer_touched_paths(subject, cfg=None):
    """Guess relevant kernel path prefixes from a commit subject.

    Uses subsystem_path_hints.json from the scoring directory.
    """
    hints  = _load_hints(cfg)
    low    = (subject or '').lower()
    result = []
    for keyword, paths in hints.items():
        if keyword.lower() in low:
            result.extend(paths if isinstance(paths, list) else [str(paths)])
    return sorted(set(result))


def score_commit(commit, product_map, profile_rules, cfg=None):
    """Score a single commit.

    v8.6: score = sum of per-profile rule scores ONLY.

    security_score, performance_score, stable_score and product_score are
    computed and stored in commit['scoring']['meta'] for reporting/display
    purposes but DO NOT add to the combined score.

    Path-based filtering (blacklisted paths / no product-map coverage) is
    handled upstream by stage 04 (filter_commits); score_commit() does not
    need to replicate it.

    Returns a shallow copy of *commit* augmented with:
        score            – combined integer score (profile rules only)
        scoring          – {profiles: {name: int}, meta: {…}}
        matched_profiles – list of profile names that contributed score > 0
        product_evidence – list of evidence tags (informational)
    """
    prof_mults   = _profile_multipliers(cfg)
    result       = dict(commit)
    evidence     = []

    subject      = commit.get('subject', '') or ''
    body         = commit.get('body',    '') or ''
    full_lower   = (subject + '\n' + body).lower()
    commit_files = set(commit.get('files', []) or [])

    # ── Metadata hints (informational only, not scored) ────────────────────────
    hints = (commit.get('meta')
             or commit.get('stable_hints')
             or extract_commit_meta(commit))

    # ── Product evidence collection (informational only, not scored) ───────────
    c2p           = (product_map or {}).get('config_to_paths', {}) or {}
    touched       = set(commit.get('touched_paths_guess') or [])
    enabled_cfgs  = set((product_map or {}).get('enabled_configs', []) or [])
    config_dirs   = list((product_map or {}).get('config_dirs', []) or [])
    build_log_set = set((product_map or {}).get('built_objects_from_log', []) or [])
    artifact_set  = set((product_map or {}).get('built_artifacts_from_dir', []) or [])

    matched_syms = set()
    for sym, sym_paths in c2p.items():
        for sp in (sym_paths or []):
            sp_dir = os.path.dirname(sp)
            if any(cf == sp or (sp_dir and cf.startswith(sp_dir + '/'))
                   for cf in commit_files):
                if sym not in matched_syms:
                    evidence.append(f'config_map:{sym}')
                    matched_syms.add(sym)
                break
    for tp in touched:
        for cd in config_dirs:
            if cd.startswith(tp) or tp.startswith(cd.rstrip('/')):
                evidence.append(f'config_dir:{cd}')
                break
    for tp in touched:
        base = os.path.basename(tp.rstrip('/'))
        if not base:
            continue
        for line in build_log_set:
            if base in line:
                evidence.append(f'build_log:{base}')
                break
        for art in artifact_set:
            if base in art:
                evidence.append(f'artifact:{base}')
                break
    for sym in enabled_cfgs:
        if sym.startswith('CONFIG_') and sym[7:].lower() in full_lower:
            evidence.append(f'config_text:{sym}')
    evidence = sorted(set(evidence))

    # ── Profile rule scoring — SOLE source of score points ────────────────────
    # First pass: build per-profile blacklist exclusion set.
    _profile_blacklisted = set()
    for _pname, _pdata in (profile_rules or {}).items():
        _merged = (_pdata or {}).get('merged', {}) or {}
        for _pat in _merged.get('keywords_blacklist', []):
            if _match(_pat, subject):
                _profile_blacklisted.add(_pname)
                break
        if _pname not in _profile_blacklisted:
            for _pat in _merged.get('commit_blacklist', []):
                if _match(_pat, commit.get('commit', '')):
                    _profile_blacklisted.add(_pname)
                    break

    matched_profiles = []
    profile_scores   = {}

    for pname, pdata in (profile_rules or {}).items():
        if pname in _profile_blacklisted:
            profile_scores[pname] = 0
            continue
        merged = (pdata or {}).get('merged', {}) or {}
        rules  = (pdata or {}).get('rules',  {}) or {}
        pmult  = prof_mults.get(pname, 1.0)

        if any(_match(pat, commit.get('commit', ''))
               for pat in merged.get('commit_blacklist', [])):
            profile_scores[pname] = 0
            continue

        # Profile-level whitelist hit (used to flag 'matched' status)
        profile_hit = (
            any(_match(pat, commit.get('commit', ''))
                for pat in merged.get('commit_whitelist', []))
            or any(_match(pat, subject) or _match(pat, body)
                   for pat in merged.get('keywords_whitelist', []))
            or any(_match(pat, f)
                   for pat in merged.get('path_whitelist', [])
                   for f in commit_files)
        )

        # Rule scoring: sum rule weights for all matching rules, cap at 100
        per_rule_total = 0
        for rdata in rules.values():
            rw    = rdata.get('weight', 50)
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

        if profile_hit or final > 0:
            matched_profiles.append(pname)

    # ── Combined score: profile contributions ONLY ─────────────────────────────
    combined = sum(profile_scores.values())

    result.update({
        'score':            combined,
        'scoring': {
            'profiles': profile_scores,
        },
        # Kernel annotation flags at top-level commit['meta']
        # for direct access in CSV/HTML without traversing scoring{}.
        'meta': {k: v for k, v in hints.items() if v is True},
        'matched_profiles': matched_profiles,
        'product_evidence': evidence,
    })
    return result
