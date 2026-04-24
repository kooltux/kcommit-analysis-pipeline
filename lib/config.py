# Load JSON config files with support for relative includes, ${var} expansion,
# and selected environment-variable fallbacks such as WORKSPACE and TOOLDIR.
import copy
import json
import os
import re
from lib.io_utils import load_json_with_comments

VAR_RE = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')


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
            raise ValueError('cyclic variable reference: %s' % ' -> '.join(stack + [name]))
        if name not in variables:
            raise KeyError('undefined variable: %s' % name)
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
        raise ValueError('cyclic include detected: %s' % path)
    seen.add(path)

    cfg = load_json_with_comments(path)
    config_dir = os.path.dirname(path)

    merged = {}
    include_configs = cfg.get('include_configs', []) or []
    for inc in include_configs:
        inc_path = inc
        if not os.path.isabs(inc_path):
            inc_path = os.path.join(config_dir, inc_path)
        inc_cfg = load_config(inc_path, inherited_vars=inherited_vars, seen=seen)
        deep_merge(merged, inc_cfg)

    local = copy.deepcopy(cfg)
    local.pop('include_configs', None)
    deep_merge(merged, local)

    vars_map = {}
    if inherited_vars:
        vars_map.update(inherited_vars)
    vars_map.setdefault('WORKSPACE', os.environ.get('WORKSPACE', vars_map.get('WORKSPACE', '')))
    vars_map.setdefault('TOOLDIR', os.environ.get('TOOLDIR', os.path.abspath(os.path.join(config_dir, '..'))))
    vars_map.setdefault('CONFIGDIR', config_dir)
    vars_map.setdefault('CWD', os.getcwd())

    cfg_vars = merged.get('vars', {}) or {}
    for k, v in cfg_vars.items():
        vars_map[k] = _expand_string(v, vars_map)
    merged['vars'] = vars_map

    expanded = _expand_node(merged, vars_map)
    
    # Path resolution: inputs/profiles/rules are relative to config_dir.
    # project/output paths are relative to current working directory.
    cwd = os.getcwd()
    for key in list(expanded.keys()):
        if key in ('project', 'output', 'kernel', 'collect'):
            expanded[key] = _resolve_relative_paths(expanded[key], cwd)
        elif key not in ('vars', '_meta'):
            expanded[key] = _resolve_relative_paths(expanded[key], config_dir)

    inputs = expanded.setdefault('inputs', {})
    inputs.setdefault('profiles_dir', os.path.join(config_dir, 'profiles'))
    inputs.setdefault('rules_dir', os.path.join(config_dir, 'rules'))
    inputs.setdefault('scoring_dir', os.path.join(config_dir, 'scoring'))
    inputs.setdefault('templates_dir', os.path.join(config_dir, 'templates'))

    # Remove legacy keys if still present in loaded config
    for sec, key in [('profiles', 'dir'), ('rules', 'dir'), ('templates', 'base_dir')]:
        if sec in expanded:
            expanded[sec].pop(key, None)

    expanded['_meta'] = {
        'config_path': path,
        'config_dir': config_dir,
        'vars': vars_map,
    }
    return expanded
