#!/usr/bin/env python3
"""Stage 06: Generate CSV, JSON, and HTML reports from scored commits.
"""
import argparse
import csv
import os

from lib.config import load_config
from lib.config import load_json, save_json
from lib.validation import validate_config_only as validate_inputs
from lib.pipeline_runtime import (
    start_stage, finish_stage, fail_stage
)
from lib.html_report import generate_html_report


def _profile_coverage(scored):
    zero   = sum(1 for c in scored if not (c.get('matched_profiles') or []))
    single = sum(1 for c in scored if len(c.get('matched_profiles') or []) == 1)
    multi  = sum(1 for c in scored if len(c.get('matched_profiles') or []) > 1)
    return {
        'commits_matched_zero_profiles':     zero,
        'commits_matched_one_profile':       single,
        'commits_matched_multiple_profiles': multi,
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
        for note in notices:
            print('  NOTICE:', note)
        if problems:
            for p in problems:
                print('  ERROR:', p)
            fail_stage(state_path, 'report_commits', started,
                       error_msg='; '.join(problems))
            raise SystemExit(2)

        cache  = os.path.join(work, 'cache')
        outdir = os.path.join(work, 'output')
        os.makedirs(outdir, exist_ok=True)

        scored = (load_json(os.path.join(cache, 'scored_commits.json'),
                            default=[]) or [])
        scored = sorted(scored, key=lambda x: x.get('score', 0), reverse=True)

        # ── CSV report ────────────────────────────────────────────────────────
        csv_cols = [
            'commit', 'subject', 'author_name', 'author_time',
            'score', 'matched_profiles',
            'product_score', 'security_score', 'performance_score', 'stable_score',
            'product_evidence',
        ]
        csv_path = os.path.join(outdir, 'relevant_commits.csv')
        with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=csv_cols,
                                    extrasaction='ignore')
            writer.writeheader()
            for c in scored:
                row = dict(c)
                row['matched_profiles'] = ';'.join(c.get('matched_profiles') or [])
                row['product_evidence'] = ';'.join(c.get('product_evidence') or [])
                sc = c.get('scoring', {}) or {}
                row['product_score']     = sc.get('product', 0)
                row['security_score']    = sc.get('security', 0)
                row['performance_score'] = sc.get('performance', 0)
                row['stable_score']      = sc.get('stable', 0)
                writer.writerow(row)

        # ── JSON reports ──────────────────────────────────────────────────────
        save_json(os.path.join(outdir, 'relevant_commits.json'), scored)

        # Richer profile summary: count + total_score per profile
        profile_summary = {}
        for c in scored:
            for p in (c.get('matched_profiles') or []):
                if p not in profile_summary:
                    profile_summary[p] = {'count': 0, 'total_score': 0}
                profile_summary[p]['count']       += 1
                profile_summary[p]['total_score'] += c.get('score', 0) or 0
        for _data in profile_summary.values():
            _cnt = _data['count']
            _data['avg_score'] = round(_data['total_score'] / _cnt, 1) if _cnt else 0.0
        save_json(os.path.join(outdir, 'profile_summary.json'), profile_summary)

        # Profile matrix CSV
        with open(os.path.join(outdir, 'profile_matrix.csv'), 'w',
                     newline='', encoding='utf-8') as fh:
            writer = csv.writer(fh)
            writer.writerow(['commit', 'subject', 'profile', 'score'])
            for c in scored:
                for p in (c.get('matched_profiles') or []):
                    writer.writerow([
                        c.get('commit', ''),
                        c.get('subject', ''),
                        p,
                        c.get('score', 0),
                    ])

        # ── Stats ─────────────────────────────────────────────────────────────
        coverage = _profile_coverage(scored)
        active_profiles = list(
            ((cfg.get('profiles', {}) or {}).get('active')
             or cfg.get('active_profiles') or {})
        )
        tmpl_cfg = cfg.get('templates', {}) or {}

        report_stats = {
            'total_scored_commits':            len(scored),
            'commits_with_security_score':     sum(
                1 for c in scored
                if (c.get('scoring', {}) or {}).get('security', 0) > 0),
            'commits_with_performance_score':  sum(
                1 for c in scored
                if (c.get('scoring', {}) or {}).get('performance', 0) > 0),
            'commits_with_stable_score':       sum(
                1 for c in scored
                if (c.get('scoring', {}) or {}).get('stable', 0) > 0),
            'commits_with_product_evidence':   sum(
                1 for c in scored if c.get('product_evidence')),
            'profile_coverage':                coverage,
            'active_profiles':                 active_profiles,
            'template_options':                tmpl_cfg,
        }
        save_json(os.path.join(outdir, 'report_stats.json'), report_stats)

        # ── HTML report ───────────────────────────────────────────────────────
        html_path = None
        if tmpl_cfg.get('html_summary', True):
            try:
                html_path = generate_html_report(work, cfg)
                print('  HTML report: %s' % html_path)
            except Exception as e:
                print('  warning: HTML report generation failed: %s' % e)

        print('  reports generated in %s' % outdir)
        finish_stage(state_path, 'report_commits', started, status='ok',
                     extra={
                         'reported_commit_count': len(scored),
                         'profile_coverage':      coverage,
                         'csv_path':              csv_path,
                         'html_path':             html_path or '',
                     })

    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        fail_stage(state_path, 'report_commits', started, error_msg=str(exc))
        raise


if __name__ == '__main__':
    main()
