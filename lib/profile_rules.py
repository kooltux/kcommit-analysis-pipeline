"""Profile and rule loading for kcommit-analysis-pipeline.

v8.0 changes vs v7.19:
  - Dropped from __future__ import print_function and import io (Py2 dead code).
  - io.open() replaced with open(); %-formatting replaced with f-strings.
  - No functional changes.
"""
import json
import os


def _read_patterns(path):
    if not path or not os.path.exists(path):
        return []
    patterns = []
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith('#'):
                patterns.append(s)
    return patterns


def _load_json_with_comments(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8', errors='replace') as f:
        raw = f.read()
    lines = [l for l in raw.splitlines()
             if not l.lstrip().startswith('//') and not l.lstrip().startswith('#')]
    text = '\n'.join(lines).strip()
    return json.loads(text) if text else None


def _active_profiles(cfg):
    """Return ordered list of active profile names.

    Accepts both dict form {'name': weight, ...} and list form ['name', ...].
    """
    active = (cfg.get('profiles', {}) or {}).get('active') or cfg.get('active_profiles') or []
    if isinstance(active, dict):
        return list(active.keys())
    return list(active)


RULE_SCHEMA = {
    'keywords_whitelist': 'keywords_whitelist.txt',
    'keywords_blacklist': 'keywords_blacklist.txt',
    'path_whitelist':     'path_whitelist.txt',
    'path_blacklist':     'path_blacklist.txt',
    'commit_whitelist':   'commit_whitelist.txt',
    'commit_blacklist':   'commit_blacklist.txt',
}


def compile_rules_for_config(cfg, work_dir):
    """Compile rules for all active profiles and cache to compiled_rules.json."""
    meta       = cfg.get('_meta', {}) or {}
    config_dir = meta.get('config_dir') or os.getcwd()
    active     = _active_profiles(cfg)

    if not active:
        raise RuntimeError('no active profiles configured (profiles.active is empty)')

    profile_root = os.path.join(config_dir, 'profiles')
    rule_root    = os.path.join(config_dir, 'rules')
    if not os.path.isdir(profile_root):
        raise RuntimeError(f'profiles directory not found: {profile_root}')
    if not os.path.isdir(rule_root):
        raise RuntimeError(f'rules directory not found: {rule_root}')

    profiles_rules = {}

    for name in active:
        prof_path = os.path.join(profile_root, f'{name}.json')
        pdata = _load_json_with_comments(prof_path)
        if not pdata:
            raise RuntimeError(f'profile {name!r} not found or empty at {prof_path}')

        rules_cfg = pdata.get('rules') or {}
        if not isinstance(rules_cfg, dict) or not rules_cfg:
            raise RuntimeError(f'profile {name!r} must define a non-empty rules mapping')

        merged_accum = {key: set() for key in RULE_SCHEMA}
        per_rule     = {}

        for rname, weight in rules_cfg.items():
            rdir = os.path.join(rule_root, rname)
            if not os.path.isdir(rdir):
                raise RuntimeError(
                    f'rule folder {rname!r} for profile {name!r} not found under {rule_root}')
            try:
                w = int(weight)
            except (TypeError, ValueError):
                raise RuntimeError(
                    f'rule weight for {rname!r} in profile {name!r} must be an integer, '
                    f'got {weight!r}')

            rule_data = {'weight': w}
            for key, fname in RULE_SCHEMA.items():
                pats = _read_patterns(os.path.join(rdir, fname))
                rule_data[key] = pats
                merged_accum[key].update(pats)
            per_rule[rname] = rule_data

        profiles_rules[name] = {
            'merged': {k: sorted(v) for k, v in merged_accum.items()},
            'rules':  per_rule,
        }

    cache_path = os.path.join(work_dir, 'cache', 'compiled_rules.json')
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(profiles_rules, f, indent=2, sort_keys=True)
        f.write('\n')
    return profiles_rules


def load_profile_rules(cfg):
    """Load compiled rules from cache, recompiling if necessary."""
    work       = cfg.get('project', {}).get('work_dir', './work')
    cache_path = os.path.join(work, 'cache', 'compiled_rules.json')
    if not os.path.exists(cache_path):
        return compile_rules_for_config(cfg, work)
    with open(cache_path, encoding='utf-8') as f:
        return json.load(f)
