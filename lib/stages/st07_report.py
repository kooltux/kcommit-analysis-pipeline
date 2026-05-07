from lib.scoring import fmt_profiles, fmt_evidence
"""Stage 07 logic: generate all output formats."""
import csv
import json
import logging
import os
from lib.config import load_json, save_json
from lib.html_report import generate_html_report
from lib.manifest import CACHE_FILES


# ── Column definitions ────────────────────────────────────────────────────────
# Single definition used by all output formats (CSV, XLSX, ODS).

COMMIT_COLS = [
    'rank', 'sha12', 'subject', 'author', 'date', 'score',
    'profiles', 'product_evidence',
]

COMMIT_COLS_FILTERED = COMMIT_COLS + ['filter_reason']


def _commit_rows(commits, include_reason=False):
    rows = []
    for c in commits:
        row = [
            c.get('_rank', ''),
            (c.get('commit') or '')[:12],
            c.get('subject', ''),
            c.get('author_name', ''),
            c.get('author_time', ''),
            c.get('score', 0) or 0,
            fmt_profiles(c),
            fmt_evidence(c),
        ]
        if include_reason:
            row.append(c.get('_filter_reason', ''))
        rows.append(row)
    return rows


# ── Per-profile statistics ────────────────────────────────────────────────────

def _profile_summary(scored, profile_rules):
    """Per-profile commit count, total score, and average score."""
    summary = {}
    for pname in (profile_rules or {}):
        matched = [c for c in scored if pname in (c.get('matched_profiles') or [])]
        scores  = [c.get('score', 0) or 0 for c in matched]
        summary[pname] = {
            'description':  (profile_rules.get(pname) or {}).get('description', ''),
            'commit_count': len(matched),
            'total_score':  sum(scores),
            'avg_score':    round(sum(scores) / len(scores), 1) if scores else 0,
        }
    return summary


def _profile_matrix(scored):
    """Returns header list + list-of-rows for profile matrix CSV."""
    profiles = sorted({p for c in scored for p in (c.get('matched_profiles') or [])})
    header   = ['rank', 'sha12', 'score', 'subject'] + profiles
    rows     = []
    for c in scored:
        sc = (c.get('scoring') or {})
        ps = (sc.get('profiles') or {})
        row = [
            c.get('_rank', ''),
            (c.get('commit') or '')[:12],
            c.get('score', 0) or 0,
            c.get('subject', ''),
        ] + [ps.get(p, 0) for p in profiles]
        rows.append(row)
    return header, rows


# ── Coverage metrics (promoted to report_stats) ───────────────────────────────

def _coverage_metrics(scored):
    """Return diagnostic coverage counters included in report_stats.json.

    commits_matched_zero_profiles  -- commits that matched no profile at all
    commits_with_product_evidence  -- commits that have at least one
                                      product-evidence tag
    """
    return {
        'commits_matched_zero_profiles':
            sum(1 for c in scored if not (c.get('matched_profiles') or [])),
        'commits_with_product_evidence':
            sum(1 for c in scored if c.get('product_evidence')),
    }


# ── Output helpers ────────────────────────────────────────────────────────────

def _resolve_outputs(cfg):
    """Return the set of output format names to produce.

    Reads ``reports.outputs`` list.  Recognised names: 'csv', 'html', 'xlsx', 'ods'.
    Default when not configured: {'csv', 'html'}.
    """
    reports   = cfg.get('reports', {}) or {}
    outputs_l = reports.get('outputs')

    if outputs_l is not None:
        return {str(o).lower() for o in (outputs_l or [])}

    # No outputs configured — use default
    return {'csv', 'html'}


def _top_n(cfg):
    reports = cfg.get('reports', {}) or {}
    return int(reports.get('top_n') or 5000)


def _report_title(cfg):
    tmpl = cfg.get('reports', {}) or {}
    return tmpl.get('title', 'kcommit Analysis Report')


# ── Stage entry point ─────────────────────────────────────────────────────────

def run(cfg, cache, outdir):
    from lib.profile_rules import load_profile_rules
    try:
        from lib.spreadsheet import write_xlsx, write_ods
    except ImportError:
        write_xlsx = write_ods = None

    outputs  = _resolve_outputs(cfg)
    top_n    = _top_n(cfg)
    title    = _report_title(cfg)
    os.makedirs(outdir, exist_ok=True)

    scored        = (load_json(os.path.join(cache, CACHE_FILES['relevant']), default=[]) or [])[:top_n]
    profile_rules = load_profile_rules(cfg)

    report_stats = {
        'total_scored_commits': len(scored),
        'top_n': top_n,
        **_coverage_metrics(scored),
    }
    prof_summary      = _profile_summary(scored, profile_rules)
    mat_hdr, mat_rows = _profile_matrix(scored)

    # JSON outputs (always written)
    save_json(os.path.join(outdir, CACHE_FILES['relevant']), scored)
    save_json(os.path.join(outdir, 'report_stats.json'),        report_stats)
    save_json(os.path.join(outdir, 'profile_summary.json'),     prof_summary)
    save_json(os.path.join(outdir, 'profile_matrix.json'),
              {'header': mat_hdr, 'rows': mat_rows})

    # CSV
    if 'csv' in outputs:
        csv_path = os.path.join(outdir, 'relevant_commits.csv')
        with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(COMMIT_COLS)
            w.writerows(_commit_rows(scored))
        mat_path = os.path.join(outdir, 'profile_matrix.csv')
        with open(mat_path, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(mat_hdr)
            w.writerows(mat_rows)

    # HTML
    if 'html' in outputs:
        try:
            generate_html_report(
                scored, prof_summary, report_stats,
                os.path.join(outdir, 'summary.html',
                          templates_dir=cfg['paths'].get('templates_dir')),
                title=title,
            )
        except Exception as e:
            logging.warning('HTML report failed: %s', e)

    # XLSX
    if 'xlsx' in outputs:
        if write_xlsx:
            try:
                write_xlsx(os.path.join(outdir, 'relevant_commits.xlsx'),
                           scored, prof_summary)
            except Exception as e:
                logging.warning('XLSX failed: %s', e)
        else:
            logging.warning("'xlsx' output requested but lib.spreadsheet not available")

    # ODS
    if 'ods' in outputs:
        if write_ods:
            try:
                write_ods(os.path.join(outdir, 'relevant_commits.ods'),
                          scored, prof_summary)
            except Exception as e:
                logging.warning('ODS failed: %s', e)
        else:
            logging.warning("'ods' output requested but lib.spreadsheet not available")

    return report_stats