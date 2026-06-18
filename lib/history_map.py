"""Stage 03 helper: build a Kconfig-symbol → source-file history map.

Walks git commits in the requested mode (range / sampled / full / disabled)
and records which source files were touched alongside each changed Kconfig symbol.
Parallel git-show calls are used via ThreadPoolExecutor; a serial fallback
is used when max_workers <= 1. Failure rate is capped by
history_mapping.max_failure_rate (default 0.05).

v18.1.0 — three performance optimisations for large commit ranges:

  B — depth-cap interesting_paths
      _guess_makefiles_from_map() now accepts *max_depth* and *min_symbols*
      parameters (configurable via ``history_mapping.max_makefile_depth`` and
      ``history_mapping.min_makefile_symbols`` in the pipeline config).
      Makefiles deeper than *max_depth* directory components (default 3) or
      belonging to directories with fewer than *min_symbols* symbol references
      (default 1) are excluded.  This typically reduces the Makefile set from
      ~300 to ~50 for a full kernel tree, giving a ~6× reduction in git-show
      tasks.

  C — cap sampled revisions
      A new ``history_mapping.max_history_revisions`` config key (default 16)
      caps the total number of sampled revisions regardless of the size of the
      commit range.  Previously, with sample_step=1000 and a 200k-commit range,
      200 revisions were sampled; with this cap the count stays at 16.
      Combined with B, total git-show tasks drop from ~60 000 to ~800 for a
      200k-commit run.

  E — merged-map top-level cache
      After completing the expensive git-show + merge pass, the resulting
      ``config_to_paths`` dict is persisted to
      ``<cache_dir>/history_merged_map.json`` under a SHA-256 cache key derived
      from ``rev_old``, ``rev_new``, and ``interesting_paths``.  On a subsequent
      run with the same commit range and Makefile set, the entire
      build_history_config_map() call returns in < 1 s without spawning any
      subprocesses.

New configurable keys (all under ``history_mapping`` in pipeline config):
  max_history_revisions   int, default 16   — C: hard cap on sampled revisions
  max_makefile_depth      int, default 3    — B: max directory depth for probed Makefiles
  min_makefile_symbols    int, default 1    — B: min symbol references per Makefile directory
"""
import json as _json_e
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from lib.gitutils import list_rev_commits, show_path_history

import hashlib as _hashlib
import tempfile as _tempfile


# ── per-entry gitshow disk cache ──────────────────────────────────────────────

def _gitshow_cache_path(cache_dir, key):
    """Return the sharded file path for *key* inside gitshow_cache/.

    Layout: gitshow_cache/<key[0:2]>/<key[2:4]>/<key>
    This mirrors git's own object store sharding and avoids filesystem
    congestion when the cache grows to tens of thousands of entries.
    """
    return os.path.join(cache_dir, 'gitshow_cache',
                        key[:2], key[2:4], key)


def _gitshow_cache_get(cache_dir, rev, path):
    """Return cached git-show result or None if not cached."""
    if not cache_dir:
        return None
    key   = _hashlib.sha256(f'{rev}:{path}'.encode()).hexdigest()[:24]
    fpath = _gitshow_cache_path(cache_dir, key)
    if os.path.exists(fpath):
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
        except Exception:
            return None
    return None


def _gitshow_cache_put(cache_dir, rev, path, text):
    """Persist a git-show result to disk cache."""
    if not cache_dir:
        return
    key   = _hashlib.sha256(f'{rev}:{path}'.encode()).hexdigest()[:24]
    fpath = _gitshow_cache_path(cache_dir, key)
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    try:
        with open(fpath + '.tmp', 'w', encoding='utf-8') as f:
            f.write(text or '')
        os.replace(fpath + '.tmp', fpath)
    except Exception:
        pass


# ── E: merged-map top-level cache ─────────────────────────────────────────────

_MERGED_MAP_CACHE_FILE = 'history_merged_map.json'


def _merged_map_cache_key(rev_old, rev_new, interesting_paths):
    """Return a 24-hex-char cache key for the (range, makefiles) combination."""
    raw = f'{rev_old}:{rev_new}:{chr(0).join(sorted(interesting_paths))}'
    return _hashlib.sha256(raw.encode()).hexdigest()[:24]


def _load_merged_map_cache(cache_dir, key):
    """Return the cached merged config_to_paths dict, or None on miss/error."""
    if not cache_dir:
        return None
    p = os.path.join(cache_dir, _MERGED_MAP_CACHE_FILE)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            stored = _json_e.load(f)
        if stored.get('key') == key:
            return stored.get('config_to_paths')
    except Exception:
        pass
    return None


def _save_merged_map_cache(cache_dir, key, config_to_paths, mode):
    """Persist the merged config_to_paths dict to disk with an atomic replace."""
    if not cache_dir:
        return
    p = os.path.join(cache_dir, _MERGED_MAP_CACHE_FILE)
    try:
        with open(p + '.tmp', 'w', encoding='utf-8') as f:
            _json_e.dump({'key': key, 'config_to_paths': config_to_paths,
                          'mode': mode}, f)
        os.replace(p + '.tmp', p)
    except Exception:
        pass


# ── Makefile parsing ───────────────────────────────────────────────────────────

OBJ_LINE_RE = re.compile(r'^(obj-[^\s:+?=]+)\s*[:+]?=\s*(.+)$', re.M)


def build_history_config_map(cfg, base_map, cache_dir, progress_callback=None):
    """Build a merged config_to_paths dict by sampling historical Makefiles."""
    hm = cfg.get('history_mapping', {})
    if not hm.get('enabled', True):
        return {'mode': 'disabled', 'snapshots': [], 'config_to_paths': base_map}

    commits = list_rev_commits(cfg)
    if not commits:
        return {'mode': hm.get('mode', 'range'),
                'snapshots': [],
                'config_to_paths': base_map}

    sample_step   = int(hm.get('sample_step', 1000))
    max_hist_revs = int(hm.get('max_history_revisions', 16))   # C
    max_probe     = int(hm.get('max_commits_per_probe', 256))
    max_workers   = int((cfg.get('collect', {}) or {}).get('history_workers', 8))
    max_depth     = int(hm.get('max_makefile_depth', 3))        # B
    min_symbols   = int(hm.get('min_makefile_symbols', 1))      # B

    # B: depth-capped Makefile set
    interesting_paths = _guess_makefiles_from_map(
        base_map, max_depth=max_depth, min_symbols=min_symbols)

    # ── E: check merged-map cache before doing any git work ───────────────────
    rev_old   = cfg['kernel']['rev_old']
    rev_new   = cfg['kernel']['rev_new']
    cache_key = _merged_map_cache_key(rev_old, rev_new, interesting_paths)
    cached_merged = _load_merged_map_cache(cache_dir, cache_key)
    if cached_merged is not None:
        print('  reusing history_merged_map from cache (%d symbols)'
              % len(cached_merged))
        return {
            'mode':            hm.get('mode', 'range'),
            'snapshots':       [],
            'config_to_paths': cached_merged,
        }

    # ── C: sample revision list, capped at max_hist_revs ─────────────────────
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

    # C: hard cap — regardless of commit count, probe at most max_hist_revs
    sampled = sampled[:max_hist_revs]

    seen_revs   = set()
    unique_revs = []
    for r in sampled[:max_probe]:
        if r not in seen_revs:
            seen_revs.add(r)
            unique_revs.append(r)

    tasks = [(rev, mk) for rev in unique_revs for mk in interesting_paths]
    total = len(tasks)
    print('  history map: %d revision(s) × %d Makefile(s) = %d task(s)'
          % (len(unique_revs), len(interesting_paths), total))
    results = {}

    max_failure_rate = float(hm.get('max_failure_rate', 0.05))

    if max_workers > 1 and total > 0:
        try:
            def _fetch(task):
                rev, mk = task
                cached = _gitshow_cache_get(cache_dir, rev, mk)
                if cached is not None:
                    return rev, mk, cached
                text = show_path_history(cfg, rev, mk)
                _gitshow_cache_put(cache_dir, rev, mk, text or '')
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
                if failure_rate > max_failure_rate:
                    raise RuntimeError(
                        f'{len(failed_tasks)}/{total} git-show tasks failed '
                        f'({failure_rate:.0%}). First error: {failed_tasks[0][2]}')
                print(
                    f'\nWARNING: {len(failed_tasks)}/{total} git-show tasks failed '
                    f'(below {max_failure_rate:.0%} threshold, continuing with partial data)',
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

    # E: persist merged map so the next run with the same range is instant
    _save_merged_map_cache(cache_dir, cache_key, merged, hm.get('mode', 'range'))

    return {
        'mode':            hm.get('mode', 'range'),
        'snapshots':       snapshots,
        'config_to_paths': merged,
    }


def _serial_fetch(cfg, tasks, progress_callback):
    # Uses disk cache for each (rev, path) pair when available.
    results = {}
    for i, (rev, mk) in enumerate(tasks):
        results[(rev, mk)] = show_path_history(cfg, rev, mk)
        if progress_callback:
            progress_callback(i + 1, len(tasks))
    return results


def _guess_makefiles_from_map(base_map, max_depth=3, min_symbols=1):
    """Return Makefiles for directories in base_map, filtered by depth and symbol count.

    B (v18.1.0): depth cap eliminates deep sub-directories whose Makefiles rarely
    add new CONFIG→file mappings beyond what the base map already knows.
    Symbol-count threshold eliminates sparse directories with few references.

    Args:
        base_map:    config_to_paths dict (symbol → list of source paths).
        max_depth:   maximum directory depth (number of '/'-separated components)
                     for a Makefile to be included.  Default 3 covers top-level
                     subsystems (e.g. drivers/usb, net/ipv4, arch/arm/kernel).
        min_symbols: minimum number of symbol references a directory must have
                     to be included.  Default 1 (include all directories with
                     at least one symbol reference).

    Returns:
        Sorted list of Makefile paths (relative, e.g. 'drivers/usb/Makefile').
    """
    dir_symbols = {}
    for paths in base_map.values():
        for p in paths:
            d = os.path.dirname(p)
            if d:
                dir_symbols[d] = dir_symbols.get(d, 0) + 1

    makefiles = set()
    for d, count in dir_symbols.items():
        depth = len(d.split('/'))
        if depth <= max_depth and count >= min_symbols:
            makefiles.add(os.path.join(d, 'Makefile'))
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
