from __future__ import print_function
import os
import re

from lib.gitutils import list_rev_commits, show_path_history


OBJ_LINE_RE = re.compile(r'^(obj-[^\s:+?=]+)\s*[:+]?=\s*(.+)$', re.M)


def build_history_config_map(cfg, base_map):
    hm = cfg.get('history_mapping', {})
    if not hm.get('enabled', True):
        return {'mode': 'disabled', 'snapshots': [], 'config_to_paths': base_map}
    commits = list_rev_commits(cfg)
    if not commits:
        return {'mode': hm.get('mode', 'range'), 'snapshots': [], 'config_to_paths': base_map}
    sample_step = int(hm.get('sample_step', 1000))
    max_probe = int(hm.get('max_commits_per_probe', 256))
    snapshots = []
    interesting_paths = _guess_makefiles_from_map(base_map)
    sampled = []
    if hm.get('mode', 'range') == 'range':
        sampled.append(cfg['kernel']['rev_old'])
        idx = sample_step
        while idx < len(commits):
            sampled.append(commits[idx - 1])
            idx += sample_step
        sampled.append(cfg['kernel']['rev_new'])
    else:
        sampled = [cfg['kernel']['rev_old'], cfg['kernel']['rev_new']]
    seen = set()
    for rev in sampled[:max_probe]:
        if rev in seen:
            continue
        seen.add(rev)
        snap = {'rev': rev, 'config_to_paths': {}}
        for mk in interesting_paths:
            text = show_path_history(cfg, rev, mk)
            if not text:
                continue
            rel_dir = os.path.dirname(mk)
            parsed = _parse_makefile_blob(rel_dir, text)
            for sym, paths in parsed.items():
                snap['config_to_paths'].setdefault(sym, set()).update(paths)
        snap['config_to_paths'] = dict((k, sorted(v)) for k, v in snap['config_to_paths'].items())
        snapshots.append(snap)
    merged = {}
    for snap in snapshots:
        for sym, paths in snap['config_to_paths'].items():
            merged.setdefault(sym, set()).update(paths)
    for sym, paths in base_map.items():
        merged.setdefault(sym, set()).update(paths)
    merged = dict((k, sorted(v)) for k, v in merged.items())
    return {'mode': hm.get('mode', 'range'), 'snapshots': snapshots, 'config_to_paths': merged}


def _guess_makefiles_from_map(base_map):
    makefiles = set()
    for paths in base_map.values():
        for p in paths:
            makefiles.add(os.path.join(os.path.dirname(p), 'Makefile'))
    return sorted(makefiles)


def _parse_makefile_blob(rel_dir, text):
    out = {}
    for m in OBJ_LINE_RE.finditer(text):
        selector = m.group(1)
        rhs = m.group(2)
        if 'CONFIG_' not in selector:
            continue
        config_symbol = selector.split('$(')[-1].rstrip(')') if '$(' in selector else None
        if not config_symbol or not config_symbol.startswith('CONFIG_'):
            continue
        for token in rhs.split():
            if token.endswith('.o'):
                src = os.path.normpath(os.path.join(rel_dir, token[:-2] + '.c'))
                out.setdefault(config_symbol, set()).add(src)
    return out
