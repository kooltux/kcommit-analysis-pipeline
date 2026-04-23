"""Historical Kbuild/Makefile config-to-paths mapping for kcommit-analysis-pipeline.

v7.18 changes vs v7.17:
  - Parallel git-show calls via concurrent.futures.ThreadPoolExecutor.
    The old inner loop ran serial subprocess calls (one per rev x makefile).
    For a 15k-makefile kernel with 10 sampled revisions that is 150k
    subprocess calls executed one at a time.  The new implementation fans them
    out across a thread pool (default 8 workers, configurable via
    cfg['collect']['history_workers']).  Expected wall-clock speedup: 5-10x
    on a typical SSD + 4-core machine.
  - progress_callback(done, total) parameter: callers can pass a callable to
    receive incremental progress notifications (used by stage 03 to update the
    terminal progress bar).
  - Falls back to the serial path when max_workers <= 1 or the ThreadPoolExecutor
    is unavailable (Python <3.2, which cannot happen for 3.6+ but is guarded).
  - Python 3.6 compatible (concurrent.futures available since 3.2).
"""
from __future__ import print_function
import os
import re

from lib.gitutils import list_rev_commits, show_path_history


OBJ_LINE_RE = re.compile(r'^(obj-[^\s:+?=]+)\s*[:+]?=\s*(.+)$', re.M)


def build_history_config_map(cfg, base_map, progress_callback=None):
    """Build a merged config_to_paths dict by sampling historical Makefiles.

    Parameters
    ----------
    cfg               : loaded pipeline config dict
    base_map          : dict  CONFIG_XXX -> [paths] from the current tree
    progress_callback : callable(done, total) or None

    Returns a dict with keys: mode, snapshots, config_to_paths.
    """
    hm = cfg.get('history_mapping', {})
    if not hm.get('enabled', True):
        return {'mode': 'disabled', 'snapshots': [], 'config_to_paths': base_map}

    commits = list_rev_commits(cfg)
    if not commits:
        return {'mode': hm.get('mode', 'range'),
                'snapshots': [],
                'config_to_paths': base_map}

    sample_step = int(hm.get('sample_step', 1000))
    max_probe   = int(hm.get('max_commits_per_probe', 256))
    max_workers = int((cfg.get('collect', {}) or {}).get('history_workers', 8))

    interesting_paths = _guess_makefiles_from_map(base_map)

    # ── sample revision list ─────────────────────────────────────────────────
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

    # deduplicate while preserving order
    seen_revs  = set()
    unique_revs = []
    for r in sampled[:max_probe]:
        if r not in seen_revs:
            seen_revs.add(r)
            unique_revs.append(r)

    tasks = [(rev, mk) for rev in unique_revs for mk in interesting_paths]
    total = len(tasks)

    # results accumulator: rev -> {mk -> text}
    results = {}   # (rev, mk) -> text_or_None

    if max_workers > 1 and total > 0:
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def _fetch(task):
                rev, mk = task
                text = show_path_history(cfg, rev, mk)
                return rev, mk, text

            done_count = [0]
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = dict(
                    (executor.submit(_fetch, t), t) for t in tasks
                )
                for future in as_completed(future_map):
                    try:
                        rev, mk, text = future.result()
                    except Exception:
                        rev, mk = future_map[future]
                        text = None
                    results[(rev, mk)] = text
                    done_count[0] += 1
                    if progress_callback:
                        progress_callback(done_count[0], total)

        except Exception:
            # fallback to serial
            results = _serial_fetch(cfg, tasks, progress_callback)
    else:
        results = _serial_fetch(cfg, tasks, progress_callback)

    # ── assemble snapshots ────────────────────────────────────────────────────
    snapshots = []
    for rev in unique_revs:
        snap = {'rev': rev, 'config_to_paths': {}}
        for mk in interesting_paths:
            text = results.get((rev, mk))
            if not text:
                continue
            rel_dir = os.path.dirname(mk)
            parsed  = _parse_makefile_blob(rel_dir, text)
            for sym, paths in parsed.items():
                snap['config_to_paths'].setdefault(sym, set()).update(paths)
        snap['config_to_paths'] = dict(
            (k, sorted(v)) for k, v in snap['config_to_paths'].items()
        )
        snapshots.append(snap)

    # ── merge all snapshots + base_map ────────────────────────────────────────
    merged = {}
    for snap in snapshots:
        for sym, paths in snap['config_to_paths'].items():
            merged.setdefault(sym, set()).update(paths)
    for sym, paths in base_map.items():
        merged.setdefault(sym, set()).update(paths)
    merged = dict((k, sorted(v)) for k, v in merged.items())

    return {
        'mode':           hm.get('mode', 'range'),
        'snapshots':      snapshots,
        'config_to_paths': merged,
    }


def _serial_fetch(cfg, tasks, progress_callback):
    results = {}
    for i, (rev, mk) in enumerate(tasks):
        results[(rev, mk)] = show_path_history(cfg, rev, mk)
        if progress_callback:
            progress_callback(i + 1, len(tasks))
    return results


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
        rhs      = m.group(2)
        if 'CONFIG_' not in selector:
            continue
        sym = (selector.split('$(')[-1].rstrip(')')
               if '$(' in selector else None)
        if not sym or not sym.startswith('CONFIG_'):
            continue
        for token in rhs.split():
            if token.endswith('.o'):
                src = os.path.normpath(
                    os.path.join(rel_dir, token[:-2] + '.c'))
                out.setdefault(sym, set()).add(src)
    return out
