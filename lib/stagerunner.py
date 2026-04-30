import argparse
import os
import time
from lib.config import load_config, apply_override

def runstage(stage_key, index, run_func):
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--override', default=None, metavar='JSON')
    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.override:
        apply_override(cfg, args.override)
    work = cfg.get('paths', {}).get('work_dir') or cfg.get('project', {}).get('work_dir') or cfg.get('work_dir')
    if not work:
        raise SystemExit('work_dir missing from resolved config')
    os.makedirs(work, exist_ok=True)
    statepath = os.path.join(work, 'pipeline_state.json')
    started = time.time()
    return run_func(cfg, work, statepath, started)
