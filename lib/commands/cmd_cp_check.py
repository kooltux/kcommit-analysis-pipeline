"""kcommit-analysis-pipeline — cp-check subcommand (v19.2.0).

Standalone cherry-pick feasibility checker, replacing the previously
generated output/cherry_pick_check.py script.  Running the real
lib.gitutils logic directly (instead of an embedded copy baked into a
generated file) eliminates the risk of the two implementations drifting
apart -- a bug class that bit the generated script twice in earlier
sessions (missing stdin piping, then an indentation error in the embedded
SQL template).

Usage
─────
  kcommit_pipeline.py cp-check --config cfg.json
  kcommit_pipeline.py cp-check --config cfg.json --update   (default; same as no flag)
  kcommit_pipeline.py cp-check --config cfg.json --force    (wipe cache, retest all)
  kcommit_pipeline.py cp-check --config cfg.json --json
  kcommit_pipeline.py cp-check --config cfg.json --verbose

Unlike the stage-06 inline cherry-pick test (gated on collect.cherry_pick_test),
this command always runs the check, regardless of that config flag -- it is
meant as an explicit, on-demand tool: "check cherry-pick feasibility for the
current relevant-commit set", independent of whether the full pipeline run
had the feature turned on.

Commit source: the current CACHE_FILES['prefilter_kept'] cache (i.e. the
commit set that passed the prefilter and entered scoring).  This is the
largest "product-touching" set before scoring/thresholding.  Requires that
the pipeline has been run at least through stage 04 (prefilter_commits) so
that cache exists; a clear error is raised otherwise.
"""
import json
import os
import sys

from lib.commands.base import load_cfg
from lib.config import load_json
from lib.manifest import CACHE_FILES
from lib.gitutils import batch_can_cherry_pick
from lib.cherrypick_db import load_or_create_db, delete_db


def _resolve_workers(cfg):
    collect = cfg.get('collect', {}) or {}
    configured = int(collect.get('cherry_pick_workers', 0) or 0)
    try:
        default_workers = os.cpu_count() or 1
    except Exception:
        default_workers = 1
    return configured if configured > 0 else default_workers


def cmd_cp_check(args):
    cfg = load_cfg(args)

    kernel  = cfg.get('kernel', {}) or {}
    collect = cfg.get('collect', {}) or {}

    target_rev = kernel.get('rev_old')
    if not target_rev:
        raise SystemExit('cp-check: kernel.rev_old is required in the config.')

    cache_dir = collect.get('cherry_pick_cache_dir')
    if not cache_dir:
        raise SystemExit(
            'cp-check: collect.cherry_pick_cache_dir is required. '
            'Add "cherry_pick_cache_dir": "/path/to/cache" to the "collect" '
            'section of your config file.'
        )

    # Use cache_dir to find prefilter_kept_commits.json, since that's where
    # the pipeline writes it (stage 04 writes to cache, not output).
    # cfg['paths']['cache_dir'] is set by load_config() to an absolute path.
    pipeline_cache_dir = cfg.get('paths', {}).get('cache_dir')
    if not pipeline_cache_dir:
        # Fallback: construct from work_dir if paths.cache_dir is missing
        work_dir = cfg.get('paths', {}).get('work_dir')
        if work_dir:
            pipeline_cache_dir = os.path.join(work_dir, 'cache')
        else:
            raise SystemExit(
                'cp-check: paths.work_dir is required in the config. '
                'Add "work_dir": "/path/to/work" to the "paths" section.'
            )

    prefilter_kept = load_json(
        os.path.join(pipeline_cache_dir, CACHE_FILES['prefilter_kept']), default=None)
    if prefilter_kept is None:
        raise SystemExit(
            'cp-check: %s not found in %s. Run the pipeline through stage 04 '
            '(prefilter_commits) first, e.g.:\n'
            '  kcommit_pipeline.py run --config %s'
            % (CACHE_FILES['prefilter_kept'], pipeline_cache_dir, args.config)
        )

    shas = [c.get('commit') for c in prefilter_kept if c.get('commit')]
    if not shas:
        print('cp-check: no commits with a SHA found; nothing to test.')
        return

    if args.force:
        removed = delete_db(cache_dir, target_rev)
        if args.verbose:
            print('  %s cherry-pick cache for %s'
                  % ('Cleared' if removed else 'No existing cache found for', target_rev))

    db = load_or_create_db(cache_dir, target_rev)
    tested_shas = set() if args.force else db.get_all_shas()
    new_shas = [s for s in shas if s not in tested_shas]

    cached_results = {} if args.force else db.get_results(shas)

    workers = _resolve_workers(cfg)

    if new_shas:
        if not args.json:
            print('Testing %d commit(s) for cherry-pick onto %s (%d worker(s))...'
                  % (len(new_shas), target_rev, workers))

        last_display = [-1]

        def _progress(done, total, eta_seconds):
            if args.json:
                return
            percent = int(done / float(total) * 100)
            if percent % 5 == 0 and percent != last_display[0] or done == total:
                last_display[0] = percent
                sys.stdout.write('\r  %d/%d (%.1f%%)' % (done, total, percent))
                sys.stdout.flush()

        new_results = batch_can_cherry_pick(
            cfg, new_shas, target_rev, progress_callback=_progress, workers=workers)

        for sha, result in new_results.items():
            db.add_result(sha, result)
        db.flush()

        if not args.json:
            sys.stdout.write('\n')
            sys.stdout.flush()
    else:
        new_results = {}
        if not args.json:
            print('All %d commit(s) already cached for %s; nothing new to test.'
                  % (len(shas), target_rev))

    db.save()

    all_results = dict(cached_results)
    all_results.update(new_results)

    ok_count   = sum(1 for r in all_results.values() if r.get('ok'))
    fail_count = len(all_results) - ok_count

    if args.json:
        print(json.dumps({
            'summary': {
                'total':        len(shas),
                'clean':        ok_count,
                'conflicts':    fail_count,
                'target_rev':   target_rev,
                'tested_now':   len(new_results),
                'reused_cache': len(shas) - len(new_results),
            },
            'results': [
                dict(sha=sha, **all_results.get(sha, {'ok': None, 'conflicts': [], 'error': 'not tested'}))
                for sha in shas
            ],
        }, indent=2, default=str))
        return

    print('\nSummary: %d/%d clean, %d with conflicts (target: %s)'
          % (ok_count, len(shas), fail_count, target_rev))
    if new_results:
        print('  Tested %d new commit(s), reused %d cached result(s)'
              % (len(new_results), len(shas) - len(new_results)))

    if args.verbose:
        print()
        for sha in shas:
            result = all_results.get(sha)
            if result is None:
                status = '? not tested'
            elif result.get('ok'):
                status = '\u2713 clean'
            else:
                n = len(result.get('conflicts') or [])
                status = '\u2717 conflict' + (' (%d files)' % n if n else '')
            print('  %s  %s' % (sha[:12], status))
