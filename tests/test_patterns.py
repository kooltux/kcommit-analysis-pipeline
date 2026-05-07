"""Tests for lib.patterns — match, anymatches, anyfilematches, allfilesmatch."""
import re, os

from lib.patterns import match, anymatches, anyfilematches, allfilesmatch, precompile_rules, compilepat


def test_match_plain_substring():
    assert match('usb', 'usb: fix bulk transfer') is True


def test_match_plain_case_insensitive():
    assert match('USB', 'usb: fix bulk transfer') is True


def test_match_no_hit():
    assert match('bluetooth', 'usb: fix bulk transfer') is False


def test_match_regex():
    assert match(re.compile(r'CVE-\d{4}-\d+', re.I), 'CVE-2024-12345 fixed') is True


def test_match_regex_no_hit():
    assert match(re.compile(r'CVE-\d{4}-\d+', re.I), 'no cve here') is False


def test_anymatches_hit():
    pats = ['bluetooth', 'usb', 'audio']
    assert anymatches(pats, 'usb: remove deprecated API') is True


def test_anymatches_miss():
    pats = ['bluetooth', 'audio']
    assert anymatches(pats, 'usb: remove deprecated API') is False


def test_anymatches_empty_patterns():
    assert anymatches([], 'anything') is False


def test_anyfilematches_hit():
    pats  = ['drivers/usb/']
    files = ['drivers/usb/core/hub.c', 'include/linux/usb.h']
    assert anyfilematches(pats, files) is True


def test_anyfilematches_miss():
    pats  = ['drivers/net/']
    files = ['drivers/usb/core/hub.c']
    assert anyfilematches(pats, files) is False


def test_allfilesmatch_true():
    pats  = ['Documentation/']
    files = ['Documentation/foo.rst', 'Documentation/bar.rst']
    assert allfilesmatch(pats, files) is True


def test_allfilesmatch_partial():
    pats  = ['Documentation/']
    files = ['Documentation/foo.rst', 'drivers/usb/hub.c']
    assert allfilesmatch(pats, files) is False


def test_precompile_rules_idempotent():
    rules = {
        'profile_a': {
            'rules': {'r1': {'patterns': ['usb', 'audio'], 'weight': 3}},
            'merged': {},
        }
    }
    precompile_rules(rules)
    # Second call must not raise
    precompile_rules(rules)


# ── glob branch ───────────────────────────────────────────────────────────────
def test_match_glob_star():
    assert match('drivers/usb/*', 'drivers/usb/core/hub.c') is True


def test_match_glob_star_miss():
    assert match('drivers/net/*', 'drivers/usb/core/hub.c') is False


def test_match_glob_question_mark():
    assert match('CVE-????-*', 'CVE-2024-12345') is True


def test_match_glob_brackets():
    assert match('[Uu][Ss][Bb]*', 'USB driver fix') is True


# ── re: prefix ────────────────────────────────────────────────────────────────
def test_match_re_prefix_case_sensitive():
    assert match('re:CVE-\\d{4}-\\d+', 'CVE-2024-12345') is True


def test_match_re_prefix_case_sensitive_miss():
    assert match('re:CVE-\\d{4}-\\d+', 'cve-2024-12345') is False


def test_match_re_prefix_explicit_ignore_case():
    assert match('re:(?i)CVE-\\d{4}-\\d+', 'cve-2024-12345') is True


def test_match_re_prefix_invalid_regex_no_crash():
    # Invalid regex should not raise — returns False
    assert match('re:[invalid(', 'anything') is False


# ── compilepat ────────────────────────────────────────────────────────────────
def test_compilepat_keyword_returns_pattern():
    import re as _re
    result = compilepat('usb')
    assert isinstance(result, _re.Pattern)


def test_compilepat_glob_returns_string():
    import re as _re
    result = compilepat('drivers/usb/*')
    assert isinstance(result, str)


def test_compilepat_re_prefix_returns_pattern():
    import re as _re
    result = compilepat('re:CVE-\\d{4}')
    assert isinstance(result, _re.Pattern)


def test_compilepat_idempotent():
    """Calling compilepat on an already-compiled pattern returns it unchanged."""
    import re as _re
    p = _re.compile(r'usb')
    assert compilepat(p) is p


def test_compilepat_escaped_glob_char_is_keyword():
    """'CVE-\\*' has an escaped glob char → treated as keyword, not glob."""
    import re as _re
    result = compilepat('CVE-\\*')
    # Should compile to a regex (keyword path), not stay as a string
    assert isinstance(result, _re.Pattern)


# ── escaped glob in match() ───────────────────────────────────────────────────
def test_match_escaped_star_literal():
    """Escaped \\* matches literal asterisk, not glob."""
    assert match('CVE-\\*', 'CVE-*') is True


def test_match_escaped_star_not_glob():
    """Escaped \\* does NOT glob-match 'CVE-2024-12345'."""
    assert match('CVE-\\*', 'CVE-2024-12345') is False


# ── allfilesmatch edge cases ──────────────────────────────────────────────────
def test_allfilesmatch_empty_files():
    """Empty file list: allfilesmatch returns False (no file matched any pattern)."""
    assert allfilesmatch(['Documentation/'], []) is False


def test_allfilesmatch_empty_patterns():
    assert allfilesmatch([], ['drivers/usb/hub.c']) is False
