"""Load JSON config files with ${var} expansion, relative includes, and comment stripping."""
import copy
import json
import os
import re

VAR_RE = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')

# ── Lightweight config schema ─────────────────────────────────────────────────
#
# Each entry describes one key that may appear anywhere in the config tree.
# "path"  → string (or list of strings) resolved relative to config_dir.
# "bool"  → must be True/False (not 0/1).
# "int"   → must be an integer.
# "float" → must be a number.
# "str"   → must be a string.
# "list"  → must be a list.
# "dict"  → must be a dict.
#
# Path resolution is the only behaviour driven by this schema at load time.
# Type validation is consumed by lib/validation.py.

CONFIG_SCHEMA = {
    # kernel section
    'kernel': {
        '__type__': 'dict',
        'source_dir':       {'type': 'path',   'required': True},
        'rev_old':          {'type': 'str',    'required': True},
        'rev_new':          {'type': 'str',    'required': True},
        'kernel_config':    {'type': 'path'},
        'build_dir':        {'type': 'path'},
        'kernel_build_log': {'type': 'path'},
        'yocto_build_log':  {'type': 'path'},
        'dts_roots':        {'type': 'path',   'list': True},
    },
    # paths section — populated by load_config() from user config + derived values.
    # User may set work_dir (and optionally cache_dir/output_dir) directly;
    # cache_dir and output_dir default to <work_dir>/cache and <work_dir>/output.
    # profiles_dirs/rules_dirs/scoring_dir/templates_dir/css_override are
    # resolved from their source sections and written here for uniform access.
    'paths': {
        '__type__': 'dict',
        'work_dir':      {'type': 'path'},
        'cache_dir':     {'type': 'path'},
        'output_dir':    {'type': 'path'},
    },
    # profiles section
    'profiles': {
        '__type__': 'dict',
        'active':        {'type': 'dict'},
        'profiles_dirs': {'type': 'path', 'list': True},
    },
    # rules section
    'rules': {
        '__type__': 'dict',
        'rules_dirs': {'type': 'path', 'list': True},
    },
    # filter section
    'filter': {
        '__type__': 'dict',
        'enabled':                  {'type': 'bool'},
        'min_score':                {'type': 'float'},
        'path_blacklist_global':    {'type': 'bool'},
        'require_kconfig_coverage': {'type': 'bool'},
    },
    # collect section
    'collect': {
        '__type__': 'dict',
        'use_numstat':         {'type': 'bool'},
        'no_merges':           {'type': 'bool'},
        'first_parent':        {'type': 'bool'},
        'score_workers':       {'type': 'int'},
        'max_commits':         {'type': 'int'},
        'git_binary':          {'type': 'str'},
        'use_name_only':       {'type': 'bool'},
        'extra_git_log_args':  {'type': 'list'},
        'jsonl':               {'type': 'bool'},
        'include_parents':     {'type': 'bool'},
    },
    # scoring section
    'scoring': {
        '__type__': 'dict',
        'scoring_dir': {'type': 'path'},
    },
    # reports section
    'reports': {
        '__type__': 'dict',
        'outputs':       {'type': 'list'},
        'title':         {'type': 'str'},
        'top_n':         {'type': 'int'},
        'templates_dir': {'type': 'path'},
        'css_override':  {'type': 'path'},
    },
    # history_mapping section
    'history_mapping': {
        '__type__': 'dict',
        'mode':                   {'type': 'str'},
        'sample_step':            {'type': 'int'},
        'max_commits_per_probe':  {'type': 'int'},
        'max_failure_rate':       {'type': 'float'},
        'history_workers':        {'type': 'int'},
    },
}

# Flat set of all keys that are path-typed, derived from the schema.
# Used by _resolve_known_paths() — single source of truth.
_PATH_KEYS = frozenset(
    key
    for section in CONFIG_SCHEMA.values()
    for key, spec in section.items()
    if key != '__type__' and spec.get('type') == 'path'
)


# ── JSON helpers ──────────────────────────────────────────────────────────────

def load_json(path, default=None):
    """Return parsed JSON from *path*, or *default* when the file is absent."""
    if not os.path.exists(path):
        return default
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    """Persist *data* as indented JSON at *path*, creating parent dirs."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write('\n')


# ── Deep merge ────────────────────────────────────────────────────────────────

def deep_merge(base, patch):
    """Recursively merge *patch* dict into *base* in-place. Returns base."""
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return patch
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base


# ── Variable expansion ────────────────────────────────────────────────────────

def _expand_string(text, variables, stack=None):
    if stack is None:
        stack = []

    def repl(match):
        name = match.group(1)
        if name in stack:
            raise ValueError('cyclic variable reference: {}'.format(
                ' -> '.join(stack + [name])))
        if name not in variables:
            raise KeyError('undefined variable: {}'.format(name))
        value = variables[name]
        if not isinstance(value, str):
            value = str(value)
        return _expand_string(value, variables, stack + [name])

    prev = None
    cur = text
    while prev != cur:
        prev = cur
        cur = VAR_RE.sub(repl, cur)
    return cur


def _expand_node(node, variables):
    if isinstance(node, dict):
        return {k: _expand_node(v, variables) for k, v in node.items()}
    if isinstance(node, list):
        return [_expand_node(v, variables) for v in node]
    if isinstance(node, str):
        return _expand_string(node, variables)
    return node


# ── Comment stripping ─────────────────────────────────────────────────────────

INLINE_COMMENT_RE = re.compile(r'(^|(?<=\s))#.*$', re.MULTILINE)
_INLINE_SLASH_RE  = re.compile(r'(^|(?<=\s))//.*$', re.MULTILINE)


def _blank_comment(m):
    leading     = m.group(1)
    comment_len = len(m.group(0)) - len(leading)
    return leading + ' ' * comment_len


def _strip_json_comments(text):
    """Remove /* */, // and # comments from JSON-like text, preserving positions."""
    def _blank_block(m):
        return re.sub(r'[^\n]', ' ', m.group(0))

    text = re.sub(r'/\*.*?\*/', _blank_block, text, flags=re.S)

    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith('//'):
            cleaned_lines.append(' ' * len(line))
        else:
            line = _INLINE_SLASH_RE.sub(_blank_comment, line)
            line = INLINE_COMMENT_RE.sub(_blank_comment, line)
            cleaned_lines.append(line)
    return '\n'.join(cleaned_lines)


def _load_json(path):
    with open(path, encoding='utf-8') as fd:
        raw = fd.read()
    raw = _strip_json_comments(raw)
    return json.loads(raw)


# ── Path resolution (schema-driven) ──────────────────────────────────────────

def _resolve_path(value, base_dir):
    """Resolve *value* as a path relative to *base_dir*.

    Absolute paths, URLs, ${VAR} references, and empty strings are returned
    unchanged. Called only for keys whose schema entry has type='path'.
    """
    if not isinstance(value, str):
        return value
    if not value or '://' in value or value.startswith('${') \
            or value.startswith('/') or value.startswith('~'):
        return value
    return os.path.normpath(os.path.join(base_dir, value))


def _resolve_known_paths(node, base_dir):
    """Walk a config dict and resolve path-typed keys (driven by _PATH_KEYS).

    _PATH_KEYS is derived from CONFIG_SCHEMA, so adding a new path-typed key
    to the schema automatically enables resolution here — no separate edit needed.
    """
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k in _PATH_KEYS:
                out[k] = ([_resolve_path(i, base_dir) for i in v]
                          if isinstance(v, list)
                          else _resolve_path(v, base_dir))
            else:
                out[k] = _resolve_known_paths(v, base_dir)
        return out
    if isinstance(node, list):
        return [_resolve_known_paths(v, base_dir) for v in node]
    return node


# ── Config loader ─────────────────────────────────────────────────────────────

_ALLOWED_TOP_LEVEL = frozenset(CONFIG_SCHEMA.keys())


def _reject_unknown_keys(cfg):
    unknown = sorted(set(cfg) - _ALLOWED_TOP_LEVEL - {'vars'})
    if unknown:
        raise ValueError('unknown top-level keys: {}'.format(', '.join(unknown)))


def load_config(path, inherited_vars=None, seen=None):
    path = os.path.abspath(path)
    if seen is None:
        seen = set()
    if path in seen:
        raise ValueError('cyclic include detected: {}'.format(path))
    seen.add(path)

    cfg = _load_json(path)
    _reject_unknown_keys(cfg)
    config_dir = os.path.dirname(path)

    merged = {}
    for inc in cfg.get('include_configs', []) or []:
        inc_path = inc if os.path.isabs(inc) else os.path.join(config_dir, inc)
        inc_cfg = load_config(inc_path, inherited_vars=inherited_vars, seen=seen)
        deep_merge(merged, inc_cfg)

    local = copy.deepcopy(cfg)
    local.pop('include_configs', None)
    deep_merge(merged, local)

    vars_map = {}
    if inherited_vars:
        vars_map.update(inherited_vars)
    vars_map.setdefault('WORKSPACE', os.environ.get('WORKSPACE', vars_map.get('WORKSPACE', '')))
    vars_map.setdefault('TOOLDIR', os.environ.get('TOOLDIR',
        os.path.abspath(os.path.join(config_dir, '..'))))
    vars_map.setdefault('CONFIGDIR', config_dir)
    vars_map.setdefault('CWD', os.getcwd())

    for k, v in (merged.get('vars', {}) or {}).items():
        vars_map[k] = _expand_string(v, vars_map)
    merged['vars'] = vars_map

    expanded = _expand_node(merged, vars_map)
    expanded = _resolve_known_paths(expanded, config_dir)

    # ── Canonical paths namespace ─────────────────────────────────────────────
    work_raw = (expanded.get('paths', {}) or {}).get('work_dir', './work')
    work = (os.path.normpath(os.path.join(config_dir, work_raw))
            if not os.path.isabs(work_raw) else work_raw)

    _scoring_cfg = expanded.get('scoring', {}) or {}
    _scoring_raw = _scoring_cfg.get('scoring_dir')
    if _scoring_raw and not os.path.isabs(_scoring_raw):
        _scoring_raw = os.path.normpath(os.path.join(config_dir, _scoring_raw))
    scoring_dir  = _scoring_raw if _scoring_raw else os.path.join(config_dir, 'scoring')
    # templates_dir: from reports.templates_dir in config, else pipeline's own configs/html/
    _reports_cfg  = expanded.get('reports', {}) or {}
    _tool_dir     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _default_tpl  = os.path.join(_tool_dir, 'configs', 'html')
    _custom_tpl   = _reports_cfg.get('templates_dir')
    if _custom_tpl and not os.path.isabs(_custom_tpl):
        _custom_tpl = os.path.normpath(os.path.join(config_dir, _custom_tpl))
    templates_dir = _custom_tpl if _custom_tpl else _default_tpl
    _profiles_cfg = expanded.get('profiles', {}) or {}
    _rules_cfg    = expanded.get('rules', {}) or {}

    def _resolve_dir_list(cfg_section, key_plural, key_singular, default_dir):
        raw = cfg_section.get(key_plural)
        if raw in (None, [], ''):
            raw = cfg_section.get(key_singular)
        if raw not in (None, [], ''):
            entries = raw if isinstance(raw, list) else [raw]
            return [r if os.path.isabs(r) else os.path.normpath(os.path.join(config_dir, r))
                    for r in entries]
        return [default_dir]

    profiles_dirs = _resolve_dir_list(_profiles_cfg, 'profiles_dirs', 'profiles_dir',
                                      os.path.join(config_dir, 'profiles'))
    rules_dirs    = _resolve_dir_list(_rules_cfg, 'rules_dirs', 'rules_dir',
                                      os.path.join(config_dir, 'rules'))

    expanded['paths'] = {
        'work_dir':      work,
        'cache_dir':     os.path.join(work, 'cache'),
        'output_dir':    os.path.join(work, 'output'),
        'profiles_dirs': profiles_dirs,
        'rules_dirs':    rules_dirs,
        'scoring_dir':   scoring_dir,
        'templates_dir': templates_dir,
    }

    expanded['_meta'] = {
        'config_path': path,
        'config_dir':  config_dir,
        'vars':        vars_map,
    }
    expanded['config_dir'] = config_dir
    return expanded


# ── Override helper ───────────────────────────────────────────────────────────

def apply_override(cfg, override_json):
    """Parse *override_json* string and deep-merge into *cfg*.

    Raises SystemExit on parse error or non-object input.
    """
    try:
        patch = json.loads(override_json)
    except json.JSONDecodeError as exc:
        raise SystemExit('--override invalid JSON: {}'.format(exc))
    if not isinstance(patch, dict):
        raise SystemExit('--override top-level JSON value must be an object')
    return deep_merge(cfg, patch)
