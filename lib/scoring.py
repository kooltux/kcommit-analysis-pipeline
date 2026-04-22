# Shared commit scoring helpers used by top-level pipeline stages.
from __future__ import print_function

from lib import rules as _rules


def infer_touched_paths(subject):
    # Infer coarse subsystem paths from commit text so later scoring can relate commits to product evidence.
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
    # Extract simple security/performance/stable hints from commit text.
    subj = (subject or '').lower()
    return {
        'security_terms': int(any(k in subj for k in ['cve', 'overflow', 'uaf', 'use-after-free', 'oob', 'security', 'race', 'refcount'])),
        'performance_terms': int(any(k in subj for k in ['performance', 'latency', 'throughput', 'regression', 'slow', 'faster', 'optimize'])),
        'stable_terms': int(any(k in subj for k in ['stable', 'fixes'])),
    }


def _profile_match_flags(commit, profile_rules):
    """Return (matched_profiles, has_rule_security, has_rule_performance).

    This applies per-profile whitelists/blacklists and keyword rules using
    the shared helpers from lib.rules.
    """
    text = '%s\n%s' % (commit.get('subject', ''), commit.get('body', ''))
    files = commit.get('files', []) or []

    matched_profiles = []
    any_sec = False
    any_perf = False

    for profile, rules in (profile_rules or {}).items():
        msg_whitelist = _rules.match_message_whitelist(text, rules)
        msg_blacklist = _rules.match_message_blacklist(text, rules)
        path_hits = _rules.match_path_list(files, rules.get('path_whitelist', []))
        path_black = _rules.match_path_list(files, rules.get('path_blacklist', []))
        sec_hits = _rules.extract_keywords(text, rules.get('security_keywords', []))
        perf_hits = _rules.extract_keywords(text, rules.get('performance_keywords', []))

        forced_exclude = _rules.is_forced_exclude(commit, rules)
        forced_include = _rules.is_forced_include(commit, rules)

        is_candidate = forced_include or (
            (msg_whitelist or sec_hits or perf_hits or path_hits) and not (msg_blacklist or path_black)
        )

        if not forced_exclude and is_candidate:
            matched_profiles.append(profile)
            if sec_hits:
                any_sec = True
            if perf_hits:
                any_perf = True

    return matched_profiles, any_sec, any_perf


def score_commit(commit, product_map, profile_rules):
    """Score a single commit for product, security, and performance relevance.

    The score combines:
    - textual path guesses from the subject,
    - build evidence from logs and optional build_dir scanning,
    - Kbuild-derived config_dirs and config_to_paths from product_map,
    - simple keyword-based patch features,
    - and per-profile rule matches.
    """
    guesses = commit.get('touched_paths_guess', []) or []
    built_log = "\n".join(product_map.get('built_objects_from_log', []))
    built_dir = "\n".join(product_map.get('built_artifacts_from_dir', []))
    enabled_cfg = "\n".join(product_map.get('enabled_configs', []))
    config_dirs = "\n".join(product_map.get('config_dirs', []))
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

    # Direct file-to-config mapping based on Kbuild-derived config_to_paths.
    files = commit.get('files', []) or []
    config_hits = set()
    for sym, paths in (cfg_map or {}).items():
        for p in paths:
            if p in files:
                config_hits.add(sym)
                break
    for sym in sorted(config_hits):
        product += 10
        evidence.append('config_symbol:%s' % sym)

    if guesses and product == 0 and not config_hits:
        product += 5
        evidence.append('textual-path-guess')
    product = min(product, 60)

    patch = commit.get('patch_features', {}) or {}
    # Rule-based matches may add extra security/performance weight.
    matched_profiles, rules_security, rules_performance = _profile_match_flags(commit, profile_rules)

    sec = 50 if (patch.get('security_terms') or rules_security) else 0
    perf = 50 if (patch.get('performance_terms') or rules_performance) else 0

    # Stable/backport hints from both simple term matching and trailers.
    trailers = _rules.trailer_flags(commit)
    stable_hint = (
        patch.get('stable_terms')
        or trailers.get('has_fixes')
        or trailers.get('has_stable_cc')
        or trailers.get('has_cve')
    )
    stable = 10 if stable_hint else 0

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
