# Load JSON config files with support for relative includes, ${var} expansion,
# and selected environment-variable fallbacks such as WORKSPACE and TOOLDIR.
from __future__ import print_function
import copy
import io
import json
import os
import re

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
        return dict((k, _expand_node(v, variables)) for k, v in node.items())
    if isinstance(node, list):
        return [_expand_node(v, variables) for v in node]
    if isinstance(node, str):
        return _expand_string(node, variables)
    return node

def _load_json(path):
    with io.open(path, 'r', encoding='utf-8') as fd:
        return json.load(fd)

def load_config(path, inherited_vars=None, seen=None):
    path = os.path.abspath(path)
    if seen is None:
        seen = []
    if path in seen:
        raise ValueError('config include cycle detected: %s' % ' -> '.join(seen + [path]))
    data = _load_json(path)
    config_dir = os.path.dirname(path)
    vars_map = {}
    if inherited_vars:
        vars_map.update(inherited_vars)
    vars_map.setdefault('config_dir', config_dir)
    vars_map.setdefault('cwd', os.getcwd())
    vars_map.setdefault('TOOLDIR', os.environ.get('TOOLDIR', os.path.abspath(os.path.join(config_dir, '..'))))
    if os.environ.get('WORKSPACE'):
        vars_map.setdefault('WORKSPACE', os.environ['WORKSPACE'])
    for key, value in data.get('vars', {}).items():
        if key in ('WORKSPACE', 'TOOLDIR') and key in vars_map and isinstance(value, str) and value == '${%s}' % key:
            continue
        vars_map[key] = value
    expanded_vars = {}
    for key, value in vars_map.items():
        if isinstance(value, str) and '${' in value:
            expanded_vars[key] = _expand_string(value, vars_map, [key])
        else:
            expanded_vars[key] = value
    vars_map = expanded_vars
    merged = {}
    for inc in data.get('include_configs', []):
        inc_expanded = _expand_string(inc, vars_map) if isinstance(inc, str) else inc
        if not os.path.isabs(inc_expanded):
            inc_expanded = os.path.normpath(os.path.join(config_dir, inc_expanded))
        child = load_config(inc_expanded, inherited_vars=vars_map, seen=seen + [path])
        deep_merge(merged, child)
    body = copy.deepcopy(data)
    body.pop('include_configs', None)
    body = _expand_node(body, vars_map)
    deep_merge(merged, body)
    merged['_meta'] = {'config_path': path, 'config_dir': config_dir, 'vars': vars_map}
    return merged
