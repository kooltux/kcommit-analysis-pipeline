"""Tests for lib.patterns — match, anymatches, anyfilematches, allfilesmatch."""
import re, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.patterns import match, anymatches, anyfilematches, allfilesmatch, precompile_rules


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
