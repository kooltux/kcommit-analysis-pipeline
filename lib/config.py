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
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Tuple

VAR_RE = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')
INLINE_COMMENT_RE = re.compile(r'(^|(?<=\s))#.*$', re.MULTILINE)

CONFIG_SCHEMA = {
    # Path attributes (v20.1.0): kind=file|dir, access=read|create, needs=always|ai|html,
    # severity=error|notice, default=<relative path under the initial config dir>,
    # content=text|markdown|json|ai_result_schema.  Validation is driven by these.
    'kernel': {'__type__': 'dict',
               'source_dir': {'type': 'path', 'kind': 'dir', 'severity': 'notice'},
               'rev_old': {'type': 'str', 'required': True},
               'rev_new': {'type': 'str', 'required': True},
               'kernel_config': {'type': 'path', 'kind': 'file', 'severity': 'notice'},
               'build_dir': {'type': 'path', 'kind': 'dir', 'severity': 'notice'},
               'kernel_build_log': {'type': 'path', 'kind': 'file', 'severity': 'notice'},
               'yocto_build_log': {'type': 'path', 'kind': 'file', 'severity': 'notice'},
               'dts_roots': {'type': 'path', 'list': True, 'kind': 'dir', 'severity': 'notice'}},
    'paths': {'__type__': 'dict',
              'work_dir': {'type': 'path', 'kind': 'dir', 'access': 'create'},
              'cache_dir': {'type': 'path', 'kind': 'dir', 'access': 'create'},
              'output_dir': {'type': 'path', 'kind': 'dir', 'access': 'create'},
              'assets_dir': {'type': 'path', 'kind': 'dir', 'severity': 'notice'},
              'profiles_dirs': {'type': 'path', 'list': True, 'kind': 'dir'},
              'rules_dirs': {'type': 'path', 'list': True, 'kind': 'dir'},
              'scoring_dir': {'type': 'path', 'kind': 'dir', 'severity': 'notice'},
              'templates_dir': {'type': 'path', 'kind': 'dir', 'needs': 'html'}},
    'profiles': {'__type__': 'dict', 'active': {'type': 'dict'}, 'profiles_dirs': {'type': 'path', 'list': True, 'kind': 'dir'}},
    'rules': {'__type__': 'dict', 'rules_dirs': {'type': 'path', 'list': True, 'kind': 'dir'}},
    'filter': {'__type__': 'dict', 'enabled': {'type': 'bool'}, 'min_score': {'type': 'float'}, 'path_blacklist_global': {'type': 'bool'}, 'require_kconfig_coverage': {'type': 'bool'}},
    'collect': {'__type__': 'dict', 'use_numstat': {'type': 'bool'}, 'count_hunks': {'type': 'bool'}, 'cherry_pick_test': {'type': 'bool'}, 'cherry_pick_cache_dir': {'type': 'path', 'kind': 'dir', 'access': 'create'}, 'cherry_pick_workers': {'type': 'int'}, 'no_merges': {'type': 'bool'}, 'first_parent': {'type': 'bool'}, 'score_workers': {'type': 'int'}, 'max_commits': {'type': 'int'}, 'git_binary': {'type': 'str'}, 'use_name_only': {'type': 'bool'}, 'extra_git_log_args': {'type': 'list'}, 'jsonl': {'type': 'bool'}, 'include_parents': {'type': 'bool'}},
    'scoring': {'__type__': 'dict', 'scoring_dir': {'type': 'path', 'kind': 'dir', 'severity': 'notice'}},
    'reports': {'__type__': 'dict', 'outputs': {'type': 'list'}, 'title': {'type': 'str'}, 'top_n': {'type': 'int'},
                'templates_dir': {'type': 'path', 'kind': 'dir', 'needs': 'html'},
                'css_override': {'type': 'path', 'kind': 'file', 'needs': 'html', 'content': 'text'}},
    'history_mapping': {'__type__': 'dict', 'mode': {'type': 'str'}, 'sample_step': {'type': 'int'}, 'max_commits_per_probe': {'type': 'int'}, 'max_failure_rate': {'type': 'float'}, 'history_workers': {'type': 'int'}},
    # The ai section is active when present unless ai.enabled is false (see ai_active()).
    'ai': {'__type__': 'dict',
           'enabled': {'type': 'bool'},
           'prompt_path': {'type': 'path', 'kind': 'file', 'needs': 'ai', 'default': 'ai/ai_analysis_prompt.md', 'content': 'markdown'},
           'front_page_path': {'type': 'path', 'kind': 'file', 'needs': 'ai', 'default': 'ai/ai_server_front_page.md', 'content': 'markdown'},
           'result_schema_path': {'type': 'path', 'kind': 'file', 'needs': 'ai', 'default': 'ai/ai_analysis_result_schema.json', 'content': 'ai_result_schema'},
           'chunk_size': {'type': 'int', 'min': 1}},
}


def ai_active(cfg):
    """True when the configuration declares an ``ai`` section not disabled.

    v20.1.0: AI preparation (Stage 08) and AI asset validation are driven by
    the configuration only.  A missing ``ai`` section or ``ai.enabled: false``
    disables both.
    """
    section = (cfg or {}).get('ai')
    return isinstance(section, dict) and section.get('enabled', True) is not False


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


def _relative_value(value, base_dir, aliases=None):
    """Return *value* relative to *base_dir* when it is an absolute filesystem path.

    Anything else (relative paths, URLs, empty strings, values with unresolved
    ``${VAR}`` references, ``~`` paths, non-strings) is returned unchanged.
    *aliases* is an optional callable returning the symlink alias map used to find
    a shorter spelling when the plain result climbs three levels or more.
    """
    if (not isinstance(value, str) or not value or '://' in value or '${' in value
            or not os.path.isabs(value)):
        return value
    best = _physical_relpath(value, base_dir)
    if aliases is None or _climb(best) < _ALIAS_MIN_CLIMB:
        return best
    for candidate in _alias_candidates(value, aliases()):
        rel = _physical_relpath(candidate, base_dir)
        if (_climb(rel), len(rel)) < (_climb(best), len(best)):
            best = rel
    return best


_ALIAS_MIN_CLIMB = 3      # only look for symlink aliases when the path climbs this much
_ALIAS_MAX_DEPTH = 3      # directory levels explored below each ancestor of the base
_ALIAS_PER_DIR = 1000     # entries examined per directory
_ALIAS_MAX_ENTRIES = 20000  # entries examined in total


def _climb(rel):
    """Number of leading '..' components of a relative path."""
    count = 0
    for part in rel.split('/'):
        if part != '..':
            break
        count += 1
    return count


def _symlink_aliases(base_dir):
    """Map real directory -> nearest symlink spelling found around *base_dir*.

    Directories below every ancestor of *base_dir* are explored (nearest ancestor
    first, bounded in depth and entry count, symlinks never followed while walking)
    and every symlink to a directory is recorded under its real target.  A path
    inside such a target can then be spelled through the (usually nearer) symlink.
    """
    aliases = {}
    seen = set()
    budget = [_ALIAS_MAX_ENTRIES]

    def scan(path, depth):
        if depth > _ALIAS_MAX_DEPTH or budget[0] <= 0 or path in seen:
            return
        seen.add(path)
        try:
            iterator = os.scandir(path)
        except OSError:
            return
        with iterator:
            for number, entry in enumerate(iterator):
                if number >= _ALIAS_PER_DIR or budget[0] <= 0:
                    break
                budget[0] -= 1
                try:
                    if entry.is_symlink():
                        if entry.is_dir():
                            aliases.setdefault(os.path.realpath(entry.path), entry.path)
                    elif entry.is_dir(follow_symlinks=False):
                        scan(entry.path, depth + 1)
                except OSError:
                    continue

    parts = [p for p in os.path.normpath(base_dir).split(os.sep) if p]
    for count in range(len(parts), -1, -1):
        scan(os.sep + os.sep.join(parts[:count]), 1)
    return aliases


def _alias_candidates(value, aliases):
    """Spellings of *value* through the known directory symlinks."""
    parts = [p for p in os.path.realpath(value).split(os.sep) if p]
    for count in range(len(parts), 0, -1):
        alias = aliases.get(os.sep + os.sep.join(parts[:count]))
        if alias:
            yield os.path.join(alias, *parts[count:])


def _physical_relpath(value, base_dir):
    """Shortest relative path from *base_dir* to *value*, comparing real locations.

    The deepest ancestor of *base_dir* that is the same filesystem object as an
    ancestor of *value* (``os.path.samestat``) is used as the common root, so
    symlinks, bind mounts and differently spelled mount points (for example
    ``/net/storage/AI`` seen through two paths) do not make the result climb to
    ``/`` and come back down.  Without a common object other than ``/`` (or when
    the paths cannot be examined) the purely lexical relative path is returned.
    """
    v = [p for p in os.path.normpath(value).split(os.sep) if p]
    b = [p for p in os.path.normpath(base_dir).split(os.sep) if p]

    def anchor(parts, count):
        return os.sep + os.sep.join(parts[:count])

    v_stats = []
    for j in range(len(v), -1, -1):
        try:
            v_stats.append((j, os.stat(anchor(v, j))))
        except OSError:
            continue
    for i in range(len(b), -1, -1):
        try:
            base_stat = os.stat(anchor(b, i))
        except OSError:
            continue
        for j, stat in v_stats:
            if os.path.samestat(base_stat, stat):
                return '/'.join(['..'] * (len(b) - i) + v[j:]) or '.'
    return os.path.relpath(value, base_dir)


def relativize_paths(cfg, base_dir):
    """Return a deep copy of *cfg* whose absolute paths are relative to *base_dir*.

    v20.1.1: used for the exported ``output/pipeline_config.json`` so that the
    manifest holds no absolute path and can be moved anywhere together with the
    output directory.  Values of every schema ``path`` key (scalars and list
    items, in any section) and every absolute value of the top-level ``vars``
    section are converted; other strings are never rewritten.  ``vars.CONFIGDIR``
    is the directory of the original configuration file and is converted like
    every other path (it is not the directory of the exported file).
    """
    base_dir = os.path.realpath(os.path.abspath(os.fspath(base_dir)))
    alias_map = []

    def aliases():
        # Symlink aliases are explored lazily, once, only when a path climbs far.
        if not alias_map:
            alias_map.append(_symlink_aliases(base_dir))
        return alias_map[0]

    def rel(value):
        return _relative_value(value, base_dir, aliases)

    def convert(node, top=False):
        if isinstance(node, dict):
            out = {}
            for key, value in node.items():
                if top and key == 'vars' and isinstance(value, dict):
                    out[key] = {k: rel(v) for k, v in value.items()}
                elif key in _PATH_KEYS and isinstance(value, list):
                    out[key] = [rel(v) for v in value]
                elif key in _PATH_KEYS:
                    out[key] = rel(value)
                else:
                    out[key] = convert(value)
            return out
        if isinstance(node, list):
            return [convert(v) for v in node]
        return node

    return convert(copy.deepcopy(cfg), top=True)


_EXPLICIT_PATHS = (
    ('paths', 'work_dir'), ('paths', 'cache_dir'), ('paths', 'output_dir'),
    ('paths', 'assets_dir'), ('profiles', 'profiles_dirs'), ('rules', 'rules_dirs'),
    ('scoring', 'scoring_dir'), ('reports', 'templates_dir'),
)


def materialize_resources(manifest_cfg, runtime_cfg):
    """Return a copy of *manifest_cfg* with every implicit resource location explicit.

    v20.1.1: the exported configuration must reproduce the run when it is used as
    the initial configuration from another directory.  Locations that were only
    conventional (``profiles/``, ``rules/``, ``scoring/``, ``html/``, ``assets/``
    under the original configuration directory, the work/cache/output directories
    and the ``ai`` assets) are copied from the loaded *runtime_cfg* into the
    user-facing keys, unless the manifest already sets them.
    """
    from lib.resources import resource_path
    out = copy.deepcopy(manifest_cfg)
    runtime_paths = (runtime_cfg or {}).get('paths') or {}

    def fill(section, key, value):
        if value in (None, '', []):
            return
        target = out.setdefault(section, {})
        if isinstance(target, dict) and target.get(key) in (None, '', []):
            target[key] = copy.deepcopy(value)

    for section, key in _EXPLICIT_PATHS:
        fill(section, key, runtime_paths.get(key))
    if ai_active(out):
        for key, spec in CONFIG_SCHEMA['ai'].items():
            if key != '__type__' and spec.get('default'):
                fill('ai', key, resource_path(runtime_cfg, None, *spec['default'].split('/')))
    return out


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


def _default_tool_dir():
    """Tool installation root, spelled the way the tool was started.

    Python resolves symlinks of the script directory, so ``__file__`` points to the
    physical location of the tool (for example ``/net/storage/AI/kcap``) even when it
    is started through a nearby symlink such as ``../../tools/kcap``.  v20.1.1: when
    ``sys.argv[0]`` names the same installation (checked on lib/config.py), the
    directory as spelled there is returned, so relative paths exported from it stay
    short.  Otherwise the physical location is used.
    """
    physical = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    argv0 = sys.argv[0] if sys.argv else ''
    if argv0:
        spelled = os.path.dirname(os.path.abspath(argv0))
        marker = os.path.join(spelled, 'lib', 'config.py')
        try:
            if spelled != physical and os.path.samefile(marker, os.path.abspath(__file__)):
                return spelled
        except OSError:
            pass
    return physical


def _initial_variables(config_dir, inherited_vars=None):
    variables = dict(inherited_vars or {})
    variables.setdefault('WORKSPACE', os.environ.get('WORKSPACE', ''))
    variables.setdefault('TOOLDIR', os.environ.get('TOOLDIR', _default_tool_dir()))
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
    def dirs(section, plural, default):
        raw = section.get(plural)
        vals = raw if isinstance(raw, list) else [raw] if raw else [default]
        return [v if os.path.isabs(v) else os.path.normpath(os.path.join(config_dir, v)) for v in vals]
    expanded['paths'] = {
        'work_dir': work,
        'cache_dir': paths.get('cache_dir') or os.path.join(work, 'cache'),
        'output_dir': paths.get('output_dir') or os.path.join(work, 'output'),
        'assets_dir': assets,
        'profiles_dirs': dirs(profiles, 'profiles_dirs', os.path.join(config_dir, 'profiles')),
        'rules_dirs': dirs(rules, 'rules_dirs', os.path.join(config_dir, 'rules')),
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
