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

v13.0.0 changes:
  - E.2: _needs_recompile() now re-computes the schema_hash and compares it
    with the cached value so that a stale cache (rule/profile files changed
    since last compile) is detected and the rules are recompiled.
  - E.8: _compute_schema_hash() hashes only the files that were actually
    loaded (profile JSON + rule body files), not every file in rules_dirs.
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

    Also accepts the singular compatibility aliases ``profiles_dir`` and
    ``rules_dir`` in the derived ``paths`` mapping, normalizing them to the
    same list form used internally.
    Falls back to <config_dir>/<default_subdir> when not set.
    """
    paths = cfg.get('paths', {}) or {}
    if paths.get(key_plural):
        return list(paths[key_plural])
    key_singular = key_plural[:-1] if key_plural.endswith('s') else key_plural
    raw = paths.get(key_singular)
    if raw not in (None, [], ''):
        return list(raw) if isinstance(raw, list) else [raw]
    meta       = cfg.get('_meta', {}) or {}
    config_dir = meta.get('config_dir') or os.getcwd()
    return [os.path.join(config_dir, default_subdir)]


def _find_unique(name, dirs, suffix=''):
    """Find *name* (with optional *suffix*) across *dirs*, enforcing uniqueness.

    Returns the full path of the unique match, or None if not found.
    Raises RuntimeError if the name is found in more than one directory.
    """
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
    """Find *name* with preference order: primary dirs first, fallback dirs second.

    Uniqueness is enforced within each tier; primary cleanly overrides a same-name
    fallback. Used for D.1 fallback so external configs can override built-in rules.
    """
    primary = _find_unique(name, primary_dirs, suffix=suffix) if primary_dirs else None
    if primary is not None:
        return primary
    return _find_unique(name, fallback_dirs, suffix=suffix) if fallback_dirs else None


def _rule_name_candidates(name):
    """Return preferred fallback candidate names for legacy external rule names."""
    candidates = [name]
    if name.startswith('artemis_'):
        stripped = name[len('artemis_'):]
        if stripped and stripped not in candidates:
            candidates.append(stripped)
    return candidates


def _merged_patterns(pdata):
    """Return the merged pattern dict from a profile data entry (safe, never None)."""
    if not isinstance(pdata, dict):
        logging.warning('_merged_patterns: expected dict, got %s %r — skipping',
                        type(pdata).__name__, pdata)
        return {}
    return pdata.get('merged', {}) or {}


def _compute_schema_hash(active_profile_names_list, profiles_dirs, rule_bodies_by_name,
                         rules_dirs, builtin_rules_dirs):
    """Compute a hash over the actually-loaded profile and rule files.

    E.8 (v13.0.0): hashes only the files that were actually loaded (profile
    JSON + the pattern files inside each loaded rule directory), not every
    file in rules_dirs. This avoids both false positives (unused rule files
    triggering needless recompilation) and reads all content once.
    """
    hash_parts = []
    builtin_profiles_dirs = [os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'configs', 'profiles')]

    for pname in sorted(active_profile_names_list):
        prof_path = _find_preferred(pname, profiles_dirs, builtin_profiles_dirs, suffix='.json')
        if prof_path and os.path.isfile(prof_path):
            try:
                hash_parts.append(open(prof_path, 'rb').read().hex())
            except Exception:
                hash_parts.append('missing:%s' % pname)
        else:
            hash_parts.append('missing:%s' % pname)

    all_rule_dirs = list(rules_dirs)
    for d in builtin_rules_dirs:
        if d not in all_rule_dirs:
            all_rule_dirs.append(d)

    for rname in sorted(rule_bodies_by_name.keys()):
        rdir = _find_preferred(rname, rules_dirs, builtin_rules_dirs)
        if rdir and os.path.isdir(rdir):
            for fname in sorted(RULE_SCHEMA.values()):
                fpath = os.path.join(rdir, fname)
                if os.path.isfile(fpath):
                    try:
                        hash_parts.append(open(fpath, 'rb').read().hex())
                    except Exception:
                        hash_parts.append('unreadable:%s/%s' % (rname, fname))

    return hashlib.sha1('|'.join(hash_parts).encode()).hexdigest()[:16]


def compile_rules_for_config(cfg, cache_dir=None):
    """Compile rules for all active profiles and cache to compiled_rules.json.

    v9.12: writes a deduplicated on-disk schema:
        {
          "rules":    { rule_name: { patterns… } },          # each rule body once
          "profiles": { profile_name: {                       # per-profile metadata
              "rules":  { rule_name: { "weight": N } },       # weight only — body in rules{}
              "merged": { keyword/path lists … }              # union of all rule patterns
          }},
          "schema_hash": "<sha1[:16]>"                        # content fingerprint
        }

    The in-memory return value remains the inflated form expected by scoring.py
    and prefilter.py:
        { profile_name: { "merged": {…}, "rules": { rule_name: {weight+patterns} } } }
    so no other module needs changing.

    v9.8: searches multiple profiles_dirs and rules_dirs; raises on name collision.
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

    # D.1: tool's built-in shipped configs act as fallback roots after
    # any external config directories.
    _tool_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    builtin_profiles_dirs = [os.path.join(_tool_root, 'configs', 'profiles')]
    builtin_rules_dirs    = [os.path.join(_tool_root, 'configs', 'rules')]

    for d in profiles_dirs + builtin_profiles_dirs:
        if not os.path.isdir(d):
            raise RuntimeError('profiles directory not found: %s' % d)
    for d in rules_dirs + builtin_rules_dirs:
        if not os.path.isdir(d):
            raise RuntimeError('rules directory not found: %s' % d)

    # rule_bodies: rule_name -> full pattern dict (shared across profiles)
    rule_bodies   = {}
    # in-memory result (inflated): profile_name -> {merged, rules{name:{weight+patterns}}}
    profiles_mem  = {}

    for name in active:
        prof_path = _find_preferred(name, profiles_dirs, builtin_profiles_dirs, suffix='.json')
        if prof_path is None:
            searched = ', '.join(profiles_dirs)
            raise RuntimeError(
                'profile %r not found in any profiles directory (%s)' % (name, searched))

        pdata = _load_json_config(prof_path)
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
        per_rule_mem = {}   # {rule_name: {weight + patterns}}

        for rname, rule_spec in rules_cfg.items():
            # ── resolve weight & extras from profile rule spec ──────────────────
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

            # ── load pattern files only once per rule name ──────────────────
            if rname not in rule_bodies:
                rdir = None
                for candidate_name in _rule_name_candidates(rname):
                    rdir = _find_preferred(candidate_name, rules_dirs, builtin_rules_dirs)
                    if rdir is not None:
                        break
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
                    pats = list(_read_patterns(os.path.join(rdir, fname)))
                    extra_key = key + '_extra'
                    if extra_key in extras:
                        extra_pats = extras[extra_key]
                        if isinstance(extra_pats, list):
                            pats = pats + [str(p) for p in extra_pats]
                    body[key] = pats
                if not any(body[k] for k in RULE_SCHEMA):
                    raise RuntimeError(
                        'rule %r in profile %r has no pattern files under %r — '
                        'at least one *list.txt must be non-empty' % (rname, name, rdir))
                rule_bodies[rname] = body
            else:
                body = rule_bodies[rname]

            # accumulate merged patterns for this profile
            for key in RULE_SCHEMA:
                merged_accum[key].update(body[key])

            per_rule_mem[rname] = {'weight': w}
            per_rule_mem[rname].update(body)

        profiles_mem[name] = {
            'merged':      {k: sorted(v) for k, v in merged_accum.items()},
            'rules':       per_rule_mem,
            'description': pdata.get('description', ''),
        }

    # ── Compute hash over only the files that were actually loaded (E.8) ─────
    schema_hash = _compute_schema_hash(
        active, profiles_dirs, rule_bodies, rules_dirs, builtin_rules_dirs)

    # ── Write deduplicated schema ───────────────────────────────────────────────
    disk_doc = {
        'rules': rule_bodies,
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
    """Compute the expected hash for the current config, without compiling rules.

    Used by _needs_recompile() to compare against the cached hash.
    Returns None on any error.

    E.2 (v13.0.0): this enables _needs_recompile() to detect stale caches by
    comparing the live hash against the stored hash, not just checking that
    a hash field is present.
    """
    try:
        active        = active_profile_names(cfg)
        profiles_dirs = _resolve_dirs(cfg, 'profiles_dirs', 'profiles')
        rules_dirs    = _resolve_dirs(cfg, 'rules_dirs',    'rules')
        _tool_root    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        builtin_rules_dirs = [os.path.join(_tool_root, 'configs', 'rules')]

        # We need the list of rule names that would be loaded. We do this by
        # scanning profile JSONs without a full compile.
        builtin_profiles_dirs = [os.path.join(_tool_root, 'configs', 'profiles')]
        rule_names_seen = []  # ordered, de-duplicated
        _seen = set()
        for name in active:
            prof_path = _find_preferred(name, profiles_dirs, builtin_profiles_dirs, suffix='.json')
            if not prof_path:
                return None
            try:
                with open(prof_path, encoding='utf-8') as _f:
                    pdata = json.load(_f)
            except Exception:
                return None
            for rname in (pdata.get('rules') or {}):
                if rname not in _seen:
                    _seen.add(rname)
                    rule_names_seen.append(rname)

        # Build a minimal rule_bodies_by_name with just the names
        rule_bodies_by_name = {rn: {} for rn in rule_names_seen}
        return _compute_schema_hash(
            active, profiles_dirs, rule_bodies_by_name, rules_dirs, builtin_rules_dirs)
    except Exception:
        return None


def load_profile_rules(cfg):
    """Load and inflate compiled_rules.json into the in-memory form:
        { profile_name: { "merged": {…}, "rules": { rule_name: {weight+patterns} } } }

    Recompiles if the cache is missing, unreadable, hash-free, or stale.

    E.2 (v13.0.0): the cached schema_hash is now compared against a freshly
    computed hash of the source files. A mismatch triggers recompilation
    instead of silently using a stale cache.
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
        # E.2: compute the expected hash and compare it against the cached one
        current_hash = _current_schema_hash(cfg)
        if current_hash is None:
            # Cannot compute hash (config error). Fall through to compile which
            # will produce a proper error with a useful message.
            return True, 'hash computation failed'
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
    inflated    = {}
    for pname, pdata in doc['profiles'].items():
        per_rule = {
            rname: {'weight': rmeta.get('weight', 50), **rule_bodies[rname]}
            for rname, rmeta in (pdata.get('rules') or {}).items()
        }
        inflated[pname] = {'merged': pdata.get('merged') or {}, 'rules': per_rule}
    return inflated
