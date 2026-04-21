# Shared commit scoring helpers used by top-level pipeline stages.
from __future__ import print_function


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
        ('qcom', 'drivers/soc/qcom/'),
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


def score_commit(commit, product_map, active_profiles):
    # Combine textual path guesses with available build evidence from logs and optional build_dir scanning.
    guesses = commit.get('touched_paths_guess', []) or []
    built_log = '
'.join(product_map.get('built_objects_from_log', []))
    built_dir = '
'.join(product_map.get('built_artifacts_from_dir', []))
    enabled_cfg = '
'.join(product_map.get('enabled_configs', []))
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
    if guesses and product == 0:
        product += 5
        evidence.append('textual-path-guess')
    product = min(product, 60)
    sec = 50 if commit.get('patch_features', {}).get('security_terms') else 0
    perf = 50 if commit.get('patch_features', {}).get('performance_terms') else 0
    stable = 10 if commit.get('patch_features', {}).get('stable_terms') else 0
    scored = dict(commit)
    scored.update({
        'product_score': product,
        'security_score': sec,
        'performance_score': perf,
        'stable_score': stable,
        'candidate_score': product + max(sec, perf) + stable,
        'matched_profiles': active_profiles,
        'product_evidence': evidence,
    })
    return scored
