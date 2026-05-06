"""Profile and rule loading for kcommit-analysis-pipeline.

v9.8 changes:
  - compile_rules_for_config() now reads cfg['paths']['profiles_dirs'] and
    cfg['paths']['rules_dirs'] (lists). Falls back to the single-dir legacy
    keys when the list keys are absent.
  - Name-collision detection: if a profile or rule name is found in more than
    one directory, an error is raised listing both conflicting paths.
  - _read_patterns(): unchanged.
  - load_profile_rules(): unchanged.
"""
import json
import logging
import os
import re

from lib.config import _load_json as _load_json_config, INLINE_COMMENT_RE as _PATTERN_COMMENT_RE


def _read_patterns(path):
    """Read a pattern file, stripping blank lines and bash-style comments."""
    if not path:
        return []
    if not os.path.exists(path):
        logging.debug('kcommit: rule pattern file not found (optional): %s', path)
        return []
    patterns = []
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            stripped = _PATTERN_COMMENT_RE.sub('', line).strip()
            if stripped:
                patterns.append(stripped)
    return patterns


def active_profile_names(cfg):
    """Return ordered list of active profile names."""
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


def _resolve_dirs(cfg, key_plural, key_singular, default_subdir):
    """Return the list of directories to search for *key_plural*.

    Priority:
      1. cfg['paths'][key_plural]  — set by load_config() from profiles_dirs / rules_dirs
      2. cfg['paths'][key_singular] — legacy single-dir key
      3. <config_dir>/<default_subdir>  — hardcoded default
    """
    paths = cfg.get('paths', {}) or {}
    if key_plural in paths and paths[key_plural]:
        return list(paths[key_plural])
    if key_singular in paths and paths[key_singular]:
        return [paths[key_singular]]
    meta       = cfg.get('_meta', {}) or {}
    config_dir = meta.get('config_dir') or os.getcwd()
    return [os.path.join(config_dir, default_subdir)]


def _find_unique(name, dirs, suffix=''):
    """Find *name* (with optional *suffix*) across *dirs*, enforcing uniqueness.

    Returns the full path of the unique match.
    Raises RuntimeError if the name is found in more than one directory,
    or if it is not found in any directory (returns None in that case).
    """
    found = []
    for d in dirs:
        candidate = os.path.join(d, name + suffix) if suffix else os.path.join(d, name)
        if os.path.exists(candidate):
            found.append(candidate)
    if len(found) > 1:
        paths_str = '\n  '.join(found)
        raise RuntimeError(
            f'name collision: {name!r} found in multiple directories:\n  {paths_str}\n'
            f'Each name must be unique across all search paths.')
    return found[0] if found else None


def compile_rules_for_config(cfg, work_dir):
    """Compile rules for all active profiles and cache to compiled_rules.json.

    v9.8: searches multiple profiles_dirs and rules_dirs; raises on name collision.
    """
    active        = active_profile_names(cfg)
    if not active:
        raise RuntimeError('no active profiles configured (profiles.active is empty)')

    profiles_dirs = _resolve_dirs(cfg, 'profiles_dirs', 'profiles_dir', 'profiles')
    rules_dirs    = _resolve_dirs(cfg, 'rules_dirs',    'rules_dir',    'rules')

    # Validate all search directories exist
    for d in profiles_dirs:
        if not os.path.isdir(d):
            raise RuntimeError(f'profiles directory not found: {d}')
    for d in rules_dirs:
        if not os.path.isdir(d):
            raise RuntimeError(f'rules directory not found: {d}')

    profiles_rules = {}

    for name in active:
        prof_path = _find_unique(name, profiles_dirs, suffix='.json')
        if prof_path is None:
            searched = ', '.join(profiles_dirs)
            raise RuntimeError(
                f'profile {name!r} not found in any profiles directory ({searched})')

        pdata = _load_json_config(prof_path)
        if not pdata:
            raise RuntimeError(f'profile {name!r} not found or empty at {prof_path}')

        rules_cfg = pdata.get('rules') or {}
        if not isinstance(rules_cfg, dict) or not rules_cfg:
            raise RuntimeError(f'profile {name!r} must define a non-empty rules mapping')

        merged_accum = {key: set() for key in RULE_SCHEMA}
        per_rule     = {}

        for rname, rule_spec in rules_cfg.items():
            rdir = _find_unique(rname, rules_dirs)
            if rdir is None:
                searched = ', '.join(rules_dirs)
                raise RuntimeError(
                    f'rule folder {rname!r} for profile {name!r} not found '
                    f'in any rules directory ({searched})')
            if not os.path.isdir(rdir):
                raise RuntimeError(
                    f'rule path {rdir!r} for rule {rname!r} in profile {name!r} '
                    f'is not a directory')

            if isinstance(rule_spec, dict):
                try:
                    w = int(rule_spec.get('weight', 50))
                except (TypeError, ValueError):
                    raise RuntimeError(
                        f'rule weight for {rname!r} in profile {name!r} must be an integer')
                extras = {k: v for k, v in rule_spec.items() if k != 'weight'}
            else:
                try:
                    w = int(rule_spec)
                except (TypeError, ValueError):
                    raise RuntimeError(
                        f'rule weight for {rname!r} in profile {name!r} must be an integer, '
                        f'got {rule_spec!r}')
                extras = {}

            rule_data = {'weight': w}
            for key, fname in RULE_SCHEMA.items():
                pats = list(_read_patterns(os.path.join(rdir, fname)))
                extra_key = key + '_extra'
                if extra_key in extras:
                    extra_pats = extras[extra_key]
                    if isinstance(extra_pats, list):
                        pats = pats + [str(p) for p in extra_pats]
                rule_data[key] = pats
                merged_accum[key].update(pats)
            per_rule[rname] = rule_data
            if not any(rule_data[k] for k in RULE_SCHEMA):
                raise RuntimeError(
                    f'rule {rname!r} in profile {name!r} has no pattern files '
                    f'under {rdir} — at least one *list.txt must be non-empty')

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
    paths      = cfg.get('paths', {}) or {}
    work_dir   = paths.get('work_dir') or cfg.get('project', {}).get('work_dir', './work')
    cache_path = os.path.join(work_dir, 'cache', 'compiled_rules.json')

    if not os.path.exists(cache_path):
        logging.warning(
            'compiled_rules.json not found — recompiling now. '
            'Run stage 00 (prepare_pipeline) first for faster startup.')
        return compile_rules_for_config(cfg, work_dir)

    with open(cache_path, encoding='utf-8') as f:
        return json.load(f)
