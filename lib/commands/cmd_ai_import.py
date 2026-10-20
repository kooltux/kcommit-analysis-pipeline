"""Validate AI results against the current work package and regenerate reports."""
import os

from lib.ai_exchange import Progress, WorkPackage, read_assessments
from lib.commands.base import load_cfg
from lib.config import load_json, save_json
from lib.manifest import CACHE_FILES


def import_results(cfg, bundle_path):
    """Import a server ZIP, result JSON or directory, independent of assessment grouping."""
    progress = Progress('ai-import')
    cache = cfg['paths']['cache_dir']
    outdir = cfg['paths']['output_dir']
    package = WorkPackage(cfg, progress)
    accepted = read_assessments(package, bundle_path, progress)
    merged = accepted.results
    prefilter = load_json(os.path.join(cache, CACHE_FILES['prefilter_kept']))
    if not isinstance(prefilter, list):
        raise ValueError('Missing prefilter cache')
    if not set(merged).issubset({commit['commit'] for commit in prefilter}):
        raise ValueError('AI result not found in local source cache')
    progress.say('All input validated; writing result sidecar and regenerating reports')
    dest = os.path.join(outdir, 'ai_analysis_results.json')
    save_json(dest, {'run_id': package.manifest['run_id'], 'results': merged})
    from lib.stages.st07_ai_report import run as report_run
    report_run(cfg, cache, outdir)
    progress.say('Done: ' + accepted.summary())
    return {'run_id': package.manifest['run_id'], 'analyzed_commits': len(merged)}


def cmd_ai_import(args):
    cfg = load_cfg(args)
    result = import_results(cfg, args.results_bundle)
    print('AI results imported: {} commit(s), run {}'.format(
        result['analyzed_commits'], result['run_id']))
