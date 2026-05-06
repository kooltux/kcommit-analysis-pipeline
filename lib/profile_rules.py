"""Profile and rule loading for kcommit-analysis-pipeline.

v9.12 changes:
  - compiled_rules.json uses a deduplicated schema:
      { "rules": { rule_name: {patterns…} }, "profiles": { name: { "rules": {rule_name: {weight}}, "merged": {…} } } }
    Rule pattern data is stored once even when shared across profiles.
  - compile_rules_for_config() writes the new schema.
  - load_profile_rules() inflates it back to the in-memory form expected by
    scoring.py / prefilter.py: { profile_name: { "merged": {…}, "rules": { rule_name: {patterns+weight} } } }

v9.8 changes (historical):
  - compile_rules_for_config() now reads cfg['paths']['profiles_dirs'] and
    cfg['paths']['rules_dirs'] (lists). Falls back to the single-dir legacy
    keys when the list keys are absent.
  - Name-collision detection: if a profile or rule name is found in more than
    one directory, an error is raised listing both conflicting paths.
  - _read_patterns(): unchanged.
  - load_profile_rules(): unchanged.
"""
import hashlib
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
    active = (cfg.get('profiles', {}) or {}).get('active') or []
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


def _resolve_dirs(cfg, key_plural, default_subdir):
    """Return the directory list for *key_plural* from cfg['paths'].
    Falls back to <config_dir>/<default_subdir> when not set.
    """
    paths = cfg.get('paths', {}) or {}
    if paths.get(key_plural):
        return list(paths[key_plural])
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

    v9.12: writes a deduplicated on-disk schema:
        {
          "rules":    { rule_name: { patterns… } },          # each rule body once
          "profiles": { profile_name: {                       # per-profile metadata
              "rules":  { rule_name: { "weight": N } },       # weight only — body in rules{}
              "merged": { keyword/path lists … }              # union of all rule patterns
          }}
        }

    The in-memory return value remains the inflated form expected by scoring.py
    and prefilter.py:
        { profile_name: { "merged": {…}, "rules": { rule_name: {weight+patterns} } } }
    so no other module needs changing.

    v9.8: searches multiple profiles_dirs and rules_dirs; raises on name collision.
    """
    active        = active_profile_names(cfg)
    if not active:
        raise RuntimeError('no active profiles configured (profiles.active is empty)')

    profiles_dirs = _resolve_dirs(cfg, 'profiles_dirs', 'profiles')
    rules_dirs    = _resolve_dirs(cfg, 'rules_dirs',    'rules')

    for d in profiles_dirs:
        if not os.path.isdir(d):
            raise RuntimeError(f'profiles directory not found: {d}')
    for d in rules_dirs:
        if not os.path.isdir(d):
            raise RuntimeError(f'rules directory not found: {d}')

    # rule_bodies: rule_name -> full pattern dict (shared across profiles)
    rule_bodies   = {}
    # in-memory result (inflated): profile_name -> {merged, rules{name:{weight+patterns}}}
    profiles_mem  = {}

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
        per_rule_mem = {}   # {rule_name: {weight + patterns}}

        for rname, rule_spec in rules_cfg.items():
            # ── resolve weight & extras from profile rule spec ──────────────
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

            # ── load pattern files only once per rule name ──────────────────
            if rname not in rule_bodies:
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
                body = {}
                for key, fname in RULE_SCHEMA.items():
                    pats = list(_read_patterns(os.path.join(rdir, fname)))
                    extra_key = key + '_extra'
                    if extra_key in extras:
                        extra_pats = extras[extra_key]
                        if isinstance(extra_pats, list):
                            pats = pats + [str(p) for p in extra_pats]
                    body[key] = pats
                if not any(body[k] for k in RULE_SCHEMA):
                    raise RuntimeError(
                        f'rule {rname!r} in profile {name!r} has no pattern files '
                        f'under {rdir} — at least one *list.txt must be non-empty')
                rule_bodies[rname] = body
            else:
                body = rule_bodies[rname]

            # accumulate merged patterns for this profile
            for key in RULE_SCHEMA:
                merged_accum[key].update(body[key])

            per_rule_mem[rname] = {'weight': w, **body}

        profiles_mem[name] = {
            'merged': {k: sorted(v) for k, v in merged_accum.items()},
            'rules':  per_rule_mem,
        }

    # ── Write deduplicated schema ────────────────────────────────────────────
    disk_doc = {
        'rules':    rule_bodies,
        'profiles': {
            pname: {
                'rules':  {rn: {'weight': rv['weight']} for rn, rv in pdata['rules'].items()},
                'merged': pdata['merged'],
            }
            for pname, pdata in profiles_mem.items()
        },
    }
    # Compute a hash over the input profile/rule files so load_profile_rules()
    # can detect stale caches automatically.
    _hash_parts = []
    for _pname in sorted(profiles_mem):
        _hash_parts.append(_pname)
        _pdir = _find_unique(_pname, profiles_dirs, suffix='.json')
        if _pdir:
            _hash_parts.append(open(_pdir, 'rb').read().hex())
    schema_hash = hashlib.sha1('|'.join(_hash_parts).encode()).hexdigest()[:16]

    cache_path = os.path.join(work_dir, 'cache', 'compiled_rules.json')
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(disk_doc, f, indent=2, sort_keys=True)
        f.write('\n')
    return profiles_mem


def load_profile_rules(cfg):
    """Load and inflate compiled_rules.json into the in-memory form:
        { profile_name: { "merged": {…}, "rules": { rule_name: {weight+patterns} } } }
    Recompiles if the cache is missing.
    """
    paths      = cfg.get('paths', {}) or {}
    work_dir   = paths.get('work_dir') or cfg.get('project', {}).get('work_dir', './work')
    cache_path = os.path.join(work_dir, 'cache', 'compiled_rules.json')

    def _needs_recompile(cache_p):
        if not os.path.exists(cache_p):
            return True, 'not found'
        try:
            with open(cache_p, encoding='utf-8') as f:
                d = json.load(f)
        except Exception:
            return True, 'unreadable'
        cached_hash = d.get('schema_hash')
        if not cached_hash:
            return True, 'no schema_hash (pre-v9.12 cache)'
        return False, None

    _stale, _reason = _needs_recompile(cache_path)
    if _stale:
        logging.warning(
            'compiled_rules.json %s — recompiling now. '
            'Run stage 00 (prepare_pipeline) first for faster startup.', _reason)
        return compile_rules_for_config(cfg, work_dir)

    with open(cache_path, encoding='utf-8') as f:
        doc = json.load(f)

    rule_bodies = doc['rules']
    inflated    = {}
    for pname, pdata in doc['profiles'].items():
        per_rule = {
            rname: {'weight': rmeta.get('weight', 50), **rule_bodies[rname]}
            for rname, rmeta in (pdata.get('rules') or {}).items()
        }
        inflated[pname] = {'merged': pdata.get('merged') or {}, 'rules': per_rule}
    return inflated
