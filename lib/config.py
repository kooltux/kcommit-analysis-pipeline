"""Load JSON config files with ${var} expansion, relative includes, and comment stripping.

v9.8 changes:
  - deep_merge() was defined twice; second shadowed first. Canonical single
    definition kept; camelCase alias deepmerge() retained for compatibility.
  - _resolve_relative_paths() was over-eager: it absolutised any string
    containing '/' or starting with '.', corrupting git refs, regex patterns,
    and URL fragments. Now operates on an explicit allowlist of path-typed keys.
  - apply_override() moved to module level and exported directly; stage scripts
    no longer need to import it from kcommit_pipeline.
  - load_config(): profiles_dirs and rules_dirs lists resolved and stored in
    cfg['paths'] alongside the legacy single-dir keys.
"""
import copy
import json
import os
import re

VAR_RE = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')

# Keys whose string values should be treated as filesystem paths and resolved
# relative to the config file's directory.
_PATH_KEYS = frozenset({
    'source_dir', 'build_dir', 'work_dir', 'cache_dir', 'output_dir',
    'kernel_config', 'kernel_build_log', 'yocto_build_log',
    'profiles_dir', 'rules_dir', 'scoring_dir', 'templates_dir',
    'css_override',
})

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


# Backward-compatible camelCase alias
def deepmerge(base, patch):
    return deep_merge(base, patch)


# ── Variable expansion ────────────────────────────────────────────────────────

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


# ── Comment stripping ─────────────────────────────────────────────────────────

# Shared regex for bash-style inline hash comments.
# Matches # at column 0 OR preceded by whitespace; exported so other
# modules (e.g. profile_rules) can import rather than re-define it.
INLINE_COMMENT_RE = re.compile(r'(^|(?<=\s))#.*$', re.MULTILINE)
_INLINE_HASH_RE   = INLINE_COMMENT_RE   # backward-compat alias

# Regex for inline // comments: // preceded by whitespace (or start of line).
_INLINE_SLASH_RE = re.compile(r'(^|(?<=\s))//.*$', re.MULTILINE)


def _blank_comment(m):
    leading     = m.group(1)
    comment_len = len(m.group(0)) - len(leading)
    return leading + ' ' * comment_len


def _strip_json_comments(text):
    """Remove comments from JSON-like text, preserving line AND column positions.

    Supported comment styles:
      /* … */  block comments (may span multiple lines)
      //       whole-line OR inline — only when // follows whitespace or is at
               column 0.  :// in URLs is NOT stripped (colon ≠ whitespace).
      #        whole-line OR inline — same whitespace rule as bash comments.
    """
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


# ── Path resolution (allowlist-based) ────────────────────────────────────────

def _resolve_path(value, base_dir):
    """Resolve *value* as a path relative to *base_dir* if it looks like one.

    Only called for keys in _PATH_KEYS.  Absolute paths, URLs, and ${VAR}
    references are returned unchanged.
    """
    if not isinstance(value, str):
        return value
    if '://' in value or value.startswith('${') or value.startswith('/') or value.startswith('~'):
        return value
    if value == '':
        return value
    return os.path.normpath(os.path.join(base_dir, value))


def _resolve_known_paths(node, base_dir):
    """Walk a config dict and resolve only known path-typed keys."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k in _PATH_KEYS:
                if isinstance(v, list):
                    out[k] = [_resolve_path(item, base_dir) for item in v]
                else:
                    out[k] = _resolve_path(v, base_dir)
            else:
                out[k] = _resolve_known_paths(v, base_dir)
        return out
    if isinstance(node, list):
        return [_resolve_known_paths(v, base_dir) for v in node]
    return node


# ── Config loader ─────────────────────────────────────────────────────────────

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
    expanded = _resolve_known_paths(expanded, config_dir)

    # ── Canonical paths namespace ─────────────────────────────────────────────
    work_raw = (expanded.get('project', {}) or {}).get('work_dir', './work')
    work = (os.path.normpath(os.path.join(config_dir, work_raw))
            if not os.path.isabs(work_raw) else work_raw)

    # Single-dir defaults (backward compat)
    profiles_dir  = os.path.join(config_dir, 'profiles')
    rules_dir     = os.path.join(config_dir, 'rules')
    scoring_dir   = os.path.join(config_dir, 'scoring')
    templates_dir = os.path.join(config_dir, 'templates')

    # Multi-dir support: profiles.profiles_dirs / rules.rules_dirs
    # If a list is provided, use it; otherwise wrap the single dir in a list.
    _profiles_cfg = expanded.get('profiles', {}) or {}
    _rules_cfg    = expanded.get('rules', {}) or {}

    if 'profiles_dirs' in _profiles_cfg:
        raw = _profiles_cfg['profiles_dirs']
        profiles_dirs = [r if os.path.isabs(r) else os.path.normpath(os.path.join(config_dir, r))
                         for r in (raw if isinstance(raw, list) else [raw])]
    elif 'profiles_dir' in _profiles_cfg:
        d = _profiles_cfg['profiles_dir']
        profiles_dirs = [d if os.path.isabs(d) else os.path.normpath(os.path.join(config_dir, d))]
    else:
        profiles_dirs = [profiles_dir]

    if 'rules_dirs' in _rules_cfg:
        raw = _rules_cfg['rules_dirs']
        rules_dirs = [r if os.path.isabs(r) else os.path.normpath(os.path.join(config_dir, r))
                      for r in (raw if isinstance(raw, list) else [raw])]
    elif 'rules_dir' in _rules_cfg:
        d = _rules_cfg['rules_dir']
        rules_dirs = [d if os.path.isabs(d) else os.path.normpath(os.path.join(config_dir, d))]
    else:
        rules_dirs = [rules_dir]

    expanded['paths'] = {
        'work_dir':      work,
        'cache_dir':     os.path.join(work, 'cache'),
        'output_dir':    os.path.join(work, 'output'),
        'profiles_dir':  profiles_dirs[0],   # primary (legacy callers)
        'profiles_dirs': profiles_dirs,       # full list (new callers)
        'rules_dir':     rules_dirs[0],       # primary (legacy callers)
        'rules_dirs':    rules_dirs,          # full list (new callers)
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
    Importable directly from lib.config — no need to import from kcommit_pipeline.
    """
    try:
        patch = json.loads(override_json)
    except json.JSONDecodeError as exc:
        raise SystemExit(f'--override invalid JSON: {exc}')
    if not isinstance(patch, dict):
        raise SystemExit('--override top-level JSON value must be an object')
    return deep_merge(cfg, patch)


# Backward-compatible camelCase alias
def applyoverride(cfg, override_json):
    return apply_override(cfg, override_json)
