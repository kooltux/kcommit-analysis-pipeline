"""Profile and rule loading for kcommit-analysis-pipeline.

v9.12 changes:
  - compiled_rules.json uses a deduplicated schema:
      { "rules": { rule_name: {patterns…} }, "profiles": { name: { "rules": {rule_name: {weight}}, "merged": {…} } } }
    Rule pattern data is stored once even when shared across profiles.
  - compile_rules_for_config() writes the new schema.
  - load_profile_rules() inflates it back to the in-memory form expected by
    scoring.py / prefilter.py: { profile_name: { "merged": {…}, "rules": { rule_name: {weight+patterns} } } }

v9.8 changes (historical):
  - compile_rules_for_config() now reads cfg['paths']['profiles_dirs'] and
    cfg['paths']['rules_dirs'] (lists). Falls back to the single-dir legacy
    keys when the list keys are absent.
  - Name-collision detection: if a profile or rule name is found in more than
    one directory, an error is raised listing both conflicting paths.

v13.0.0 changes:
  - E.2: _needs_recompile() now re-computes the schema_hash and compares it
    with the cached value so that a stale cache (rule/profile files changed
    since last compile) is detected and the rules are recompiled.
  - E.8: _compute_schema_hash() hashes only the files that were actually
    loaded (profile JSON + rule body files), not every file in rules_dirs.
  - compile_rules_for_config() only validates existence of explicitly-configured
    external profiles_dirs / rules_dirs entries, not the CWD-default fallback
    path (which is irrelevant when the built-in configs/ tree covers the profiles).

v19.11.0 changes:
  - Removed the product-specific rule-name alias (_rule_name_candidates): rule
    names are now looked up exactly as written in the profile, first in the
    configured rules_dirs, then in the built-in configs/rules/ tree.
v20.0.0 changes:
  - Product profile/rule isolation: samples require explicitly selected roots.
  - Cache validation includes roots and profile identity and fails closed.


Pattern source tracking:
  _read_patterns() now returns (patterns, sources) where sources is a list of
  (filepath, lineno) tuples parallel to patterns.  Rule bodies store
  _sources_<key> alongside each pattern list so that scoring._all_matches()
  can include the origin file and line number in each match hit.
"""
import hashlib
import json
import logging
import os
import re

from lib.config import load_json, INLINE_COMMENT_RE


def _read_patterns(path):
    """Read a pattern file, stripping blank lines and bash-style comments.

    Returns (patterns, sources) where patterns is a list of pattern strings
    and sources is a parallel list of (filepath, lineno) tuples.
    """
    if not path:
        return [], []
    if not os.path.exists(path):
        logging.debug('kcommit: rule pattern file not found (optional): %s', path)
        return [], []
    patterns = []
    sources  = []
    with open(path, encoding='utf-8', errors='replace') as f:
        for lineno, line in enumerate(f, 1):
            stripped = INLINE_COMMENT_RE.sub('', line).strip()
            if stripped:
                patterns.append(stripped)
                sources.append((path, lineno))
    return patterns, sources


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
    from lib.resources import resource_path
    paths = cfg.get('paths', {}) or {}
    raw = paths.get(key_plural)
    if raw in (None, ''):
        return [resource_path(cfg, None, default_subdir)]
    values = raw if isinstance(raw, list) else [raw]
    return [resource_path(cfg, value, default_subdir) for value in values]


def _dirs_explicitly_configured(cfg, key_plural):
    paths = cfg.get('paths', {}) or {}
    return bool(paths.get(key_plural))


def _find_unique(name, dirs, suffix=''):
    found = []
    for d in dirs:
        candidate = os.path.join(d, name + suffix) if suffix else os.path.join(d, name)
        if os.path.exists(candidate):
            found.append(candidate)
    if len(found) > 1:
        paths_str = '\n  '.join(found)
        raise RuntimeError(
            'name collision: %r found in multiple directories:\n  %s\n'
            'Each name must be unique across all search paths.' % (name, paths_str))
    return found[0] if found else None


def _find_preferred(name, primary_dirs, fallback_dirs, suffix=''):
    primary = _find_unique(name, primary_dirs, suffix=suffix) if primary_dirs else None
    if primary is not None:
        return primary
    return _find_unique(name, fallback_dirs, suffix=suffix) if fallback_dirs else None


def _merged_patterns(pdata):
    if not isinstance(pdata, dict):
        logging.warning('_merged_patterns: expected dict, got %s %r — skipping',
                        type(pdata).__name__, pdata)
        return {}
    return pdata.get('merged', {}) or {}


def _compute_schema_hash(active_profile_names_list, profiles_dirs, rule_bodies_by_name,
                         rules_dirs):
    hash_parts = ['resource-scope-v1', json.dumps({
        'active': sorted(active_profile_names_list),
        'profiles_dirs': [os.path.abspath(d) for d in profiles_dirs],
        'rules_dirs': [os.path.abspath(d) for d in rules_dirs],
    }, sort_keys=True)]

    def add_file(path, optional=False):
        hash_parts.append(os.path.abspath(path))
        if optional and not os.path.exists(path):
            hash_parts.append('missing')
        else:
            with open(path, 'rb') as stream:
                hash_parts.append(stream.read().hex())

    for pname in sorted(active_profile_names_list):
        prof_path = _find_unique(pname, profiles_dirs, suffix='.json')
        if not prof_path:
            raise RuntimeError('profile %r cannot be validated' % pname)
        add_file(prof_path)

    for rname in sorted(rule_bodies_by_name):
        rdir = _find_unique(rname, rules_dirs)
        if not rdir or not os.path.isdir(rdir):
            raise RuntimeError('rule folder %r cannot be validated' % rname)
        for fname in sorted(RULE_SCHEMA.values()):
            add_file(os.path.join(rdir, fname), optional=True)

    return hashlib.sha1('|'.join(hash_parts).encode()).hexdigest()[:16]


def compile_rules_for_config(cfg, cache_dir=None):
    """Compile rules for all active profiles and cache to compiled_rules.json.

    Pattern source tracking: each rule body stores _sources_<key> alongside
    the pattern list for each RULE_SCHEMA key.  _sources_<key> is a list of
    [filepath, lineno] pairs parallel to the patterns list, enabling
    scoring._all_matches() to report the origin of every match.
    """
    if cache_dir is None:
        paths     = cfg.get('paths', {}) or {}
        work_dir  = paths.get('work_dir') or cfg.get('project', {}).get('work_dir', './work')
        cache_dir = paths.get('cache_dir') or os.path.join(work_dir, 'cache')

    active        = active_profile_names(cfg)
    if not active:
        raise RuntimeError('no active profiles configured (profiles.active is empty)')

    profiles_dirs = _resolve_dirs(cfg, 'profiles_dirs', 'profiles')
    rules_dirs    = _resolve_dirs(cfg, 'rules_dirs',    'rules')

    for d in profiles_dirs:
        if not os.path.isdir(d):
            raise RuntimeError('profiles directory not found: %s' % d)
    for d in rules_dirs:
        if not os.path.isdir(d):
            raise RuntimeError('rules directory not found: %s' % d)

    rule_bodies   = {}
    profiles_mem  = {}

    for name in active:
        prof_path = _find_unique(name, profiles_dirs, suffix='.json')
        if prof_path is None:
            searched = ', '.join(profiles_dirs)
            raise RuntimeError(
                'profile %r not found in any profiles directory (%s)' % (name, searched))

        pdata = load_json(prof_path)
        if not pdata:
            raise RuntimeError('profile %r not found or empty at %s' % (name, prof_path))

        _json_name = pdata.get('name')
        if _json_name is not None and _json_name != name:
            raise RuntimeError(
                'profile file %r declares name=%r but was loaded as %r. '
                'Rename the file to %r.json or update the "name" field.' % (
                    os.path.basename(prof_path), _json_name, name, _json_name))

        rules_cfg = pdata.get('rules') or {}
        if not isinstance(rules_cfg, dict) or not rules_cfg:
            raise RuntimeError('profile %r must define a non-empty rules mapping' % name)

        merged_accum = {key: set() for key in RULE_SCHEMA}
        per_rule_mem = {}

        for rname, rule_spec in rules_cfg.items():
            if isinstance(rule_spec, dict):
                try:
                    w = int(rule_spec.get('weight', 50))
                except (TypeError, ValueError):
                    raise RuntimeError(
                        'rule weight for %r in profile %r must be an integer' % (rname, name))
                extras = {k: v for k, v in rule_spec.items() if k != 'weight'}
            else:
                try:
                    w = int(rule_spec)
                except (TypeError, ValueError):
                    raise RuntimeError(
                        'rule weight for %r in profile %r must be an integer, got %r' % (
                            rname, name, rule_spec))
                extras = {}

            if rname not in rule_bodies:
                rdir = _find_unique(rname, rules_dirs)
                if rdir is None:
                    searched = ', '.join(rules_dirs)
                    raise RuntimeError(
                        'rule folder %r for profile %r not found in any rules directory (%s)' % (
                            rname, name, searched))
                if not os.path.isdir(rdir):
                    raise RuntimeError(
                        'rule path %r for rule %r in profile %r is not a directory' % (
                            rdir, rname, name))
                body = {}
                for key, fname in RULE_SCHEMA.items():
                    pats, srcs = _read_patterns(os.path.join(rdir, fname))
                    extra_key  = key + '_extra'
                    if extra_key in extras:
                        extra_pats = extras[extra_key]
                        if isinstance(extra_pats, list):
                            # Extra patterns injected from profile have no file source
                            extra_srcs = [('(profile:%s)' % name, 0)] * len(extra_pats)
                            pats = pats + [str(p) for p in extra_pats]
                            srcs = srcs + extra_srcs
                    body[key]                    = pats
                    body['_sources_' + key]      = srcs
                if not any(body[k] for k in RULE_SCHEMA):
                    raise RuntimeError(
                        'rule %r in profile %r has no pattern files under %r — '
                        'at least one *list.txt must be non-empty' % (rname, name, rdir))
                rule_bodies[rname] = body
            else:
                body = rule_bodies[rname]

            for key in RULE_SCHEMA:
                merged_accum[key].update(body[key])

            per_rule_mem[rname] = {'weight': w}
            per_rule_mem[rname].update(body)

        profiles_mem[name] = {
            'merged':      {k: sorted(v) for k, v in merged_accum.items()},
            'rules':       per_rule_mem,
            'description': pdata.get('description', ''),
        }

    schema_hash = _compute_schema_hash(
        active, profiles_dirs, rule_bodies, rules_dirs)

    # _sources_* keys are runtime-only; strip them from the on-disk JSON to
    # keep the cache human-readable and avoid bloat. They are rebuilt from
    # the source .txt files on every load via load_profile_rules().
    def _strip_sources(d):
        return {k: v for k, v in d.items() if not k.startswith('_sources_')}

    disk_doc = {
        'rules': {rn: _strip_sources(rb) for rn, rb in rule_bodies.items()},
        'profiles': {
            pname: {
                'rules':  {rn: {'weight': rv['weight']} for rn, rv in pdata['rules'].items()},
                'merged': pdata['merged'],
            }
            for pname, pdata in profiles_mem.items()
        },
        'schema_hash': schema_hash,
    }

    cache_path = os.path.join(cache_dir, 'compiled_rules.json')
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(disk_doc, f, indent=2, sort_keys=True)
        f.write('\n')
    return profiles_mem


def _current_schema_hash(cfg):
    try:
        active = active_profile_names(cfg)
        if not active:
            return None
        profiles_dirs = _resolve_dirs(cfg, 'profiles_dirs', 'profiles')
        rules_dirs = _resolve_dirs(cfg, 'rules_dirs', 'rules')
        rule_names = {}
        for name in active:
            prof_path = _find_unique(name, profiles_dirs, suffix='.json')
            if not prof_path:
                return None
            pdata = load_json(prof_path)
            if not isinstance(pdata, dict) or not isinstance(pdata.get('rules'), dict):
                return None
            rule_names.update({rname: {} for rname in pdata['rules']})
        return _compute_schema_hash(active, profiles_dirs, rule_names, rules_dirs)
    except Exception:
        return None


def load_profile_rules(cfg):
    """Load and inflate compiled_rules.json into the in-memory form:
        { profile_name: { "merged": {…}, "rules": { rule_name: {weight+patterns} } } }

    After inflating from the on-disk cache, _sources_<key> entries are
    re-attached by re-reading the source .txt files so that scoring has
    file+line provenance for every pattern.
    """
    paths      = cfg.get('paths', {}) or {}
    work_dir   = paths.get('work_dir') or cfg.get('project', {}).get('work_dir', './work')
    cache_dir  = paths.get('cache_dir') or os.path.join(work_dir, 'cache')
    cache_path = os.path.join(cache_dir, 'compiled_rules.json')

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
        current_hash = _current_schema_hash(cfg)
        if current_hash is None:
            return True, 'cannot validate configured sources'
        if current_hash != cached_hash:
            return True, 'schema_hash mismatch (rules/profiles changed)'
        return False, None

    _stale, _reason = _needs_recompile(cache_path)
    if _stale:
        if _reason == 'unreadable':
            logging.warning('profile_rules: compiled_rules.json %s — recompiling.', _reason)
        elif _reason in ('no schema_hash (pre-v9.12 cache)', 'schema_hash mismatch (rules/profiles changed)'):
            logging.info('profile_rules: compiled_rules.json %s — recompiling. '
                         'Re-run stage 00 once to persist the updated cache.', _reason)
        else:
            logging.debug('profile_rules: compiled_rules.json %s — recompiling.', _reason)
        return compile_rules_for_config(cfg, cache_dir)

    with open(cache_path, encoding='utf-8') as f:
        doc = json.load(f)

    rule_bodies = doc['rules']

    # Re-attach _sources_<key> by re-reading the source .txt files.
    # This is cheap (the files are small) and keeps the on-disk cache clean.
    rules_dirs    = _resolve_dirs(cfg, 'rules_dirs', 'rules')

    for rname, rbody in rule_bodies.items():
        rdir = _find_unique(rname, rules_dirs)
        for key, fname in RULE_SCHEMA.items():
            src_key = '_sources_' + key
            if rdir:
                _, srcs = _read_patterns(os.path.join(rdir, fname))
            else:
                srcs = []
            # Align sources list length to pattern list length (safety)
            pats = rbody.get(key, [])
            if len(srcs) != len(pats):
                srcs = srcs[:len(pats)] + [('(unknown)', 0)] * max(0, len(pats) - len(srcs))
            rbody[src_key] = srcs

    inflated = {}
    for pname, pdata in doc['profiles'].items():
        per_rule = {}
        for rname, rmeta in (pdata.get('rules') or {}).items():
            if rname not in rule_bodies:
                continue
            rb = rule_bodies[rname]
            entry = {'weight': rmeta.get('weight', 50)}
            for key in RULE_SCHEMA:
                entry[key]                 = rb.get(key, [])
                entry['_sources_' + key]  = rb.get('_sources_' + key, [])
            per_rule[rname] = entry
        inflated[pname] = {'merged': pdata.get('merged') or {}, 'rules': per_rule}
    return inflated
