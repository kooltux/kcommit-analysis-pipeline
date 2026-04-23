# Shared commit scoring helpers used by top-level pipeline stages.
from __future__ import print_function

from lib import rules as _rules


def infer_touched_paths(subject):
    """Infer coarse subsystem paths from commit text.

    This is a best-effort textual guess used to relate commits to
    product-specific evidence (build logs, artifacts, and config dirs).
    """
    s = (subject or '').lower()
    paths = []
    mapping = [
        ('can', 'drivers/net/can/'),
        ('ethernet', 'drivers/net/ethernet/'),
        ('wifi', 'drivers/net/wireless/'),
        ('wireless', 'net/wireless/'),
        ('bluetooth', 'net/bluetooth/'),
        ('mmc', 'drivers/mmc/'),
        ('ext4', 'fs/ext4/'),
        ('crypto', 'crypto/'),
        ('security', 'security/'),
        ('watchdog', 'drivers/watchdog/'),
        ('thermal', 'drivers/thermal/'),
        ('usb', 'drivers/usb/'),
        ('pci', 'drivers/pci/'),
        ('tty', 'drivers/tty/'),
        ('serial', 'drivers/tty/serial/'),
        ('net', 'net/'),
    ]
    for token, path in mapping:
        if token in s:
            paths.append(path)
    return sorted(set(paths))


def extract_patch_features(subject):
    """Extract simple security/performance/stable hints from commit text."""
    subj = (subject or '').lower()
    return {
        'security_terms': int(any(k in subj for k in ['cve', 'overflow', 'uaf', 'use-after-free', 'oob', 'security', 'race', 'refcount'])),
        'performance_terms': int(any(k in subj for k in ['performance', 'latency', 'throughput', 'regression', 'slow', 'faster', 'optimize'])),
        'stable_terms': int(any(k in subj for k in ['stable', 'fixes'])),
    }


def _compute_profile_rule_scores(commit, profile_rules):
    """Compute per-profile numeric rule scores and matched profile list.

    profile_rules is the compiled structure from lib.profile_rules:

        {
          'profile_name': {
              'merged': { ... },
              'rules': {
                  'rule_name': { 'weight': int, ...patterns... },
                  ...
              }
          },
          ...
        }

    Returns (matched_profiles, profile_scores) where profile_scores maps
    profile name to an aggregate numeric score in roughly [-100, 100].
    """
    if not profile_rules:
        return [], {}

    scores = {}
    matched = []

    for pname, pdata in profile_rules.items():
        rules = pdata.get('rules', {}) or {}
        total = 0.0
        for rname, rdata in rules.items():
            weight = float(rdata.get('weight', 0))
            if weight <= 0:
                continue
            base = float(_rules.evaluate_rule(commit, rdata))
            if base == 0.0:
                continue
            total += (weight / 100.0) * base
        scores[pname] = total

    # Simple threshold to decide which profiles consider this commit a candidate.
    for pname, val in scores.items():
        if val >= 40.0:
            matched.append(pname)

    return matched, scores


def _security_and_performance_from_profiles(commit, profile_rules):
    """Derive security and performance rule scores from per-profile data."""
    matched_profiles, profile_scores = _compute_profile_rule_scores(commit, profile_rules)

    # Security-oriented profiles: names containing "security".
    sec_profiles = [
        name for name in profile_scores.keys()
        if 'security' in name
    ]
    # Performance-oriented profiles: names containing "performance".
    perf_profiles = [
        name for name in profile_scores.keys()
        if 'performance' in name
    ]

    sec_raw = max((profile_scores[p] for p in sec_profiles), default=0.0)
    perf_raw = max((profile_scores[p] for p in perf_profiles), default=0.0)

    # Map raw rule scores in [-100, 100] to [0, 50]. Negative scores do not
    # explicitly penalize the security/performance score; they simply clamp to 0.
    def _scale(raw):
        return max(0.0, min(50.0, raw / 2.0))

    return matched_profiles, _scale(sec_raw), _scale(perf_raw)


def score_commit(commit, product_map, profile_rules):
    """Score a single commit for product, security, and performance relevance.

    The score combines:
    - textual path guesses from the subject,
    - build evidence from logs and optional build_dir scanning,
    - Kbuild-derived config_dirs and config_to_paths from product_map,
    - simple keyword-based patch features,
    - and per-profile, weighted rule matches.
    """
    # Global commit-level whitelist/blacklist across all profiles.
    merged_whitelist = set()
    merged_blacklist = set()
    for pdata in (profile_rules or {}).values():
        merged = pdata.get('merged', {}) or {}
        merged_whitelist.update(merged.get('commit_whitelist', []) or [])
        merged_blacklist.update(merged.get('commit_blacklist', []) or [])

    sha = commit.get('commit', '')
    forced_keep = sha in merged_whitelist
    forced_drop = (sha in merged_blacklist) and not forced_keep

    # Product scoring based on guessed paths and product_map evidence.
    guesses = commit.get('touched_paths_guess', []) or []
    built_log = '\n'.join(product_map.get('built_objects_from_log', []))
    built_dir = '\n'.join(product_map.get('built_artifacts_from_dir', []))
    enabled_cfg = '\n'.join(product_map.get('enabled_configs', []))
    config_dirs = '\n'.join(product_map.get('config_dirs', []))
    cfg_map = product_map.get('config_to_paths', {}) or {}

    product = 0
    evidence = []
    for guess in guesses:
        token = guess.strip('/').split('/')[-1]
        if token and token in built_log:
            product += 20
            evidence.append('build_log:%s' % guess)
        if token and token in built_dir:
            product += 20
            evidence.append('build_dir:%s' % guess)
        if token and token.upper() in enabled_cfg:
            product += 10
            evidence.append('config:%s' % token)
        if guess and guess in config_dirs:
            product += 15
            evidence.append('config_map_dir:%s' % guess)

    files = commit.get('files', []) or []
    config_hits = set()
    for sym, paths in (cfg_map or {}).items():
        for pth in paths:
            if pth in files:
                config_hits.add(sym)
                break
    for sym in sorted(config_hits):
        product += 10
        evidence.append('config_symbol:%s' % sym)

    if guesses and product == 0 and not config_hits:
        product += 5
        evidence.append('textual-path-guess')
    product = min(product, 60)

    # Early drop based on global commit blacklist.
    if forced_drop:
        scored = dict(commit)
        scored.update({
            'product_score': 0,
            'security_score': 0,
            'performance_score': 0,
            'stable_score': 0,
            'candidate_score': 0,
            'matched_profiles': [],
            'product_evidence': [],
            'filtered_by_commit_blacklist': True,
        })
        return scored

    # Rule-driven security and performance scoring.
    matched_profiles, sec_from_rules, perf_from_rules = _security_and_performance_from_profiles(commit, profile_rules)

    patch = commit.get('patch_features', {}) or {}
    trailers = _rules.trailer_flags(commit)

    # Patch-based hints can bump scores when rules are neutral.
    sec = sec_from_rules
    perf = perf_from_rules

    if patch.get('security_terms'):
        sec = max(sec, 20.0)
    if patch.get('performance_terms'):
        perf = max(perf, 20.0)

    # Stable/backport hints from both simple term matching and trailers.
    stable_hint = (
        patch.get('stable_terms')
        or trailers.get('has_fixes')
        or trailers.get('has_stable_cc')
        or trailers.get('has_cve')
    )
    stable = 10 if stable_hint else 0

    # Forced keep can give a small additional bump.
    if forced_keep:
        sec = max(sec, 30.0)
        perf = max(perf, 30.0)

    sec = float(min(50.0, sec))
    perf = float(min(50.0, perf))

    scored = dict(commit)
    scored.update({
        'product_score': product,
        'security_score': sec,
        'performance_score': perf,
        'stable_score': stable,
        'candidate_score': product + max(sec, perf) + stable,
        'matched_profiles': matched_profiles or list((profile_rules or {}).keys()),
        'product_evidence': evidence,
    })
    return scored
