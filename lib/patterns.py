"""Pattern matching primitives for kcommit-analysis-pipeline.

v9.3 semantics:
  keyword  (no glob metacharacters, or glob-chars escaped with backslash)
             -> case-insensitive whole-word match (\\b boundaries).
             Backslash-escaped glob chars (\\*, \\?, \\[) are treated as
             literals in the keyword, not as glob wildcards.
  glob     (contains unescaped * ? or [ )
             -> case-insensitive fnmatch (entire string against pattern).
  re:EXPR  -> regex search, case-SENSITIVE by default.
             Use re:(?i)EXPR for case-insensitive regex.

E.3 (v13.0.0): removed stale module-level 'from lib.profile_rules import
_merged_patterns' that created a circular import with profile_rules.py.
_merged_patterns is not used anywhere in this module.
"""
import fnmatch
import re

# Private sentinel key used by precompile_rules — never collides with profile names.
_COMPILED_SENTINEL = object()


# Characters that trigger glob mode when unescaped
_GLOB_CHARS = frozenset('*?[')
# Regex that detects an unescaped glob metacharacter
_UNESCAPED_GLOB_RE = re.compile(r'(?<!\\)[*?\[]')


def _is_glob(pattern):  # type: (str) -> bool
    """Return True if *pattern* contains unescaped glob metacharacters."""
    return bool(_UNESCAPED_GLOB_RE.search(pattern))


def _unescape_glob(pattern):  # type: (str) -> str
    """Remove backslash escapes from glob metacharacters.

    '\\*' -> '*',  '\\?' -> '?',  '\\[' -> '['
    Other backslash sequences are left untouched.
    """
    return re.sub(r'\\([*?\[])', r'\1', pattern)


def compilepat(p):
    """Pre-compile a pattern string to a re.Pattern where possible."""
    if isinstance(p, re.Pattern):
        return p
    if not isinstance(p, str):
        return p
    if p.startswith('re:'):
        try:
            return re.compile(p[3:])          # case-SENSITIVE by default
        except re.error:
            return p
    # Keywords (no unescaped glob chars): compile to a regex.
    if not _is_glob(p):
        literal = _unescape_glob(p)
        try:
            if re.match(r'^\w', literal) and re.search(r'\w$', literal):
                return re.compile(r'(?i)\b' + re.escape(literal) + r'\b')
            else:
                return re.compile(r'(?i)' + re.escape(literal))
        except re.error:
            return p
    # Glob patterns are left as strings; matched via fnmatch at call-time.
    return p


def match(pattern, text):  # type: (object, str) -> bool
    """Match *pattern* against *text*.

    Dispatch order:
      1. re.Pattern (pre-compiled)    -> pattern.search(text)
      2. 're:EXPR'  (string literal)  -> re.search(EXPR, text) -- case-sensitive
      3. glob (unescaped * ? [)       -> fnmatch.fnmatch(lower, lower)
      4. keyword                      -> case-insensitive whole-word regex
    """
    text = text or ''
    if isinstance(pattern, re.Pattern):
        return bool(pattern.search(text))
    if not isinstance(pattern, str):
        return False
    if pattern.startswith('re:'):
        try:
            return bool(re.search(pattern[3:], text))  # case-sensitive
        except re.error:
            return False
    if _is_glob(pattern):
        return fnmatch.fnmatch(text.lower(), pattern.lower())
    literal = _unescape_glob(pattern)
    try:
        if re.match(r'^\w', literal) and re.search(r'\w$', literal):
            return bool(re.search(r'(?i)\b' + re.escape(literal) + r'\b', text))
        else:
            return bool(re.search(r'(?i)' + re.escape(literal), text))
    except re.error:
        return pattern.lower() in text.lower()


def match_span(pattern, text):  # type: (object, str) -> tuple | None
    """Return (start, end) char offsets of the first match in *text*, or None.

    Dispatch logic mirrors match() exactly so the two are always consistent.
    For glob patterns (which test the whole string via fnmatch) the span is
    (0, len(text)) when the pattern matches, or None otherwise.
    """
    text = text or ''
    if isinstance(pattern, re.Pattern):
        m = pattern.search(text)
        return (m.start(), m.end()) if m else None
    if not isinstance(pattern, str):
        return None
    if pattern.startswith('re:'):
        try:
            m = re.search(pattern[3:], text)
            return (m.start(), m.end()) if m else None
        except re.error:
            return None
    if _is_glob(pattern):
        return (0, len(text)) if fnmatch.fnmatch(text.lower(), pattern.lower()) else None
    literal = _unescape_glob(pattern)
    try:
        rx = (r'(?i)\b' + re.escape(literal) + r'\b'
              if re.match(r'^\w', literal) and re.search(r'\w$', literal)
              else r'(?i)' + re.escape(literal))
        m = re.search(rx, text)
        return (m.start(), m.end()) if m else None
    except re.error:
        idx = text.lower().find(pattern.lower())
        return (idx, idx + len(pattern)) if idx != -1 else None


def anymatches(patterns, text):  # type: (list, str) -> bool
    return any(match(p, text) for p in (patterns or []))


def anyfilematches(patterns, files):  # type: (list, list) -> bool
    files = files or []
    return any(match(p, f) for p in (patterns or []) for f in files)


def allfilesmatch(patterns, files):  # type: (list, list) -> bool
    """Return True iff ALL files match at least one pattern."""
    files = files or []
    if not patterns or not files:
        return False
    return all(any(match(p, f) for p in patterns) for f in files)


def precompile_rules(profile_rules):
    """Compile all pattern strings in *profile_rules* in-place.

    Idempotent: repeated calls on the same dict object are no-ops (id check).
    """
    if profile_rules.get(_COMPILED_SENTINEL):
        return profile_rules
    profile_rules[_COMPILED_SENTINEL] = True
    keys = ('keywords_whitelist', 'keywords_blacklist',
            'path_whitelist', 'path_blacklist',
            'commit_whitelist', 'commit_blacklist')
    for pdata in (profile_rules or {}).values():
        if not isinstance(pdata, dict):
            continue
        from lib.profile_rules import _merged_patterns
        merged = _merged_patterns(pdata)
        for key in keys:
            merged[key] = [compilepat(p) for p in merged.get(key, [])]
        for rdata in ((pdata or {}).get('rules') or {}).values():
            for key in keys:
                rdata[key] = [compilepat(p) for p in rdata.get(key, [])]
    return profile_rules
