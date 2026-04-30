"""Load JSON config files with ${var} expansion, relative includes, and comment stripping.

v8.4 changes vs v8.3:
  - INLINE_COMMENT_RE exported as a public name so profile_rules.py can
    import it rather than re-defining the same compiled regex.
  - _strip_json_comments(): inline // comments (// preceded by whitespace)
    now stripped in addition to whole-line // comments — safe because
    :// in URLs is not preceded by whitespace.
  - Comment replacement now consistently uses spaces rather than empty
    strings, preserving both line numbers AND approximate column positions
    so json.JSONDecodeError reports the exact source location.

v8.3 changes vs v8.2:
  - _strip_json_comments(): now also supports shell-style inline # comments
    using regex (^|\\s+)#.*$ — a # preceded by whitespace or at column 0
    strips the rest of the line, mirroring bash comment behaviour.
  - configs/example-arm-embedded-default.json removed (superseded by full).

v8.2 changes vs v8.1:
  - _strip_json_comments(): comments now replaced with whitespace/blank lines instead
    of being removed, so json.JSONDecodeError line numbers match the source file.
  - Legacy alias block (cfg['inputs']['profiles_dir'] etc.) removed: all callers
    now use cfg['paths'] directly.

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


# Shared regex for bash-style inline hash comments.
# Matches # at column 0 OR preceded by whitespace; exported so other
# modules (e.g. profile_rules) can import rather than re-define it.
# Pattern: (^|\s+)#.*$  — same as bash comment stripping.
INLINE_COMMENT_RE = re.compile(r'(^|(?<=\s))#.*$', re.MULTILINE)
_INLINE_HASH_RE   = INLINE_COMMENT_RE   # backward-compat alias


# Regex for inline // comments: // preceded by whitespace (or start of line).
# This safely ignores :// in URLs (colon is not whitespace).
_INLINE_SLASH_RE = re.compile(r'(^|(?<=\s))//.*$', re.MULTILINE)


def _blank_comment(m):
    """Replace a comment match with spaces, preserving the leading whitespace
    and the total character count so that column positions stay accurate."""
    leading      = m.group(1)           # the whitespace before the marker
    comment_len  = len(m.group(0)) - len(leading)
    return leading + ' ' * comment_len


def _strip_json_comments(text):
    """Remove comments from JSON-like text, preserving line AND column positions.

    All comment content is replaced with spaces (never removed), so that
    json.JSONDecodeError line/column numbers refer to the exact location in
    the original source file.

    Supported comment styles:
      /* … */  block comments (may span multiple lines)
      //       whole-line OR inline — only when // follows whitespace or is at
               column 0.  :// in URLs is NOT stripped (colon ≠ whitespace).
      #        whole-line OR inline — same whitespace rule as bash comments.
               regex: (^|\\s+)#.*$

    Replacement strategy:
      - Every non-newline character inside a comment → space.
      - Newlines inside block comments are kept verbatim.
      - Result has identical line count and near-identical column count as
        the source, making error messages accurate without any offset mapping.
    """
    # ── 1. /* ... */ block comments — replace non-newline chars with spaces ──
    def _blank_block(m):
        return re.sub(r'[^\n]', ' ', m.group(0))

    text = re.sub(r'/\*.*?\*/', _blank_block, text, flags=re.S)

    # ── 2. Line-by-line: // whole-line, // inline, # whole-line, # inline ────
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith('//'):
            # Whole-line // comment: replace entire line content with spaces
            # (keeps the line in place for accurate line-number reporting)
            cleaned_lines.append(' ' * len(line))
        else:
            # Inline // (only after whitespace — safe for URLs)
            line = _INLINE_SLASH_RE.sub(_blank_comment, line)
            # Inline/whole-line # comments (bash-style)
            line = INLINE_COMMENT_RE.sub(_blank_comment, line)
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


    expanded['_meta'] = {
        'config_path': path,
        'config_dir':  config_dir,
        'vars':        vars_map,
    }
    expanded['config_dir'] = config_dir
    return expanded


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


def apply_override(cfg, override_json):
    """Parse *override_json* string and deep-merge into *cfg*.
    Raises SystemExit on parse error or non-object input.
    """
    import json as _json
    try:
        patch = _json.loads(override_json)
    except _json.JSONDecodeError as exc:
        raise SystemExit('--override invalid JSON: %s' % exc)
    if not isinstance(patch, dict):
        raise SystemExit('--override top-level JSON value must be an object')
    return deep_merge(cfg, patch)


# Backward-compatible camelCase aliases used by older callers
def deepmerge(base, patch):
    return deep_merge(base, patch)


def applyoverride(cfg, override_json):
    return apply_override(cfg, override_json)
