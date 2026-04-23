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


RULE_SCHEMA = {
    'keywords_whitelist': 'keywords_whitelist.txt',
    'keywords_blacklist': 'keywords_blacklist.txt',
    'path_whitelist': 'path_whitelist.txt',
    'path_blacklist': 'path_blacklist.txt',
    'commit_whitelist': 'commit_whitelist.txt',
    'commit_blacklist': 'commit_blacklist.txt',
}


def compile_rules_for_config(cfg, work_dir):
    """Compile and deduplicate rules across all active profiles.

    For each active profile, this loads its JSON definition from
    configs/profiles/<name>.json and the referenced rule folders from
    configs/rules/<rule_name>/.

    The compiled data has the following shape:

        {
          "profiles": {
            "profile_name": {
              "merged": { ... },
              "rules": {
                "rule_name": { "weight": int, ...patterns... },
                ...
              }
            },
            ...
          }
        }

    The "merged" entry aggregates all patterns across the profile's rules
    for fast global checks (e.g., commit-wide blacklist). The per-rule
    entries retain individual weights so scoring can treat them differently.
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

    profiles_rules = {}

    for name in active:
        prof_path = os.path.join(profile_root, name + '.json')
        pdata = _load_json_with_comments(prof_path)
        if not pdata:
            raise RuntimeError('profile %r not found or empty at %s' % (name, prof_path))

        rules_cfg = pdata.get('rules') or {}
        if not isinstance(rules_cfg, dict) or not rules_cfg:
            raise RuntimeError('profile %r must define a non-empty rules mapping' % name)

        merged_accum = {key: set() for key in RULE_SCHEMA.keys()}
        per_rule = {}

        for rname, weight in rules_cfg.items():
            rdir = os.path.join(rule_root, rname)
            if not os.path.isdir(rdir):
                raise RuntimeError('rule folder %r for profile %r not found under %s' % (rname, name, rule_root))
            try:
                w = int(weight)
            except (TypeError, ValueError):
                raise RuntimeError('rule %r in profile %r has non-integer weight %r' % (rname, name, weight))
            w = max(0, min(100, w))

            rule_data = {'weight': w}
            for key, fname in RULE_SCHEMA.items():
                patterns = _read_patterns(os.path.join(rdir, fname))
                rule_data[key] = patterns
                merged_accum[key].update(patterns)

            per_rule[rname] = rule_data

        merged = {key: sorted(values) for key, values in merged_accum.items()}
        profiles_rules[name] = {
            'merged': merged,
            'rules': per_rule,
        }

    cache = os.path.join(work_dir, 'cache')
    os.makedirs(cache, exist_ok=True)
    out_path = os.path.join(cache, 'compiled_rules.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({'profiles': profiles_rules}, f, indent=2)
        f.write('\n')
    return profiles_rules


def load_profile_rules(cfg):
    """Load compiled rules for active profiles.

    Prefers compiled_rules.json produced by the prepare_pipeline stage. Falls
    back to on-the-fly compilation when compiled data is missing.
    """
    work = cfg.get('project', {}).get('work_dir', './work')
    compiled_path = os.path.join(work, 'cache', 'compiled_rules.json')
    if os.path.exists(compiled_path):
        with io.open(compiled_path, 'r', encoding='utf-8', errors='replace') as f:
            data = json.load(f)
        return data.get('profiles', {}) or {}

    return compile_rules_for_config(cfg, work)
