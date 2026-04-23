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


def _strip_json_comments(text):
    """Best-effort removal of //, #, and /* */ style comments from JSON content.

    This keeps lines that do not start with a comment marker and removes
    block comments. It is intentionally simple and targets our config style
    (full-line comments), not arbitrary JSON-with-comments dialects.
    """
    # Remove C-style block comments first
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith('//') or stripped.startswith('#'):
            continue
        cleaned_lines.append(line)
    return '\n'.join(cleaned_lines)


def _load_json(path):
    with io.open(path, 'r', encoding='utf-8') as fd:
        raw = fd.read()
    raw = _strip_json_comments(raw)
    return json.loads(raw)


def load_config(path, inherited_vars=None, seen=None):
    path = os.path.abspath(path)
    if seen is None:
        seen = []
    if path in seen:
        raise ValueError('config include cycle detected: %s' % ' -> '.join(seen + [path]))

    data = _load_json(path)
    config_dir = os.path.dirname(path)

    # Seed variable map with inherited variables and environment-derived values.
    vars_map = {}
    if inherited_vars:
        vars_map.update(inherited_vars)
    vars_map.setdefault('config_dir', config_dir)
    vars_map.setdefault('cwd', os.getcwd())
    vars_map.setdefault('TOOLDIR', os.environ.get('TOOLDIR', os.path.abspath(os.path.join(config_dir, '..'))))
    if os.environ.get('WORKSPACE'):
        vars_map.setdefault('WORKSPACE', os.environ['WORKSPACE'])

    # Accept both "vars" and "variables" sections for user convenience.
    var_section = {}
    var_section.update(data.get('vars', {}))
    var_section.update(data.get('variables', {}))

    for key, value in var_section.items():
        # Keep shell-supplied WORKSPACE/TOOLDIR if the config simply mirrors them
        if key in ('WORKSPACE', 'TOOLDIR') and key in vars_map and isinstance(value, str) and value == '${%s}' % key:
            continue
        vars_map[key] = value

    # Expand variables, supporting nested ${var} references with cycle detection.
    expanded_vars = {}
    for key, value in vars_map.items():
        if isinstance(value, str) and '${' in value:
            expanded_vars[key] = _expand_string(value, vars_map, [key])
        else:
            expanded_vars[key] = value
    vars_map = expanded_vars

    # Recursively load and merge any included configs first.
    merged = {}
    for inc in data.get('include_configs', []):
        inc_expanded = _expand_string(inc, vars_map) if isinstance(inc, str) else inc
        if not os.path.isabs(inc_expanded):
            inc_expanded = os.path.normpath(os.path.join(config_dir, inc_expanded))
        child = load_config(inc_expanded, inherited_vars=vars_map, seen=seen + [path])
        deep_merge(merged, child)

    # Merge the current config body after variable expansion, excluding include list.
    body = copy.deepcopy(data)
    body.pop('include_configs', None)
    body = _expand_node(body, vars_map)
    deep_merge(merged, body)

    merged['_meta'] = {'config_path': path, 'config_dir': config_dir, 'vars': vars_map}
    return merged
