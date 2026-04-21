# Rule matching helpers for substring, wildcard, and regex-based patterns.
from __future__ import print_function
import fnmatch
import re


def _is_regex(pattern):
    return pattern.startswith('re:')


def _regex_body(pattern):
    return pattern[3:] if pattern.startswith('re:') else pattern


def _string_match(value, pattern):
    # Match a value against regex, wildcard, or plain substring patterns.
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


def match_message_whitelist(message, rules):
    return match_any_string(message, rules.get('message_whitelist', []))


def match_message_blacklist(message, rules):
    return match_any_string(message, rules.get('message_blacklist', []))


def match_path_list(paths, patterns):
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


def classify_message(commit, rules):
    text = '%s\n%s' % (commit.get('subject', ''), commit.get('body', ''))
    sec = extract_keywords(text, rules.get('security_keywords', []))
    perf = extract_keywords(text, rules.get('performance_keywords', []))
    return sec, perf


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


def is_forced_include(commit, rules):
    sha = commit.get('commit', '')
    paths = commit.get('files', [])
    return bool(list_contains_pattern([sha], rules.get('force_include_commits', [])) or match_path_list(paths, rules.get('force_include_paths', [])))


def is_forced_exclude(commit, rules):
    sha = commit.get('commit', '')
    paths = commit.get('files', [])
    return bool(list_contains_pattern([sha], rules.get('force_exclude_commits', [])) or match_path_list(paths, rules.get('force_exclude_paths', [])))


def profile_matches(commit, profile_rules):
    text = '%s\n%s' % (commit.get('subject', ''), commit.get('body', ''))
    paths = commit.get('files', [])
    result = {}
    for rule_key, data in profile_rules.items():
        for profile, patterns in data.get('profiles', {}).items():
            if profile not in result:
                result[profile] = {}
            if rule_key.startswith('message_') or rule_key.endswith('_keywords'):
                hits = match_any_string(text, patterns)
            elif 'commits' in rule_key:
                hits = match_any_string(commit.get('commit', ''), patterns)
            else:
                hits = match_path_list(paths, patterns)
            if hits:
                result[profile][rule_key] = hits
    return result
