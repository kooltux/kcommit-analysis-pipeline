# Rule matching helpers and scoring primitives.
from __future__ import print_function
import fnmatch
import re


def _is_regex(pattern):
    return pattern.startswith('re:')


def _regex_body(pattern):
    return pattern[3:] if pattern.startswith('re:') else pattern


def _string_match(value, pattern):
    """Match a value against regex, wildcard, or plain substring patterns."""
    value = value or ''
    if _is_regex(pattern):
        return re.search(_regex_body(pattern), value, re.IGNORECASE) is not None
    if any(ch in pattern for ch in ['*', '?', '[']):
        return fnmatch.fnmatch(value.lower(), pattern.lower())
    return pattern.lower() in value.lower()


def match_any_string(value, patterns):
    hits = []
    for pattern in patterns or []:
        if _string_match(value, pattern):
            hits.append(pattern)
    return hits


def match_path_list(paths, patterns):
    """Return the list of paths that match at least one pattern."""
    hits = []
    for path in paths or []:
        for pattern in patterns or []:
            if _is_regex(pattern):
                if re.search(_regex_body(pattern), path):
                    hits.append(path)
                    break
            elif any(ch in pattern for ch in ['*', '?', '[']):
                if fnmatch.fnmatch(path, pattern):
                    hits.append(path)
                    break
            elif path.startswith(pattern):
                hits.append(path)
                break
    return hits


def extract_keywords(text, patterns):
    return match_any_string(text or '', patterns)


def match_keywords_whitelist(text, rules):
    return match_any_string(text, rules.get('keywords_whitelist', []))


def match_keywords_blacklist(text, rules):
    return match_any_string(text, rules.get('keywords_blacklist', []))


def trailer_flags(commit):
    text = '%s\n%s' % (commit.get('subject', ''), commit.get('body', ''))
    text_l = text.lower()
    return {
        'has_fixes': 'fixes:' in text_l,
        'has_stable_cc': 'stable@vger.kernel.org' in text_l or 'cc: stable@' in text_l,
        'has_cve': 'cve-' in text_l,
        'has_reported_by': 'reported-by:' in text_l,
        'has_syzbot': 'syzbot' in text_l,
    }


def list_contains_pattern(values, patterns):
    matched = []
    for value in values or []:
        for pattern in patterns or []:
            if _string_match(value, pattern):
                matched.append(value)
                break
    return matched


def _any_path_in_list(paths, patterns):
    return bool(match_path_list(paths, patterns))


def _all_paths_in_list(paths, patterns):
    if not paths:
        return False
    for p in paths:
        if not match_path_list([p], patterns):
            return False
    return True


def evaluate_rule(commit, rule):
    """Evaluate a single rule dict for one commit.

    The rule dict is expected to have the unified schema keys:
      - keywords_whitelist / keywords_blacklist
      - path_whitelist / path_blacklist
      - commit_whitelist / commit_blacklist

    Returns a base score in [-100, 100] representing this rule's vote
    for the commit, before applying any per-rule weight.
    """
    sha = commit.get('commit', '')
    paths = commit.get('files', []) or []
    text = '%s\n%s' % (commit.get('subject', ''), commit.get('body', ''))

    # 1) Commit ID filters: hard overrides for this rule.
    if list_contains_pattern([sha], rule.get('commit_whitelist', [])):
        return 100
    if list_contains_pattern([sha], rule.get('commit_blacklist', [])):
        return -100

    # 2) Path filters: strong signals.
    if _any_path_in_list(paths, rule.get('path_whitelist', [])):
        return 60
    if _all_paths_in_list(paths, rule.get('path_blacklist', [])):
        return -60

    # 3) Keyword filters: weaker, text-only signals.
    if match_keywords_whitelist(text, rule):
        return 30
    if match_keywords_blacklist(text, rule):
        return -30

    return 0
