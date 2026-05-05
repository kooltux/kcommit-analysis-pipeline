"""Pattern matching primitives for kcommit-analysis-pipeline.

v9.3 semantics:
  keyword  (no glob metacharacters, or glob-chars escaped with backslash)
             → case-insensitive whole-word match (\\b boundaries).
             Backslash-escaped glob chars (\\*, \\?, \\[) are treated as
             literals in the keyword, not as glob wildcards.
  glob     (contains unescaped * ? or [ )
             → case-insensitive fnmatch (entire string against pattern).
  re:EXPR  → regex search, case-SENSITIVE by default.
             Use re:(?i)EXPR for case-insensitive regex.
"""
import fnmatch
import re

_PRECOMPILED_IDS: set = set()

# Characters that trigger glob mode when unescaped
_GLOB_CHARS = frozenset('*?[')
# Regex that detects an unescaped glob metacharacter
_UNESCAPED_GLOB_RE = re.compile(r'(?<!\\)[*?\[]')


def _is_glob(pattern: str) -> bool:
    """Return True if *pattern* contains unescaped glob metacharacters."""
    return bool(_UNESCAPED_GLOB_RE.search(pattern))


def _unescape_glob(pattern: str) -> str:
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
    # If the unescaped literal is bounded by word-chars on both sides, use \b
    # for whole-word matching.  If the literal itself starts/ends with a
    # non-word character (e.g. escaped "CVE-*" → literal "CVE-*"), fall back
    # to a plain case-insensitive search (no boundary anchors needed).
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


def match(pattern, text: str) -> bool:
    """Match *pattern* against *text*.

    Dispatch order:
      1. re.Pattern (pre-compiled)    → pattern.search(text)
      2. 're:EXPR'  (string literal)  → re.search(EXPR, text) — case-sensitive
      3. glob (unescaped * ? [)       → fnmatch.fnmatch(lower, lower)
      4. keyword                      → case-insensitive whole-word regex
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
    # keyword: case-insensitive.
    # Whole-word (\b) when literal is word-bounded; plain substring otherwise.
    literal = _unescape_glob(pattern)
    try:
        if re.match(r'^\w', literal) and re.search(r'\w$', literal):
            return bool(re.search(r'(?i)\b' + re.escape(literal) + r'\b', text))
        else:
            return bool(re.search(r'(?i)' + re.escape(literal), text))
    except re.error:
        return pattern.lower() in text.lower()


def anymatches(patterns, text: str) -> bool:
    return any(match(p, text) for p in (patterns or []))


def anyfilematches(patterns, files) -> bool:
    files = files or []
    return any(match(p, f) for p in (patterns or []) for f in files)


def allfilesmatch(patterns, files) -> bool:
    """Return True iff ALL files match at least one pattern."""
    files = files or []
    if not patterns or not files:
        return False
    return all(any(match(p, f) for p in patterns) for f in files)


def precompile_rules(profile_rules):
    """Compile all pattern strings in *profile_rules* in-place.

    Idempotent: repeated calls on the same dict object are no-ops (id check).
    """
    if id(profile_rules) in _PRECOMPILED_IDS:
        return profile_rules
    _PRECOMPILED_IDS.add(id(profile_rules))
    keys = ('keywords_whitelist', 'keywords_blacklist',
            'path_whitelist', 'path_blacklist',
            'commit_whitelist', 'commit_blacklist')
    for pdata in (profile_rules or {}).values():
        merged = (pdata or {}).get('merged', {}) or {}
        for key in keys:
            merged[key] = [compilepat(p) for p in merged.get(key, [])]
        for rdata in ((pdata or {}).get('rules') or {}).values():
            for key in keys:
                rdata[key] = [compilepat(p) for p in rdata.get(key, [])]
    return profile_rules
