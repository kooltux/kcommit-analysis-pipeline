#!/usr/bin/env python3
"""Stage 00: Prepare compiled rules and validate configuration.

v7.17: fail_stage on error; profiles.active accepts dict or list form.
"""
import argparse
import json
import os

from lib.config import load_config
from lib.profile_rules import compile_rules_for_config, _active_profiles

from lib.validation import validate_inputs
from lib.pipeline_runtime import start_stage, finish_stage, fail_stage


def main():
    ap = argparse.ArgumentParser(description='Prepare compiled rules and validate configuration')
    ap.add_argument('--config', required=True)
    args = ap.parse_args()

    cfg   = load_config(args.config)
    work  = cfg.get('project', {}).get('work_dir', './work')
    cache = os.path.join(work, 'cache')
    os.makedirs(cache, exist_ok=True)
    state_path = os.path.join(work, 'pipeline_state.json')
    started = start_stage(state_path, 'prepare_pipeline', 1, 7)

    try:
        problems, notices = validate_inputs(cfg)
        for note in notices:
            print(note)
        if problems:
            for p in problems:
                print('ERROR:', p)
            fail_stage(state_path, 'prepare_pipeline', started,
                       error_msg='; '.join(problems))
            raise SystemExit(2)

        meta       = cfg.get('_meta', {}) or {}
        config_dir = meta.get('config_dir') or os.getcwd()
        issues     = []

        if not os.path.isdir(os.path.join(config_dir, 'profiles')):
            issues.append('profiles directory not found: %s'
                          % os.path.join(config_dir, 'profiles'))
        if not os.path.isdir(os.path.join(config_dir, 'rules')):
            issues.append('rules directory not found: %s'
                          % os.path.join(config_dir, 'rules'))

        active_names = _active_profiles(cfg)
        if not active_names:
            issues.append('no active profiles configured (profiles.active is empty)')
        for name in active_names:
            pjson = os.path.join(config_dir, 'profiles', name + '.json')
            if not os.path.exists(pjson):
                issues.append('profile %r not found at %s' % (name, pjson))

        if issues:
            for msg in issues:
                print('CONFIG ERROR:', msg)
            fail_stage(state_path, 'prepare_pipeline', started,
                       error_msg='; '.join(issues))
            raise SystemExit(2)

        compiled = compile_rules_for_config(cfg, work)
        summary  = {
            'active_profiles': sorted(compiled.keys()),
            'work_dir':        work,
            'config_path':     args.config,
        }
        with open(os.path.join(cache, 'prepare_summary.json'), 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2)
            f.write('\n')

        print('prepared rules for %d profiles' % len(compiled))
        finish_stage(state_path, 'prepare_pipeline', started, status='ok',
                     extra={'profile_count': len(compiled)})

    except SystemExit:
        raise
    except Exception as exc:
        fail_stage(state_path, 'prepare_pipeline', started, error_msg=str(exc))
        raise


if __name__ == '__main__':
    main()
