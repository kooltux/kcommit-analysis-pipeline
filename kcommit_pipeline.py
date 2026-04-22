#!/usr/bin/env python3
from __future__ import print_function
import argparse
import os
import subprocess
import sys

from lib.config import load_config


STAGES = [
    ('prepare_rules', '00_prepare_rules.py'),
    ('collect_commits', '01_collect_commits.py'),
    ('collect_build_context', '02_collect_build_context.py'),
    ('build_product_map', '03_build_product_map.py'),
    ('enrich_commits', '04_enrich_commits.py'),
    ('score_commits', '05_score_commits.py'),
    ('report_commits', '06_report_commits.py'),
]


def _resolve_stage(name_or_index):
    if not name_or_index:
        return None
    # Numeric index (1-based) or stage name.
    try:
        idx = int(name_or_index)
        if 1 <= idx <= len(STAGES):
            return STAGES[idx - 1][0]
    except ValueError:
        pass
    key = str(name_or_index).strip().lower()
    for name, _ in STAGES:
        if name == key:
            return name
    raise SystemExit('Unknown stage %r (expected 1-6 or one of %s)' % (name_or_index, ', '.join(n for n, _ in STAGES)))


def main(argv=None):
    ap = argparse.ArgumentParser(description='Run kcommit-analysis-pipeline stages')
    ap.add_argument('--config', required=True, help='Path to workspace configuration JSON')
    ap.add_argument('--stage', help='Single stage to run (1-6 or name). If omitted, runs all stages in order.')
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    work_dir = cfg.get('project', {}).get('work_dir', './work')
    os.makedirs(work_dir, exist_ok=True)

    stage_name = _resolve_stage(args.stage) if args.stage else None

    to_run = []
    if stage_name is None:
        to_run = [name for name, _ in STAGES]
    else:
        to_run = [stage_name]

    for name, script in STAGES:
        if name not in to_run:
            continue
        cmd = [sys.executable, os.path.join(os.path.dirname(__file__), script), '--config', args.config]
        print('Running stage %s: %s' % (name, ' '.join(cmd)))
        subprocess.check_call(cmd)


if __name__ == '__main__':
    main()
