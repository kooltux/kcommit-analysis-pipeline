from __future__ import print_function
import io
import json
import os

from lib import rules as _rules


def _read_patterns(path):
    patterns = []
    if not path or not os.path.exists(path):
        return patterns
    with io.open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            patterns.append(s)
    return patterns


def _load_profile_json(profile_root, name):
    path = os.path.join(profile_root, name + '.json')
    if not os.path.exists(path):
        return None, None
    with io.open(path, 'r', encoding='utf-8', errors='replace') as f:
        data = json.load(f)
    return path, data


# Security rule categories: concise, factorized patterns per theme.
SECURITY_CATEGORY_PATTERNS = {
    'security_general': [
        'security', 'secure', 'hardening', 'harden', 'mitigation', 'exploit', 'vulnerability',
        'sanitize', 'sanitizer', 'validate', 'validation',
    ],
    'security_cve_bugs': [
        'CVE-', 'Fixes:', 'bug', 'BUG:', 'race condition', 'deadlock', 'use-after-free', 'UAF',
        'double free', 'null pointer dereference', 'NULL dereference',
    ],
    'security_memory': [
        'use-after-free', 'UAF', 'double free', 'heap overflow', 'stack overflow',
        'buffer overflow', 'out-of-bounds', 'out of bounds', 'UAF write', 'dangling pointer',
    ],
    'security_bounds': [
        'bounds check', 'boundary check', 'index check', 'array index', 'range check',
        'off-by-one', 'off by one', 'OOB read', 'OOB write',
    ],
    'security_auth_caps': [
        'authentication', 'authorization', 'privilege escalation', 'priv esc',
        'credentials', 'passwd', 'password', 'acl', 'access control',
        'capable(', 'cap_capable', 'capability', 'capabilities', 'uid', 'gid', 'fsuid', 'fsgid',
    ],
    'security_crypto_timing': [
        'constant-time', 'constant time', 'side channel', 'side-channel',
        'timing leak', 'timing side channel', 'crypto', 'cipher', 'encryption', 'decryption',
        'mac', 'hmac', 'digest', 'hash', 'key material', 'key leakage',
    ],
    'security_syscalls': [
        'syscall', 'syscalls', 'sys_enter', 'sys_exit', 'seccomp', 'ptrace',
        'userfaultfd', 'io_uring', 'io uring',
    ],
}

PERFORMANCE_CATEGORY_PATTERNS = {
    'performance_general': [
        'performance', 'throughput', 'latency', 'reduce latency', 'speed up', 'speedup',
        'optimize', 'optimization', 'micro-optim', 'fast path', 'slow path', 'regression',
        'scalability', 'scale better', 'cacheline', 'cache line', 'false sharing',
    ],
}


def _categories_for_profile(profile_data):
    cats = profile_data.get('rule_categories') or []
    return [c for c in cats if isinstance(c, str)]


def compile_rules_for_config(cfg, work_dir):
    """Compile and deduplicate rules across all active profiles for this config.

    The result is written to <work_dir>/cache/compiled_rules.json and contains
    a mapping {profile_name: rules_dict}, where each rules_dict has the same
    shape expected by lib.rules helpers (message_whitelist, message_blacklist,
    path_whitelist, path_blacklist, security_keywords, performance_keywords,
    and optional force_* entries).
    """
    meta = cfg.get('_meta', {}) or {}
    config_dir = meta.get('config_dir') or os.getcwd()
    profiles_cfg = cfg.get('profiles', {}) or {}

    # Determine active profiles: prefer profiles.active, fall back to legacy top-level active_profiles.
    active = []
    if profiles_cfg.get('active'):
        active = profiles_cfg.get('active') or []
    elif cfg.get('active_profiles'):
        active = cfg.get('active_profiles') or []

    if not active:
        return {}

    profile_root = profiles_cfg.get('profile_root') or ''
    if profile_root and not os.path.isabs(profile_root):
        profile_root = os.path.normpath(os.path.join(config_dir, profile_root))
    if not profile_root:
        profile_root = os.path.normpath(os.path.join(config_dir, 'profiles'))

    # Shared rule roots for legacy generic rules.
    rule_root = profiles_cfg.get('rule_root') or ''
    if rule_root and not os.path.isabs(rule_root):
        rule_root = os.path.normpath(os.path.join(config_dir, rule_root))
    shared_root = os.path.join(rule_root, '_shared') if rule_root else ''

    # Load shared baseline patterns once.
    shared = {
        'message_whitelist': _read_patterns(os.path.join(shared_root, 'message_whitelist.txt')),
        'message_blacklist': _read_patterns(os.path.join(shared_root, 'message_blacklist.txt')),
        'path_whitelist': _read_patterns(os.path.join(shared_root, 'path_whitelist.txt')),
        'path_blacklist': _read_patterns(os.path.join(shared_root, 'path_blacklist.txt')),
        'security_keywords': _read_patterns(os.path.join(shared_root, 'security_keywords.txt')),
        'performance_keywords': _read_patterns(os.path.join(shared_root, 'performance_keywords.txt')),
    }

    profiles_rules = {}

    for name in active:
        profile_path, pdata = _load_profile_json(profile_root, name)
        if not pdata:
            continue
        cats = _categories_for_profile(pdata)

        msg_whitelist = set(shared['message_whitelist'])
        msg_blacklist = set(shared['message_blacklist'])
        path_whitelist = set(shared['path_whitelist'])
        path_blacklist = set(shared['path_blacklist'])
        sec_keywords = set(shared['security_keywords'])
        perf_keywords = set(shared['performance_keywords'])

        # Category-driven security/performance keywords.
        for cat in cats:
            if cat in SECURITY_CATEGORY_PATTERNS:
                sec_keywords.update(SECURITY_CATEGORY_PATTERNS[cat])
                # Security categories also act as message whitelist hints.
                msg_whitelist.update(SECURITY_CATEGORY_PATTERNS[cat])
            if cat in PERFORMANCE_CATEGORY_PATTERNS:
                perf_keywords.update(PERFORMANCE_CATEGORY_PATTERNS[cat])
                msg_whitelist.update(PERFORMANCE_CATEGORY_PATTERNS[cat])

        rules = {
            'message_whitelist': sorted(msg_whitelist),
            'message_blacklist': sorted(msg_blacklist),
            'path_whitelist': sorted(path_whitelist),
            'path_blacklist': sorted(path_blacklist),
            'security_keywords': sorted(sec_keywords),
            'performance_keywords': sorted(perf_keywords),
            'force_include_commits': [],
            'force_exclude_commits': [],
            'force_include_paths': [],
            'force_exclude_paths': [],
        }
        profiles_rules[name] = rules

    cache = os.path.join(work_dir, 'cache')
    os.makedirs(cache, exist_ok=True)
    out_path = os.path.join(cache, 'compiled_rules.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({'profiles': profiles_rules}, f, indent=2)
        f.write('\n')
    return profiles_rules


def load_profile_rules(cfg):
    """Load rules for active profiles.

    Prefers compiled_rules.json produced by the prepare_rules stage. Falls
    back to legacy on-the-fly loading when compiled data is missing.
    """
    work = cfg.get('project', {}).get('work_dir', './work')
    compiled_path = os.path.join(work, 'cache', 'compiled_rules.json')
    if os.path.exists(compiled_path):
        with open(compiled_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('profiles', {}) or {}

    # Fallback: compile on the fly and return the in-memory result.
    return compile_rules_for_config(cfg, work)

