"""Pipeline state tracking and progress for kcommit-analysis-pipeline.

v9.12 changes:
  - update_stage_progress() writes to stderr and is suppressed entirely when
    stderr is not a TTY (i.e. when output is redirected or --progress-json
    is active). This prevents the bar characters from corrupting JSON streams.
  - start_stage(), finish_stage(), fail_stage(), print_stage_input() and
    print_stage_output() also write to stderr so they never pollute stdout.
"""
import json
import os
import sys
import time

_PROGRESS_REFRESH = 0.5
_LINE_WIDTH       = 100
_stage_t0 = {}   # (index, total) -> monotonic start time
_last_upd  = {}   # (index, total) -> monotonic last update time

# Evaluate once at import time; stages inherit the same stderr fd as the
# parent process so this correctly tracks redirection done before exec.
_STDERR_IS_TTY = hasattr(sys.stderr, 'isatty') and sys.stderr.isatty()


def _fmt_hms(secs):
    secs = max(0, int(secs))
    h, r = divmod(secs, 3600)
    m, s = divmod(r, 60)
    return ('%d:%02d:%02d' % (h, m, s)) if h else ('%d:%02d' % (m, s))


def _read(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _write(path, state):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)
        f.write('\n')


def _bar(done, total, width=20):
    n = int(width * done / max(total, 1))
    return '[%s%s] %d/%d' % ('#' * n, '-' * (width - n), done, total)


def _eprint(*args, **kwargs):
    """Print to stderr and flush."""
    kwargs.setdefault('file', sys.stderr)
    print(*args, **kwargs)
    sys.stderr.flush()


def init_pipeline_state(path):
    _write(path, {'stages': {}, 'created_at': time.strftime('%Y-%m-%dT%H:%M:%S')})


def get_pipeline_state(path):
    return _read(path)


def is_stage_done(path, key):
    return _read(path).get('stages', {}).get(key, {}).get('status') == 'ok'


def update_stage_progress(index, total, frac, label,
                           n_done=None, n_total=None):
    """Render an in-place progress bar on stderr.

    Suppressed entirely when stderr is not a TTY so that redirected log
    files and --progress-json stdout streams are never polluted with bar
    characters.
    """
    if not _STDERR_IS_TTY:
        return

    key = (index, total)
    now = time.monotonic()
    if now - _last_upd.get(key, 0.0) < _PROGRESS_REFRESH and frac < 1.0:
        return
    _last_upd[key] = now
    if key not in _stage_t0:
        _stage_t0[key] = now
    el = now - _stage_t0[key]

    w  = 16
    f  = int(w * max(0.0, min(1.0, frac)))
    b  = '[%s%s] %d/%d  %-24s' % ('#' * f, '-' * (w - f), index, total, label)
    counts = ('  %d/%d' % (n_done, n_total) if n_done is not None and n_total is not None
              else ('  %d' % n_done) if n_done is not None else '')
    rate = ('  %.1f/s' % (n_done / el)) if n_done and el > 0.5 else ''
    eta  = ('  ETA %s' % _fmt_hms((el / n_done) * (n_total - n_done))
            if n_done and n_total and frac > 0.01 else '')
    line = '\r%s%s  %s%s%s' % (b, counts, _fmt_hms(el), rate, eta)
    if len(line) < _LINE_WIDTH:
        line += ' ' * (_LINE_WIDTH - len(line))
    sys.stderr.write(line)
    sys.stderr.flush()


def start_stage(path, key, index, total):
    state = _read(path)
    state.setdefault('stages', {})
    started = time.time()
    state['stages'][key] = {
        'status': 'running', 'index': index, 'total': total,
        'start_time': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    _write(path, state)
    sk = (index, total)
    _stage_t0[sk] = time.monotonic()
    _last_upd[sk] = 0.0
    _eprint('%s running %s' % (_bar(index - 1, total), key.ljust(30)))
    return started


def finish_stage(path, key, started, status='ok', extra=None):
    el    = time.time() - started
    state = _read(path)
    state.setdefault('stages', {})
    e = state['stages'].get(key, {})
    e.update({'status': status, 'end_time': time.strftime('%Y-%m-%dT%H:%M:%S'),
              'duration_sec': round(el, 2)})
    if extra:
        e.update(extra)
    state['stages'][key] = e
    _write(path, state)
    _eprint('%s %s  %.1fs' % (_bar(e.get('index', 1), e.get('total', 1)),
                               key.ljust(30), el))


def fail_stage(path, key, started, error_msg=''):
    el    = time.time() - started
    state = _read(path)
    state.setdefault('stages', {})
    e = state['stages'].get(key, {})
    e.update({'status': 'failed', 'end_time': time.strftime('%Y-%m-%dT%H:%M:%S'),
              'duration_sec': round(el, 2), 'error': error_msg or '(unknown)'})
    state['stages'][key] = e
    _write(path, state)
    _eprint('FAILED %s  %.1fs  %s' % (key.ljust(30), el, error_msg or ''))


def wipe_downstream(path, from_key, work_dir, stage_outputs, stage_order=None):
    state = _read(path)
    ss    = state.get('stages', {})
    if stage_order:
        ordered = list(stage_order)
    else:
        keyed   = {v.get('index', 999): k for k, v in ss.items()}
        ordered = [keyed[i] for i in sorted(keyed)]
    try:
        start = ordered.index(from_key)
    except ValueError:
        return
    for key in ordered[start:]:
        for rel in stage_outputs.get(key, []):
            full = os.path.join(work_dir, rel)
            if os.path.exists(full):
                os.remove(full)
        if key in ss:
            ss[key]['status'] = None
    state['stages'] = ss
    _write(path, state)


def print_stage_input(label, data):
    """Print a brief summary of the data fed into a stage.

    *data* may be a list (records) or a dict (map).
    """
    if isinstance(data, list):
        _eprint('  \u250c input  [%s]: %s records' % (label, format(len(data), ',')))
    elif isinstance(data, dict):
        _eprint('  \u250c input  [%s]: %s entries' % (label, format(len(data), ',')))
    else:
        _eprint('  \u250c input  [%s]: %r' % (label, data))


def print_stage_output(label, kept, dropped=None, reasons=None, elapsed=None):
    """Print a summary of what a stage produced.

    Args:
        label   -- stage name / output description
        kept    -- number of records kept / produced
        dropped -- number of records dropped (optional)
        reasons -- dict {reason_str: count} breakdown (optional)
        elapsed -- wall-clock seconds (optional)
    """
    reasons = reasons or {}
    total  = kept + (dropped or 0)
    pct    = ('  (%.0f%% kept)' % (100.0 * kept / total)) if total else ''
    t      = ('  [%.1fs]' % elapsed) if elapsed is not None else ''
    drop_s = ('  dropped=%s' % format(dropped, ',')) if dropped is not None else ''
    _eprint('  \u2514 output [%s]: kept=%s%s%s%s'
            % (label, format(kept, ','), drop_s, pct, t))
    if reasons:
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            _eprint('      %-40s %6s' % (reason, format(count, ',')))


def finish_progress_line():
    """Write a newline to stderr to terminate an in-place progress bar line."""
    import sys
    sys.stderr.write('\n')
    sys.stderr.flush()
