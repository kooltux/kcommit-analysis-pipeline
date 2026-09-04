"""Load JSON/JSONC configurations, including optional ordered fragments."""
from __future__ import annotations

import copy
import json
import os
import re
import warnings
from pathlib import Path
from typing import Any, Dict, List, Tuple

VAR_RE = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')
INLINE_COMMENT_RE = re.compile(r'(^|(?<=\s))#.*$', re.MULTILINE)

CONFIG_SCHEMA = {
    'kernel': {'__type__': 'dict', 'source_dir': {'type': 'path', 'required': True}, 'rev_old': {'type': 'str', 'required': True}, 'rev_new': {'type': 'str', 'required': True}, 'kernel_config': {'type': 'path'}, 'build_dir': {'type': 'path'}, 'kernel_build_log': {'type': 'path'}, 'yocto_build_log': {'type': 'path'}, 'dts_roots': {'type': 'path', 'list': True}},
    'paths': {'__type__': 'dict', 'work_dir': {'type': 'path'}, 'cache_dir': {'type': 'path'}, 'output_dir': {'type': 'path'}, 'assets_dir': {'type': 'path'}, 'profiles_dirs': {'type': 'path', 'list': True}, 'rules_dirs': {'type': 'path', 'list': True}, 'scoring_dir': {'type': 'path'}, 'templates_dir': {'type': 'path'}},
    'profiles': {'__type__': 'dict', 'active': {'type': 'dict'}, 'profiles_dirs': {'type': 'path', 'list': True}, 'profiles_dir': {'type': 'path'}},
    'rules': {'__type__': 'dict', 'rules_dirs': {'type': 'path', 'list': True}, 'rules_dir': {'type': 'path'}},
    'filter': {'__type__': 'dict', 'enabled': {'type': 'bool'}, 'min_score': {'type': 'float'}, 'path_blacklist_global': {'type': 'bool'}, 'require_kconfig_coverage': {'type': 'bool'}},
    'collect': {'__type__': 'dict', 'use_numstat': {'type': 'bool'}, 'count_hunks': {'type': 'bool'}, 'cherry_pick_test': {'type': 'bool'}, 'cherry_pick_cache_dir': {'type': 'path'}, 'cherry_pick_workers': {'type': 'int'}, 'no_merges': {'type': 'bool'}, 'first_parent': {'type': 'bool'}, 'score_workers': {'type': 'int'}, 'max_commits': {'type': 'int'}, 'git_binary': {'type': 'str'}, 'use_name_only': {'type': 'bool'}, 'extra_git_log_args': {'type': 'list'}, 'jsonl': {'type': 'bool'}, 'include_parents': {'type': 'bool'}},
    'scoring': {'__type__': 'dict', 'scoring_dir': {'type': 'path'}},
    'reports': {'__type__': 'dict', 'outputs': {'type': 'list'}, 'title': {'type': 'str'}, 'top_n': {'type': 'int'}, 'templates_dir': {'type': 'path'}, 'css_override': {'type': 'path'}},
    'history_mapping': {'__type__': 'dict', 'mode': {'type': 'str'}, 'sample_step': {'type': 'int'}, 'max_commits_per_probe': {'type': 'int'}, 'max_failure_rate': {'type': 'float'}, 'history_workers': {'type': 'int'}},
    'ai': {'__type__': 'dict', 'prompt_path': {'type': 'path'}, 'chunk_size': {'type': 'int'}},
}
_ALLOWED_TOP_LEVEL = frozenset(CONFIG_SCHEMA.keys()) | {'vars', 'include'}
_PATH_KEYS = frozenset(key for section in CONFIG_SCHEMA.values() for key, spec in section.items() if key != '__type__' and spec.get('type') == 'path')


def _strip_json_comments(text: str) -> str:
    out, in_string, escaped, i = [], False, False, 0
    while i < len(text):
        ch = text[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
        elif ch == '"':
            in_string = True
            out.append(ch)
            i += 1
        elif ch == '/' and i + 1 < len(text) and text[i + 1] == '/':
            end = text.find('\n', i)
            if end < 0:
                break
            out.append('\n')
            i = end + 1
        elif ch == '/' and i + 1 < len(text) and text[i + 1] == '*':
            end = text.find('*/', i + 2)
            if end < 0:
                break
            out.extend('\n' if c == '\n' else ' ' for c in text[i:end + 2])
            i = end + 2
        elif ch == '#':
            end = text.find('\n', i)
            if end < 0:
                break
            out.append('\n')
            i = end + 1
        else:
            out.append(ch)
            i += 1
    return ''.join(out)


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding='utf-8') as f:
        return json.loads(_strip_json_comments(f.read()))


def _load_json(path, default=None):
    return load_json(path, default=default)


def save_json(path, data):
    os.makedirs(os.path.dirname(str(path)) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write('\n')


def _expand_string(text, variables, stack=None):
    stack = [] if stack is None else stack
    def repl(match):
        name = match.group(1)
        if name in stack:
            raise ValueError('cyclic variable reference: ' + ' -> '.join(stack + [name]))
        if name not in variables:
            raise KeyError('undefined variable: ' + name)
        return _expand_string(str(variables[name]), variables, stack + [name])
    previous = None
    while previous != text:
        previous, text = text, VAR_RE.sub(repl, text)
    return text


def _expand_node(node, variables):
    if isinstance(node, dict):
        return {k: _expand_node(v, variables) for k, v in node.items()}
    if isinstance(node, list):
        return [_expand_node(v, variables) for v in node]
    return _expand_string(node, variables) if isinstance(node, str) else node


def _resolve_path(value, base_dir):
    if not isinstance(value, str) or not value or '://' in value or value.startswith(('/', '~', '${')):
        return value
    return os.path.normpath(os.path.join(base_dir, value))


def _resolve_known_paths(node, base_dir):
    if isinstance(node, dict):
        return {k: ([_resolve_path(v, base_dir) for v in value] if k in _PATH_KEYS and isinstance(value, list) else _resolve_path(value, base_dir) if k in _PATH_KEYS else _resolve_known_paths(value, base_dir)) for k, value in node.items()}
    if isinstance(node, list):
        return [_resolve_known_paths(v, base_dir) for v in node]
    return node


def deep_merge(base, patch, source=None, events=None, path_prefix=''):
    """Recursively merge patch into base in-place and return base."""
    if events is None:
        events = []
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return patch
    for key, value in patch.items():
        dotted = f"{path_prefix}.{key}" if path_prefix else key
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value, source, events, dotted)
        elif isinstance(value, list) and isinstance(base.get(key), list):
            seen = {json.dumps(v, sort_keys=True, separators=(',', ':')) for v in base[key]}
            for item in value:
                marker = json.dumps(item, sort_keys=True, separators=(',', ':'))
                if marker not in seen:
                    base[key].append(copy.deepcopy(item))
                    seen.add(marker)
        else:
            if source is not None and key in base and base[key] != value:
                events.append({"path": dotted, "event": "scalar_replaced", "source": source, "old_value": base[key], "new_value": value})
                warnings.warn(f"Repeated assignment at '{dotted}' from {source}")
            base[key] = copy.deepcopy(value)
    return base


def apply_override(cfg, override_json):
    try:
        patch = json.loads(override_json)
    except json.JSONDecodeError as exc:
        raise SystemExit('--override invalid JSON: {}'.format(exc))
    if not isinstance(patch, dict):
        raise SystemExit('--override top-level value must be an object')
    deep_merge(cfg, patch)
    return cfg


def _merge_includes(path, active, is_root=True):
    path = os.path.abspath(path)
    if path in active:
        raise ValueError('cyclic include detected: {}'.format(path))
    raw = load_json(path)
    if not isinstance(raw, dict):
        raise ValueError('configuration must be an object: {}'.format(path))
    if 'include_configs' in raw:
        raise ValueError("unknown top-level key 'include_configs'; use 'include'")
    if is_root and set(raw) - _ALLOWED_TOP_LEVEL:
        raise ValueError('unknown top-level keys: {}'.format(', '.join(sorted(set(raw) - _ALLOWED_TOP_LEVEL))))
    includes = raw.get('include', [])
    if not isinstance(includes, list) or not all(isinstance(v, str) for v in includes):
        raise ValueError("'include' must be an array of strings")
    merged = {}
    events = []
    for include in includes:
        child_path = include if os.path.isabs(include) else os.path.join(os.path.dirname(path), include)
        child, child_events = _merge_includes(child_path, active + (path,), is_root=False)
        for key, value in child.items():
            if key not in merged:
                merged[key] = copy.deepcopy(value)
            elif isinstance(value, dict) and isinstance(merged[key], dict):
                deep_merge(merged[key], value, source=child_path, events=events, path_prefix=key)
            elif isinstance(value, list) and isinstance(merged[key], list):
                seen = {json.dumps(v, sort_keys=True, separators=(',', ':')) for v in merged[key]}
                added = []
                for item in value:
                    marker = json.dumps(item, sort_keys=True, separators=(',', ':'))
                    if marker not in seen:
                        seen.add(marker)
                        added.append(copy.deepcopy(item))
                if added:
                    merged[key].extend(added)
                    events.append({"path": key, "event": "array_contribution", "source": child_path, "added": added})
                    warnings.warn(f"Array contribution at '{key}' from {child_path}")
            else:
                events.append({"path": key, "event": "scalar_replaced", "source": child_path, "old_value": merged[key], "new_value": value})
                warnings.warn(f"Repeated assignment at '{key}' from {child_path}")
                merged[key] = copy.deepcopy(value)
    own = copy.deepcopy(raw)
    own.pop('include', None)
    for key, value in own.items():
        if key not in merged:
            merged[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(merged[key], dict):
            deep_merge(merged[key], value, source=path, events=events, path_prefix=key)
        elif isinstance(value, list) and isinstance(merged[key], list):
            seen = {json.dumps(v, sort_keys=True, separators=(',', ':')) for v in merged[key]}
            added = []
            for item in value:
                marker = json.dumps(item, sort_keys=True, separators=(',', ':'))
                if marker not in seen:
                    seen.add(marker)
                    added.append(copy.deepcopy(item))
            if added:
                merged[key].extend(added)
                events.append({"path": key, "event": "array_contribution", "source": path, "added": added})
                warnings.warn(f"Array contribution at '{key}' from {path}")
        else:
            events.append({"path": key, "event": "scalar_replaced", "source": path, "old_value": merged[key], "new_value": value})
            warnings.warn(f"Repeated assignment at '{key}' from {path}")
            merged[key] = copy.deepcopy(value)
    return merged, events


def _build_raw_merged_config(path):
    """Build the merged config without variable expansion or path resolution.
    
    This is used for generating pipeline_config.json manifest that preserves
    the original variable references (e.g., ${WORKSPACE}/work) for reproducibility.
    
    Returns the merged config dict with minimal processing:
    - Includes are merged
    - vars section is kept as-is (not expanded)
    - paths are not resolved
    - No _meta section added
    """
    path = os.path.abspath(path)
    cfg, _events = _merge_includes(path, tuple(), is_root=True)
    # Keep vars as-is without expansion
    # Do not resolve paths
    # Do not add _meta or config_dir
    return cfg


def load_config(path, inherited_vars=None, seen=None):
    path = os.path.abspath(path)
    cfg, _events = _merge_includes(path, tuple(seen or ()), is_root=True)
    config_dir = os.path.dirname(path)
    variables = dict(inherited_vars or {})
    variables.setdefault('WORKSPACE', os.environ.get('WORKSPACE', ''))
    variables.setdefault('TOOLDIR', os.environ.get('TOOLDIR', os.path.abspath(os.path.join(config_dir, '..'))))
    variables.setdefault('CONFIGDIR', config_dir)
    variables.setdefault('CWD', os.getcwd())
    user_vars = cfg.get('vars', {}) or {}
    for key, value in user_vars.items():
        variables[key] = _expand_string(str(value), variables)
    cfg['vars'] = variables
    expanded = _resolve_known_paths(_expand_node(cfg, variables), config_dir)
    paths = expanded.setdefault('paths', {})
    work = paths.get('work_dir', os.path.join(config_dir, 'work'))
    if not os.path.isabs(work):
        work = os.path.normpath(os.path.join(config_dir, work))
    tool_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    scoring = (expanded.get('scoring') or {}).get('scoring_dir') or os.path.join(config_dir, 'scoring')
    templates = (expanded.get('reports') or {}).get('templates_dir') or os.path.join(tool_dir, 'configs', 'html')
    assets = paths.get('assets_dir') or os.path.join(tool_dir, 'configs', 'assets')
    profiles = (expanded.get('profiles') or {})
    rules = (expanded.get('rules') or {})
    def dirs(section, plural, singular, default):
        raw = section.get(plural, section.get(singular))
        vals = raw if isinstance(raw, list) else [raw] if raw else [default]
        return [v if os.path.isabs(v) else os.path.normpath(os.path.join(config_dir, v)) for v in vals]
    expanded['paths'] = {
        'work_dir': work,
        'cache_dir': paths.get('cache_dir') or os.path.join(work, 'cache'),
        'output_dir': paths.get('output_dir') or os.path.join(work, 'output'),
        'assets_dir': assets,
        'profiles_dirs': dirs(profiles, 'profiles_dirs', 'profiles_dir', os.path.join(config_dir, 'profiles')),
        'rules_dirs': dirs(rules, 'rules_dirs', 'rules_dir', os.path.join(config_dir, 'rules')),
        'scoring_dir': scoring,
        'templates_dir': templates,
    }
    expanded['_meta'] = {'config_path': path, 'config_dir': config_dir, 'vars': variables, 'include_events': _events}
    expanded['config_dir'] = config_dir
    return expanded


def load_config_with_raw(path, inherited_vars=None, seen=None):
    """Load config and return both expanded and raw (non-expanded) versions.
    
    Returns:
        tuple: (expanded_cfg, raw_cfg) where:
            - expanded_cfg: Fully processed config (current load_config behavior)
            - raw_cfg: Merged config with original variable references preserved,
                       suitable for pipeline_config.json manifest
    """
    expanded = load_config(path, inherited_vars=inherited_vars, seen=seen)
    raw = _build_raw_merged_config(path)
    return expanded, raw
