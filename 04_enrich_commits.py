#!/usr/bin/env python3
"""Stage 04: Enrich commits with stable hints and touched-path guesses.

v7.17: extract_stable_hints replaces extract_patch_features; cfg passed to
       infer_touched_paths so path hints are loaded from the external JSON file;
       fail_stage on error.
"""
from __future__ import print_function
import argparse
import os

from lib.config import load_config
from lib.io_utils import ensure_dir, load_json, save_json
from lib.scoring import extract_stable_hints, infer_touched_paths
from lib.validation import validate_inputs
from lib.pipeline_runtime import start_stage, finish_stage, fail_stage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    args = ap.parse_args()

    cfg        = load_config(args.config)
    work       = cfg.get('project', {}).get('work_dir', './work')
    state_path = os.path.join(work, 'pipeline_state.json')
    started    = start_stage(state_path, 'enrich_commits', 5, 7)

    try:
        problems, notices = validate_inputs(cfg)
        for note in notices:
            print(note)
        if problems:
            for p in problems:
                print(p)
            fail_stage(state_path, 'enrich_commits', started,
                       error_msg='; '.join(problems))
            raise SystemExit(2)

        cache = os.path.join(work, 'cache')
        ensure_dir(cache)

        commits = load_json(os.path.join(cache, 'commits.json'), default=[]) or []
        for c in commits:
            c['stable_hints']        = extract_stable_hints(c)
            c['touched_paths_guess'] = infer_touched_paths(c.get('subject', ''), cfg)

        save_json(os.path.join(cache, 'enriched_commits.json'), commits)
        print('enriched %d commits' % len(commits))
        finish_stage(state_path, 'enrich_commits', started, status='ok',
                     extra={'commit_count': len(commits)})

    except SystemExit:
        raise
    except Exception as exc:
        fail_stage(state_path, 'enrich_commits', started, error_msg=str(exc))
        raise


if __name__ == '__main__':
    main()
