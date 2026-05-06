"""Stage 07 logic: generate all output formats."""
import csv
import json
import os
from lib.config import load_json, save_json
from lib.html_report import generate_html_report


def _coverage(scored):
    return {
        'commits_matched_zero_profiles':
            sum(1 for c in scored if not (c.get('matched_profiles') or [])),
        'commits_with_product_evidence':
            sum(1 for c in scored if c.get('product_evidence')),
    }


def _profile_summary(scored, profile_rules):
    """Per-profile commit count and average score."""
    summary = {}
    for pname in (profile_rules or {}):
        matched = [c for c in scored if pname in (c.get('matched_profiles') or [])]
        scores  = [c.get('score', 0) or 0 for c in matched]
        summary[pname] = {
            'commit_count': len(matched),
            'avg_score':    round(sum(scores) / len(scores), 1) if scores else 0,
        }
    return summary


def _profile_matrix(scored):
    """Returns header list + list-of-rows for profile matrix CSV."""
    profiles = sorted({p for c in scored for p in (c.get('matched_profiles') or [])})
    header   = ['rank', 'sha12', 'score', 'subject'] + profiles
    rows     = []
    for c in scored:
        mp = set(c.get('matched_profiles') or [])
        sc = c.get('scoring', {}) or {}
        ps = (sc.get('profiles') or {})
        row = [
            c.get('_rank', ''),
            (c.get('commit') or '')[:12],
            c.get('score', 0) or 0,
            c.get('subject', ''),
        ] + [ps.get(p, 0) for p in profiles]
        rows.append(row)
    return header, rows


COMMIT_COLS_FILTERED = [
    'rank', 'sha12', 'subject', 'author', 'date', 'score',
    'profiles', 'product_evidence', 'filter_reason',
]

COMMIT_COLS_RELEVANT = [
    'rank', 'sha12', 'subject', 'author', 'date', 'score',
    'profiles', 'product_evidence',
]


def _commit_rows(commits, include_reason=False):
    rows = []
    for c in commits:
        sc = c.get('scoring', {}) or {}
        row = [
            c.get('_rank', ''),
            (c.get('commit') or '')[:12],
            c.get('subject', ''),
            c.get('author_name', ''),
            c.get('author_time', ''),
            c.get('score', 0) or 0,
            '; '.join(c.get('matched_profiles') or []),
            '; '.join(c.get('product_evidence') or []),
        ]
        if include_reason:
            row.append(c.get('_filter_reason', ''))
        rows.append(row)
    return rows


def run(cfg, cache, outdir):
    from lib.profile_rules import load_profile_rules
    from lib.spreadsheet import write_xlsx, write_ods, COMMIT_COLS

    tmpl       = cfg.get('templates') or {}
    title      = tmpl.get('report_title', 'kcommit Analysis Report')
    top_n      = int(tmpl.get('top_n', 5000) or 5000)
    os.makedirs(outdir, exist_ok=True)

    scored        = load_json(os.path.join(cache, '06_relevant_commits.json'), default=[]) or []
    scored        = scored[:top_n]
    profile_rules = load_profile_rules(cfg)

    report_stats = {
        'total_scored_commits': len(scored),
        'top_n': top_n,
        **_coverage(scored),
    }
    prof_summary  = _profile_summary(scored, profile_rules)
    mat_hdr, mat_rows = _profile_matrix(scored)

    # JSON outputs
    save_json(os.path.join(outdir, '06_relevant_commits.json'), scored)
    save_json(os.path.join(outdir, 'report_stats.json'), report_stats)
    save_json(os.path.join(outdir, 'profile_summary.json'), prof_summary)
    save_json(os.path.join(outdir, 'profile_matrix.json'),
              {'header': mat_hdr, 'rows': mat_rows})

    # CSV
    if tmpl.get('csv_output', True):
        csv_path = os.path.join(outdir, 'relevant_commits.csv')
        with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(COMMIT_COLS_RELEVANT)
            w.writerows(_commit_rows(scored))
        mat_path = os.path.join(outdir, 'profile_matrix.csv')
        with open(mat_path, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(mat_hdr)
            w.writerows(mat_rows)

    # HTML
    if tmpl.get('html_summary', True):
        try:
            generate_html_report(
                scored, prof_summary, report_stats,
                os.path.join(outdir, 'summary.html'),
                title=title,
            )
        except Exception as e:
            import logging; logging.warning('HTML report failed: %s', e)

    # XLSX
    if tmpl.get('xls_output', False):
        try:
            write_xlsx(os.path.join(outdir, 'relevant_commits.xlsx'),
                       scored, prof_summary)
        except Exception as e:
            import logging; logging.warning('XLSX failed: %s', e)

    # ODS
    if tmpl.get('ods_output', False):
        try:
            write_ods(os.path.join(outdir, 'relevant_commits.ods'),
                      scored, prof_summary)
        except Exception as e:
            import logging; logging.warning('ODS failed: %s', e)

    return report_stats
