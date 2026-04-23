#!/usr/bin/env python3
"""Stage 06: Generate CSV, JSON, and HTML reports from scored commits.

v7.17 changes vs v7.13:
  - Sort key changed from 'candidate_score' to 'score'.
  - CSV columns updated: score, matched_profiles, product/security/performance/
    stable_score (promoted from scoring sub-dict), product_evidence.
  - report_stats.json gains profile_coverage sub-dict with three bucket counts.
  - get_pipeline_state() used to embed current state into stats.
  - fail_stage on error.
"""
from __future__ import print_function
import argparse
import csv
import os

from lib.config import load_config
from lib.io_utils import ensure_dir, load_json, save_json
from lib.validation import validate_inputs
from lib.pipeline_runtime import start_stage, finish_stage, fail_stage, get_pipeline_state
from lib.html_report import generate_html_report


def _profile_coverage(scored):
    zero   = sum(1 for c in scored if not c.get('matched_profiles'))
    single = sum(1 for c in scored if len(c.get('matched_profiles', [])) == 1)
    multi  = sum(1 for c in scored if len(c.get('matched_profiles', [])) > 1)
    return {
        'commits_matched_zero_profiles':    zero,
        'commits_matched_one_profile':      single,
        'commits_matched_multiple_profiles': multi,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    args = ap.parse_args()

    cfg        = load_config(args.config)
    work       = cfg.get('project', {}).get('work_dir', './work')
    state_path = os.path.join(work, 'pipeline_state.json')
    started    = start_stage(state_path, 'report_commits', 7, 7)

    try:
        problems, notices = validate_inputs(cfg)
        for note in notices:
            print(note)
        if problems:
            for p in problems:
                print(p)
            fail_stage(state_path, 'report_commits', started,
                       error_msg='; '.join(problems))
            raise SystemExit(2)

        cache  = os.path.join(work, 'cache')
        outdir = os.path.join(work, 'output')
        ensure_dir(outdir)

        scored = load_json(os.path.join(cache, 'scored_commits.json'), default=[]) or []
        # v7.17: sort by 'score' (replaces 'candidate_score')
        scored = sorted(scored, key=lambda x: x.get('score', 0), reverse=True)

        # ── CSV report ────────────────────────────────────────────────────────
        csv_cols = [
            'commit', 'subject', 'author_name', 'author_time',
            'score', 'matched_profiles',
            'product_score', 'security_score', 'performance_score', 'stable_score',
            'product_evidence',
        ]
        with open(os.path.join(outdir, 'relevant_commits.csv'), 'w',
                  newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=csv_cols, extrasaction='ignore')
            writer.writeheader()
            for c in scored:
                row = dict(c)
                row['matched_profiles'] = ';'.join(c.get('matched_profiles', []))
                row['product_evidence'] = ';'.join(c.get('product_evidence', []))
                sc = c.get('scoring', {}) or {}
                row['product_score']     = sc.get('product', 0)
                row['security_score']    = sc.get('security', 0)
                row['performance_score'] = sc.get('performance', 0)
                row['stable_score']      = sc.get('stable', 0)
                writer.writerow(row)

        # ── JSON reports ──────────────────────────────────────────────────────
        save_json(os.path.join(outdir, 'relevant_commits.json'), scored)

        profile_summary = {}
        for c in scored:
            for p in c.get('matched_profiles', []):
                profile_summary[p] = profile_summary.get(p, 0) + 1
        save_json(os.path.join(outdir, 'profile_summary.json'), profile_summary)

        with open(os.path.join(outdir, 'profile_matrix.csv'), 'w',
                  newline='', encoding='utf-8') as fh:
            writer = csv.writer(fh)
            writer.writerow(['commit', 'subject', 'profile'])
            for c in scored:
                for p in c.get('matched_profiles', []):
                    writer.writerow([c.get('commit', ''), c.get('subject', ''), p])

        # ── Stats ─────────────────────────────────────────────────────────────
        profiles_cfg = cfg.get('profiles', {}) or {}
        active       = profiles_cfg.get('active') or cfg.get('active_profiles') or []
        active_names = list(active.keys()) if isinstance(active, dict) else list(active)
        templates_cfg = cfg.get('templates', {}) or {}

        sc_vals  = [c.get('scoring', {}) or {} for c in scored]
        coverage = _profile_coverage(scored)

        report_stats = {
            'total_scored_commits':           len(scored),
            'commits_with_security_score':    sum(1 for s in sc_vals if s.get('security', 0) > 0),
            'commits_with_performance_score': sum(1 for s in sc_vals if s.get('performance', 0) > 0),
            'commits_with_stable_score':      sum(1 for s in sc_vals if s.get('stable', 0) > 0),
            'commits_with_product_evidence':  sum(1 for c in scored if c.get('product_evidence')),
            'active_profiles':                active_names,
            'profile_coverage':               coverage,
            'templates':                      templates_cfg,
            'pipeline_state':                 get_pipeline_state(state_path),
        }
        save_json(os.path.join(outdir, 'report_stats.json'), report_stats)

        # HTML report reads scored_commits.json from outdir
        save_json(os.path.join(outdir, 'scored_commits.json'), scored)

        # ── HTML report ───────────────────────────────────────────────────────
        if templates_cfg.get('html_summary', True):
            try:
                html_path = generate_html_report(work, cfg)
                print('HTML report: %s' % html_path)
            except Exception as e:
                print('warning: HTML report generation failed: %s' % e)

        print('reports generated in %s' % outdir)
        finish_stage(state_path, 'report_commits', started, status='ok',
                     extra={
                         'reported_commit_count': len(scored),
                         'profile_summary':       profile_summary,
                         'profile_coverage':      coverage,
                     })

    except SystemExit:
        raise
    except Exception as exc:
        fail_stage(state_path, 'report_commits', started, error_msg=str(exc))
        raise


if __name__ == '__main__':
    main()
