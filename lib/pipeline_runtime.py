"""Pipeline state tracking and progress utilities for kcommit-analysis-pipeline.

v8.0 changes vs v7.19:
  - Dropped from __future__ import print_function (Py2 dead code).
  - %-formatting replaced with f-strings; open() replaces io.open().
  - wipe_downstream(): accepts explicit stage_order list so ordering is
    deterministic on fresh workspaces (no longer depends on stored 'index'
    fields in pipeline_state.json).
"""
import json
import os
import sys
import time


def _read_state(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
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
    return f'[{bar}] {done}/{total}'


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
    """Print an in-place within-stage progress bar using \\r."""
    width  = 16
    filled = int(width * max(0.0, min(1.0, inner_fraction)))
    bar    = '#' * filled + '-' * (width - filled)
    counts = ''
    if n_done is not None and n_total is not None:
        counts = f'  {n_done}/{n_total}'
    elif n_done is not None:
        counts = f'  {n_done}'
    sys.stdout.write(f'\r[{bar}] {index}/{total}  {label:<26}{counts}')
    sys.stdout.flush()


def start_stage(path, key, index, total):
    """Record stage start; print progress; return start timestamp."""
    state = _read_state(path)
    state.setdefault('stages', {})
    started = time.time()
    state['stages'][key] = {
        'status':     'running',
        'index':      index,
        'total':      total,
        'start_time': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    _write_state(path, state)
    print(f'{_progress_bar(index - 1, total)} running {key:<30}')
    sys.stdout.flush()
    return started


def finish_stage(path, key, started, status='ok', extra=None):
    """Record stage completion; print duration."""
    elapsed = time.time() - started
    state   = _read_state(path)
    state.setdefault('stages', {})
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
    print(f'{_progress_bar(entry.get("index", 1), entry.get("total", 1))} '
          f'{key:<30}  {elapsed:.1f}s')
    sys.stdout.flush()


def fail_stage(path, key, started, error_msg=''):
    """Mark a stage as failed; print error."""
    elapsed = time.time() - started
    state   = _read_state(path)
    state.setdefault('stages', {})
    entry = state['stages'].get(key, {})
    entry.update({
        'status':       'failed',
        'end_time':     time.strftime('%Y-%m-%dT%H:%M:%S'),
        'duration_sec': round(elapsed, 2),
        'error':        error_msg or '(unknown error)',
    })
    state['stages'][key] = entry
    _write_state(path, state)
    print(f'FAILED {key:<30}  {elapsed:.1f}s  {error_msg or ""}')
    sys.stdout.flush()


def wipe_downstream(path, from_key, work_dir, stage_outputs, stage_order=None):
    """Remove intermediate output files for *from_key* and all following stages.

    Parameters
    ----------
    path          : path to pipeline_state.json
    from_key      : stage key to start wiping from (inclusive)
    work_dir      : base directory for relative paths in stage_outputs
    stage_outputs : dict mapping stage key -> list of relative output paths
    stage_order   : explicit ordered list of all stage keys (recommended).
                    When provided, ordering is deterministic regardless of
                    state file content — critical on fresh workspaces where
                    no 'index' fields have been written yet.
                    Falls back to index-field ordering for older state files.
    """
    state        = _read_state(path)
    stages_state = state.get('stages', {})

    if stage_order:
        ordered_keys = list(stage_order)
    else:
        # Legacy fallback: infer order from stored index fields
        keyed = {}
        for k, v in stages_state.items():
            keyed[v.get('index', 999)] = k
        ordered_keys = [keyed[i] for i in sorted(keyed)]

    try:
        start_idx = ordered_keys.index(from_key)
    except ValueError:
        return  # from_key not found — nothing to wipe

    for key in ordered_keys[start_idx:]:
        for rel_path in stage_outputs.get(key, []):
            full = os.path.join(work_dir, rel_path)
            if os.path.exists(full):
                os.remove(full)
        if key in stages_state:
            stages_state[key]['status'] = None

    state['stages'] = stages_state
    _write_state(path, state)
