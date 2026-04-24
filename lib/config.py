"""Load JSON config files with ${var} expansion, relative includes, and comment stripping.

v8.0 changes vs v7.19:
  - Dropped from __future__ import print_function and import io (Py2 dead code).
  - io.open() replaced with open(); %-formatting replaced with f-strings.
  - load_json() / save_json() helpers moved here from the deleted lib/io_utils.py.
  - cfg['paths'] canonical namespace added (work_dir, cache_dir, output_dir,
    profiles_dir, rules_dir, scoring_dir, templates_dir).  Legacy sub-keys
    (cfg['inputs'], cfg['profiles']['dir'], etc.) kept as aliases.
"""
import copy
import json
import os
import re

VAR_RE = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')


# ── JSON helpers (previously in lib/io_utils.py) ─────────────────────────────

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


# ── Config loader ─────────────────────────────────────────────────────────────

def deep_merge(dst, src):
    for key, value in src.items():
        if key in dst and isinstance(dst[key], dict) and isinstance(value, dict):
            deep_merge(dst[key], value)
        else:
            dst[key] = copy.deepcopy(value)
    return dst


def _expand_string(text, variables, stack=None):
    if stack is None:
        stack = []

    def repl(match):
        name = match.group(1)
        if name in stack:
            raise ValueError(f"cyclic variable reference: {' -> '.join(stack + [name])}")
        if name not in variables:
            raise KeyError(f'undefined variable: {name}')
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


def _strip_json_comments(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith('//') or stripped.startswith('#'):
            continue
        cleaned_lines.append(line)
    return '\n'.join(cleaned_lines)


def _load_json(path):
    with open(path, encoding='utf-8') as fd:
        raw = fd.read()
    raw = _strip_json_comments(raw)
    return json.loads(raw)


def _resolve_relative_paths(node, base_dir):
    if isinstance(node, dict):
        return {k: _resolve_relative_paths(v, base_dir) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_relative_paths(v, base_dir) for v in node]
    if isinstance(node, str):
        if '://' in node or node.startswith('${') or node.startswith('/') or node.startswith('~'):
            return node
        if '/' in node or node.startswith('.'):
            return os.path.normpath(os.path.join(base_dir, node))
    return node


def load_config(path, inherited_vars=None, seen=None):
    path = os.path.abspath(path)
    if seen is None:
        seen = set()
    if path in seen:
        raise ValueError(f'cyclic include detected: {path}')
    seen.add(path)

    cfg = _load_json(path)
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
    expanded = _resolve_relative_paths(expanded, config_dir)

    # ── Canonical paths namespace ─────────────────────────────────────────────
    work_raw = (expanded.get('project', {}) or {}).get('work_dir', './work')
    work = (os.path.normpath(os.path.join(config_dir, work_raw))
            if not os.path.isabs(work_raw) else work_raw)
    profiles_dir  = os.path.join(config_dir, 'profiles')
    rules_dir     = os.path.join(config_dir, 'rules')
    scoring_dir   = os.path.join(config_dir, 'scoring')
    templates_dir = os.path.join(config_dir, 'templates')

    expanded['paths'] = {
        'work_dir':      work,
        'cache_dir':     os.path.join(work, 'cache'),
        'output_dir':    os.path.join(work, 'output'),
        'profiles_dir':  profiles_dir,
        'rules_dir':     rules_dir,
        'scoring_dir':   scoring_dir,
        'templates_dir': templates_dir,
    }

    # Legacy aliases — deprecated, kept for internal libs during this release
    inputs = expanded.setdefault('inputs', {})
    inputs.setdefault('profiles_dir',  profiles_dir)
    inputs.setdefault('rules_dir',     rules_dir)
    inputs.setdefault('scoring_dir',   scoring_dir)
    inputs.setdefault('templates_dir', templates_dir)
    expanded.setdefault('profiles', {}).setdefault('dir', profiles_dir)
    expanded.setdefault('rules',    {}).setdefault('dir', rules_dir)
    expanded.setdefault('templates',{}).setdefault('base_dir', templates_dir)

    expanded['_meta'] = {
        'config_path': path,
        'config_dir':  config_dir,
        'vars':        vars_map,
    }
    expanded['config_dir'] = config_dir
    return expanded
