"""Pipeline state tracking and progress utilities for kcommit-analysis-pipeline.

v7.18 additions vs v7.17:
  - fail_stage():         Mark a stage as 'failed' with an optional error message.
  - get_pipeline_state(): Return the current state dict (safe even if file missing).
  - is_stage_done():      Return True if stage key already has status 'ok'.
  - wipe_downstream():    Remove intermediate output files for a stage and all
                          following stages, and reset their status in the state JSON.
  - init_pipeline_state(): Create a fresh empty state JSON.
  - update_stage_progress(): In-place \\r progress bar for inner loops.
  - State dict keyed by stage name (string) instead of a positional list, so
    re-runs of individual stages never create duplicate entries.
"""
from __future__ import print_function
import json
import os
import sys
import time


def _read_state(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _write_state(path, state):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)
        f.write('\n')


def _progress_bar(done, total, width=20):
    filled = int(width * done / max(total, 1))
    bar    = '#' * filled + '-' * (width - filled)
    return '[%s] %d/%d' % (bar, done, total)


def init_pipeline_state(path):
    """Create a fresh empty state file."""
    _write_state(path, {'stages': {}, 'created_at': time.strftime('%Y-%m-%dT%H:%M:%S')})


def get_pipeline_state(path):
    """Return the full state dict; empty dict if the file does not exist."""
    return _read_state(path)


def is_stage_done(path, key):
    """Return True if *key* has status 'ok' in the state file."""
    state = _read_state(path)
    return state.get('stages', {}).get(key, {}).get('status') == 'ok'


def update_stage_progress(index, total, inner_fraction, label,
                          n_done=None, n_total=None):
    """Print an in-place within-stage progress bar using \\r.

    index/total      : stage position (same values passed to start_stage)
    inner_fraction   : 0.0-1.0 completion of THIS stage inner loop
    label            : short description of current work
    n_done/n_total   : optional numeric counts appended to the line
    """
    width  = 16
    filled = int(width * max(0.0, min(1.0, inner_fraction)))
    bar    = '#' * filled + '-' * (width - filled)
    if n_done is not None and n_total is not None:
        counts = '  %d/%d' % (n_done, n_total)
    elif n_done is not None:
        counts = '  %d' % n_done
    else:
        counts = ''
    line = '[%s] %d/%d  %-26s%s' % (bar, index, total, label, counts)
    sys.stdout.write('\r' + line)
    sys.stdout.flush()


def start_stage(path, key, index, total):
    """Record stage start; print progress; return start timestamp."""
    state = _read_state(path)
    if 'stages' not in state:
        state['stages'] = {}
    started = time.time()
    state['stages'][key] = {
        'status':     'running',
        'index':      index,
        'total':      total,
        'start_time': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    _write_state(path, state)
    print('%s running %-30s' % (_progress_bar(index - 1, total), key))
    sys.stdout.flush()
    return started


def finish_stage(path, key, started, status='ok', extra=None):
    """Record stage completion; print duration."""
    elapsed = time.time() - started
    state   = _read_state(path)
    if 'stages' not in state:
        state['stages'] = {}
    entry = state['stages'].get(key, {})
    entry.update({
        'status':       status,
        'end_time':     time.strftime('%Y-%m-%dT%H:%M:%S'),
        'duration_sec': round(elapsed, 2),
    })
    if extra:
        entry.update(extra)
    state['stages'][key] = entry
    _write_state(path, state)
    print('%s %-30s  %.1fs' % (
        _progress_bar(entry.get('index', 1), entry.get('total', 1)),
        key, elapsed))
    sys.stdout.flush()


def fail_stage(path, key, started, error_msg=''):
    """Mark a stage as failed; print error."""
    elapsed = time.time() - started
    state   = _read_state(path)
    if 'stages' not in state:
        state['stages'] = {}
    entry = state['stages'].get(key, {})
    entry.update({
        'status':       'failed',
        'end_time':     time.strftime('%Y-%m-%dT%H:%M:%S'),
        'duration_sec': round(elapsed, 2),
        'error':        error_msg or '(unknown error)',
    })
    state['stages'][key] = entry
    _write_state(path, state)
    print('FAILED %-30s  %.1fs  %s' % (key, elapsed, error_msg or ''))
    sys.stdout.flush()


def wipe_downstream(path, from_key, work_dir, stage_outputs):
    """Remove intermediate output files for *from_key* and all following stages.

    *stage_outputs* maps stage key → list of paths relative to *work_dir*.
    Resets their status in the state JSON to None so they can be re-run.

    Stage ordering is inferred from the 'index' field stored in the state, or
    falls back to the natural dict insertion order of *stage_outputs*.
    """
    state      = _read_state(path)
    stages_map = state.get('stages', {}) or {}
    keys_ordered = list(stage_outputs.keys())

    if from_key not in keys_ordered:
        return  # nothing to wipe

    from_idx = keys_ordered.index(from_key)
    to_wipe  = keys_ordered[from_idx:]

    for k in to_wipe:
        for rel_path in (stage_outputs.get(k) or []):
            abs_path = os.path.join(work_dir, rel_path)
            if os.path.exists(abs_path):
                try:
                    os.remove(abs_path)
                    print('  removed %s' % abs_path)
                except OSError as e:
                    print('  warning: could not remove %s: %s' % (abs_path, e))
        if k in stages_map:
            stages_map[k]['status'] = None
    state['stages'] = stages_map
    _write_state(path, state)
