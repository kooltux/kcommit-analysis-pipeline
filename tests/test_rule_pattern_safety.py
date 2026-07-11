"""Tests: keyword pattern files match expected real-world commit subjects.

Each test picks one rule's keyword file and one representative commit
subject that MUST match it.  The helper ``_any`` replicates the exact
matching semantics of ``lib.patterns.match`` so failures are unambiguous.

Path resolution: every keyword file path is relative to the repository
root (the directory from which pytest is invoked).
"""
import re
import fnmatch
from pathlib import Path


# ---------------------------------------------------------------------------
# Internal helper — mirrors lib.patterns.match() exactly so we don't need
# to import the library (avoids sys.path assumptions in CI environments).
# ---------------------------------------------------------------------------

_UNESCAPED_GLOB_RE = re.compile(r'(?<!\\)[*?\[]')


def _match(pattern, text):
    """Single-pattern match with lib.patterns semantics.

    Dispatch order:
      1. 're:EXPR'  -> re.search(EXPR, text)  (case-sensitive by default;
                       use re:(?i)EXPR for case-insensitive)
      2. glob       -> fnmatch on lowercased strings
      3. keyword    -> case-insensitive whole-word regex (\\b boundaries)
    """
    text = text or ''
    if pattern.startswith('re:'):
        try:
            return bool(re.search(pattern[3:], text))
        except re.error:
            return False
    if _UNESCAPED_GLOB_RE.search(pattern):
        return fnmatch.fnmatch(text.lower(), pattern.lower())
    # keyword: unescape any escaped glob chars, then whole-word match
    literal = re.sub(r'\\([*?\[])', r'\1', pattern)
    try:
        if re.match(r'^\w', literal) and re.search(r'\w$', literal):
            rx = r'(?i)\b' + re.escape(literal) + r'\b'
        else:
            rx = r'(?i)' + re.escape(literal)
        return bool(re.search(rx, text))
    except re.error:
        return pattern.lower() in text.lower()


def _any(keyword_file, text):
    """Return True if *text* matches any non-comment pattern in *keyword_file*.

    ``keyword_file`` is a path relative to the repository root.
    """
    path = Path(keyword_file)
    if not path.exists():
        raise FileNotFoundError(
            f'Keyword file not found: {path.resolve()!s}\n'
            f'(cwd={Path.cwd()!s})'
        )
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.split('#')[0].strip()  # strip inline comments
        if not line:
            continue
        if _match(line, text):
            return True
    return False


# ---------------------------------------------------------------------------
# security_bounds
# ---------------------------------------------------------------------------

def test_security_bounds_matches_real_boundary_terms():
    text = 'net: add minimum boundary check for length validation'
    assert _any('configs/rules/security_bounds/keywords_whitelist.txt', text)


# ---------------------------------------------------------------------------
# security_general
# ---------------------------------------------------------------------------

def test_security_general_matches_security_fix_phrase():
    text = 'security fix for privilege escalation in ioctl path'
    assert _any('configs/rules/security_general/keywords_whitelist.txt', text)


# ---------------------------------------------------------------------------
# product_scope
# ---------------------------------------------------------------------------

def test_product_scope_qcom_word_boundary():
    assert _any('configs/rules/product_scope/keywords_whitelist.txt', 'qcom: fix glink transport')


# ---------------------------------------------------------------------------
# security_memory
# ---------------------------------------------------------------------------

def test_security_memory_uaf_word_boundary():
    assert _any('configs/rules/security_memory/keywords_whitelist.txt', 'fix use after free in packet path')


# ---------------------------------------------------------------------------
# security_syscalls
# ---------------------------------------------------------------------------

def test_security_syscalls_keeps_user_boundary_terms():
    assert _any('configs/rules/security_syscalls/keywords_whitelist.txt', 'bpf: validate user pointer in ioctl handler')


# ---------------------------------------------------------------------------
# generic blacklist — commits that MUST be dropped
# ---------------------------------------------------------------------------

def test_generic_blacklist_cleanup_only_still_matches():
    assert _any('configs/rules/generic/keywords_blacklist.txt', 'treewide: cleanup only for comments')


def test_generic_blacklist_documentation_phrase_is_conservative():
    assert _any('configs/rules/generic/keywords_blacklist.txt', 'docs: documentation only update')
