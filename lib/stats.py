"""Per-host timing statistics used to predict stage and step durations (v20.2.0).

After every stage (and every progress step with a known item count) one record
is added to ``<paths.stats_dir>/<hostname>.json``.  Only the last ``KEEP_RUNS``
records per entry are kept; the averages are recomputed from them each time:

* ``avg_seconds``      mean duration of the kept runs
* ``sec_per_commit``   total seconds / total collected commits (stages)
* ``sec_per_item``     total seconds / total items (steps with an item count)

Statistics never make the pipeline fail: every I/O problem is logged and ignored.
Entries are keyed ``<stage_key>`` for stages and ``<stage_key>/<label>`` for steps.
"""
import json
import logging
import os
import re
import socket
import tempfile
import time

KEEP_RUNS = 10
VERSION = 1


def host_name():
    return re.sub(r'[^A-Za-z0-9_.-]', '_', socket.gethostname() or 'unknown')


def stats_file(stats_dir, host=None):
    return os.path.join(stats_dir, (host or host_name()) + '.json')


def load(stats_dir, host=None):
    """Return the statistics of *host* (an empty skeleton when missing or unreadable)."""
    empty = {'version': VERSION, 'host': host or host_name(), 'entries': {}}
    if not stats_dir:
        return empty
    try:
        with open(stats_file(stats_dir, host), encoding='utf-8') as stream:
            data = json.load(stream)
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict) or not isinstance(data.get('entries'), dict):
        return empty
    return data


def _positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def summarize(runs):
    """Averages over *runs* (list of {'seconds', 'commits', 'items'} dicts)."""
    seconds = [r['seconds'] for r in runs if _positive(r.get('seconds'))]
    summary = {'run_count': len(runs),
               'avg_seconds': (sum(seconds) / len(seconds)) if seconds else None,
               'sec_per_commit': None, 'sec_per_item': None}
    for field, key in (('commits', 'sec_per_commit'), ('items', 'sec_per_item')):
        used = [r for r in runs if _positive(r.get(field)) and _positive(r.get('seconds'))]
        total = sum(r[field] for r in used)
        if used and total:
            summary[key] = sum(r['seconds'] for r in used) / total
    return summary


def record(stats_dir, key, seconds, commits=None, items=None, host=None, now=None):
    """Add one run to entry *key*, keep the last KEEP_RUNS and rewrite the file.

    Returns the updated entry, or None when nothing was recorded.
    """
    if not stats_dir or not _positive(seconds):
        return None
    try:
        data = load(stats_dir, host)
        entry = data['entries'].setdefault(key, {'runs': []})
        runs = list(entry.get('runs') or [])
        runs.append({'ts': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now or time.time())),
                     'seconds': round(float(seconds), 3),
                     'commits': int(commits) if _positive(commits) else None,
                     'items': int(items) if _positive(items) else None})
        runs = runs[-KEEP_RUNS:]
        entry.clear()
        entry['runs'] = runs
        entry.update(summarize(runs))
        data['version'] = VERSION
        data['host'] = host or host_name()
        os.makedirs(stats_dir, exist_ok=True)
        handle, tmp = tempfile.mkstemp(prefix='.stats-', dir=stats_dir)
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write('\n')
        os.replace(tmp, stats_file(stats_dir, host))
        return entry
    except (OSError, ValueError, TypeError) as exc:
        logging.warning('pipeline statistics not recorded: %s', exc)
        return None


def predict(stats_dir, key, commits=None, items=None, host=None):
    """Predict the duration in seconds of entry *key*; returns (seconds, run_count).

    With an item count the per-item rate is used, then the per-commit rate with a
    commit count, then the plain average duration.  (None, 0) when there is no history.
    """
    entry = load(stats_dir, host)['entries'].get(key)
    if not entry:
        return None, 0
    runs = [r for r in entry.get('runs') or [] if isinstance(r, dict)]
    summary = summarize(runs)
    seconds = None
    if _positive(items) and summary['sec_per_item']:
        seconds = summary['sec_per_item'] * items
    elif _positive(commits) and summary['sec_per_commit']:
        seconds = summary['sec_per_commit'] * commits
    else:
        seconds = summary['avg_seconds']
    return seconds, len(runs)


def remaining(stats_dir, keys, commits=None, host=None):
    """Predicted seconds for the stages *keys*; returns (seconds, stages_without_history)."""
    total, unknown = 0.0, 0
    for key in keys:
        seconds, _ = predict(stats_dir, key, commits=commits, host=host)
        if seconds is None:
            unknown += 1
        else:
            total += seconds
    return total, unknown


def format_duration(seconds):
    seconds = max(0, int(round(seconds)))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return ('%d:%02d:%02d' % (hours, minutes, secs)) if hours else ('%d:%02d' % (minutes, secs))
