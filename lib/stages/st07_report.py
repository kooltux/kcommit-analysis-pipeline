from lib.scoring import fmt_profiles, fmt_evidence, order_commit_details
"""Stage 07 logic: generate all output formats."""
import csv
import json
import logging
import os
from lib.config import load_json, save_json
from lib.html_report import generate_html_report
from lib.manifest import CACHE_FILES


# Column definitions imported from manifest (single source of truth)
from lib.manifest import COMMIT_COLS as _MC, COMMIT_COLS_FILTERED as _MCF
# Use lowercase keys for CSV row construction; headers come from manifest
_COMMIT_KEYS          = ["rank", "sha", "subject", "author", "date",
                         "score", "profiles"]
_COMMIT_KEYS_FILTERED = _COMMIT_KEYS + ["filter_reason"]


def _fmt_date(ts):
    """Format a Unix timestamp or ISO string as YYYY-MM-DD HH:MM."""
    if not ts:
        return ''
    try:
        import datetime
        return datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')
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




def _trace_summary(commit):
    trace = (((commit or {}).get('scoring') or {}).get('trace') or {}).get('profiles') or {}
    parts = []
    for pname in sorted(trace):
        pdata = trace.get(pname) or {}
        rules = pdata.get('rules') or {}
        matched = sum(1 for rv in rules.values() if (rv or {}).get('matched'))
        parts.append('%s:%s/%s=%s' % (pname, matched, len(rules), pdata.get('final_score', 0)))
    return '; '.join(parts)


TRACE_COLS = ['sha', 'profile', 'rule', 'matched_level', 'rule_score', 'profile_score', 'pattern_type', 'pattern', 'matched_value']

def _trace_rows(scored):
    header = TRACE_COLS
    rows = []
    for c in scored or []:
        sha = (c.get('commit') or '')[:12]
        trace = (((c.get('scoring') or {}).get('trace') or {}).get('profiles') or {})
        for pname in sorted(trace):
            pdata = trace.get(pname) or {}
            pscore = pdata.get('final_score', 0)
            rules = pdata.get('rules') or {}
            if not rules:
                rows.append([sha, pname, '', '', 0, pscore, '', '', ''])
                continue
            for rname in sorted(rules):
                rdata = rules.get(rname) or {}
                matches = rdata.get('matches') or {}
                emitted = False
                for kind in ['keywords_whitelist', 'path_whitelist', 'commit_whitelist']:
                    for m in (matches.get(kind) or []):
                        rows.append([sha, pname, rname, rdata.get('matched_level', ''), rdata.get('score', 0), pscore, kind, m.get('pattern', ''), m.get('value', '')])
                        emitted = True
                if not emitted:
                    rows.append([sha, pname, rname, rdata.get('matched_level', ''), rdata.get('score', 0), pscore, '', '', ''])
    return header, rows



def _canonical_commit(commit):
    return order_commit_details(commit)


def _write_commit_details(root, commits):
    written = 0
    if not commits:
        return written
    os.makedirs(root, exist_ok=True)
    seen = set()
    for c in commits:
        full = c.get('commit') or ''
        if not full or full in seen:
            continue
        seen.add(full)
        shard = os.path.join(root, full[:2], full[2:4])
        os.makedirs(shard, exist_ok=True)
        _save_ordered_json(os.path.join(shard, full + '.json'), _canonical_commit(c))
        written += 1
    return written


def _write_table_json(path, commits, include_reason=False):
    rows = []
    for c in commits:
        row = {
            'commit': c.get('commit', ''),
            'subject': c.get('subject', ''),
            'author_name': c.get('author_name', ''),
            'author_time': c.get('author_time', ''),
            'score': c.get('score', 0) or 0,
            'matched_profiles': list(c.get('matched_profiles') or []),
        }
        if include_reason and c.get('_filter_reason', ''):
            row['_filter_reason'] = c.get('_filter_reason', '')
        rows.append(order_commit_details(row))
    _save_ordered_json(path, rows)

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




def _save_ordered_json(path, data):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
        f.write('\n')

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
    reports_cfg = cfg.get('reports', {}) or {}
    html_detail_mode = reports_cfg.get('html_detail_mode', 'sidecar')
    html_embed_compression = reports_cfg.get('html_embed_compression', 'none')
    stage_state_path = os.path.join(outdir, 'runtime_status.json')
    os.makedirs(outdir, exist_ok=True)
    _written = []  # every file actually written this run

    def _emit(path):
        """Record path as successfully written. Call AFTER the write."""
        try:
            _written.append(os.path.relpath(path, outdir))
        except ValueError:
            _written.append(path)



    scored        = (load_json(os.path.join(cache, CACHE_FILES['relevant']), default=[]) or [])
    if top_n is not None:
        scored = scored[:top_n]
    prefiltered   = load_json(os.path.join(cache, CACHE_FILES['filtered']), default=[]) or []
    postfiltered  = load_json(os.path.join(cache, CACHE_FILES['postfilter_dropped']), default=[]) or []
    filtered      = list(prefiltered) + list(postfiltered)
    profile_rules = load_profile_rules(cfg)

    # Stage counts for the hierarchical sidebar (D.12)
    _all_scored  = load_json(os.path.join(cache, CACHE_FILES['scored']), default=[]) or []
    _collected   = load_json(os.path.join(cache, CACHE_FILES['commits']), default=[]) or []
    _pf_kept     = load_json(os.path.join(cache, CACHE_FILES['prefilter_kept']), default=[]) or []
    _threshold   = (lambda filt: float(filt.get('min_score', 0) or 0))(cfg.get('filter', {}) or {})
    _scores_all  = [float(c.get('score', 0) or 0) for c in scored]


    def _update_stage7_progress(current, total, message):
        payload = {
            'current': int(current),
            'total': max(1, int(total)),
            'message': message,
        }
        save_json(stage_state_path, {
            'stage': 'report_commits',
            'stage_number': 7,
            'stage_total': 7,
            'progress': payload,
        })

    report_stats = {
        # Stage 01 — collection
        'st01_collected':           len(_collected),
        # Stage 04 — prefilter
        'st04_prefilter_kept':      len(_pf_kept),
        'st04_prefilter_dropped':   len(_collected) - len(_pf_kept),
        # Stage 05 — scoring
        'st05_total_scored':        len(_all_scored),
        # Stage 06 — postfilter
        'st06_threshold':           _threshold,
        'st06_postfilter_dropped':  len(postfiltered),
        # Stage 07 — report
        'total_scored_commits':     len(scored),
        'top_n':                    top_n,
        'score_highest':            max(_scores_all) if _scores_all else 0,
        'score_lowest':             min(_scores_all) if _scores_all else 0,
        'score_avg':                round(sum(_scores_all) / len(_scores_all), 1) if _scores_all else 0,
        **_coverage_metrics(scored),
    }
    prof_summary      = _profile_summary(scored, profile_rules)
    mat_hdr, mat_rows = _profile_matrix(scored)
    details_root = os.path.join(outdir, 'commits')
    _write_commit_details(details_root, list(scored) + list(filtered))

    # JSON outputs (always written)
    _p = os.path.join(outdir, 'relevant_commits.json')
    _save_ordered_json(_p, [_canonical_commit(c) for c in scored]);  _emit(_p)
    _p = os.path.join(outdir, 'profile_summary.json')
    save_json(_p, prof_summary);  _emit(_p)
    _p = os.path.join(outdir, 'profile_matrix.json')
    save_json(_p, {'header': mat_hdr, 'rows': mat_rows});  _emit(_p)
    trace_hdr, trace_rows = _trace_rows(scored)
    _p = os.path.join(outdir, 'rule_trace.json')
    save_json(_p, {'header': trace_hdr, 'rows': trace_rows});  _emit(_p)
    if filtered:
        _p = os.path.join(outdir, 'filtered_commits.json')
        _save_ordered_json(_p, [_canonical_commit(c) for c in filtered]);  _emit(_p)

    # CSV
    if 'csv' in outputs:
        csv_path = os.path.join(outdir, 'relevant_commits.csv')
        with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(_MC)
            w.writerows(_commit_rows(scored))
        _emit(csv_path)
        mat_path = os.path.join(outdir, 'profile_matrix.csv')
        with open(mat_path, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(mat_hdr)
            w.writerows(mat_rows)
        _emit(mat_path)
        ps_path = os.path.join(outdir, 'profile_summary.csv')
        with open(ps_path, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(['profile', 'count', 'total_score', 'avg_score'])
            for pname, pd in sorted(prof_summary.items(),
                                    key=lambda kv: kv[1].get('commit_count', 0),
                                    reverse=True):
                w.writerow([pname, pd.get('commit_count', 0),
                             pd.get('total_score', 0), pd.get('avg_score', 0)])
        _emit(ps_path)
        # Filtered-out commits
        if filtered:
            flt_path = os.path.join(outdir, 'filtered_commits.csv')
            with open(flt_path, 'w', newline='', encoding='utf-8') as fh:
                w = csv.writer(fh)
                w.writerow(_MCF)
                w.writerows(_commit_rows(filtered, include_reason=True))
            _emit(flt_path)

    metadata = {
        'report_title': title,
        'git': cfg.get('git', {}) or {},
        'analysis': {
            'top_n': top_n,
            'outputs': sorted(outputs),
            'html_detail_mode': html_detail_mode,
            'html_embed_compression': html_embed_compression,
            'filter': cfg.get('filter', {}) or {},
            'reports': reports_cfg,
            'active_profiles': sorted((cfg.get('profiles', {}) or {}).get('active', {}).keys()),
        },
        'report_stats': report_stats,
        'profile_summary': prof_summary,
    }

    # HTML
    if 'html' in outputs:
        try:
            _update_stage7_progress(1, 4, 'Writing report metadata')
            _save_ordered_json(os.path.join(outdir, 'report_metadata.json'), metadata)
            _emit(os.path.join(outdir, 'report_metadata.json'))
            _update_stage7_progress(2, 4, 'Writing report index JSON')
            _hp = os.path.join(outdir, 'relevant_commits.html')
            _tp = os.path.join(outdir, 'relevant_commits.table.json')
            _write_table_json(_tp, scored, include_reason=False)
            _emit(_tp)
            _update_stage7_progress(3, 4, 'Writing per-commit detail JSON')
            _update_stage7_progress(4, 4, 'Generating HTML pages')
            generate_html_report(
                scored, prof_summary, report_stats, _hp,
                title=title,
                templates_dir=cfg['paths'].get('templates_dir'),
                detail_mode=html_detail_mode,
                commit_index_path='./relevant_commits.table.json' if html_detail_mode == 'sidecar' else None,
                commit_detail_root='./commits',
                embed_compression=html_embed_compression,
            )
            _emit(_hp)
        except Exception as e:
            logging.warning('HTML report failed: %s', e)
        if filtered:
            try:
                _fhp = os.path.join(outdir, 'filtered_commits.html')
                _ftp = os.path.join(outdir, 'filtered_commits.table.json')
                _write_table_json(_ftp, filtered, include_reason=True)
                _emit(_ftp)
                generate_html_report(
                    filtered, {}, {'total_scored_commits': len(filtered)},
                    _fhp, title=title + ' — Filtered Commits',
                    is_filtered=True,
                    templates_dir=cfg['paths'].get('templates_dir'),
                    detail_mode=html_detail_mode,
                    commit_index_path='./filtered_commits.table.json' if html_detail_mode == 'sidecar' else None,
                    commit_detail_root='./commits',
                    embed_compression=html_embed_compression,
                )
                _emit(_fhp)
            except Exception as e:
                logging.warning('HTML filtered report failed: %s', e)

    # XLSX
    if 'xlsx' in outputs:
        if write_xlsx:
            try:
                write_xlsx(os.path.join(outdir, 'relevant_commits.xlsx'),
                           scored, prof_summary,
                           sheet_name='Relevant Commits')
                _emit(os.path.join(outdir, 'relevant_commits.xlsx'))
            except Exception as e:
                logging.warning('XLSX failed: %s', e)
            if filtered:
                try:
                    write_xlsx(os.path.join(outdir, 'filtered_commits.xlsx'),
                               filtered, {},
                               sheet_name='Filtered Commits',
                               include_reason=True)
                    _emit(os.path.join(outdir, 'filtered_commits.xlsx'))
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
                _emit(os.path.join(outdir, 'summary.xlsx'))
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
                _emit(os.path.join(outdir, 'relevant_commits.ods'))
            except Exception as e:
                logging.warning('ODS failed: %s', e)
            if filtered:
                try:
                    write_ods(os.path.join(outdir, 'filtered_commits.ods'),
                              filtered, {},
                              sheet_name='Filtered Commits',
                              include_reason=True)
                    _emit(os.path.join(outdir, 'filtered_commits.ods'))
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
                _emit(os.path.join(outdir, 'summary.ods'))
            except Exception as e:
                logging.warning('ODS summary failed: %s', e)
        else:
            logging.warning("'ods' output requested but lib.spreadsheet not available")
    # Embed generated_files list, then write report_stats.json last
    report_stats['generated_files'] = sorted(set(
        f for f in _written if f != 'report_stats.json'))
    save_json(os.path.join(outdir, 'report_stats.json'), report_stats)
    return report_stats
