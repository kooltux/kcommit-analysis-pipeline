"""Load imported AI findings for report-only display."""
import os

from lib.config import load_json


def load_ai_results(outdir):
    """Return run-bound findings, ignoring an obsolete sidecar."""
    manifest_path = os.path.join(outdir, 'ai_analysis_bundle_manifest.json')
    results_path = os.path.join(outdir, 'ai_analysis_results.json')
    if not os.path.isfile(manifest_path) or not os.path.isfile(results_path):
        return {}
    manifest = load_json(manifest_path)
    sidecar = load_json(results_path)
    if (not isinstance(manifest, dict) or not isinstance(sidecar, dict)
            or not isinstance(sidecar.get('results'), dict)
            or sidecar.get('run_id') != manifest.get('run_id')):
        return {}
    return sidecar['results']


def attach_ai_results(commits, results):
    """Decorate copied commits without modifying stage caches or ordering."""
    decorated = []
    for commit in commits:
        item = dict(commit)
        sha = item.get('commit')
        if sha in results:
            item['ai_analysis'] = dict(results[sha])
        decorated.append(item)
    return decorated
