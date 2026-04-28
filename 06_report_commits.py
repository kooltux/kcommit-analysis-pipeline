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
import argparse, csv, os

from lib.config          import load_config, load_json, save_json
from lib.validation      import validate_config_only as validate_inputs
from lib.pipeline_runtime import start_stage, finish_stage, fail_stage
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
    args = ap.parse_args()

    cfg        = load_config(args.config)
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

        # ── threshold ─────────────────────────────────────────────────────────
        tmpl_cfg    = cfg.get('templates', {}) or {}
        reports_cfg = cfg.get('reports', {}) or {}
        min_score   = float(reports_cfg.get('min_score', 0) or 0)
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
            cols = ['rank', 'commit', 'subject', 'author_name', 'author_time',
                    'score', 'matched_profiles',
                    'product_score', 'security_score',
                    'performance_score', 'stable_score', 'product_evidence']
            csv_path = os.path.join(outdir, 'relevant_commits.csv')
            with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
                w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
                w.writeheader()
                for c in scored:
                    row = dict(c)
                    row['rank']              = c.get('_rank', '')
                    row['matched_profiles']  = ';'.join(c.get('matched_profiles') or [])
                    row['product_evidence']  = ';'.join(c.get('product_evidence') or [])
                    sc                       = c.get('scoring', {}) or {}
                    row['product_score']     = sc.get('product', 0)
                    row['security_score']    = sc.get('security', 0)
                    row['performance_score'] = sc.get('performance', 0)
                    row['stable_score']      = sc.get('stable', 0)
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
        report_stats = {
            'total_scored_commits':           len(scored),
            'min_score_threshold':            min_score,
            'commits_with_security_score':    sum(
                1 for c in scored if (c.get('scoring',{}) or {}).get('security',0) > 0),
            'commits_with_performance_score': sum(
                1 for c in scored if (c.get('scoring',{}) or {}).get('performance',0) > 0),
            'commits_with_stable_score':      sum(
                1 for c in scored if (c.get('scoring',{}) or {}).get('stable',0) > 0),
            'commits_with_product_evidence':  sum(
                1 for c in scored if c.get('product_evidence')),
            'profile_coverage':   coverage,
            'active_profiles':    list(((cfg.get('profiles',{}) or {}).get('active')
                                        or cfg.get('active_profiles') or {})),
            'template_options':   tmpl_cfg,
        }
        save_json(os.path.join(outdir, 'report_stats.json'), report_stats)

        # ── HTML ──────────────────────────────────────────────────────────────
        html_path = None
        if want_html:
            try:
                html_path = generate_html_report(work, cfg)
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
