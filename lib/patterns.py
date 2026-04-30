import fnmatch
import re

_PRECOMPILED_IDS = set()

def compilepat(p):
    if isinstance(p, re.Pattern):
        return p
    if not isinstance(p, str):
        return p
    if p.startswith('re:'):
        try:
            return re.compile(p[3:], re.I)
        except re.error:
            return p
    return p

def match(pattern, text):
    text = text or ''
    if isinstance(pattern, re.Pattern):
        return bool(pattern.search(text))
    if not isinstance(pattern, str):
        return False
    if pattern.startswith('re:'):
        try:
            return bool(re.search(pattern[3:], text, re.I))
        except re.error:
            return False
    if any(c in pattern for c in '*?['):
        return fnmatch.fnmatch(text, pattern)
    return pattern.lower() in text.lower()

def anymatches(patterns, text):
    return any(match(p, text) for p in (patterns or []))

def anyfilematches(patterns, files):
    files = files or []
    return any(match(p, f) for p in (patterns or []) for f in files)

def allfilesmatch(patterns, files):
    files = files or []
    if not patterns or not files:
        return False
    return all(any(match(p, f) for p in patterns) for f in files)

def precompile_rules(profile_rules):
    if id(profile_rules) in _PRECOMPILED_IDS:
        return profile_rules
    _PRECOMPILED_IDS.add(id(profile_rules))
    keys = ('keywords_whitelist', 'keywords_blacklist', 'path_whitelist', 'path_blacklist', 'commit_whitelist', 'commit_blacklist')
    for pdata in (profile_rules or {}).values():
        merged = (pdata or {}).get('merged', {})
        for key in keys:
            merged[key] = [compilepat(p) for p in merged.get(key, [])]
        for rdata in ((pdata or {}).get('rules') or {}).values():
            for key in keys:
                rdata[key] = [compilepat(p) for p in rdata.get(key, [])]
    return profile_rules
