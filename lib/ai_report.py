"""Load imported AI findings for report-only display."""
from lib.ai_import_store import load_report_results


def load_ai_results(outdir):
    """Return validated current-run store or legacy findings without writing."""
    return load_report_results(outdir)


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
