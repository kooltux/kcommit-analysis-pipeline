#!/usr/bin/env python3
# Prepare and compile rules for all active profiles in the configuration.
from __future__ import print_function
import argparse
import json
import os

from lib.config import load_config
from lib.profile_rules import compile_rules_for_config
from lib.io_utils import ensure_dir
from lib.validation import validate_inputs
from lib.pipeline_runtime import start_stage, finish_stage


def main():
    ap = argparse.ArgumentParser(description='Prepare compiled rules and validate configuration')
    ap.add_argument('--config', required=True)
    args = ap.parse_args()

    cfg = load_config(args.config)
    work = cfg.get('project', {}).get('work_dir', './work')
    cache = os.path.join(work, 'cache')
    ensure_dir(cache)

    state_path = os.path.join(work, 'pipeline_state.json')
    started = start_stage(state_path, 'prepare_pipeline', 1, 7)

    problems, notices = validate_inputs(cfg)
    for note in notices:
        print(note)
    if problems:
        for problem in problems:
            print(problem)
        finish_stage(state_path, 'prepare_pipeline', started, status='error', extra={'errors': problems})
        raise SystemExit(2)

    # Basic config/profile/rule consistency checks.
    meta = cfg.get('_meta', {}) or {}
    config_dir = meta.get('config_dir') or os.getcwd()
    profiles_dir = os.path.join(config_dir, 'profiles')
    rules_dir = os.path.join(config_dir, 'rules')

    issues = []
    if not os.path.isdir(profiles_dir):
        issues.append('profiles directory not found: %s' % profiles_dir)
    if not os.path.isdir(rules_dir):
        issues.append('rules directory not found: %s' % rules_dir)

    profiles_cfg = cfg.get('profiles', {}) or {}
    active = profiles_cfg.get('active') or cfg.get('active_profiles') or []
    if not active:
        issues.append('no active profiles configured (profiles.active is empty)')

    for name in active:
        pjson = os.path.join(profiles_dir, name + '.json')
        if not os.path.exists(pjson):
            issues.append('profile %r not found at %s' % (name, pjson))

    if issues:
        for msg in issues:
            print('CONFIG ERROR:', msg)
        finish_stage(state_path, 'prepare_pipeline', started, status='error', extra={'errors': issues})
        raise SystemExit(2)

    # Compile rules; this also validates that referenced rule folders exist.
    compiled = compile_rules_for_config(cfg, work)
    summary = {
        'active_profiles': sorted(compiled.keys()),
        'work_dir': work,
        'config_path': args.config,
    }
    summary_path = os.path.join(cache, 'prepare_summary.json')
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
        f.write('\n')

    print('prepared rules for %d profiles' % len(compiled))
    finish_stage(state_path, 'prepare_pipeline', started, status='ok', extra={'profile_count': len(compiled)})


if __name__ == '__main__':
    main()
