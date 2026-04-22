# Runtime helpers for progress display and per-stage timing.
from __future__ import print_function
import json
import os
import sys
import time


def load_state(path):
    if os.path.exists(path):
        with open(path, 'r', encoding="utf-8") as f:
            return json.load(f)
    return {"stages": []}


def save_state(path, data):
    with open(path, 'w', encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def start_stage(state_path, name, index, total):
    state = load_state(state_path)
    now = time.time()
    entry = {"name": name, "index": index, "total": total, "start_time": now, "end_time": None, "duration_sec": None, "status": "running"}
    state['stages'].append(entry)
    save_state(state_path, state)
    render_progress(index - 1, total, 'starting %s' % name)
    return now


def finish_stage(state_path, name, started_at, status='ok', extra=None):
    state = load_state(state_path)
    now = time.time()
    for entry in reversed(state['stages']):
        if entry['name'] == name and entry['end_time'] is None:
            entry['end_time'] = now
            entry['duration_sec'] = round(now - started_at, 3)
            entry['status'] = status
            if extra:
                entry['extra'] = extra
            break
    save_state(state_path, state)
    total = state['stages'][-1]['total'] if state['stages'] else 1
    done = len([s for s in state['stages'] if s.get('end_time') is not None])
    render_progress(done, total, 'finished %s' % name)


def render_progress(done, total, label=''):
    width = 30
    total = max(total, 1)
    ratio = float(done) / float(total)
    filled = int(width * ratio)
    bar = '#' * filled + '-' * (width - filled)
    msg = '[%s] %d/%d %s' % (bar, done, total, label)
    sys.stdout.write("\n" + msg[:200])
    sys.stdout.flush()
    if done >= total:
        sys.stdout.write("\n")
        sys.stdout.flush()
