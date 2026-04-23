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


def _load_json_with_comments(path):
    if not os.path.exists(path):
        return None
    with io.open(path, 'r', encoding='utf-8', errors='replace') as f:
        raw = f.read()
    lines = []
    for line in raw.splitlines():
        stripped = line.lstrip()
        if stripped.startswith('//') or stripped.startswith('#'):
            continue
        lines.append(line)
    text = '\n'.join(lines)
    if not text.strip():
        return None
    return json.loads(text)


def _active_profiles(cfg):
    profiles_cfg = cfg.get('profiles', {}) or {}
    if profiles_cfg.get('active'):
        return profiles_cfg.get('active') or []
    if cfg.get('active_profiles'):
        return cfg.get('active_profiles') or []
    return []


def compile_rules_for_config(cfg, work_dir):
    """Compile and deduplicate rules across all active profiles for this config.

    Profiles are resolved from configs/profiles/<name>.json and rules from
    configs/rules/<rule_folder>/*, relative to the configuration directory.
    The result is written to <work_dir>/cache/compiled_rules.json and
    returned as {profile_name: rules_dict}.
    """
    meta = cfg.get('_meta', {}) or {}
    config_dir = meta.get('config_dir') or os.getcwd()

    active = _active_profiles(cfg)
    if not active:
        raise RuntimeError('no active profiles configured (profiles.active is empty)')

    profile_root = os.path.join(config_dir, 'profiles')
    rule_root = os.path.join(config_dir, 'rules')
    if not os.path.isdir(profile_root):
        raise RuntimeError('profiles directory not found: %s' % profile_root)
    if not os.path.isdir(rule_root):
        raise RuntimeError('rules directory not found: %s' % rule_root)

    # Always include shared rules from rules/_shared when present.
    shared_root = os.path.join(rule_root, '_shared')
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
        prof_path = os.path.join(profile_root, name + '.json')
        pdata = _load_json_with_comments(prof_path)
        if not pdata:
            raise RuntimeError('profile %r not found or empty at %s' % (name, prof_path))
        rule_names = pdata.get('rules') or []
        if not rule_names:
            raise RuntimeError('profile %r does not define any rules' % name)

        msg_whitelist = set(shared['message_whitelist'])
        msg_blacklist = set(shared['message_blacklist'])
        path_whitelist = set(shared['path_whitelist'])
        path_blacklist = set(shared['path_blacklist'])
        sec_keywords = set(shared['security_keywords'])
        perf_keywords = set(shared['performance_keywords'])
        force_inc_c = set()
        force_exc_c = set()
        force_inc_p = set()
        force_exc_p = set()

        for rname in rule_names:
            rdir = os.path.join(rule_root, rname)
            if not os.path.isdir(rdir):
                raise RuntimeError('rule folder %r for profile %r not found under %s' % (rname, name, rule_root))
            msg_whitelist.update(_read_patterns(os.path.join(rdir, 'message_whitelist.txt')))
            msg_blacklist.update(_read_patterns(os.path.join(rdir, 'message_blacklist.txt')))
            path_whitelist.update(_read_patterns(os.path.join(rdir, 'path_whitelist.txt')))
            path_blacklist.update(_read_patterns(os.path.join(rdir, 'path_blacklist.txt')))
            sec_keywords.update(_read_patterns(os.path.join(rdir, 'security_keywords.txt')))
            perf_keywords.update(_read_patterns(os.path.join(rdir, 'performance_keywords.txt')))
            force_inc_c.update(_read_patterns(os.path.join(rdir, 'force_include_commits.txt')))
            force_exc_c.update(_read_patterns(os.path.join(rdir, 'force_exclude_commits.txt')))
            force_inc_p.update(_read_patterns(os.path.join(rdir, 'force_include_paths.txt')))
            force_exc_p.update(_read_patterns(os.path.join(rdir, 'force_exclude_paths.txt')))

        rules = {
            'message_whitelist': sorted(msg_whitelist),
            'message_blacklist': sorted(msg_blacklist),
            'path_whitelist': sorted(path_whitelist),
            'path_blacklist': sorted(path_blacklist),
            'security_keywords': sorted(sec_keywords),
            'performance_keywords': sorted(perf_keywords),
            'force_include_commits': sorted(force_inc_c),
            'force_exclude_commits': sorted(force_exc_c),
            'force_include_paths': sorted(force_inc_p),
            'force_exclude_paths': sorted(force_exc_p),
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
    back to on-the-fly compilation when compiled data is missing.
    """
    work = cfg.get('project', {}).get('work_dir', './work')
    compiled_path = os.path.join(work, 'cache', 'compiled_rules.json')
    if os.path.exists(compiled_path):
        with open(compiled_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('profiles', {}) or {}

    return compile_rules_for_config(cfg, work)
