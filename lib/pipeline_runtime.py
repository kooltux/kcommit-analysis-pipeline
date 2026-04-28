"""Pipeline state tracking and progress for kcommit-analysis-pipeline.

v8.5: elapsed, rate, ETA in update_stage_progress(); progress throttled to
      0.5 s; wipe_downstream() accepts stage_order for fresh-workspace safety;
      f-strings throughout; from __future__ removed.
"""
import json, os, sys, time

_PROGRESS_REFRESH = 0.5
_LINE_WIDTH       = 100
_stage_t0:  dict  = {}
_last_upd:  dict  = {}


def _fmt_hms(secs):
    secs = max(0, int(secs))
    h, r = divmod(secs, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _read(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write(path, state):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def _bar(done, total, width=20):
    n = int(width * done / max(total, 1))
    return f"[{'#'*n}{'-'*(width-n)}] {done}/{total}"


def init_pipeline_state(path):
    _write(path, {"stages": {}, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")})


def get_pipeline_state(path):
    return _read(path)


def is_stage_done(path, key):
    return _read(path).get("stages", {}).get(key, {}).get("status") == "ok"


def update_stage_progress(index, total, frac, label,
                           n_done=None, n_total=None):
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
    b  = f"[{'#'*f}{'-'*(w-f)}] {index}/{total}  {label:<24}"
    counts = (f"  {n_done}/{n_total}" if n_done is not None and n_total is not None
              else f"  {n_done}" if n_done is not None else "")
    rate = f"  {n_done/el:.1f}/s" if n_done and el > 0.5 else ""
    eta  = (f"  ETA {_fmt_hms((el/n_done)*(n_total-n_done))}"
            if n_done and n_total and frac > 0.01 else "")
    line = f"\r{b}{counts}  {_fmt_hms(el)}{rate}{eta}"
    if len(line) < _LINE_WIDTH:
        line += " " * (_LINE_WIDTH - len(line))
    sys.stdout.write(line)
    sys.stdout.flush()


def start_stage(path, key, index, total):
    state = _read(path)
    state.setdefault("stages", {})
    started = time.time()
    state["stages"][key] = {
        "status": "running", "index": index, "total": total,
        "start_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _write(path, state)
    sk = (index, total)
    _stage_t0[sk] = time.monotonic()
    _last_upd[sk] = 0.0
    print(f"{_bar(index-1, total)} running {key:<30}")
    sys.stdout.flush()
    return started


def finish_stage(path, key, started, status="ok", extra=None):
    el    = time.time() - started
    state = _read(path)
    state.setdefault("stages", {})
    e = state["stages"].get(key, {})
    e.update({"status": status, "end_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "duration_sec": round(el, 2)})
    if extra:
        e.update(extra)
    state["stages"][key] = e
    _write(path, state)
    print(f"{_bar(e.get('index',1), e.get('total',1))} {key:<30}  {el:.1f}s")
    sys.stdout.flush()


def fail_stage(path, key, started, error_msg=""):
    el    = time.time() - started
    state = _read(path)
    state.setdefault("stages", {})
    e = state["stages"].get(key, {})
    e.update({"status": "failed", "end_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "duration_sec": round(el, 2), "error": error_msg or "(unknown)"})
    state["stages"][key] = e
    _write(path, state)
    print(f"FAILED {key:<30}  {el:.1f}s  {error_msg or ''}")
    sys.stdout.flush()


def wipe_downstream(path, from_key, work_dir, stage_outputs, stage_order=None):
    state = _read(path)
    ss    = state.get("stages", {})
    if stage_order:
        ordered = list(stage_order)
    else:
        keyed = {v.get("index",999): k for k, v in ss.items()}
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
            ss[key]["status"] = None
    state["stages"] = ss
    _write(path, state)
