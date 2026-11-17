"""Load imported AI findings for report-only display."""
from copy import deepcopy

from lib.ai_import_store import load_report_results


AI_SUMMARY_FIELDS = (
    ('AI security fix', 'ai_is_security_fix'),
    ('AI bug fix', 'ai_is_bug_fix'),
    ('AI product impact', 'ai_impact_on_product'),
    ('AI backport effort', 'ai_backport_effort'),
    ('AI recommendation', 'ai_backport_recommendation'),
    ('AI summary', 'ai_summary'),
    ('Reviewer agreement', 'rv_agreement'),
)
AI_SUMMARY_COLUMNS = ('AI assessed',) + tuple(title for title, _ in AI_SUMMARY_FIELDS)


def has_ai_results(commits):
    return any(isinstance(commit.get('ai_analysis'), dict) for commit in commits)


def ai_columns(columns, commits):
    return list(columns) + (list(AI_SUMMARY_COLUMNS) if has_ai_results(commits) else [])


def ai_summary_cells(commit):
    assessment = commit.get('ai_analysis')
    if not isinstance(assessment, dict):
        return [''] * len(AI_SUMMARY_COLUMNS)
    def text(value):
        if value is None:
            return ''
        if isinstance(value, bool):
            return 'Yes' if value else 'No'
        value = str(value)
        return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value
    return ['Yes'] + [text(assessment.get(key)) for _, key in AI_SUMMARY_FIELDS]


def load_ai_results(outdir):
    """Return validated current-run store or legacy findings without writing."""
    return load_report_results(outdir)


def attach_ai_results(commits, results):
    """Decorate independent copies; missing current findings remain unassessed."""
    decorated = []
    for commit in commits:
        item = deepcopy(commit)
        item.pop('ai_analysis', None)
        sha = item.get('commit')
        if sha in results:
            item['ai_analysis'] = deepcopy(results[sha])
        decorated.append(item)
    return decorated
