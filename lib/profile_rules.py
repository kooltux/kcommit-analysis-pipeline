from __future__ import print_function
import io
import json
import os


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


def load_profile_rules(cfg):
    """Load rule sets for each active profile.

    Returns a mapping {profile_name: rules_dict}. Each rules_dict may contain
    keys like message_whitelist, message_blacklist, path_whitelist,
    path_blacklist, security_keywords, performance_keywords, and optional
    force_include/force_exclude lists.
    """
    profiles_cfg = cfg.get('profiles', {}) or {}
    active = cfg.get('active_profiles', []) or []
    meta = cfg.get('_meta', {}) or {}
    config_dir = meta.get('config_dir', os.getcwd())

    profile_root = profiles_cfg.get('profile_root') or ''
    if profile_root and not os.path.isabs(profile_root):
        profile_root = os.path.normpath(os.path.join(config_dir, profile_root))
    if not profile_root:
        # No profile metadata configured.
        return {}

    result = {}
    for name in active:
        profile_path, pdata = _load_profile_json(profile_root, name)
        if not pdata:
            continue
        pdir = os.path.dirname(profile_path)

        # Resolve rule roots relative to the profile file.
        rule_root = pdata.get('rule_root') or pdata.get('rule_dir') or ''
        shared_root = pdata.get('shared_rule_root') or pdata.get('shared_rule_dir') or ''
        if rule_root and not os.path.isabs(rule_root):
            rule_root = os.path.normpath(os.path.join(pdir, rule_root))
        if shared_root and not os.path.isabs(shared_root):
            shared_root = os.path.normpath(os.path.join(pdir, shared_root))

        # Helper to locate a given rule filename, consulting explicit rule_files
        # entries first, then falling back to rule_root/shared_root.
        def paths_for(filename):
            explicit = None
            for key, value in (pdata.get('rule_files') or {}).items():
                if key == filename:
                    explicit = value
                    break
            candidates = []
            if explicit:
                p = explicit
                if not os.path.isabs(p):
                    p = os.path.normpath(os.path.join(pdir, p))
                candidates.append(p)
            if shared_root:
                candidates.append(os.path.join(shared_root, filename))
            if rule_root:
                candidates.append(os.path.join(rule_root, filename))
            # Deduplicate while preserving order.
            seen = set()
            out = []
            for c in candidates:
                if c not in seen:
                    seen.add(c)
                    out.append(c)
            return out

        def load_merged(filename):
            pats = []
            for p in paths_for(filename):
                pats.extend(_read_patterns(p))
            return pats

        rules = {
            'message_whitelist': load_merged('message_whitelist.txt'),
            'message_blacklist': load_merged('message_blacklist.txt'),
            'path_whitelist': load_merged('path_whitelist.txt'),
            'path_blacklist': load_merged('path_blacklist.txt'),
            'security_keywords': load_merged('security_keywords.txt'),
            'performance_keywords': load_merged('performance_keywords.txt'),
            'force_include_commits': load_merged('force_include_commits.txt'),
            'force_exclude_commits': load_merged('force_exclude_commits.txt'),
            'force_include_paths': load_merged('force_include_paths.txt'),
            'force_exclude_paths': load_merged('force_exclude_paths.txt'),
        }

        result[name] = rules

    return result
