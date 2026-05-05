import time
#!/usr/bin/env python3
"""Stage 06: Generate reports from scored commits.

v8.5.1: XLSX now stdlib-only (no openpyxl).

v8.5:
  - reports.min_score: commits below threshold excluded from all outputs.
  - Rank column: c['_rank'] (1-based) assigned before any output.
  - Format flags: templates.csv_output / html_summary / xls_output / ods_output.
  - XLSX via lib.spreadsheet.write_xlsx (needs openpyxl).
  - ODS  via lib.spreadsheet.write_ods  (stdlib only).
  - avg_score added to profile_summary.json.
  - rank as first column in profile_matrix.csv.
  - f-strings throughout.
"""
import json
import argparse, csv, os

from lib.config          import load_config, load_json, save_json
from lib.validation      import validate_config_only as validate_inputs
from lib.pipeline_runtime import (
    start_stage, finish_stage, fail_stage,
    print_stage_input, print_stage_output,
)
from lib.html_report     import generate_html_report


def _coverage(scored):
    return {
        'commits_matched_zero_profiles':
            sum(1 for c in scored if not (c.get('matched_profiles') or [])),
        'commits_matched_one_profile':
            sum(1 for c in scored if len(c.get('matched_profiles') or []) == 1),
        'commits_matched_multiple_profiles':
            sum(1 for c in scored if len(c.get('matched_profiles') or []) > 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--override', default=None, metavar='JSON',
                    help='Deep-merge JSON into config (forwarded from kcommit_pipeline)')
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.override:
        from kcommit_pipeline import apply_override
        apply_override(cfg, args.override)
    work       = cfg['paths']['work_dir']
    state_path = os.path.join(work, 'pipeline_state.json')
    started    = start_stage(state_path, 'report_commits', 6, 7)

    try:
        problems, notices = validate_inputs(cfg)
        for n in notices:
            print(f'  NOTICE: {n}')
        if problems:
            for p in problems: print(f'  ERROR: {p}')
            fail_stage(state_path, 'report_commits', started,
                       error_msg='; '.join(problems))
            raise SystemExit(2)

        cache  = os.path.join(work, 'cache')
        outdir = os.path.join(work, 'output')
        os.makedirs(outdir, exist_ok=True)

        scored = (load_json(os.path.join(cache, 'scored_commits.json'),
                            default=[]) or [])
        scored = sorted(scored, key=lambda x: x.get('score', 0), reverse=True)
        _t0_stage = time.time()
        print_stage_input('report input', scored)

        # ── threshold ─────────────────────────────────────────────────────────
        tmpl_cfg    = cfg.get('templates', {}) or {}
        reports_cfg = cfg.get('reports', {}) or {}
        min_score   = float(reports_cfg.get('min_score', 1) or 0)
        if min_score > 0:
            before = len(scored)
            scored = [c for c in scored if (c.get('score', 0) or 0) >= min_score]
            print(f'  threshold {min_score}: {len(scored)}/{before} commits kept')

        # ── rank ──────────────────────────────────────────────────────────────
        for rank, c in enumerate(scored, 1):
            c['_rank'] = rank

        # ── format flags ──────────────────────────────────────────────────────
        want_csv  = bool(tmpl_cfg.get('csv_output',  True))
        want_html = bool(tmpl_cfg.get('html_summary', True))
        want_xlsx = bool(tmpl_cfg.get('xls_output',  False))
        want_ods  = bool(tmpl_cfg.get('ods_output',  False))

        # ── CSV ───────────────────────────────────────────────────────────────
        csv_path = None
        if want_csv:
            # v8.7: stale dimension columns removed; flags + per-profile scores added
            active_profs = list(((cfg.get('profiles', {}) or {}).get('active')
                                  or cfg.get('active_profiles') or {}) or [])
            cols = (['rank', 'commit', 'subject', 'author_name', 'author_time',
                     'score', 'matched_profiles', 'flags', 'product_evidence']
                    + [f'score_{p}' for p in active_profs])
            csv_path = os.path.join(outdir, 'relevant_commits.csv')
            with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
                w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
                w.writeheader()
                for c in scored:
                    row = dict(c)
                    row['rank']             = c.get('_rank', '')
                    row['matched_profiles'] = ';'.join(c.get('matched_profiles') or [])
                    row['product_evidence'] = ';'.join(c.get('product_evidence') or [])
                    # flags: all True boolean keys in commit['meta'] -- fully generic
                    _cmeta = (c.get('meta')
                              or (c.get('scoring') or {}).get('meta')
                              or {})
                    row['flags'] = ','.join(
                        k for k, v in sorted(_cmeta.items()) if v is True)
                    # per-profile score columns
                    prof_scores = (c.get('scoring', {}) or {}).get('profiles', {}) or {}
                    for p in active_profs:
                        row[f'score_{p}'] = prof_scores.get(p, 0)
                    w.writerow(row)
            print(f'  CSV:  {csv_path}')

        # ── JSON ──────────────────────────────────────────────────────────────
        save_json(os.path.join(outdir, 'relevant_commits.json'), scored)

        profile_summary = {}
        for c in scored:
            for p in (c.get('matched_profiles') or []):
                if p not in profile_summary:
                    profile_summary[p] = {'count': 0, 'total_score': 0}
                profile_summary[p]['count']       += 1
                profile_summary[p]['total_score'] += c.get('score', 0) or 0
        for d in profile_summary.values():
            c_ = d['count']
            d['avg_score'] = round(d['total_score'] / c_, 1) if c_ else 0.0
        save_json(os.path.join(outdir, 'profile_summary.json'), profile_summary)

        with open(os.path.join(outdir, 'profile_matrix.csv'), 'w',
                  newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(['rank', 'commit', 'subject', 'profile',
                        'total_score', 'profile_score'])
            for c in scored:
                for p in (c.get('matched_profiles') or []):
                    w.writerow([
                        c.get('_rank', ''), c.get('commit', ''),
                        c.get('subject', ''), p, c.get('score', 0),
                        (c.get('scoring', {}) or {}).get('profiles', {}).get(p, 0)])

        coverage = _coverage(scored)
        # Generic meta-flag counts (all True boolean keys across all commits)
        meta_flag_counts = {}
        for _c in scored:
            _m = (_c.get('meta')
                  or (_c.get('scoring') or {}).get('meta')
                  or {})
            for _k, _v in _m.items():
                if _v is True:
                    meta_flag_counts[_k] = meta_flag_counts.get(_k, 0) + 1

        # Per-profile match counts (one entry per active profile)
        per_profile_counts = {}
        for _c in scored:
            for _p in (_c.get('matched_profiles') or []):
                per_profile_counts[_p] = per_profile_counts.get(_p, 0) + 1

        filter_stats = {}
        try:
            import json as _j
            _ps = _j.load(open(state_path))
            filter_stats = _ps.get('stages', {}).get('filter_commits', {})
        except Exception:
            pass
        report_stats = {
            'total_scored_commits':          len(scored),
            'min_score_threshold':           min_score,
            'meta_flag_counts':              meta_flag_counts,
            'per_profile_counts':            per_profile_counts,
            'commits_with_profile_score':    sum(1 for c in scored
                                                  if c.get('matched_profiles')),
            'commits_with_product_evidence': sum(1 for c in scored
                                                  if c.get('product_evidence')),
            'profile_coverage':              coverage,
            'active_profiles':               list(((cfg.get('profiles', {}) or {})
                                                    .get('active') or {})),
            'template_options':              tmpl_cfg,
            'filter_stats':                  filter_stats,
        }
        save_json(os.path.join(outdir, 'report_stats.json'), report_stats)

        # ── HTML ──────────────────────────────────────────────────────────────
        html_path = None
        if want_html:
            try:
                html_path = os.path.join(outdir, 'summary.html')
                generate_html_report(
                    scored, profile_summary, report_stats, html_path,
                    title=tmpl_cfg.get('report_title',
                                       'kcommit Analysis Report'))
                print(f'  HTML: {html_path}')
            except Exception as e:
                print(f'  WARNING: HTML failed: {e}')

        # ── XLSX ──────────────────────────────────────────────────────────────
        xlsx_path = None
        if want_xlsx:
            from lib.spreadsheet import write_xlsx
            xlsx_path = os.path.join(outdir, 'relevant_commits.xlsx')
            write_xlsx(xlsx_path, scored, profile_summary,
                       report_title=tmpl_cfg.get('report_title',
                                                  'kcommit Analysis Report'))
            print(f'  XLSX: {xlsx_path}')

        # ── ODS ───────────────────────────────────────────────────────────────
        ods_path = None
        if want_ods:
            try:
                from lib.spreadsheet import write_ods
                ods_path = os.path.join(outdir, 'relevant_commits.ods')
                write_ods(ods_path, scored, profile_summary,
                          report_title=tmpl_cfg.get('report_title',
                                                     'kcommit Analysis Report'))
                print(f'  ODS:  {ods_path}')
            except Exception as e:
                print(f'  WARNING: ODS failed: {e}')

        print(f'  reports done in {outdir}  ({len(scored)} commits)')
        print_stage_output('report outputs', len(scored),
            elapsed=time.time()-_t0_stage)
        finish_stage(state_path, 'report_commits', started, status='ok',
                     extra={
                         'reported_commit_count': len(scored),
                         'min_score_threshold':   min_score,
                         'profile_coverage':      coverage,
                         'csv_path':              csv_path  or '',
                         'html_path':             html_path or '',
                         'xlsx_path':             xlsx_path or '',
                         'ods_path':              ods_path  or '',
                     })

    except SystemExit:
        raise
    except Exception as exc:
        import traceback; traceback.print_exc()
        fail_stage(state_path, 'report_commits', started, error_msg=str(exc))
        raise


if __name__ == '__main__':
    main()
