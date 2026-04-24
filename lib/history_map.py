"""Historical Kbuild/Makefile config-to-paths mapping for kcommit-analysis-pipeline.

v8.0 changes vs v7.19:
  - Dropped from __future__ import print_function (Py2 dead code).
  - %-formatting replaced with f-strings.
  - Fixed silent error swallowing in the ThreadPoolExecutor loop: individual
    task failures are now counted.  If more than 5% of git-show tasks fail,
    a RuntimeError is raised to fail the stage loudly.  Below the threshold,
    a stderr warning is printed and the pipeline continues with partial data.

v7.18 additions vs v7.17:
  - Parallel git-show calls via concurrent.futures.ThreadPoolExecutor.
  - progress_callback(done, total) parameter.
  - Serial fallback when max_workers <= 1.
"""
import os
import re
import sys

from lib.gitutils import list_rev_commits, show_path_history


OBJ_LINE_RE = re.compile(r'^(obj-[^\s:+?=]+)\s*[:+]?=\s*(.+)$', re.M)


def build_history_config_map(cfg, base_map, progress_callback=None):
    """Build a merged config_to_paths dict by sampling historical Makefiles."""
    hm = cfg.get('history_mapping', {})
    if not hm.get('enabled', True):
        return {'mode': 'disabled', 'snapshots': [], 'config_to_paths': base_map}

    commits = list_rev_commits(cfg)
    if not commits:
        return {'mode': hm.get('mode', 'range'),
                'snapshots': [],
                'config_to_paths': base_map}

    sample_step  = int(hm.get('sample_step', 1000))
    max_probe    = int(hm.get('max_commits_per_probe', 256))
    max_workers  = int((cfg.get('collect', {}) or {}).get('history_workers', 8))

    interesting_paths = _guess_makefiles_from_map(base_map)

    # ── sample revision list ──────────────────────────────────────────────────
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

    seen_revs   = set()
    unique_revs = []
    for r in sampled[:max_probe]:
        if r not in seen_revs:
            seen_revs.add(r)
            unique_revs.append(r)

    tasks = [(rev, mk) for rev in unique_revs for mk in interesting_paths]
    total = len(tasks)
    results = {}

    if max_workers > 1 and total > 0:
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def _fetch(task):
                rev, mk = task
                text = show_path_history(cfg, rev, mk)
                return rev, mk, text

            done_count   = [0]
            failed_tasks = []

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {executor.submit(_fetch, t): t for t in tasks}
                for future in as_completed(future_map):
                    try:
                        rev, mk, text = future.result()
                    except Exception as exc:
                        rev, mk = future_map[future]
                        text = None
                        failed_tasks.append((rev, mk, str(exc)))
                    results[(rev, mk)] = text
                    done_count[0] += 1
                    if progress_callback:
                        progress_callback(done_count[0], total)

            if failed_tasks:
                failure_rate = len(failed_tasks) / max(total, 1)
                if failure_rate > 0.05:
                    raise RuntimeError(
                        f'{len(failed_tasks)}/{total} git-show tasks failed '
                        f'({failure_rate:.0%}). First error: {failed_tasks[0][2]}')
                print(
                    f'\nWARNING: {len(failed_tasks)}/{total} git-show tasks failed '
                    f'(below 5%% threshold, continuing with partial data)',
                    file=sys.stderr)

        except RuntimeError:
            raise
        except Exception:
            # Non-RuntimeError failure of the executor itself: fall back to serial
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
        snap['config_to_paths'] = {k: sorted(v) for k, v in snap['config_to_paths'].items()}
        snapshots.append(snap)

    # ── merge all snapshots + base_map ────────────────────────────────────────
    merged = {}
    for snap in snapshots:
        for sym, paths in snap['config_to_paths'].items():
            merged.setdefault(sym, set()).update(paths)
    for sym, paths in base_map.items():
        merged.setdefault(sym, set()).update(paths)
    merged = {k: sorted(v) for k, v in merged.items()}

    return {
        'mode':            hm.get('mode', 'range'),
        'snapshots':       snapshots,
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
                src = os.path.normpath(os.path.join(rel_dir, token[:-2] + '.c'))
                out.setdefault(sym, set()).add(src)
    return out
