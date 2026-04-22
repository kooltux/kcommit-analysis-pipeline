#!/usr/bin/env python3
# Prepare and compile rules for all active profiles in the configuration.
from __future__ import print_function
import argparse
import os

from lib.config import load_config
from lib.io_utils import ensure_dir
from lib.profile_rules import compile_rules_for_config
from lib.validation import validate_inputs
from lib.pipeline_runtime import start_stage, finish_stage


def main():
    ap = argparse.ArgumentParser(description='Prepare compiled rules for active profiles')
    ap.add_argument('--config', required=True)
    args = ap.parse_args()

    cfg = load_config(args.config)
    work = cfg.get('project', {}).get('work_dir', './work')
    cache = os.path.join(work, 'cache')
    ensure_dir(cache)

    state_path = os.path.join(work, 'pipeline_state.json')
    started = start_stage(state_path, 'prepare_rules', 1, 7)

    problems, notices = validate_inputs(cfg)
    for note in notices:
        print(note)
    if problems:
        for problem in problems:
            print(problem)
        raise SystemExit(2)

    compiled = compile_rules_for_config(cfg, work)
    print('prepared rules for %d profiles' % len(compiled))
    finish_stage(state_path, 'prepare_rules', started, status='ok', extra={'profile_count': len(compiled)})


if __name__ == '__main__':
    main()
