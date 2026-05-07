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
    'rank', 'sha', 'subject', 'author', 'date', 'score',
    'profiles', 'product_evidence',
]

COMMIT_COLS_FILTERED = COMMIT_COLS + ['filter_reason']


def _fmt_date(ts):
    """Format a Unix timestamp or ISO string as YYYY-MM-DD HH:MM."""
    if not ts:
        return ''
    try:
        import datetime
        return datetime.datetime.utcfromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M')
    except (TypeError, ValueError):
        return str(ts)[:16]


def _commit_rows(commits, include_reason=False):
    rows = []
    for c in commits:
        row = [
            c.get('_rank', ''),
            (c.get('commit') or '')[:12],
            c.get('subject', ''),
            c.get('author_name', ''),
            _fmt_date(c.get('author_time', '')),
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
    """Return the top-N limit, or None when top_n is 0 (meaning no limit)."""
    reports = cfg.get('reports', {}) or {}
    val = reports.get('top_n')
    if val is None:
        return 5000  # default
    n = int(val)
    return None if n == 0 else n  # 0 → no limit


def _report_title(cfg):
    tmpl = cfg.get('reports', {}) or {}
    return tmpl.get('title', 'kcommit Analysis Report')


# ── Stage entry point ─────────────────────────────────────────────────────────

def run(cfg, cache, outdir):
    from lib.profile_rules import load_profile_rules
    try:
        from lib.spreadsheet import (
            write_xlsx, write_ods,
            write_profile_summary_xlsx, write_profile_matrix_xlsx,
            write_profile_summary_ods,  write_profile_matrix_ods,
            write_summary_xlsx, write_summary_ods,
        )
    except ImportError:
        write_xlsx = write_ods = None

    outputs  = _resolve_outputs(cfg)
    top_n    = _top_n(cfg)
    title    = _report_title(cfg)
    os.makedirs(outdir, exist_ok=True)

    scored        = (load_json(os.path.join(cache, CACHE_FILES['relevant']), default=[]) or [])
    if top_n is not None:
        scored = scored[:top_n]
    filtered      = load_json(os.path.join(cache, CACHE_FILES['filtered']), default=[]) or []
    profile_rules = load_profile_rules(cfg)

    report_stats = {
        'total_scored_commits': len(scored),
        'top_n': top_n,
        **_coverage_metrics(scored),
    }
    prof_summary      = _profile_summary(scored, profile_rules)
    mat_hdr, mat_rows = _profile_matrix(scored)

    # JSON outputs (always written)
    save_json(os.path.join(outdir, 'relevant_commits.json'),  scored)
    save_json(os.path.join(outdir, 'report_stats.json'),      report_stats)
    save_json(os.path.join(outdir, 'profile_summary.json'),   prof_summary)
    save_json(os.path.join(outdir, 'profile_matrix.json'),
              {'header': mat_hdr, 'rows': mat_rows})
    if filtered:
        save_json(os.path.join(outdir, 'filtered_commits.json'), filtered)

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
        ps_path = os.path.join(outdir, 'profile_summary.csv')
        with open(ps_path, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(['profile', 'count', 'total_score', 'avg_score'])
            for pname, pd in sorted(prof_summary.items(),
                                    key=lambda kv: kv[1].get('commit_count', 0),
                                    reverse=True):
                w.writerow([pname, pd.get('commit_count', 0),
                             pd.get('total_score', 0), pd.get('avg_score', 0)])
        # Filtered-out commits
        if filtered:
            flt_path = os.path.join(outdir, 'filtered_commits.csv')
            with open(flt_path, 'w', newline='', encoding='utf-8') as fh:
                w = csv.writer(fh)
                w.writerow(COMMIT_COLS_FILTERED)
                w.writerows(_commit_rows(filtered, include_reason=True))

    # HTML
    if 'html' in outputs:
        try:
            generate_html_report(
                scored, prof_summary, report_stats,
                os.path.join(outdir, 'relevant_commits.html'),
                title=title,
                templates_dir=cfg['paths'].get('templates_dir'),
            )
        except Exception as e:
            logging.warning('HTML report failed: %s', e)
        if filtered:
            try:
                generate_html_report(
                    filtered, {}, {'total_scored_commits': len(filtered)},
                    os.path.join(outdir, 'filtered_commits.html'),
                    title=title + ' — Filtered Commits',
                    is_filtered=True,
                    templates_dir=cfg['paths'].get('templates_dir'),
                )
            except Exception as e:
                logging.warning('HTML filtered report failed: %s', e)

    # XLSX
    if 'xlsx' in outputs:
        if write_xlsx:
            try:
                write_xlsx(os.path.join(outdir, 'relevant_commits.xlsx'),
                           scored, prof_summary,
                           sheet_name='Relevant Commits')
            except Exception as e:
                logging.warning('XLSX failed: %s', e)
            if filtered:
                try:
                    write_xlsx(os.path.join(outdir, 'filtered_commits.xlsx'),
                               filtered, {},
                               sheet_name='Filtered Commits',
                               include_reason=True)
                except Exception as e:
                    logging.warning('XLSX filtered failed: %s', e)
            try:
                write_profile_summary_xlsx(
                    os.path.join(outdir, 'profile_summary.xlsx'), prof_summary)
            except Exception as e:
                logging.warning('XLSX profile_summary failed: %s', e)
            try:
                write_profile_matrix_xlsx(
                    os.path.join(outdir, 'profile_matrix.xlsx'), scored)
            except Exception as e:
                logging.warning('XLSX profile_matrix failed: %s', e)
            try:
                write_summary_xlsx(os.path.join(outdir, 'summary.xlsx'),
                                   scored, filtered, prof_summary,
                                   report_stats=report_stats,
                                   report_title=title)
            except Exception as e:
                logging.warning('XLSX summary failed: %s', e)
        else:
            logging.warning("'xlsx' output requested but lib.spreadsheet not available")

    # ODS
    if 'ods' in outputs:
        if write_ods:
            try:
                write_ods(os.path.join(outdir, 'relevant_commits.ods'),
                          scored, prof_summary,
                          sheet_name='Relevant Commits')
            except Exception as e:
                logging.warning('ODS failed: %s', e)
            if filtered:
                try:
                    write_ods(os.path.join(outdir, 'filtered_commits.ods'),
                              filtered, {},
                              sheet_name='Filtered Commits',
                              include_reason=True)
                except Exception as e:
                    logging.warning('ODS filtered failed: %s', e)
            try:
                write_profile_summary_ods(
                    os.path.join(outdir, 'profile_summary.ods'), prof_summary)
            except Exception as e:
                logging.warning('ODS profile_summary failed: %s', e)
            try:
                write_profile_matrix_ods(
                    os.path.join(outdir, 'profile_matrix.ods'), scored)
            except Exception as e:
                logging.warning('ODS profile_matrix failed: %s', e)
            try:
                write_summary_ods(os.path.join(outdir, 'summary.ods'),
                                  scored, filtered, prof_summary,
                                  report_stats=report_stats,
                                  report_title=title)
            except Exception as e:
                logging.warning('ODS summary failed: %s', e)
        else:
            logging.warning("'ods' output requested but lib.spreadsheet not available")

    return report_stats