#!/usr/bin/env python3
"""Stage 04: Enrich commits with stable hints and touched-path guesses.

"""
import argparse
import os
import sys

from lib.config import load_config
from lib.io_utils import ensure_dir, load_json, save_json
from lib.scoring import extract_stable_hints, infer_touched_paths
from lib.validation import validate_inputs
from lib.pipeline_runtime import (
    start_stage, finish_stage, fail_stage, update_stage_progress
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    args = ap.parse_args()

    cfg        = load_config(args.config)
    work       = cfg.get('project', {}).get('work_dir', './work')
    state_path = os.path.join(work, 'pipeline_state.json')
    started    = start_stage(state_path, 'enrich_commits', 2, 5)

    try:
        problems, notices = validate_inputs(cfg)
        for note in notices:
            print('  NOTICE:', note)
        if problems:
            for p in problems:
                print('  ERROR:', p)
            fail_stage(state_path, 'enrich_commits', started,
                       error_msg='; '.join(problems))
            raise SystemExit(2)

        cache = os.path.join(work, 'cache')
        ensure_dir(cache)

        commits = load_json(os.path.join(cache, 'commits.json'),
                            default=[]) or []
        total   = len(commits)
        step    = max(1, total // 50)

        for i, c in enumerate(commits):
            c['stable_hints']        = extract_stable_hints(c)
            c['touched_paths_guess'] = infer_touched_paths(
                c.get('subject', ''), cfg)
            if i % step == 0 or i == total - 1:
                update_stage_progress(2, 5, (i + 1) / max(total, 1),
                                      'enriching',
                                      n_done=i + 1, n_total=total)

        sys.stdout.write('\n')
        sys.stdout.flush()

        save_json(os.path.join(cache, 'enriched_commits.json'), commits)
        print('  enriched %d commits' % total)
        finish_stage(state_path, 'enrich_commits', started, status='ok',
                     extra={'enriched_count': total})

    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        fail_stage(state_path, 'enrich_commits', started, error_msg=str(exc))
        raise


if __name__ == '__main__':
    main()
