"""Load JSON/JSONC configurations, including optional ordered fragments.

v19.11.1:
  - deep_merge() gains a ``lists`` keyword: 'union' (default, used by the
    include mechanism: ordered union with stable deduplication) or 'replace'.
  - apply_override() (--override) now merges dicts recursively but REPLACES
    lists, as documented in docs/CONFIGURATION.md.
  - load_config() fails with a clear error when a built-in variable
    (WORKSPACE, TOOLDIR, CONFIGDIR, CWD) is empty AND referenced by the
    configuration, instead of silently expanding to '' (e.g. '/work').
    Configurations that never use the variable are unaffected.
"""
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
    'ai': {'__type__': 'dict', 'prompt_path': {'type': 'path'}, 'front_page_path': {'type': 'path'}, 'chunk_size': {'type': 'int'}},
}
_ALLOWED_TOP_LEVEL = frozenset(CONFIG_SCHEMA.keys()) | {'vars', 'include'}
_PATH_KEYS = frozenset(key for section in CONFIG_SCHEMA.values() for key, spec in section.items() if key != '__type__' and spec.get('type') == 'path')

# Environment variables that must be expanded for the pipeline to run
_ENV_VARS = frozenset(['WORKSPACE', 'TOOLDIR', 'CONFIGDIR', 'CWD'])

# Built-in variables that must be non-empty whenever the configuration uses them.
_REQUIRED_VARS = ('WORKSPACE', 'TOOLDIR', 'CONFIGDIR', 'CWD')


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


def _expand_string_partial(text, variables, stack=None):
    """Expand only environment variables, leaving intermediate vars unexpanded."""
    stack = [] if stack is None else stack
    def repl(match):
        name = match.group(1)
        if name in stack:
            raise ValueError('cyclic variable reference: ' + ' -> '.join(stack + [name]))
        # Only expand if it's an environment variable
        if name not in _ENV_VARS:
            return match.group(0)  # Keep unexpanded
        if name not in variables:
            return match.group(0)  # Keep as-is if not defined
        return _expand_string_partial(str(variables[name]), variables, stack + [name])
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


def _expand_node_partial(node, variables):
    """Expand only environment variables in the config."""
    if isinstance(node, dict):
        return {k: _expand_node_partial(v, variables) for k, v in node.items()}
    if isinstance(node, list):
        return [_expand_node_partial(v, variables) for v in node]
    return _expand_string_partial(node, variables) if isinstance(node, str) else node


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


def deep_merge(base, patch, source=None, events=None, path_prefix='', lists='union'):
    """Recursively merge patch into base in-place and return base.

    lists -- how two lists under the same key are combined:
      'union'   (default) ordered union with stable canonical-JSON
                deduplication; used by the include mechanism.
      'replace' the patch list overwrites the base list; used by --override.
    """
    if lists not in ('union', 'replace'):
        raise ValueError("lists must be 'union' or 'replace', got %r" % (lists,))
    if events is None:
        events = []
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return patch
    for key, value in patch.items():
        dotted = f"{path_prefix}.{key}" if path_prefix else key
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value, source, events, dotted, lists)
        elif lists == 'union' and isinstance(value, list) and isinstance(base.get(key), list):
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
    """Deep-merge a JSON object into cfg: dicts merge, scalars and lists are replaced."""
    try:
        patch = json.loads(override_json)
    except json.JSONDecodeError as exc:
        raise SystemExit('--override invalid JSON: {}'.format(exc))
    if not isinstance(patch, dict):
        raise SystemExit('--override top-level value must be an object')
    deep_merge(cfg, patch, lists='replace')
    return cfg


def _initial_variables(config_dir, inherited_vars=None):
    variables = dict(inherited_vars or {})
    variables.setdefault('WORKSPACE', os.environ.get('WORKSPACE', ''))
    tool_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    variables.setdefault('TOOLDIR', os.environ.get('TOOLDIR', tool_dir))
    variables.setdefault('CONFIGDIR', config_dir)
    variables.setdefault('CWD', os.getcwd())
    return variables


def _variable_definitions(initial, declarations):
    definitions = dict(initial)
    definitions.update(declarations)
    for key, value in declarations.items():
        if key in _ENV_VARS and key in initial:
            marker = '${%s}' % key
            if marker in str(value):
                _check_required_variables({'value': marker}, initial)
            definitions[key] = str(value).replace(marker, str(initial[key]))
    return definitions


def _context_variables(cfg, initial):
    declarations = cfg.get('vars', {}) or {}
    if not isinstance(declarations, dict):
        raise ValueError('configuration vars must be an object')
    definitions = _variable_definitions(initial, declarations)
    _check_required_variables(cfg, definitions)
    variables = {key: _expand_string(str(value), definitions)
                 for key, value in definitions.items()}
    _check_required_variables(cfg, variables)
    return variables


def _load_context(path, inherited_vars=None, seen=None):
    path = os.path.abspath(os.path.expanduser(os.fspath(path)))
    config_dir = os.path.dirname(path)
    initial = _initial_variables(config_dir, inherited_vars)
    loaded_files = []
    raw, events = _merge_includes(path, tuple(seen or ()), is_root=True,
                                  root_dir=config_dir, variables=initial,
                                  loaded_files=loaded_files)
    return {'path': path, 'config_dir': config_dir, 'raw': raw,
            'initial_vars': initial, 'inherited_vars': dict(inherited_vars or {}),
            'variables': _context_variables(raw, initial),
            'events': events, 'loaded_files': loaded_files}


def _partial_from_context(context):
    cfg = copy.deepcopy(context['raw'])
    env_vars = {key: context['variables'][key] for key in _ENV_VARS}
    declarations = dict(context['inherited_vars'])
    declarations.update(cfg.get('vars', {}) or {})
    cfg['vars'] = {key: env_vars[key] if key in _ENV_VARS
                   else _expand_string_partial(str(value), env_vars)
                   for key, value in declarations.items()}
    return _resolve_known_paths(_expand_node_partial(cfg, env_vars), context['config_dir'])


def _merge_includes(path, active, is_root=True, root_dir=None, variables=None, loaded_files=None):
    path = os.path.abspath(os.path.expanduser(os.fspath(path)))
    root_dir = root_dir or os.path.dirname(path)
    variables = _initial_variables(root_dir) if variables is None else variables
    if os.path.realpath(path) in {os.path.realpath(value) for value in active}:
        raise ValueError('cyclic include detected: ' + ' -> '.join(active + (path,)))
    if not os.path.isfile(path):
        raise FileNotFoundError('configuration/include file missing: ' + ' -> '.join(active + (path,)))
    raw = load_json(path)
    if loaded_files is not None:
        loaded_files.append(path)
    if not isinstance(raw, dict):
        raise ValueError('configuration must be an object: {}'.format(path))
    if 'include_configs' in raw:
        raise ValueError("unknown top-level key 'include_configs'; use 'include'")
    if is_root and set(raw) - _ALLOWED_TOP_LEVEL:
        raise ValueError('unknown top-level keys: {}'.format(', '.join(sorted(set(raw) - _ALLOWED_TOP_LEVEL))))
    includes = raw.get('include', [])
    if not isinstance(includes, list) or not all(isinstance(v, str) for v in includes):
        raise ValueError("'include' must be an array of strings")
    declarations = raw.get('vars', {}) or {}
    if not isinstance(declarations, dict):
        raise ValueError('configuration vars must be an object: ' + path)
    scope = _variable_definitions(variables, declarations)
    merged = {}
    events = []
    for include in includes:
        try:
            _check_required_variables({'include': [include]}, scope)
            reference = os.path.expanduser(_expand_string(include, scope))
        except (KeyError, ValueError) as exc:
            raise ValueError('include resolution failed in ' + ' -> '.join(active + (path,)) + ': ' + str(exc)) from exc
        if not reference.strip():
            raise ValueError('empty include reference in ' + path)
        child_path = reference if os.path.isabs(reference) else os.path.join(root_dir, reference)
        child_path = os.path.abspath(child_path)
        child, child_events = _merge_includes(child_path, active + (path,), is_root=False,
                                              root_dir=root_dir, variables=scope,
                                              loaded_files=loaded_files)
        events.append({'event': 'include_loaded', 'source': path, 'target': child_path})
        events.extend(child_events)
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
    path = os.path.abspath(os.path.expanduser(os.fspath(path)))
    cfg, _events = _merge_includes(path, tuple(), is_root=True)
    # Keep vars as-is without expansion
    # Do not resolve paths
    # Do not add _meta or config_dir
    return cfg


def _build_partial_expanded_config(path, inherited_vars=None, seen=None):
    """Build merged config with only environment variables expanded.
    
    This expands WORKSPACE, TOOLDIR, CONFIGDIR, CWD but leaves intermediate
    user-defined variables unexpanded (e.g., ${OUT} stays as ${OUT} even if
    OUT=${WORKSPACE}/output).
    
    Returns the merged config dict with:
    - Includes merged
    - Environment variables expanded in vars section
    - Intermediate variables kept unexpanded
    - Paths resolved only where they don't contain unexpanded vars
    - No _meta section added
    """
    return _partial_from_context(_load_context(path, inherited_vars, seen))


def _check_required_variables(cfg, variables):
    """Raise SystemExit when a built-in variable is empty but used by *cfg*.

    An empty WORKSPACE would otherwise expand ``${WORKSPACE}/work`` to
    ``/work`` and silently read or write the wrong place.  Variables that the
    configuration never references are not required.
    """
    text = json.dumps(cfg)
    for name in _REQUIRED_VARS:
        if not variables.get(name) and ('${%s}' % name) in text:
            raise SystemExit(
                'Config error: required variable {0} is not set. '
                'Set the {0} environment variable or define it in the config '
                '"vars" section.'.format(name))


def load_config(path, inherited_vars=None, seen=None):
    return _load_config_context(_load_context(path, inherited_vars, seen))


def _load_config_context(context):
    path = context['path']
    config_dir = context['config_dir']
    cfg = copy.deepcopy(context['raw'])
    variables = dict(context['variables'])
    cfg['vars'] = variables
    expanded = _resolve_known_paths(_expand_node(cfg, variables), config_dir)
    paths = expanded.setdefault('paths', {})
    work = paths.get('work_dir', os.path.join(config_dir, 'work'))
    if not os.path.isabs(work):
        work = os.path.normpath(os.path.join(config_dir, work))
    scoring = (expanded.get('scoring') or {}).get('scoring_dir') or os.path.join(config_dir, 'scoring')
    templates = (expanded.get('reports') or {}).get('templates_dir') or os.path.join(config_dir, 'html')
    assets = paths.get('assets_dir') or os.path.join(config_dir, 'assets')
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
    expanded['_meta'] = {'config_path': path, 'config_dir': config_dir,
                         'initial_config_path': path, 'initial_config_dir': config_dir,
                         'vars': variables, 'include_events': context['events'],
                         'loaded_files': list(context['loaded_files'])}
    expanded['config_dir'] = config_dir
    return expanded


def load_config_with_raw(path, inherited_vars=None, seen=None):
    """Load config and return both expanded and manifest-ready versions.
    
    Returns:
        tuple: (expanded_cfg, manifest_cfg) where:
            - expanded_cfg: Fully processed config (current load_config behavior)
            - manifest_cfg: Config with env vars expanded but intermediate vars preserved,
                           suitable for pipeline_config.json manifest
    """
    context = _load_context(path, inherited_vars, seen)
    return _load_config_context(context), _partial_from_context(context)
